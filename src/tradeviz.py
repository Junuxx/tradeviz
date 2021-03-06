"""
Trade Visualizer for EU4
Created on 21 aug. 2013

@author: Jeroen Kools
"""

# TODO: Show countries option: ALL, specific tag
# TODO: Improve map readability at lower resolutions? (e.g. 1280x720)
# TODO: Full, tested support for Mac and Linux
# TODO: Nodes show options: Player abs trade power, player rel trade power, total trade power

# DEPENDENDIES:
# PyParsing: http://pyparsing.wikispaces.com or use 'pip install pyparsing'
# Python Imaging Library: http://www.pythonware.com/products/pil/
# On Ubuntu: aptitude install python-tk python-imaging python-imaging-tk python-pyparsing

# standardlib stuff
import logging
import time
import re
import os
import sys
import json
import zipfile
from math import sqrt, ceil, log1p
from distutils import version
import threading

# GUI stuff
import Tkinter as tk
import tkFileDialog
import tkMessageBox
import ttk
from PIL import Image, ImageTk, ImageDraw

# Tradeviz components
from TradeGrammar import tradeSection
import pyparsing
import NodeGrammar

# globals
provinceBMP = "../res/worldmap.gif"
WinRegKey = "SOFTWARE\\Wow6432Node\\Microsoft\\Windows\\CurrentVersion\\Uninstall\\Steam App 236850"  # Win64 only...
MacDefaultPath = os.path.expanduser("~/Library/Application Support/Steam/Steamapps/common/Europa Universalis IV")
LinuxDefaultPath = os.path.expanduser("~/.local/share/Steam/SteamApps/common/Europa Universalis IV")

# Colors
LIGHT_SLATE = "#36434b"
DARK_SLATE = "#29343a"
BTN_BG = "#364555"
BANNER_BG = "#9E9186"  # TODO: better color?
WHITE = "#fff"

# Fonts
SMALL_FONT = ("Cambria", 12)
BIG_FONT = ("Cambria", 18, "bold")

VERSION = "1.5.0"
COMPATIBILITY_VERSION = version.LooseVersion("1.21.1") # EU4 version
APP_NAME = "EU4 Trade Visualizer"


class TradeViz:
    """Main class for Europa Universalis Trade Visualizer"""
    def __init__(self):
        logging.debug("Initializing application")
        self.root = tk.Tk()
        self.root.withdraw()

        self.paneHeight = 195
        self.w, self.h = self.root.winfo_screenwidth(), self.root.winfo_screenheight()
        self.root.title("%s v%s" % (APP_NAME, VERSION))
        self.root.bind("<Escape>", lambda x: self.exit("Escape"))
        self.root.wm_protocol("WM_DELETE_WINDOW", lambda: self.exit("Close Window"))
        self.zeroArrows = []

        try:
            self.root.iconbitmap(r"../res/merchant.ico")
        except Exception as e:
            logging.error("Error setting application icon (expected on Unix): %s" % e)

        try:
            self.mapImg = Image.open(provinceBMP).convert("RGB")
            self.mapWidth = self.mapImg.size[0]
            self.mapHeight = self.mapImg.size[1]
            self.mapImg.thumbnail((self.w - 10, self.h), Image.BICUBIC)
            self.drawImg = self.mapImg.convert("RGB")
            self.mapThumbSize = self.mapImg.size
            self.ratio = self.mapThumbSize[0] / float(self.mapWidth)
            self.provinceImage = ImageTk.PhotoImage(self.mapImg)
        except Exception as e:
            logging.critical("Error preparing the world map!\n%s" % e)


        logging.debug("Setting up GUI")
        self.setupGUI()
        self.tradenodes = []
        self.player = ""
        self.date = ""
        self.zoomed = False
        self.saveVersion = ""
        self.preTradeSectionLines = 0
        self.root.grid_columnconfigure(1, weight=1)
        self.root.grid_rowconfigure(7, weight=1)
        self.getConfig()
        self.root.deiconify()

        # self.root.focus_set()
        logging.debug("Entering main loop")
        self.root.mainloop()


    def getConfig(self):
        """Retrieve settings from config file"""

        logging.debug("Getting config")

        if os.path.exists(r"../tradeviz.cfg"):
            with open(r"../tradeviz.cfg") as f:
                self.config = json.load(f)

        else:
            self.config = {}

        if "savefile" in self.config:
            self.saveEntry.insert(0, self.config["savefile"])
        if "showZeroRoutes" in self.config:
            self.showZeroVar.set(self.config["showZeroRoutes"])
        if "nodesShow" in self.config:
            self.nodesShowVar.set(self.config["nodesShow"])
        if "lastModPath" in self.config:
            self.modPathVar.set(self.config["lastModPath"])
        if "modPaths" in self.config:
            self.modPathComboBox.configure(values=[""] + self.config["modPaths"])
        if "arrowScale" in self.config:
            self.arrowScaleVar.set(self.config["arrowScale"])

        defaults = {"savefile": "", "showZeroRoutes": 0, "nodesShow": "Total value",
                    "modPaths": [], "lastModPath": "", "arrowScale": "Square root"}

        for k in defaults:
            if not k in self.config:
                self.config[k] = defaults[k]

        if not "installDir" in self.config or not os.path.exists(self.config["installDir"]):
            self.getInstallDir()

        self.saveConfig()


    def saveConfig(self):
        """Store settings in config file"""

        logging.debug("Saving config")

        with open(r"../tradeviz.cfg", "w") as f:
            json.dump(self.config, f)


    def getInstallDir(self):
        """Find the EU4 install path and store it in the config for later use"""

        logging.debug("Getting install dir")

        if sys.platform == "win32":
            import _winreg
            try:
                key = _winreg.OpenKey(_winreg.HKEY_LOCAL_MACHINE, WinRegKey)
                i = 0
                while 1:
                    quotedName, val, _type = _winreg.EnumValue(key, i)
                    if quotedName == "InstallLocation":
                        logging.info("Found install dir in Windows registry: %s" % val)
                        self.config["installDir"] = val
                        break
                    i += 1

            except WindowsError as e:
                logging.error("Error while trying to find install dir in Windows registry: %s" % e)

        elif sys.platform == "darwin":  # OS X

            if os.path.exists(MacDefaultPath):
                self.config["installDir"] = MacDefaultPath

        else:  # Assume it's Linux
            if os.path.exists(LinuxDefaultPath):
                self.config["installDir"] = LinuxDefaultPath

        if not "installDir" in self.config:
            self.config["installDir"] = ""

        if self.config["installDir"] == "" or not os.path.exists(self.config["installDir"]):
            self.showError("EU4 installation folder not found!",
                    "Europa Universalis 4 installation could not be found! " +
                    "The program needs to read some files from the game to work correctly. " +
                    "Please select your installation folder manually.")
            folder = tkFileDialog.askdirectory(initialdir="/")
            if os.path.exists(os.path.join(folder, "common")):
                self.config["installDir"] = folder


    def setupGUI(self):
        """Initialize the user interface elements"""

        self.canvas = tk.Canvas(self.root, width=self.mapThumbSize[0], height=self.mapThumbSize[1],
                                highlightthickness=0, border=5, relief="flat", bg=DARK_SLATE)
        self.canvas.grid(row=1, column=0, columnspan=4, sticky="W", padx=5)
        self.canvas.bind("<Button-1>", self.clickMap)
        self.setupTkStyles()
        self.root.geometry("%dx%d+0+0" % (self.w, self.h))
        self.root.minsize(self.w, self.h - 20)
        self.root.maxsize(self.w, self.h - 20)
        self.root.wm_state('zoomed')
        self.root.configure(background=DARK_SLATE)

        # Labels, entries, checkboxes

        tk.Label(self.root, text="EU4 Trade Visualizer", bg=BANNER_BG, fg=WHITE, font=BIG_FONT).grid(
                 row=0, column=0, columnspan=4, sticky="WE", padx=10, pady=(10, 5))

        tk.Label(self.root, text="Save file:", bg=DARK_SLATE, fg=WHITE,
                 font=SMALL_FONT, anchor="w").grid(row=2, column=0, padx=6, pady=2, sticky="WE")
        self.saveEntry = tk.Entry(self.root, bd=0, border=0, font=SMALL_FONT, bg=LIGHT_SLATE, fg="white")
        self.saveEntry.config(highlightbackground="red", border=3, relief="flat")
        self.saveEntry.grid(row=2, column=1, columnspan=2, sticky="WE", padx=6, pady=4, ipady=0)

        tk.Label(self.root, text="Mod:", bg=DARK_SLATE, fg=WHITE,
                 font=SMALL_FONT).grid(row=3, column=0, padx=(6, 2), pady=2, sticky="W")
        self.modPathVar = tk.StringVar()
        self.modPathComboBox = ttk.Combobox(self.root, textvariable=self.modPathVar, values=[""], state="readonly", font=SMALL_FONT, style="My.TCombobox")
        self.modPathComboBox.grid(row=3, column=1, columnspan=2, sticky="WE", padx=6, pady=2)
        self.modPathVar.trace("w", self.modPathChanged)

        tk.Label(self.root, text="Nodes show:", bg=DARK_SLATE, fg=WHITE, font=SMALL_FONT).grid(row=4, column=0, padx=(6, 2), pady=2, sticky="W")
        self.nodesShowVar = tk.StringVar()
        self.nodesShowVar.set("Total value")
        self.nodesShow = ttk.Combobox(self.root, textvariable=self.nodesShowVar, values=["Local value", "Total value"],
                                      state="readonly", font=SMALL_FONT, style="My.TCombobox")
        self.nodesShow.grid(row=4, column=1, columnspan=2, sticky="W", padx=6, pady=2)
        self.nodesShowVar.trace("w", self.nodesShowChanged)

        tk.Label(self.root, text="Arrow scaling:", bg=DARK_SLATE, fg=WHITE, font=SMALL_FONT).grid(row=5, column=0, padx=(6, 2), pady=2, sticky="W")
        self.arrowScaleVar = tk.StringVar()
        self.arrowScaleVar.set("Square root")
        self.arrowScale = ttk.Combobox(self.root, textvariable=self.arrowScaleVar, values=["Linear", "Square root", "Logarithmic"],
                                      state="readonly", font=SMALL_FONT, style="My.TCombobox")
        self.arrowScale.grid(row=5, column=1, columnspan=2, sticky="W", padx=6, pady=2)
        self.arrowScaleVar.trace("w", self.arrowScaleChanged)

        self.showZeroVar = tk.IntVar(value=1)
        self.showZeroes = tk.Checkbutton(self.root, text="Show unused trade routes",
                                         bg=DARK_SLATE, fg=WHITE, font=SMALL_FONT, selectcolor=LIGHT_SLATE,
                                         activebackground=DARK_SLATE, activeforeground=WHITE,
                                         variable=self.showZeroVar, command=self.toggleShowZeroes)
        self.showZeroes.grid(row=6, column=0, columnspan=2, sticky="W", padx=6, pady=2)

        # Buttons

        self.browseFileBtn = tk.Button(self.root, text="Browse...", command=self.browseSave,
                                       bg=BTN_BG, fg=WHITE, font=SMALL_FONT, relief="ridge")
        self.browseFileBtn.grid(row=2, column=3, sticky="WSEN", padx=7, pady=3)

        self.browseModFolderBtn = tk.Button(self.root, text="Browse...", command=self.browseMod,
                                            bg=BTN_BG, fg=WHITE, font=SMALL_FONT, relief="ridge")
        self.browseModFolderBtn.grid(row=3, column=3, sticky="WSEN", padx=7, pady=3, ipady=1)

        self.goButton = tk.Button(self.root, text="Go!", command=self.go, bg=BTN_BG, fg=WHITE,
                                  font=SMALL_FONT + ("bold",), relief="ridge")
        self.goButton.grid(row=7, column=1, sticky="SE", ipadx=20, padx=7, pady=15)

        self.saveImgButton = tk.Button(self.root, text="Save Map", command=self.saveMap, bg=BTN_BG, fg=WHITE,
                                       font=SMALL_FONT, relief="ridge")
        self.saveImgButton.grid(row=7, column=2, sticky="SE", padx=7, pady=15)

        self.exitButton = tk.Button(self.root, text="Exit", command=lambda: self.exit("Button"),
                                    bg=BTN_BG, fg=WHITE, font=SMALL_FONT, relief="ridge")
        self.exitButton.grid(row=7, column=3, sticky="SWE", padx=7, pady=15)


    def setupTkStyles(self):
        style = ttk.Style()
        style.element_create("plain.field", "from", "default")

        # TODO: change colors in dropdown menu
        # http://wiki.tcl.tk/37973 says: "I could not find a way to set the listbox hover background and foreground."
        # -__-
        style.layout("My.TCombobox",
                   [('Combobox.plain.field', {'children': [(
                         'Combobox.background', {'children': [(
                             'Combobox.padding', {'children': [(
                                 'Combobox.textarea', {'sticky': 'nswe'}
                              )],
                          'sticky': 'nswe'})],
                     'sticky': 'nswe'}),
                     ('Combobox.downarrow', {'sticky': 'nse'})], 'border':'0', 'sticky': 'nswe'})])

        style.map("TCombobox", selectbackground=[('!focus', LIGHT_SLATE), ('focus', LIGHT_SLATE)],
                               selectforeground=[('!focus', WHITE), ('focus', WHITE)])
        style.configure("My.TCombobox",
                                        background=LIGHT_SLATE,
                                        foreground=WHITE
                                        )

        listboxstyle = ttk.Style()
        listboxstyle.configure("TListbox", background="#f00", foreground="#00f")
        listboxstyle.map("TListbox", selectbackground=[('!focus', LIGHT_SLATE), ('focus', LIGHT_SLATE)],
                               selectforeground=[('!focus', WHITE), ('focus', WHITE)])
        listboxstyle.configure("TListbox",
                                        background=LIGHT_SLATE,
                                        foreground=WHITE
                                        )

    def browseSave(self, event=None):
        """Let the user browseSave for an EU4 save file to be used by the program"""

        logging.debug("Browsing for save file")

        initialDir = "."
        if "savefile" in self.config:
            initialDir = os.path.dirname(self.config["savefile"])

        filename = tkFileDialog.askopenfilename(filetypes=[("EU4 Saves", "*.eu4")], initialdir=initialDir)
        logging.info("Selected save file %s" % os.path.basename(filename))
        self.config["savefile"] = filename
        self.saveConfig()

        self.saveEntry.delete(0, tk.END)
        self.saveEntry.insert(0, self.config["savefile"])


    def browseMod(self, event=None):

        logging.debug("Browsing for mod")

        initDir = "/"
        if self.config["lastModPath"]:
            initDir = os.path.split(self.config["lastModPath"])[0]
        else:
            for path in self.config["modPaths"]:
                if path:  # not empty
                    initDir = os.path.basename(path)
                    break

        modpath = tkFileDialog.askopenfilename(filetypes=[("EU4 Mods", "*.mod")], initialdir=initDir)

        logging.debug("Selected mod path %s" % modpath)

        modzip = modpath.replace(".mod", ".zip")
        moddir = modpath.replace(".mod", "")

        if not os.path.exists(modzip) and not os.path.exists(moddir):
            if modpath:
                self.showError("ModDir %s and modzip %s do not appeat to be a valid mod" % (moddir, modzip),
                               "This does not seem to be a valid mod path!")
            return

        self.modPathVar.set(modpath)
        if not modpath in self.config["modPaths"]:
            self.config["modPaths"] += [modpath]

        self.config["lastModPath"] = modpath


    def go(self, event=None):
        """Start parsing the selected save file and show the results on the map"""

        logging.info("Processing save file")
        self.done = False
        self.goTime = time.time()
        self.clearMap()
        waitIconThread = threading.Thread(target=self.doWaitIcon)
        waitIconThread.start()

        if self.config["savefile"]:

            try:
                txt = self.getSaveText()
            except ReadError as e:
                self.showError("Failed to get savefile text: " + e.message,
                                "This save file %s and can't be processed by %s" % (e.message, APP_NAME))
                self.drawMap(True)
                return

            try:
                tradesection = txt[1]                                       # drop part before trade section starts
                tradesection = tradesection.split("production_leader")[0]   # drop the part after the end
                self.getTradeData(tradesection)
                self.getNodeData()

            except Exception as e:
                msg = "Tradeviz could not parse this file. You might be trying to open a corrupted save," + \
                      "or a save created with an unsupported mod or game version."
                if type(e) == pyparsing.ParseException:
                    print "----------------------------"
                    print e.line
                    print " "*(e.column - 1) + "^"
                    print e

                    msg += "Error: " + str(e)
                elif type(e) == IndexError:
                    print e.message
                    print ("+" + str(self.preTradeSectionLines))

                self.showError(e, "Can't read file! " + msg)

            try:
                self.drawMap(True)
            except InvalidTradeNodeException as e:
                self.showError("Invalid trade node index: %s" % e,
                               "Save file contains invalid trade node info. " +
                               "If your save is from a modded game, please indicate the mod folder and try again.")

    def doWaitIcon(self, angle=0):

        my = (self.h) / 2 - self.paneHeight + 40
        mx = self.w / 2
        radius = 16
        arcs = []
        arcs.append (self.canvas.create_arc(mx - radius, my - radius, mx + radius, my + radius, fill=WHITE, outline=WHITE, start=angle))
        arcs.append (self.canvas.create_arc(mx - radius, my - radius, mx + radius, my + radius, fill=WHITE, outline=WHITE, start=(angle + 180)))

        while not self.done and (time.time() - self.goTime) < 10:

            self.canvas.itemconfig(arcs[0], start=angle)
            self.canvas.itemconfig(arcs[1], start=angle + 180)

            self.canvas.update_idletasks()
            angle -= 8
            time.sleep(.05)

        for arc in arcs:
            self.canvas.delete(arc)


    def getSaveText(self):
        """Extract the text from the selected save file"""

        self.canvas.create_text((self.mapThumbSize[0] / 2, self.mapThumbSize[1] / 2),
                                text="Please wait... Save file is being processed...",
                                fill="white",
                                font=SMALL_FONT)
        self.root.update()
        logging.debug("Reading save file %s" % os.path.basename(self.config["savefile"]))

        with open(self.config["savefile"]) as f:
            txt = f.read()

            txt = self.checkForCompression(txt)
            self.checkForIronMan(txt)
            self.checkForVersion(txt)

            if not txt.startswith("EU4txt"):
                logging.error("Savefile starts with %s, not EU4txt" % txt[:10])
                raise ReadError("appears to be in an invalid format")


            for line in txt[:2000].split("\n"):
                if "=" in line:
                    key, val = line.split("=")
                    if key == "date":
                        self.date = val.strip('" \n')
                    elif key == "player":
                        self.player = val.strip('" \n')
                    elif key == "speed":
                        break

            txt = txt.split("trade=")
            self.preTradeSectionLines = txt[0].count("\n")

        return txt


    def checkForIronMan(self, txt):
        if txt.startswith("EU4binM"):
            raise ReadError("appears to be an Ironman save")


    def checkForCompression(self, txt):
        """Check whether the save file text is compressed. If so, return uncompressed text, otherwise return the text unchanged"""
        if txt[:2] == "PK":
            logging.info("Save file is compressed, unzipping...")
            zippedSave = zipfile.ZipFile(self.config["savefile"])
            filename = [x for x in zippedSave.namelist() if x.endswith(".eu4")][0]
            unzippedSave = zippedSave.open(filename)
            txt = unzippedSave.read()
            return txt
        else:
            return txt


    def checkForVersion(self, txt):
        versionTuple = re.findall("first=(\d+)\s+second=(\d+)\s+third=(\d+)", txt[:500])
        if versionTuple == []:
            logging.warning("Could not find version info!")
        else:
            versionTuple = versionTuple[0]
            self.saveVersion = version.LooseVersion("%s.%s.%s" % versionTuple)
            logging.info("Savegame version is %s" % self.saveVersion)
            if self.saveVersion > COMPATIBILITY_VERSION:
                tkMessageBox.showwarning("Version warning", ("This savegame is from an a newer EU4 version (%s) than " + \
                                                "the version this tool designed to work for (%s). " + \
                                                "It might not work correctly!") % (self.saveVersion.vstring, COMPATIBILITY_VERSION.vstring))


    def toggleShowZeroes(self, event=None):
        """Turn the display of trade routes with a value of zero on or off"""

        logging.debug("Show zeroes toggled")
        self.config["showZeroRoutes"] = self.showZeroVar.get()
        self.root.update()

        if not self.zeroArrows and self.showZeroVar.get():
            self.drawMap()
        else:
            for itemId in self.zeroArrows:
                if self.showZeroVar.get():
                    self.canvas.itemconfig(itemId, state="normal")
                else:
                    self.canvas.itemconfig(itemId, state="hidden")

        self.saveConfig()


    def nodesShowChanged(self, *args):
        self.config["nodesShow"] = self.nodesShowVar.get()
        self.drawMap()


    def arrowScaleChanged(self, *args):
        self.config["arrowScale"] = self.arrowScaleVar.get()
        self.drawMap()


    def modPathChanged(self, *args):
        self.config["lastModPath"] = self.modPathVar.get()


    def exit(self, arg=""):
        """Close the program"""

        self.saveConfig()
        self.root.update()
        logging.info("Exiting... (%s)" % arg)
        logging.shutdown()
        self.root.quit()


    def getTradeData(self, tradesection):
        """Extract the trade data from the selected save file"""

        logging.info("Parsing %i chars" % len(tradesection))
        t0 = time.time()

        logging.debug("Parsing trade section...")
        # pydev thinks tradeSection.parseString is an undefined import, but it's not
        result = tradeSection.parseString(tradesection) # @UndefinedVariable
        d = result.asDict()
        r = {}

        logging.info("Finished parsing save in %.3f seconds" % (time.time() - t0))

        self.maxIncoming = 0
        self.maxCurrent = 0
        self.maxLocal = 0

        logging.debug("Processing parsed results")

        for n in d["Nodes"]:
            d = n.asDict()
            node = {}
            for k in d:
                if k not in ["quotedName" , "incomingFromNode", "incomingValue"]:
                    node[k] = d[k]
                elif k in ["incomingFromNode", "incomingValue"]:
                    node[k] = d[k].asList()

                if k == "currentValue":
                    self.maxCurrent = max(self.maxCurrent, d[k])
                if k == "localValue":
                    self.maxLocal = max(self.maxLocal, d[k])
                if k == "incomingValue":
                    self.maxIncoming = max(self.maxIncoming, *d[k].asList())

            r[d["quotedName"][0]] = node

        try:
            logging.debug("Seville:\n\t%s" % r["sevilla"])
            logging.debug("max current value: %s" % self.maxCurrent)
            logging.debug("max incoming value: %s" % self.maxIncoming)
        except KeyError:
            logging.warn("Trade node Seville not found! Save file is either from a modded game or malformed!")

        self.nodeData = r


    def getNodeName(self, nodeID):
        node = self.tradenodes[nodeID - 1]
        return node[0]


    def getNodeLocation(self, nodeID):
        if nodeID > len(self.tradenodes) + 1:
            raise InvalidTradeNodeException(nodeID)
        node = self.tradenodes[nodeID - 1]
        provinceID = node[1]


        for loc in self.provinceLocations:
            if loc[0] == provinceID:
                return loc[1:]


    def getNodeData(self):
        """Retrieve trade node and province information from the game or mod files"""

        logging.debug("Getting node data")

        tradenodes = r"common/tradenodes/00_tradenodes.txt"
        positions = r"map/positions.txt"

        modPath = self.modPathComboBox.get()
        modzip = modPath.replace(".mod", ".zip")
        moddir = modPath.replace(".mod", "")

        modType = ""
        if modPath and os.path.isdir(moddir):
            modType = "dir"
        elif os.path.exists(modzip):
            modType = "zip"

        # Get all tradenode provinceIDs, modded or default
        try:
            if modType == "zip":
                z = zipfile.ZipFile(modzip)
                if os.path.normpath(tradenodes) in z.namelist():
                    logging.debug("Using tradenodes file from zipped mod")
                    with z.open(tradenodes) as f:
                        txt = f.read()
                else:
                    tradenodesfile = os.path.join(self.config["installDir"], tradenodes)
                    logging.debug("Using default tradenodes file")

                with open(tradenodesfile, "r") as f:
                    txt = f.read()

            else:
                if modType == "dir" and os.path.exists(os.path.join(moddir, tradenodes)):
                    tradenodesfile = os.path.join(moddir, tradenodes)
                    logging.debug("Using tradenodes file from mod directory")
                else:
                    tradenodesfile = os.path.join(self.config["installDir"], tradenodes)
                    logging.debug("Using default tradenodes file")

                with open(tradenodesfile, "r") as f:
                    txt = f.read()
        except IOError as e:
            logging.critical("Could not find trade nodes file: %s" % e)

        txt = removeComments(txt)
        tradenodes = NodeGrammar.nodes.parseString(txt)
        # for tn in tradenodes: print tn
        logging.info("%i tradenodes found in %i chars" % (len(tradenodes), len(txt)))

        for i, tradenode in enumerate(tradenodes):
            tradenodes[i] = (tradenode["name"], tradenode["location"])

        self.tradenodes = tradenodes

        # Now get province positions
        try:
            if modType == "zip":
                z = zipfile.ZipFile(modzip)
                if os.path.normpath(positions) in z.namelist():
                    logging.debug("Using positions file from zipped mod")
                    with z.open(positions) as f:
                        txt = f.read()
                else:
                    tradenodesfile = os.path.join(self.config["installDir"], positions)
                    logging.debug("Using default tradenodes file")

                with open(tradenodesfile, "r") as f:
                    txt = f.read()
            else:
                if modType == "dir" and os.path.exists(os.path.join(moddir, positions)):
                    positionsfile = os.path.join(moddir, positions)
                    logging.debug("Using positions file from mod directory")
                else:
                    positionsfile = os.path.join(self.config["installDir"], positions)
                    logging.debug("Using default positions file")


                with open(positionsfile, "r") as f:
                    txt = f.read()
        except IOError as e:
            logging.critical("Could not find locations file: %s" % e)


        locations = re.findall(r"(\d+)=\s*{\s*position=\s*{\s*([\d\.]*)\s*([\d\.]*)", txt)
        for i in range(len(locations)):
            a, b, c = locations[i]

            locations[i] = (int(a), float(b), self.mapHeight - float(c))  # invert y coordinate :)

        self.provinceLocations = locations
        logging.info("Found %i province locations" % len(self.provinceLocations))


    def getNodeRadius(self, node):
        """Calculate the radius for a trade node given its value"""

        if self.config["nodesShow"] == "Total value":
            value = node["currentValue"] / self.maxCurrent
        elif self.config["nodesShow"] == "Local value":
            value = node["localValue"] / self.maxLocal
        else:
            logging.error("Invalid nodesShow option: %s" % self.config["nodesShow"])

        return 5 + int(7 * value)


    def getLineWidth(self, value):

        arrowScaleStyle = self.arrowScaleVar.get()

        if value <= 0:
            return 1

        elif arrowScaleStyle == "Linear":
            return int(ceil(10 * value / self.maxIncoming))

        elif arrowScaleStyle == "Square root":
            return int(round(10 * sqrt(value) / sqrt(self.maxIncoming)))

        elif arrowScaleStyle == "Logarithmic":
            return int(round(10 * log1p(value) / log1p(self.maxIncoming)))


    def intersectsNode(self, node1, node2):
        """
        Check whether a trade route intersects a trade node circle (other than source and target nodes)
        See http://mathworld.wolfram.com/Circle-LineIntersection.html
        """

        for n, node3 in enumerate(self.tradenodes):
            nx, ny = self.getNodeLocation(n + 1)
            data = self.nodeData[node3[0]]

            r = self.getNodeRadius(data) / self.ratio

            # assume circle center is at 0,0
            x2, y2 = self.getNodeLocation(node1)
            x1, y1 = self.getNodeLocation(node2)
            x1 -= nx
            y1 -= ny
            x2 -= nx
            y2 -= ny

            if (x1, y1) == (0, 0) or (x2, y2) == (0, 0):
                continue

            D = x1 * y2 - x2 * y1
            dx = x2 - x1
            dy = y2 - y1
            dr = sqrt(dx ** 2 + dy ** 2)
            det = r ** 2 * dr ** 2 - D ** 2

            if det > 0:
            # infinite line intersects, check whether the center node is inside the rectangle defined by the other nodes
                if min(x1, x2) < 0 and max(x1, x2) > 0 and min(y1, y2) < 0 and max(y1, y2) > 0:
                    logging.debug("%s is intersected by a trade route between %s and %s" %
                                  (self.getNodeName(n + 1), self.getNodeName(node1), self.getNodeName(node2)))
                    return True


    def drawArrow(self, fromNode, toNode, value, toRadius):
        """Draw an arrow between two nodes on the map"""

        if value <= 0 and not self.showZeroVar.get():
            return

        x2, y2 = self.getNodeLocation(fromNode)
        x, y = self.getNodeLocation(toNode)
        isPacific = self.pacificTrade(x, y, x2, y2)

        # adjust for target node radius
        dx = x - x2
        if isPacific:
            if x > x2:
                dx = x2 - self.mapWidth - x
            else:
                dx = self.mapWidth - x + x2
        dy = y - y2
        l = max(1, sqrt(dx ** 2 + dy ** 2))
        radiusFraction = toRadius / l

        # adjust to stop at node circle's edge
        x -= 3 * dx * radiusFraction
        y -= 3 * dy * radiusFraction

        # rescale to unit length
        dx /= l
        dy /= l

        ratio = self.ratio
        lineWidth = self.getLineWidth(value)
        arrowShape = (max(8, lineWidth * 2), max(10, lineWidth * 2.5), max(5, lineWidth))
        w = max(5 / ratio, 1.5 * lineWidth / ratio)
        linecolor = "#000" if value > 0 else "#ff0"

        if not isPacific:

            centerOfLine = ((x + x2) / 2 * ratio, (y + y2) / 2 * ratio)

            if self.intersectsNode(fromNode, toNode):
                d = 20
                centerOfLine = (centerOfLine[0] + d, centerOfLine[1] + d)
                z1 = self.canvas.create_line((x * ratio , y * ratio , centerOfLine[0] , centerOfLine[1]),
                        width=lineWidth, arrow=tk.FIRST, arrowshape=arrowShape, fill=linecolor)
                z2 = self.canvas.create_line((centerOfLine[0] , centerOfLine[1], x2 * ratio , y2 * ratio),
                        width=lineWidth, fill=linecolor)

                z3 = self.mapDraw.line((x * ratio , y * ratio , centerOfLine[0] , centerOfLine[1]),
                        width=lineWidth, fill=linecolor)
                z4 = self.mapDraw.polygon(
                                        (x * ratio, y * ratio,
                                        (x - w * dx + w * dy) * ratio, (y - w * dx - w * dy) * ratio,
                                        (x - w * dx - w * dy) * ratio, (y + w * dx - w * dy) * ratio
                                    ),
                                     outline=linecolor, fill=linecolor)

                z4 = self.mapDraw.line((centerOfLine[0] , centerOfLine[1], x2 * ratio , y2 * ratio),
                        width=lineWidth, fill=linecolor)

                if value == 0:
                    self.zeroArrows += [z1, z2, z3, z4]


            else:
                z1 = self.canvas.create_line((x * ratio , y * ratio , x2 * ratio , y2 * ratio),
                        width=lineWidth, arrow=tk.FIRST, arrowshape=arrowShape, fill=linecolor)

                z2 = self.mapDraw.line((x * ratio , y * ratio , x2 * ratio , y2 * ratio),
                        width=lineWidth, fill=linecolor)

                z3 = self.mapDraw.polygon(
                                    (x * ratio, y * ratio,
                                    (x - w * dx + w * dy) * ratio, (y - w * dx - w * dy) * ratio,
                                    (x - w * dx - w * dy) * ratio, (y + w * dx - w * dy) * ratio
                                    ),
                                     outline=linecolor, fill=linecolor)

                if value == 0:
                    self.zeroArrows += [z1, z2, z3]

            self.arrowLabels.append([centerOfLine, value])


        else:  # Trade route crosses edge of map

            if x < x2:  # Asia to America
                z0 = self.canvas.create_line((x * ratio , y * ratio , (-self.mapWidth + x2) * ratio , y2 * ratio),
                                    width=1, fill=linecolor, arrow=tk.FIRST, arrowshape=arrowShape)
                z1 = self.canvas.create_line(((self.mapWidth + x) * ratio , y * ratio , x2 * ratio , y2 * ratio),
                                    width=1, fill=linecolor, arrow=tk.FIRST, arrowshape=arrowShape)

                z2 = self.mapDraw.line((x * ratio , y * ratio , (-self.mapWidth + x2) * ratio , y2 * ratio),
                                    width=1, fill=linecolor)
                z3 = self.mapDraw.line(((self.mapWidth + x) * ratio , y * ratio , x2 * ratio , y2 * ratio),
                                    width=1, fill=linecolor)
                z4 = self.mapDraw.polygon(
                                        (x * ratio, y * ratio,
                                        (x - w * dx + w * dy) * ratio, (y - w * dx - w * dy) * ratio,
                                        (x - w * dx - w * dy) * ratio, (y + w * dx - w * dy) * ratio
                                    ),
                                     outline=linecolor, fill=linecolor)

                # fraction of trade route left of "date line"
                f = abs(self.mapWidth - float(x2)) / (self.mapWidth - abs(x - x2))
                # y coordinate where trade route crosses date line
                yf = y2 + f * (y - y2)

                centerOfLine = (x / 2 * ratio, (yf + y) / 2 * ratio)
                if value == 0:
                    self.zeroArrows += [z0, z1, z2, z3, z4]

            else:  # Americas to Asia
                z0 = self.canvas.create_line((x * ratio , y * ratio , (self.mapWidth + x2) * ratio , y2 * ratio),
                                    width=1, fill=linecolor, arrow=tk.FIRST, arrowshape=arrowShape)
                z1 = self.canvas.create_line(((-self.mapWidth + x) * ratio , y * ratio , x2 * ratio , y2 * ratio),
                                    width=1, fill=linecolor, arrow=tk.FIRST, arrowshape=arrowShape)

                z2 = self.mapDraw.line((x * ratio , y * ratio , (self.mapWidth + x2) * ratio , y2 * ratio),
                                    width=1, fill=linecolor)
                z3 = self.mapDraw.line(((-self.mapWidth + x) * ratio , y * ratio , x2 * ratio , y2 * ratio),
                                    width=1, fill=linecolor)
                z4 = self.mapDraw.polygon(
                                        (x * ratio, y * ratio,
                                        (x - w * dx + w * dy) * ratio, (y - w * dx - w * dy) * ratio,
                                        (x - w * dx - w * dy) * ratio, (y + w * dx - w * dy) * ratio
                                    ),
                                     outline=linecolor, fill=linecolor)

                f = abs(self.mapWidth - float(x)) / (self.mapWidth - abs(x - x2))
                yf = y + f * (y2 - y)

                centerOfLine = ((self.mapWidth + x) / 2 * ratio, (yf + y) / 2 * ratio)

            self.arrowLabels.append([centerOfLine, value])

            if value == 0:
                self.zeroArrows += [z0, z1, z2, z3, z4]


    def clearMap(self, update=False):
        self.canvas.create_image((0, 0), image=self.provinceImage, anchor=tk.NW)
        self.drawImg = self.mapImg.convert("RGB")
        self.mapDraw = ImageDraw.Draw(self.drawImg)
        if update:
            self.canvas.update()


    def drawMap(self, clear=False):
        """Top level method for redrawing the world map and trade network"""

        logging.debug("Drawing map..")
        t0 = time.time()

        self.clearMap(clear)
        self.done = True
        ratio = self.ratio
        self.zeroArrows = []


        # draw incoming trade arrows
        t1 = time.time()
        nArrows = 0
        self.arrowLabels = []

        for n, node in enumerate(self.tradenodes):
            x, y = self.getNodeLocation(n + 1)

            try:
                data = self.nodeData[node[0]]

                if "incomingValue" in data:
                    for i, value in enumerate(data["incomingValue"]):
                        fromNodeNr = data["incomingFromNode"][i]
                        if fromNodeNr >= len(self.tradenodes):
                            continue
                        self.drawArrow(fromNodeNr, n + 1, value, self.getNodeRadius(data))
                        nArrows += 1
            except KeyError:
                self.showError("Encountered unknown trade node %s!" % node[0],
                               "An invalid trade node was encountered. Savegame doesn't match" +
                               " currently installed EU4 version, or incorrect mod selected.")
                return
        logging.debug("Drew %i arrows in %.2fs" % (nArrows, time.time() - t1))

        # draw trade arrow labels
        for [centerOfLine, value] in self.arrowLabels:
            if value > 0 or self.showZeroVar.get():
                valueStr = "%i" % ceil(value) if (value >= 2 or value <= 0) else ("%.1f" % value)
                z5 = self.canvas.create_text(centerOfLine, text=valueStr, fill=WHITE)
                z6 = self.mapDraw.text((centerOfLine[0] - 4, centerOfLine[1] - 4), valueStr, fill=WHITE)

                if value == 0:
                    self.zeroArrows += [z5, z6]

        # draw trade nodes and their current value
        nNodes = 0
        for n, node in enumerate(self.tradenodes):
            x, y = self.getNodeLocation(n + 1)

            data = self.nodeData[node[0]]
            s = self.getNodeRadius(data)

            if self.config["nodesShow"] == "Total value":
                v = data["currentValue"]
                tradeNodeColor = "#d00"
            elif self.config["nodesShow"] == "Local value":
                v = data["localValue"]
                tradeNodeColor = "#90c"

            digits = len("%i" % v)

            self.canvas.create_oval((x * ratio - s, y * ratio - s, x * ratio + s, y * ratio + s),
                                    outline=tradeNodeColor, fill=tradeNodeColor)
            self.canvas.create_text((x * ratio, y * ratio), text=int(v), fill="white")

            self.mapDraw.ellipse((x * ratio - s, y * ratio - s, x * ratio + s, y * ratio + s),
                                    outline=tradeNodeColor, fill=tradeNodeColor)
            self.mapDraw.text((x * ratio - 3 * digits, y * ratio - 4), "%d" % v, fill=WHITE)
            nNodes += 1
        logging.debug("Drew %i nodes" % nNodes)

        self.canvas.create_text((10, self.mapHeight * ratio - 60), anchor="nw",
                                text="Player: %s" % self.player, fill="white")

        self.canvas.create_text((10, self.mapHeight * ratio - 40), anchor="nw",
                                text="Date: %s" % self.date, fill="white")

        self.canvas.create_text((10, self.mapHeight * ratio - 20), anchor="nw",
                                text="Version: %s" % self.saveVersion, fill="white")

        self.mapDraw.text((10, self.mapHeight * ratio - 44), "Player: %s" % self.player, fill=WHITE)
        self.mapDraw.text((10, self.mapHeight * ratio - 24), "Date: %s" % self.date, fill=WHITE)

        logging.info("Finished drawing map in %.3f seconds" % (time.time() - t0))


    def pacificTrade(self, x, y , x2, y2):
        """Check whether a line goes around the east/west edge of the map"""

        directDist = sqrt(abs(x - x2) ** 2 + abs(y - y2) ** 2)
        xDistAcross = self.mapWidth - abs(x - x2)
        distAcross = sqrt(xDistAcross ** 2 + abs(y - y2) ** 2)

        return (distAcross < directDist)


    def saveMap(self):
        """Export the current map as a .gif image"""

        logging.info("Saving map image...")

        savename = tkFileDialog.asksaveasfilename(defaultextension=".gif", filetypes=[("GIF file", ".gif")], initialdir=os.path.expanduser("~"),
                                                  title="Save as..")
        if savename:
            try:
                self.drawImg = self.drawImg.convert("P", palette=Image.ADAPTIVE, dither=Image.NONE, colors=8)
                self.drawImg.save(savename)
            except Exception as e:
                logging.error("Problem saving map image: %s" % e)


    def clickMap(self, *args):
        # TODO: implement zoom function
        x = args[0].x
        y = args[0].y
        self.zoomed = not self.zoomed

        logging.info("Map clicked at (%i, %i), self.zoomed is now %s" % (x, y, self.zoomed))


    def showError(self, logMessage, userMessage):
        if not userMessage:
            userMessage = logMessage
        logging.error(logMessage)
        tkMessageBox.showerror("Error", userMessage)


def sign(self, v):
    if v < 0:
        return -1
    else:
        return 1

def removeComments(txt):
    lines = txt.split("\n")
    for i in range(len(lines)):
        lines[i] = lines[i].split("#")[0]
    return "\n".join(lines)


class InvalidTradeNodeException(Exception):
    def __init__(self, msg):
        Exception.__init__(self)
        self.message = msg


class ReadError(Exception):
    def __init__(self, msg):
        Exception.__init__(self)
        self.message = msg


class ParseError(Exception):
    def __init__(self, msg):
        Exception.__init__(self)
        self.message = msg


if __name__ == "__main__":

    debuglevel = logging.DEBUG
    if len(sys.argv) > 1:
        arg = sys.argv[1]
        if arg in ["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"]:
            debuglevel = eval("logging." + arg)

    logging.basicConfig(filename="tradeviz.log", filemode="w", level=debuglevel,
                        format="[%(asctime)s] %(levelname)s: %(message)s",
                        datefmt="%Y/%m/%d %H:%M:%S")

    tv = TradeViz()

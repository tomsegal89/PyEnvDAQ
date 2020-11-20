##### import #####
from numpy import genfromtxt,zeros,float64,append
#import numpy # this is just for numpy.append, maybe theres a way to import just that one without overriding the usual append function?
from time import sleep,strftime,time,mktime
import datetime
from os import fsync,makedirs
from os.path import getsize,getctime,exists
from sys import argv,exit
from PyQt5.QtWidgets import QApplication,QTableWidgetItem,QAbstractItemView,QMainWindow
from PyEnvDAQGUI import Ui_PyEnvDAQ
from PyQt5.QtGui import QIcon
#from PyQt5.QtCore import QObject,pyqtSignal
from PyDAQmx import DAQmxLoadTask, DAQmxCreateTask, byref, DAQmxCreateAIVoltageChan,DAQmx_Val_Cfg_Default, \
                    DAQmx_Val_Volts,DAQmxCfgSampClkTiming, DAQmx_Val_Rising,DAQmx_Val_ContSamps, \
                    DAQmxStartTask, TaskHandle, int32, DAQmxReadAnalogF64, DAQError, DAQmxStopTask, \
                    DAQmxClearTask
from threading import Thread
import pyqtgraph as pg
#from math import floor
from PyEnvDAQCommunicator import PyEnvDAQCommunicator
from PyEnvDAQActionsExecuter import PyEnvDAQActionsExecuter
# main class
import requests # used for communication with the MCS box
from pymodbus3.client.sync import ModbusTcpClient
import struct

class Main(QMainWindow):

    # "constants"
    MEASUREMENT_PERIOD_s = 1 # the reciprocal of the sampling rate. (in s)
                               # (must be updated in THe Website as well) (for values smaller than 1s one should make sure the timestamps are saved to the required precision)
    NOTIFICATION_DELAY_s = 10 # 60*60 # defines the (maximal) frequency for sending warning messages and Telegram notifications 
    # PLOT_RESOLUTION = 10000 # defines the maximal amount of points that can be plotted at a time per channel
    # decide how often (in seconds) the plots should be automatically update if autoupdate is set.
    #   (for instance, '"hours":5*60"' means that if the time window for plotting is between 1 hour and 1 day,
    #   the plot will be automatically updated every 5*60 seconds, as in every 5 minutes)
    AUTO_UPDATE_DICT = {"seconds":5, "minutes":30, "hours":5*60, "days":60*60, \
                               "weeks":24*60*60,"months":24*60*60}
    DATA_FILES_FOLDER = "../../data/" # save data into tritium:/PyEnvDAQ/data
    LOCAL_DATA_FILES_FOLDER = "D:/EnvironmentData/" # save a copy of the data locally as well
    THEE_FILES_FOLDER = "../../THeeFiles/" # save the THee files into tritium:/PyEnvDAQ/THeeFiles
    # THEE_FILES_FOLDER = "../../../Data/env data" # save the THee files into tritium:/Data/env data
    EXPORTED_DATA_FILES_FOLDER = "../../exportedData/" # save exported data into tritium:/PyEnvDAQ/exportedData
    CONTROL_FILE_PATH = "../../PyControlFile.txt" # the control path should be in tritium/PyEnvDAQ/PyControlFile.txt
    He_FLOW_METER_TIME_STAMPS_FILE_PATH = "../../HeFlowTimeStamps.txt" # stores timestamps of rising edges for plotting.
    N2_FLOW_METER_TIME_STAMPS_FILE_PATH = "../../N2FlowTimeStamps.txt" # stores timestamps of rising edges for plotting.
    HE_FLOW_METER_CHANNEL_INDEX = 16
    N2_FLOW_METER_CHANNEL_INDEX = 17
    THee_FILES_CREATION_PERIOD_BUTTON = 60*60*24*7 # pressing the create THee files button will re-create the THee files for the last week
    # THee_FILES_CREATION_PERIOD_AUTOMATIC = 60*60*24 # the THee files for the last day will be automatically re-created every hour
    #THee_FILES_UPDATING_PERIOD = 60*60 # how often should the THee files be updated? (in seconds)
    DATA_PRECISION = 4 # how many digits after the decimal point should be saved for the environmental data?
                       #    (note that 4 is the minimal number for which mon1,2 will display significant digits)
    # Telegram user id's (confusingly officially called "chat id"'s for messaging individual users, although its impossible to message groups)
    TELEGRAM_ID_MARC = "235436034"
    TELEGRAM_ID_TOM = "296594405"
    TELEGRAM_ID_THe_Trap = "280912844" # actually called THe Trap, as in with a space, not an underscore. General user
    # Telegram bot "tokens" (used to control bots, for instance to send messages using them)
    TELEGRAM_TOKEN_THeTrap_Test = "283251386:AAESL_IwUGtOwKncGWU0d0RXg2w1cmPzM3Q" # not really planning to use it in this program
    TELEGRAM_TOKEN_Notification_bot = "249228892:AAG_eZxqsDIffy0LtKru1nAVufGW1Qr4gIg" # not really planning to use it in this program
    TELEGRAM_TOKEN_Alert_bot = "274092082:AAEkGpKd0VAjWhEuFDDSG9SUf-KUYwqvQ_0"
    GAS_COUNTER_THRESHOLD = 1 # jump size for both flow meters (He and N2), in Volts
    GAS_COUNTER_CALIBRATION_FACTOR = 28.3168; # how much N2 and/or He was detected in-between two rising edges, in litres

    def __init__(self):
        super().__init__() # initialize the QMainWindow parameters of this object?
        self.readControlFile() # read the information from the control file 
        #self.preparePyEnvFile() # prepares the header text so that it can saved into new files. (Overwritten whenever starting a new measurement)
        self.ui = Ui_PyEnvDAQ() # initialize the gui
        self.ui.setupUi(self) # setup the gui
        self.configureUi() # populate the gui table and comboboxes with data from the control file among other things
        self.actionsExecuter = PyEnvDAQActionsExecuter(self) # False shows that its a general actions executer and not an automatic THee updating actions executer
        self.connectUi() # connects the various gui components to functions
        self.isRunning = False
        self.lastAlertTimestamp = None # "None" means new warning messages and notifications can be sent immediately.
    
        self.previousHeFlowMeterValue = None
        self.currentHeFlowMeterValue = None
        self.previousN2FlowMeterValue = None
        self.currentN2FlowMeterValue = None
        self.currentDataTimeStamp = None

        self.startMeasurement()

    def readControlFile(self):
        # extract information from the control file
        try:
            controlFile = open(self.CONTROL_FILE_PATH,"r")
        except IOError:
            printMessage("error","Could not open PyControlFile.txt for writing. Please check the path and restart PyEnvDAQ.")
        else:
            self.controlFileText = controlFile.read()
            controlFile.close()
            controlFileTextLines = self.controlFileText.split("\n")
            i = 2 # 2 and not 0 to skip the first line ("NI Card: ...") and Time
            self.numOfNIChannels = 0
            self.numOfMCSChannels = 0
            self.numOfEthernetChannels = 0
            # count the number of channels to be read from the NI card
            line = controlFileTextLines[i]
            i = i +1
            self.numOfNIChannels = self.numOfNIChannels + 1
            while i<len(controlFileTextLines) and not "MCS Box" in line:
                self.numOfNIChannels = self.numOfNIChannels + 1
                line = controlFileTextLines[i]
                i = i +1
            self.numOfNIChannels = self.numOfNIChannels - 1 # compensate for the +1 erronously made before (because this is not an NI channel line)
            # count the number of channels to be read from the MCS box
            while i<len(controlFileTextLines) and not "Ethernet" in line:
                line = controlFileTextLines[i]
                self.numOfMCSChannels = self.numOfMCSChannels + 1
                i = i + 1
            self.numOfMCSChannels = self.numOfMCSChannels - 1 # compensate for the +1 erronously made before (because this is not an NI channel line)
            while i<len(controlFileTextLines):
                line = controlFileTextLines[i]
                self.numOfEthernetChannels = self.numOfEthernetChannels + 1
                i = i + 1
            # print(self.numOfNIChannels," ",self.numOfMCSChannels," ",self.numOfEthernetChannels)
            self.numOfChannels = self.numOfNIChannels + self.numOfMCSChannels + self.numOfEthernetChannels
        # sort and store the NI card-related data
        try:               
            controlFileDataNI = genfromtxt(self.CONTROL_FILE_PATH,delimiter="\t", skip_header = 2, skip_footer = self.numOfMCSChannels+1+self.numOfEthernetChannels+1, \
                              dtype=["U15","U15","<f8","<f8","<f8","<f8","U15","U15","<f8"], \
                              names=('names','units','factors','offsets','min','max','warningLow','warningHigh','index'))
            controlFileDataMCS = genfromtxt(self.CONTROL_FILE_PATH,delimiter="\t", skip_header = 2 + self.numOfNIChannels + 1, skip_footer = self.numOfEthernetChannels+1,\
                              dtype=["U15","U15","<f8","<f8","<f8","<f8","U15","U15","<f8"], \
                              names=('names','units','factors','offsets','min','max','warningLow','warningHigh','index'))
            controlFileDataMKSFlow = genfromtxt(self.CONTROL_FILE_PATH,delimiter="\t", skip_header = 2 + self.numOfNIChannels + 1 + self.numOfMCSChannels +1, \
                              dtype=["U15","U15","<f8","<f8","<f8","<f8","U15","U15","<f8"], \
                              names=('names','units','factors','offsets','min','max','warningLow','warningHigh','index'))
            controlFileDataMKSFlow = controlFileDataMKSFlow.ravel()
        except IOError:
            printError("Could not open PyControlFile.txt for writing. Please check the path and restart PyEnvDAQ.")
        else:
            self.channelNames = []
            self.channelUnits = []
            self.channelFactors = []
            self.channelOffsets = []
            self.channelMins = []
            self.channelMaxes = []
            self.channelMinsAndMaxes = []
            self.channelWarningLow = []
            self.channelWarningHigh = []
            self.channelIndex = []

            for line in controlFileDataNI:
                self.channelNames.append(line[0])
                self.channelUnits.append(line[1])
                self.channelFactors.append(line[2])
                self.channelOffsets.append(line[3])
                self.channelMins.append(line[4])
                self.channelMaxes.append(line[5])
                self.channelMinsAndMaxes.append("["+str(line[4])+","+str(line[5])+"]")
                self.channelWarningLow.append(line[6])
                self.channelWarningHigh.append(line[7])
                self.channelIndex.append(int(line[8]))
            for line in controlFileDataMCS:
                self.channelNames.append(line[0])
                self.channelUnits.append(line[1])
                self.channelFactors.append(line[2])
                self.channelOffsets.append(line[3])
                self.channelMins.append(line[4])
                self.channelMaxes.append(line[5])
                self.channelMinsAndMaxes.append("["+str(line[4])+","+str(line[5])+"]")
                self.channelWarningLow.append(line[6])
                self.channelWarningHigh.append(line[7])
                self.channelIndex.append(int(line[8]))
            for line in controlFileDataMKSFlow: # a bit dumb because controlFileDataMKSFlow is just 1 line
                self.channelNames.append(line[0])
                self.channelUnits.append(line[1])
                self.channelFactors.append(line[2])
                self.channelOffsets.append(line[3])
                self.channelMins.append(line[4])
                self.channelMaxes.append(line[5])
                self.channelMinsAndMaxes.append("["+str(line[4])+","+str(line[5])+"]")
                self.channelWarningLow.append(line[6])
                self.channelWarningHigh.append(line[7])
                self.channelIndex.append(int(line[8]))
        ## the following code is to be used when loading the task instead of creating it
        #self.numOfNIChannels = 23
        #self.channelNames = ['Time','T_Magnet_Top','p_Bore','p_Reservoir','p_Mag_Room','p_LN2','p_UHV','Fluxgate_1','Fluxgate_2_nc','Valve_Bore', \
        #    'Valve_Reservoir','Mon1','Mon2','Humidity','p_Prevac','p_Mag_Room_Com','APR3_1Torr','RoomHeater','RoomCooler','Multipurpose4_10V', \
        #    'Multipurpose5_1V','T_Glovebox','LN2_Counter','T_Top_Window','T_Top_Door','T_Mag_Wall','T_APR1']
        #self.channelUnits = ['s','C','Pa','mBar','mBar','none','log 1e-11 mBar','muT','muT','V','V','?','?','%','log mBar','Pa?','mBar','C','C','V','C','C','L/min','C','C','C','C']
        #self.channelFactors = [1,4.639,20,1,130.53,137,1,1.561,1,1,1,1,1,10,0.0000031623,30009,887,1,1,1,4.639,4.6329,1,-0.001821,-0.001827,-0.0018783,-0.001851]
        #self.channelOffsets = [0,19.09,0,0,1044.797,0,0,0,0,0,0,0,0,0,0,0,0,0,0,0,19.09,25.128,0,27.933001,27.346001,27.339001,27.541]

        #self.channelMins = [0,-5,-1,-10,-1,-10,-10,-10,-10,-10,-10,-10,-10,-10,-10,0,-10,-10,-10,-10,0,0,0,0]
        #self.channelMaxes = [0,5,1,10,1,10,10,10,10,10,10,10,10,10,10,5,10,10,10,10,4095,4095,4095,4095]
        ##self.channelMinsAndMaxes = []
        ##self.channelWarningLow = []
        ##self.channelWarningHigh = []
        #self.channelIndex = [-1,0,1,2,3,4,5,6,7,13,9,10,11,12,14,15,8,16,17,18,19,20,21,1,2,3,4]
        
    

    def preparePyEnvFile(self):
        # prepare the pyenv file header
        self.headerText = "Saving " + str(self.numOfNIChannels) + " NI channels and " + str(self.numOfMCSChannels) + " MCS channels and 1 MKSFlow channel of data at 1 Sa/s since "+strftime("%d-%m-%Y")+" "+strftime("%H:%M:%S")+".\n" \
            +"\n" \
            + self.controlFileText \
            + "\n"
        self.headerText = self.headerText + "\n" + "----------DATA----------\n"
        self.headerSize = len(self.headerText.split("\n"))-1
        # prepare the pyenv file
        self.pyEnvDataFilePath = self.DATA_FILES_FOLDER+strftime("%Y-%m-%d")+".pyenv"
        # self.pyEnvLocalDataFilePath = self.LOCAL_DATA_FILES_FOLDER+strftime("%Y-%m-%d")+".pyenv"
        # if the file doesn't exist yet, create it and write a header for it
        if not exists(self.pyEnvDataFilePath):
            try:
                self.pyEnvDataFile = open(self.pyEnvDataFilePath,"w")
                # self.pyEnvLocalDataFile = open(self.pyEnvLocalDataFilePath,"w")
            except IOError:
                self.printError("could not open "+self.pyEnvDataFilePath+" for writing.")
            else:
                self.pyEnvDataFile.write(self.headerText)
                # self.pyEnvLocalDataFile.write(self.headerText)

                self.pyEnvDataFile.close()
                # self.pyEnvLocalDataFile.close()

    def setupNICard(self):
        ## create the NI task that reads data from the NI card.
        #self.taskHandle = TaskHandle()
        #DAQmxCreateTask("pyEnvDAQ",byref(self.taskHandle))
        ## (see http://zone.ni.com/reference/en-XX/help/370471AE-01/daqmxcfunc/daqmxcreatetask/ )
        ##[DAQmxCreateAIVoltageChan(self.taskHandle, "Dev1/ai"+str(self.channelAddresses[i]), self.channelNames[i+1], DAQmx_Val_Cfg_Default, int(self.channelMins[i+1]), \
        ##    int(self.channelMaxes[i+1]), DAQmx_Val_Volts, None) for i in range(self.numOfRecordedChannels)] # we use i+1 instead of i to skip the time channel
        ##print("numOfNIChannels: ",self.numOfNIChannels)
        #channelIndices = ["Dev1/ai"+str(self.channelIndex[i]) for i in range(self.numOfNIChannels)] # note that this also contains the time channel
        ##[print("channel index: ",channelIndices[i]," name: ",self.channelNames[i]," min ",int(self.channelMins[i]), \
        ##    "max ",int(self.channelMaxes[i]),"\n") for i in range(1,self.numOfNIChannels)]
        #[DAQmxCreateAIVoltageChan(self.taskHandle, channelIndices[i], self.channelNames[i], DAQmx_Val_Cfg_Default, int(self.channelMins[i]), \
        #    int(self.channelMaxes[i]), DAQmx_Val_Volts, None) for i in range(1,self.numOfNIChannels)] # we start from 1 to skip the time channel
        #
        #DAQmxCfgSampClkTiming(self.taskHandle,"",1/self.MEASUREMENT_PERIOD_s,DAQmx_Val_Rising,DAQmx_Val_ContSamps,self.numOfNIChannels-1) # -1 because we don't actually record the time channel
        ## (see http://zone.ni.com/reference/en-XX/help/370471AE-01/daqmxcfunc/daqmxcfgsampclktiming/ )
        ## 
        #try:
        #    DAQmxStartTask(self.taskHandle)
        #except DAQError:
        #    self.printError("execution of DAQmxStartTask failed - THe-Monitor is probably on \"Run\". Try \"Pause\"ing it and restarting PyEnvDAQ.")

        self.taskHandle = TaskHandle()
        #DAQmxLoadTask("enviroment_measurement",byref(self.taskHandle))
        DAQmxLoadTask("PyEnvDAQTask",byref(self.taskHandle))
        DAQmxStartTask(self.taskHandle)

    def configureUi(self):

        # general ui changes
        self.setWindowTitle("PyEnvDAQ") # change the name of the program
        self.setWindowIcon(QIcon('icon.png')) # change the icon of the program
        self.ui.labelAlert.setStyleSheet("QLabel { background-color: red; }") # set the color of the alert line
        self.ui.labelAlert.hide() # hide the alert line
        self.ui.labelProgramName.setStyleSheet("QLabel { color:green; }") # set the color of the program name line
        self.ui.labelDataWillBeSavedInto.setStyleSheet("QLabel { color:blue; }") # set the color of the program name line
        #self.ui.tabWidget.setCurrentIndex(0) # set the default tab to be the channels tab
        self.ui.tabWidget.setCurrentIndex(1) # set the default tab to be the actions tab

        # channels tab
        self.ui.tableChannels.setSortingEnabled(False)
        self.ui.tableChannels.clearContents()
        self.ui.tableChannels.setRowCount(self.numOfChannels+1)
        # populate the channel tables with the NI card's channel names, factors, offsets, units and ranges
        # add the time
        self.ui.tableChannels.setItem(0,0,QTableWidgetItem("time")) # channel names
        self.ui.tableChannels.setItem(0,1,QTableWidgetItem("s")) # channel units
        # self.ui.tableChannels.setItem(0,2,QTableWidgetItem(0)) # channel factors        
        # self.ui.tableChannels.setItem(0,3,QTableWidgetItem(0)) # channel offsets
        for i in range(self.numOfChannels):
            print(i)
            print(self.channelNames[i])
            self.ui.tableChannels.setItem(i+1,0,QTableWidgetItem(self.channelNames[i])) # channel names
            self.ui.tableChannels.setItem(i+1,1,QTableWidgetItem(self.channelUnits[i])) # channel units
            self.ui.tableChannels.setItem(i+1,2,QTableWidgetItem(str(self.channelFactors[i]))) # channel factors
            self.ui.tableChannels.setItem(i+1,3,QTableWidgetItem(str(self.channelOffsets[i]))) # channel offsets
            #self.ui.tableChannels.setItem(i,4,QTableWidgetItem(self.channelMinsAndMaxes[i])) # channel raw range
            # 5 (raw value (V)) will be updated continously from elsewhere.
            # 6 (calibrated value) will be updated continously from elsewhere.
            statusLine = ""
            if not (self.channelWarningLow[i]=="-Infinity" and self.channelWarningHigh[i]=="Infinity"):
                self.ui.tableChannels.setItem(i+1,7,QTableWidgetItem("["+self.channelWarningLow[i]+","+self.channelWarningHigh[i]+"]")) # channel safe range
                self.ui.tableChannels.setItem(i+1,8,QTableWidgetItem("ok")) # channel statuses
        #self.ui.channelsTable.EditTrigger(QAbstractItemView.NoEditTriggers) # lock table? doesn't work?
            self.ui.tableChannels.resizeColumnsToContents()
        # actions tab
        # update plotting comboboxes
        # self.ui.comboBoxChannel2.addItem("") # make it possible to not select any channel for channel 2
        # for i in range(1,self.numOfChannels): # 1 because we want to both start the count from 1 and skip the time channel
        #     newComboBoxOption = str(i)+": "+self.channelNames[i]
        #     self.ui.comboBoxChannel1.addItem(newComboBoxOption)
        #     self.ui.comboBoxChannel2.addItem(newComboBoxOption)

        # self.ui.comboBoxTimeDuration.setCurrentIndex(2) # set the default time duration to 4
        # self.ui.comboBoxTimeUnit.setCurrentIndex(0) # set the default time unit to be seconds
        # self.ui.comboBoxChannel1.setCurrentIndex(1) # set the default first channel to be p_bore
        # self.ui.comboBoxChannel2.setCurrentIndex(2) # set the default first channel to be p_reservoir
        
        # set the default plotting time to 4 hours and the default plotted channels to p_bore and p_reservoir
        self.ui.comboBoxTimeDuration.setCurrentIndex(2) # set the default time duration to 4
        self.ui.comboBoxTimeUnit.setCurrentIndex(2) # set the default time unit to be seconds
        self.ui.comboBoxChannel1.setCurrentIndex(0) # set the default first channel to be p_bore
        self.ui.comboBoxChannel2.setCurrentIndex(2) # set the default first channel to be p_reservoir
          
        # self.ui.progressBarExecute.setValue(0) # set the export plot data progress bar to 0 percent

        # set the start and end dates to be today's date
        self.ui.textEditStartDate.setText(strftime("%Y.%m.%d")+" "+strftime("%H:%M:%S"))
        self.ui.textEditEndDate.setText(strftime("%Y.%m.%d")+" "+strftime("%H:%M:%S"))

        # messages tab
        # initialize the messages table
        self.ui.tableMessages.setSortingEnabled(False)
        self.ui.tableMessages.clearContents()
        self.ui.tableMessages.setRowCount(1)
        self.ui.tableMessages.setItem(0,0,QTableWidgetItem(strftime("%Y-%m-%d %H:%M:%S"))) # message timestamp
        self.ui.tableMessages.setItem(0,1,QTableWidgetItem("PyEnvDAQ started")) # message content
        self.ui.tableMessages.resizeColumnsToContents()

    def printMessage(self,content):
        # write the message into the messages table
        numOfRows = self.ui.tableMessages.rowCount()
        self.ui.tableMessages.setRowCount(numOfRows+1)
        self.ui.tableMessages.setItem(numOfRows,0,QTableWidgetItem(strftime("%Y-%m-%d %H:%M:%S"))) # message timestamp
        self.ui.tableMessages.setItem(numOfRows,1,QTableWidgetItem(content)) # message content
        self.ui.tableMessages.resizeColumnsToContents()

    def printError(self,content):
        # disable DAQ interactivity
        self.ui.pushButtonStart.setEnabled(False)
        self.ui.pushButtonPause.setEnabled(False)  
        self.ui.labelAlert.show() # show the alert sign
        self.ui.tabWidget.setCurrentIndex(2) # go to the messages tab
        self.printMessage(content)

    def printWarning(self,channelIndex,warningThresholdType):
        # produce an alert sign (if there isn't one already)
        if self.ui.labelAlert.isVisible()==False:
            self.ui.labelAlert.show() # show the alert sign
            self.ui.tabWidget.setCurrentIndex(2) # go to the messages tab
            self.ui.pushButtonClearAlert.setEnabled(True)
        # prepare the message
        message = "warning: " + self.channelNames[channelIndex]+" is too " + warningThresholdType + "\n" \
                + "Warnings are reported at most once every " + NOTIFICIATION_DELAY_s + "s to prevent spam and so some might be supressed.\n" \
                + "Use the \"clear alert\" button in PyEnvDAQ to clear the alert sign."
        self.lastAlertTimestamp = time() # update the last alert timestamp
        if (time()-self.lastAlertTimeStamp)>self.NOTIFICATION_DELAY_s: # produce GUI and Telegram messages (if didn't do so recently)
            self.printMessage(message) # produce a GUI message
            # send Telegram notifications
            urlString = "https://api.telegram.org/bot"+self.TELEGRAM_TOKEN_Alert_bot+"/sendMessage?chat_id="+self.TELEGRAM_ID_MARC+"&text="+message # to Marc
            urlString = "https://api.telegram.org/bot"+self.TELEGRAM_TOKEN_Alert_bot+"/sendMessage?chat_id="+self.TELEGRAM_ID_TOM+"&text="+message # to Tom
            urlString = "https://api.telegram.org/bot"+self.TELEGRAM_TOKEN_Alert_bot+"/sendMessage?chat_id="+self.TELEGRAM_ID_The_Trap+"&text="+message # to the general user

    def connectUi(self):
        self.ui.pushButtonStart.clicked.connect(self.startMeasurement)
        self.ui.pushButtonPause.clicked.connect(self.pauseMeasurement)
        self.ui.pushButtonClearAlert.clicked.connect(self.clearAlert)
        self.ui.pushButtonExecute.clicked.connect(self.actionsExecuter.executeButtonClicked)
      
    def connectMKSflow(self):
        # self.clientMKSflow = ModbusTcpClient('149.217.90.59')
        blah = 0
  
    def startMeasurement(self):
        print("started startMeasurement \n")
        if not self.isRunning:     
            self.ui.pushButtonStart.setEnabled(False)
            self.ui.pushButtonPause.setEnabled(True)
            # setup the NI card and the pyEnv file
            self.setupNICard()
            self.preparePyEnvFile()
            self.connectMKSflow()
            # open the flow meters timestamp files for appending
            try:
                self.HeFlowMeterTimeStampsFile = open(self.He_FLOW_METER_TIME_STAMPS_FILE_PATH,"a")
            except IOError:
                self.printError("could not open "+self.He_FLOW_METER_TIME_STAMPS_FILE_PATH+" for writing.")
            try:
                self.N2FlowMeterTimeStampsFile = open(self.N2_FLOW_METER_TIME_STAMPS_FILE_PATH,"a")
            except IOError:
                self.printError("could not open "+self.N2_FLOW_METER_TIME_STAMPS_FILE_PATH+" for writing.")

            # establish the data recording process
            self.gasFlowTimer = datetime.datetime.now() # this will be used to tell how long its been since we last updated the gas flow meters
            self.comDataRecording = PyEnvDAQCommunicator() # this object will send the new data thats being recorded in the form of signals
            self.comDataRecording.signalNewData.connect(self.updatePyEnvFileAndGUI) # these signals will then trigger updatePyEnvFileAndGUI
            #self.recordingThread = Thread(target=self.readEnvData, args=(self.comDataRecording,)) # readEnvData is performed in a separate thread
            self.recordingThread = Thread(target=self.readEnvData) # readEnvData is performed in a separate thread
            self.recordingThread.start()
            # establish the THee files updating process
            self.updateTHeeFilesThread = Thread(target=self.automaticallyUpdateTHeeFiles) # automaticallyUpdateTHeeFiles is performed in a separate thread
            self.updateTHeeFilesThread.start()
            # set mode to "running"
            self.isRunning = True
            self.printMessage("started measurement. Saving data into "+self.pyEnvDataFilePath)

    def pauseMeasurement(self):
        if self.isRunning:
            # stop and clear the task. Not sure whether this is really necessary.
            DAQmxStopTask(self.taskHandle)
            DAQmxClearTask(self.taskHandle)
            # stop the loop that keeps checking for new data
            self.printMessage("measurement paused.")
            self.isRunning = False
            self.HeFlowMeterTimeStampsFile.close()
            self.N2FlowMeterTimeStampsFile.close()
            self.ui.pushButtonStart.setEnabled(True)
            self.ui.pushButtonPause.setEnabled(False)

    def clearAlert(self,channelIndex):
        self.ui.pushButtonClearAlert.setEnabled(False)
        self.lastAlertTimestamp = None # allow new warning messages and notifications to be sent
        self.ui.labelAlert.hide() # hide the alert sign
        self.printMessage("alert cleared by the user. Remember that additional alerts may have been triggered and suppressed while the alert was active.")      
    # calibrates either a single given data value (if data is given and is a single value) to update the table,
    # or an entire array (if data is given and is an array) for the plotting.
    # note that in the case of calibrating LN2_Counter or LHe_Counter, an array of values must be given,
    # and therefore updating the LN/LHe flow for the table is not implemented.
    def calibrate(self,channelNum,data):
        jumps = []
        if self.channelUnits[channelNum]=="L/min":
            calibratedData = [0 for i in range(len(data))]
            for i in range(len(data)): # find where jumps (readings of ~30L gas) occured
                if(data[i]-data[i-1])>self.GAS_COUNTER_THRESHOLD:
                    jumps.append(i)
            if len(jumps)>2: # calculate the amount of gas per minute for each point
                for i in range(len(jumps)):
                    jump1 = jumps[i]
                    jump2 = jumps[i+1]
                    gasPerMinute = self.GAS_COUNTER_CALIBRATION_FACTOR/((jump2-jump1)/60)
                    for j in range(jump1,jump2):
                        calibratedData[j] = gasPerMinute
            # also return the timeStamps between which the useful data is contained
            #   (we'll crop out the res)
            return (calibratedData,jumps[0],jumps[len(jumps)-1]) 
        else:
            # logarithmic calibration
            if "log" in self.channelUnits[channelNum]:
                if isinstance(data,list):
                    return [self.channelFactors[channelNum]*10**i for i in data] 
                return self.channelFactors[channelNum]*10**data
            else:
                # linear calibration
                if isinstance(data,list):
                    return [i*self.channelFactors[channelNum]+self.channelOffsets[channelNum] for i in data]
                return data*self.channelFactors[channelNum]+self.channelOffsets[channelNum]

    def checkForWarnings(self,data):
        # only check whether warnings should be sent in case enough time passed since sending the last one
        if self.lastAlertTimestamp == None or (time()-self.lastAlertTimestamp)>NOTIFICATION_DELAY_s:
            # go over the list of high and low threshold values for the different channels and check
            #   whether warnings should be sent.
            for i in range(self.numOfChannels):
                # check the low threshold
                if self.channelWarningLow[i]!="-Infinity": # if a lower threshold was defined for this channel
                    if self.ui.tableChannels.item(i,7)<int(self.channelWarningLow[i]): # if the threshold has been crossed
                        self.printWarning(self.channelNames[i],"low") # produce a warning
                    else:
                        self.ui.tableChannels.setItem(channelIndex,8,QTableWidgetItem("ok")) # make sure the status column is on "ok"
                # check the high threshold
                if self.channelWarningHigh[i]!="Infinity": # if an upper threshold was defined for this channel
                    if self.ui.tableChannels.item(i,7)>int(self.channelWarningHigh[i]): # if the threshold has been crossed
                        self.printWarning(self.channelNames[i],"high") # produce a warning
                    else:
                        self.ui.tableChannels.setItem(channelIndex,8,QTableWidgetItem("ok")) # make sure the status column is on "ok"

    def readEnvData(self):
        print("started readEnvData \n") # commenting this out stops the program from working. why?
        dataForTable = zeros(self.numOfChannels+1, dtype=float64) # this will hold the data to update the table with. (+1 to include the time channel)
        # setup NI card-related parameters 
        dataNI = zeros((self.numOfNIChannels,), dtype=float64) # this will hold the data gathered in a single measurement. -1 because we don't record the time.        
        timeOut = 10 # 10s timeout limit?
        read = int32() # the type of data read is 32int?
        session = requests.Session()
        session.trust_env = False
        while self.isRunning == True:
            # retrieve the data from the MSC box (which is saved after the data from the NI card)
            # setup MCS box-related parameters
            res = session.get('http://tritium-remotemcs/cgi-bin/volt.cgi') # we also get something if we replace "volt" with "temp", but I don't get the values there
            content = str(res.content,"windows-1252") # get the whole HTML code for that page
            content = content[419:] # delete some bullshit before the first value
            content = content.replace("</td><td>",",") # separate the values with commas instead of with bullshit
            content = content.replace("</td></tr></table><br><table border=1><colgroup width=200 span=4></colgroup><tr><td><b>channel 5</b>,<b>channel 6</b>,<b>channel 7</b>,<b>channel 8</b></td></tr><tr><td>",",") # remove bullshit
            content = content[:-22] # get rid of some last bullshit
            content = content.split(",")
            dataMCS =[int(i,16) for i in content] # convert the data from hexadecimal to decimal format
                                                  # (note that there are 8 values here but we only save the first 4 cause we don't know what the other 4 are for)            # retrieve data from NI card's channels.
            # see http://zone.ni.com/reference/en-XX/help/370471AE-01/daqmxcfunc/daqmxreadanalogf64/
            try:
                DAQmxReadAnalogF64(self.taskHandle,1,timeOut,0,dataNI,self.numOfNIChannels,byref(read),None)
            except DAQError as err:
                self.printError("execution of DAQmxReadAnalogF64 failed. Maybe THe-Monitor is running? If so \"Pause\" it and try again.")
                self.pauseMeasurement()
            else: # this is only executed if no DAQError was raised during execution of the code in the "try:" block
                # self.checkForWarnings(dataNI) # check if some of the values are suspicious and should be reported
                timestamp = round(time()) # the time in units of s
                # save the flow data
                self.previousHeFlowMeterValue = self.currentHeFlowMeterValue
                self.previousN2FlowMeterValue = self.currentN2FlowMeterValue
                self.currentHeFlowMeterValue = dataNI[self.HE_FLOW_METER_CHANNEL_INDEX]
                self.currentN2FlowMeterValue = dataNI[self.N2_FLOW_METER_CHANNEL_INDEX]
                self.currentDataTimeStamp = timestamp

                # get MKS flow data#
                #resultMKSflow = self.clientMKSflow.read_input_registers(0x0001, 2)
                #i1MKSflow = resultMKSflow.registers[0]
                #i2MKSflow = resultMKSflow.registers[1]
                #dataMKSflow = struct.unpack('l',struct.pack('<HH',i1MKSflow,i2MKSflow))[0]/10000
                dataMKSflow=0
                # merge the data from the NI card and from the MCS box
                data = []
                for blah in dataNI:
                    data.append(blah)
                for j in range(self.numOfMCSChannels):
                    data.append(dataMCS[j])
                data.append(dataMKSflow)
                # data = append(dataNI,dataMCS)
                # data = append(data,dataMKSflow)
                dataForTable[0] = timestamp
                for j in range(self.numOfChannels):
                    dataForTable[j+1]=data[j] # +1 to skip [0] which holds the time channel
                dataPrecisionFormat = "{0:."+str(self.DATA_PRECISION)+"f}"
                writeMeIntoFile = str(timestamp)+"\t" + "\t".join([dataPrecisionFormat.format(data[j]) for j in range(self.numOfChannels)]) +"\n"
                # writeMeIntoFile = str(timestamp)+"\t" + "\t".join([str(data[j]) for j in range(self.numOfNIChannels-1+self.numOfMCSChannels)]) +"\n"
                #   (note that we save up to DATA_PRECISION=4 digits after the decimal point instead of 6 like in the original program)
                self.comDataRecording.signalNewData.emit(dataForTable,writeMeIntoFile) # emit a signal in order to trigger updatePyEnvFileAndGUI
                # (see http://stackoverflow.com/questions/7127075/what-exactly-the-pythons-file-flush-is-doing )
                sleep(self.MEASUREMENT_PERIOD_s-0.1) # read at a higher rate than the card's to make sure the buffer is cleared

    def automaticallyUpdateTHeeFiles(self):
        print("entered automaticallyUpdateTHeeFiles")
        updatedThisHourAlready = False
        THeeAutomaticUpdater = PyEnvDAQActionsExecuter(self)
        while self.isRunning:
            if datetime.datetime.now().minute == 1:
                updatedThisHourAlready = False
            # update the THee files at the first minute of every hour. If this is the first hour of a new day,
            #   update the THee files from yesterday instead. (Otherwise we would miss the last hour worth of data)
            # if ((datetime.datetime.now().minute==0 or datetime.datetime.now().minute==29) and not updatedThisHourAlready):
            if (datetime.datetime.now().minute==0 and not updatedThisHourAlready):
                print("calling THeeAutomaticUpdater.executeAction()")
                THeeAutomaticUpdater.executeAction()
                updatedThisHourAlready = True
                # self.printMessage("automatically updated the THee files.")
            sleep(1) # the loop occurs every second

    def updatePyEnvFileAndGUI(self,dataForTable,writeMeIntoFile):
        # print("started updatePyEnvFileAndGUI \n")
        self.preparePyEnvFile() # change to a new PyEnvFile and set up its header in case the day was changed
        try:
            self.pyEnvDataFile = open(self.pyEnvDataFilePath,"a") # a appends to the end of the file if it exists, as opposed to w
            # self.pyEnvLocalDataFile = open(self.pyEnvLocalDataFilePath,"a") # a appends to the end of the file if it exists, as opposed to w
        except IOError:
            self.printError("could not open "+self.pyEnvDataFilePath+" for appending.")            
        else:
            # write into the pyenv file
            self.pyEnvDataFile.write(writeMeIntoFile)
            # self.pyEnvLocalDataFile.write(writeMeIntoFile)
            self.pyEnvDataFile.flush() # transfers the data from Python's buffer to the operating system's buffer (not necessarily to disk)
            # self.pyEnvLocalDataFile.flush() # transfers the data from Python's buffer to the operating system's buffer (not necessarily to disk)
            fsync(self.pyEnvDataFile.fileno()) # transfer the data from the operating system's buffer to disk  
            # fsync(self.pyEnvLocalDataFile.fileno()) # transfer the data from the operating system's buffer to disk  
            self.pyEnvDataFile.close()
            # self.pyEnvLocalDataFile.close()
            # update the flow meter timestamps files:
            # usually this means just appending the timestamps at the end of the file, but in case a new day started, 
                # or in case the program crashed and was restarted at least 1 day after that, the current date needs to be written in first.
            # if a new day started and we didn't do it yet, go to the next line and write the date
            try:
                HeFlowMeterTimeStampsFileForReading = open(self.He_FLOW_METER_TIME_STAMPS_FILE_PATH,"r")
            except IOError:
                self.printError("could not open "+self.He_FLOW_METER_TIME_STAMPS_FILE_PATH+" for reading.")
            todaysDate = strftime("%Y-%m-%d")
            for line in HeFlowMeterTimeStampsFileForReading:
                pass
            lastLine = line
            lastDate = line.split("\t")[0]
            if (not todaysDate == lastDate):
                self.HeFlowMeterTimeStampsFile.write("\n"+strftime("%Y-%m-%d")+"\t")
                self.HeFlowMeterTimeStampsFile.flush() # transfers the data from Python's buffer to the operating system's buffer (not necessarily to disk)
                fsync(self.HeFlowMeterTimeStampsFile.fileno()) #
                self.N2FlowMeterTimeStampsFile.write("\n"+strftime("%Y-%m-%d")+"\t")
                self.N2FlowMeterTimeStampsFile.flush() # transfers the data from Python's buffer to the operating system's buffer (not necessarily to disk)
                fsync(self.N2FlowMeterTimeStampsFile.fileno()) #
            # if we already ran the program for a few seconds such that we have flow data to analyse:
            if (self.previousHeFlowMeterValue != None and self.currentHeFlowMeterValue != None \
                and self.previousN2FlowMeterValue != None and self.currentN2FlowMeterValue != None \
                and self.currentDataTimeStamp != None):
                # if a rising edge is detected, save its timestamps
                # print("current "+str(self.currentN2FlowMeterValue)+" previous "+str(self.previousN2FlowMeterValue)+"\n")
                # print(str(self.currentN2FlowMeterValue-self.previousN2FlowMeterValue)+">?"+str(self.GAS_COUNTER_THRESHOLD)+"\n")
                if ((self.currentHeFlowMeterValue-self.previousHeFlowMeterValue)>self.GAS_COUNTER_THRESHOLD):
                    self.HeFlowMeterTimeStampsFile.write(str(self.currentDataTimeStamp)+"\t")
                    self.HeFlowMeterTimeStampsFile.flush() # transfers the data from Python's buffer to the operating system's buffer (not necessarily to disk)
                    fsync(self.HeFlowMeterTimeStampsFile.fileno()) #
                if ((self.currentN2FlowMeterValue-self.previousN2FlowMeterValue)>self.GAS_COUNTER_THRESHOLD):
                    # print("entered this thing")
                    self.N2FlowMeterTimeStampsFile.write(str(self.currentDataTimeStamp)+"\t")

                    self.N2FlowMeterTimeStampsFile.flush() # transfers the data from Python's buffer to the operating system's buffer (not necessarily to disk)
                    fsync(self.N2FlowMeterTimeStampsFile.fileno()) #
            # update the gui
            for i in range(len(dataForTable)):
                self.ui.tableChannels.setItem(i,5,QTableWidgetItem(str(dataForTable[i]))) # raw value
                # display the calibrated values (but only for the channels which have a calibration)
                if i>0:
                    if not ("log" not in self.channelUnits[i-1]):
                        if not "L/min" in self.channelUnits[i-1]:
                            self.ui.tableChannels.setItem(i,6,QTableWidgetItem(str(self.calibrate(i,dataForTable[i])))) # calibrated value
                    #else:
                        # the flow meter channels require a special calibration function. Do this only once per minute as it is intensive.
                        # if datetime.datetime.now()>gasFlowTimer+60:
                            # TODO
            

if __name__ == '__main__':
    app = QApplication(argv)
    MainWindow = Main()
    MainWindow.show()
    exit(app.exec_())

from threading import Thread
from PyEnvDAQCommunicator import PyEnvDAQCommunicator
from glob import glob,iglob
from os import listdir,makedirs
from os.path import getctime,getmtime,isfile,isdir
from numpy import ceil,floor,linspace,asarray
from PyQt5.QtWidgets import QGraphicsScene
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
from time import time,mktime,strftime
import datetime

class PyEnvDAQActionsExecuter():

    timeConversionDict = {"seconds":1, "minutes":60, "hours":60*60, "days":24*60*60, \
                          "weeks":7*24*60*60,"months":4.348*7*24*60*60}

    def __init__(self,main):
        self.main = main
        self.action = "automatically creating THee files" # default action. if the execute button is clicked, this will be overwritten.
        self.ui = main.ui
        # self.plotResolution = main.PLOT_RESOLUTION
        self.dataFilePath = main.DATA_FILES_FOLDER
        #self.dataFilePath = "D:\\EnvironmentData\\"
        self.dataExportedFilesFolder = main.EXPORTED_DATA_FILES_FOLDER
        self.THeeFilesFolder = main.THEE_FILES_FOLDER
        self.autoUpdateDict = main.AUTO_UPDATE_DICT
        self.THeeFileCreationPeriodButton = main.THee_FILES_CREATION_PERIOD_BUTTON
        # self.THeeFileCreationPeriodAutomatic = main.THee_FILES_CREATION_PERIOD_AUTOMATIC
    
    def printMessage(self,content):
        self.main.printMessage(content)

    # executeButtonClicked:
    #   determines which action was selected by the user to be performed and calls executeAction to perform it in a separate thread.
    def executeButtonClicked(self):
        print("started executeButtonClicked \n")
        # prevent other tasks from being issued until this one is done
        self.ui.pushButtonExecute.setEnabled(False)
        # are we exporting, plotting or creating THee files?
        if self.ui.radioButtonPlot.isChecked():
            self.action="plotting"
        if self.ui.radioButtonExport.isChecked():
            self.action="exporting"
        if self.ui.radioButtonCreatingTHeeFiles.isChecked():
            self.action="manually creating THee files"

        # set up the communication and threading for the desired action.
        self.comAction = PyEnvDAQCommunicator() # this object will let the main program (thread) know once the data for the action has been assembled
        self.comAction.signalPlotReady.connect(self.plot) # in case of plotting, this signal will trigger the plot function, which is handled by the main thread

        # start by executing "executeAction" in a new thread. This function is the first step in the execution of all of the available actions.
        self.actionThread = Thread(target=self.executeAction)
        self.actionThread.start()

#    def CreateTHeeFilesButtonClicked(self):
#        # prevent other tasks from being issued until this one is done
#        self.ui.pushButtonExecute.setEnabled(False)
#        self.ui.pushButtonCreateTHeeFiles.setEnabled(False) 
#        # clear the status line and set it to white
#        self.ui.labelPlotAndExportStatus.setText("")
#        self.ui.labelPlotAndExportStatus.setStyleSheet("QLabel { color: white; }")
#
#        # set up the communication and threading for the plotting/exporting process
#        self.comPlotAndExport = PyEnvDAQCommunicator() # this object will let the main program (thread) know once the data for the plotting has been assembled
#        self.comPlotAndExport.signalPlotReady.connect(self.plot) # the completion signal will trigger plot (handled by the main thread)
#
#        self.plotAndExportThread = Thread(target=self.executeAction) # the gathering of the data is performed in a separate thread
#        self.plotAndExportThread.start()
#        self.executeAction()

    # executeAction:
    #   performs the action selected by the user ("plotting", "exporting", "manually creating THee files" or "compressing files")
    #       or "automatically creating THee files" if called without the button being pressed by the user.
    #       note that in the case of exporting and plotting, separate functions are called by this function in order to finish the task.
    def executeAction(self):
        self.main.printMessage("executing: "+self.action+" (takes up to 75s per pyenv file involved) \n")
        if self.action != "automatically creating THee files": 
            self.ui.tabWidget.setCurrentIndex(2) # go to the Messages tab

            # if specific dates were chosen, make sure that they are valid and set the start and end timestamps accordingly
            if self.ui.radioButtonTimeSpecific.isChecked():
                startTimeStamp = mktime(datetime.datetime.strptime( \
                    self.ui.textEditStartDate.toPlainText(), \
                    "%Y.%m.%d %H:%M:%S").timetuple()) # in s
                endTimeStamp = mktime(datetime.datetime.strptime( \
                    self.ui.textEditEndDate.toPlainText(), \
                    "%Y.%m.%d %H:%M:%S").timetuple()) # in s
            #  otherwise if a preset was selected set the start and end timestamps accordingly
            if self.ui.radioButtonTimePreset.isChecked():
                timeDuration = int(self.ui.comboBoxTimeDuration.currentText()) # the length of the time window to be plotted (unitless)
                timeUnit = self.ui.comboBoxTimeUnit.currentText() # the unit of the length of the time window to be plotted
                timeInSeconds = self.timeConversionDict[timeUnit]*timeDuration # the desired length of the time window to be plotted (in seconds)
                startTimeStamp = (time()-timeInSeconds)
                endTimeStamp = time()

            if endTimeStamp<=startTimeStamp:
                self.main.printMessage(self.action + " failed, the end time must be later than the start time.")
                self.ui.pushButtonExecute.setEnabled(True) # allow execution of another task     
                self.ui.tabWidget.setCurrentIndex(2) # go to the messages tab
                return


        # calculate all sorts of dates and timestamps which we will use in this script
        todayMidnight = datetime.datetime.combine(datetime.datetime.today(),datetime.time.min)
        todayMidnightAsTimeStamp = mktime(todayMidnight.timetuple())
        todayEnd = datetime.datetime.combine(datetime.datetime.today(),datetime.time.max)
        todayEndAsTimeStamp = mktime(todayEnd.timetuple())
        #timetuple converts datetime to time struct, time.mktime converts timestruct to timestamp, -24*60*60 makes it yesterday, fromtimestamp converts back to datetime
        yesterdayMidnight = datetime.datetime.fromtimestamp(mktime(todayMidnight.timetuple())-24*60*60)
        yesterdayMidNightAsTimeStamp = mktime(yesterdayMidnight.timetuple()) 
        yesterdayEnd = datetime.datetime.fromtimestamp(mktime(todayEnd.timetuple())-24*60*60) 
        yesterdayEndAsTimeStamp = mktime(yesterdayEnd.timetuple())


        # if creating THee files, compressing files or updating THee files, "floor" the startTime to the beginning (midnight) of that day,
        #   and "ceil" the endTime to the end of that day. this ensures that we'll create the entire THee file
        #   for the entire days in the range and not for parts of them

        if self.action == "automatically creating THee files":
            startTimeStamp = todayMidnightAsTimeStamp
            endTimeStamp = todayEndAsTimeStamp
            # if automatically updating the THee files, this means this function is called at the first minute of every hour, and this means
            #   we will miss data from the last hour of every day. Therefore, if this is the first hour of the day, instead of updating
            #   the THee files of today, we will update those of yesterday. (This means that each day will only start getting its THee files
            #   updated from its second hour as in from 01:00 and not from 00:00)
            if datetime.datetime.now().hour == 0:
                startTimeStamp = yesterdayMidNightAsTimeStamp
                endTimeStamp = yesterdayEndAsTimeStamp

        startOfChosenStartDate = datetime.datetime.combine(datetime.datetime.fromtimestamp(startTimeStamp),datetime.time.min)
        startOfChosenStartDateAsTimeStamp = mktime(startOfChosenStartDate.timetuple())
        endOfChosenEndDate = datetime.datetime.combine(datetime.datetime.fromtimestamp(endTimeStamp),datetime.time.max)
        endOfChosenEndDateAsTimeStamp = mktime(endOfChosenEndDate.timetuple())

        if self.action == "manually creating THee files" or self.action == "creating compressed files":
            # startTimeStamp = mktime(todayMidnight.timetuple())
            # endTimeStamp = mktime(todayEnd.timetuple())
            startTimeStamp = startOfChosenStartDateAsTimeStamp
            endTimeStamp = endOfChosenEndDateAsTimeStamp



        # data recording process

        # obtain a list of the relevant pyenv files:
        self.timeStamps = [] # this will keep the recorded time stamps
        self.channels = [ [] for i in range(len(self.main.channelNames))] # (for plotting/exporting we only actually save 1 or 2 channels)
        relevantFileNames = [] # this will contain the pyenv files which we'll end up actually reading data from
        for fileName in listdir(self.dataFilePath): # go over all the pyenv files
            # if the file's creation time is larger or equal than the beginning of the day of the chosen start timestamp,
            #   and if the file's creation time is smaller or equal than the end of the day of the chosen end timestamp,
            #   add it to the list of files containing relevant data.
            fileCreationTimeStamp = mktime(datetime.datetime.strptime(fileName,"%Y-%m-%d.pyenv").timetuple())
            # startTimeDate = datetime.datetime.fromtimestamp(startTimeStamp)
            # # startTimeDate = startTimeStamp
            # midnightStartTimeStamp = mktime(datetime.datetime.combine(startTimeDate,datetime.time.min).timetuple())
            # if fileCreationTimeStamp>=midnightStartTimeStamp and fileCreationTimeStamp<endTimeStamp:
            if fileCreationTimeStamp>=startOfChosenStartDateAsTimeStamp and fileCreationTimeStamp<endOfChosenEndDateAsTimeStamp: # i think theres no need for <= in the second case, < is enough
                relevantFileNames.append(fileName)    
        # if no files were found, report it and allow the execution of a new action.       
        # relevantFilePaths.sort(key=lambda x: getCreationTime(self.dataFilePath+"\\"+x)) # sort files by creation date
        if(len(relevantFileNames))==0:
            self.printMessage(self.action + " failed, no relevant files were found for the requested time period.")
            self.ui.tabWidget.setCurrentIndex(2) # go to the messages tab
            self.ui.pushButtonExecute.setEnabled(True) # allow execution of another task     
            return

        # read the information from the relevant files found:
        for i in range(len(relevantFileNames)):
            fileName = relevantFileNames[i]
            self.main.printMessage("current pyenv file: "+fileName+"\n")
            envDataFile = open(self.dataFilePath+"\\"+fileName,"r") # open the file
            fileCreationTimeStamp = mktime(datetime.datetime.strptime(fileName,"%Y-%m-%d.pyenv").timetuple())
            # create the THee files for this file/date
            if self.action == "manually creating THee files" or self.action == "automatically creating THee files":
                year = relevantFileNames[i].split(".")[0].split("-")[0]
                month = relevantFileNames[i].split(".")[0].split("-")[1]
                day = relevantFileNames[i].split(".")[0].split("-")[2]
                # create the directories for the THee files if they don't exist already
                THeeFilesSubfolder = self.THeeFilesFolder + "\\" + year + "\\month" + month
                if not isdir(THeeFilesSubfolder):
                    makedirs(THeeFilesSubfolder)
                THeeFilePaths = [THeeFilesSubfolder + "\\" + channelName \
                                + "_" + year + "-" + month + "-" + day + ".THee" \
                                for channelName in self.main.channelNames[1:]] # 1: to skip time
                THeeFiles = [open(THeeFilePath,'w') for THeeFilePath in THeeFilePaths] #'w' overwrites existing files
                THeeHeaderTexts = [ "# " + channelName + "\n" \
                                  + "# " + year + "-" + month + "-" + day + "\n" \
                                  + "# " + "Number of points in this file: 0" + "\n" \
                                  for channelName in self.main.channelNames[1:]]
                [THeeFiles[j].write(THeeHeaderTexts[j]) for j in range(len(THeeFiles))]
            # skip the header and then read the first data line and its timestamp
            [envDataFile.readline() for i in range(self.main.headerSize)]
            line = envDataFile.readline()
            timeStamp = float(line.split("\t")[0])
            # skip data earlier than the time requested (only relevant for the first file)
            counter=0
            # print("timestamp = "+str(timeStamp)+" startTimeStamp = "+str(startTimeStamp)+"\n")
            while timeStamp<startTimeStamp and line!="": # (line=="" is EOF)
                line = envDataFile.readline()
            # print("skipped "+str(counter)+" lines until we got to"+str(startTimeStamp)+"\n")
            # firstTimeStamp = float(line.split("\t")[0])
            # now that we've reached the relevant data portion, record it.
            numOfDataPoints = 0 # how many data points did we record for this particular pyenv file?
            # keep recording lines until reaching either the EOF ("") or a timestamp which exeeds the end time
            #TODO  the following loop is way too slow. read everything at once and then write it instead? TODO
            while line!="" and float(line.split("\t")[0])<endTimeStamp:
                [self.channels[j].append(float(line.split("\t")[j])) for j in range(len(self.main.channelNames))] # (plotting/exporting only actually needs 1 or 2 of those)
                # update the THee files as well if needed
                if self.action == "manually creating THee files" or self.action == "automatically creating THee files":
                    [THeeFiles[j].write(str(float(line.split("\t")[0])-fileCreationTimeStamp) + " " + line.split("\t")[j+1] + "\n") for j in range(len(THeeFiles))] # j+1, to skip the time channel
                line = envDataFile.readline()
                numOfDataPoints = numOfDataPoints + 1
            # print("read "+str(numOfDataPoints)+" lines \n")
            # update the counter of the third line. This is done by reading the file's contents, modifying the line and rewriting it.
            if self.action == "manually creating THee files" or self.action == "automatically creating THee files":
                [THeeFile.close() for THeeFile in THeeFiles]
                for THeeFilePath in THeeFilePaths:
                    THeeFile = open(THeeFilePath,"r")
                    THeeFileContents = THeeFile.readlines()
                    THeeFile.close()
                    THeeFileContents[2] = "# " + "Number of points in this file: " + str(numOfDataPoints) +"\n"
                    # rewrite the file (updating the counter of the third line and adding the new one)
                    THeeFile = open(THeeFilePath,"w") # note that w rewrites the file
                    THeeFile.writelines(THeeFileContents)
                    THeeFile.close()

        # at this point, the function either manually/automatically updated the THee files, if it was asked to do so,
        #   or, if it was asked to plot/export, there are still steps to be done.
        #   in the case of exporting, we'll use a separate function to finish the job for readability purposes.
        #   in the case of plotting, we don't call a function, but rather send a signal causing the main thread
        #   to execute the function plot. I think this is necessary because ui.graphicsViewPlot was created
        #   by the main thread and so only that thread can connect objects to it.
        #   (Namely, the figure object thats created inside the subthread which is  executing this function)
        #   therefore we send the figure object back to the main thread and it is there that we are allowed to
        #   connect it to the UI.
        if self.action == "plot":
            self.comActionExecuter.signalPlotReady.emit(fig)
        if self.action == "export":
            self.export()
        self.ui.pushButtonExecute.setEnabled(True) # allow execution of another task
        self.main.printMessage("finished executing: "+self.action+"\n")

    def export(self):
        # find an unused file name
        i = 2 
        filePath = self.dataExportedFilePath + "\\export-"+strftime("%d-%m-%Y")+".txt"
        while isfile(filePath):
            filePath = self.dataExportedFilePath + "\\export-"+strftime("%d-%m-%Y")+"-"+str(i)+".txt"
            i = i+1
        file = open(filePath,"w")
        # prepare the header
        if self.channel2Selected:
            headerTextChannels = "channels "+ self.main.channelNames[int(self.channel1Index)] + " and " + self.main.channelNames[int(self.channel1Index)]
            headerTextColumns = "time (in s), " + self.main.channelNames[int(self.channel1Index)] + " (in "+self.main.channelUnits[int(self.channel1Index)] + ")" \
                                               + " and "+ self.main.channelNames[int(self.channel2Index)] + " (in "+self.main.channelUnits[int(self.channel2Index)] + ")."
        else:
            headerTextChannels = "channel " + self.main.channelNames[self.channel1Index]
            headerTextColumns = "time (in s), " + self.main.channelNames[int(self.channel1Index)] + " (in "+self.main.channelUnits[int(self.channel1Index)] + ")."
        if self.ui.radioButtonTimeSpecific.isChecked():
            headerTextTime = "between "+self.ui.textEditStartDate.currentText()+" and "+self.ui.textEditEndDate.currentText()+"."
        if self.ui.radioButtonTimePreset.isChecked():
            headerTextTime = "the last "+self.ui.comboBoxTimeDuration.currentText()+" "+self.ui.comboBoxTimeUnit.currentText()+"."

        headerText = "exported data at " + strftime("%d-%m-%Y")+" "+strftime("%H:%M:%S") + " over the time period: "+headerTextTime+"\n" \
                   + "The columns are: "+headerTextColumns+"\n \
                      \n"
        file.write(headerText)
        # write the data into the file
        numOfDataPoints = len(timeStamps)
        for i in range(numOfDataPoints):
            if self.channel2Selected:
                file.write(str(self.timeStamps[i]) + "\t" + str(self.channel1Data[i]) + "\t" + str(self.channel2Data[i]) + "\n")
            else:
                file.write(str(self.timeStamps[i]) + "\t" + str(self.channel1Data[i]) + "\n")

    def plot(self,fig):
        # filter out points in order to not exceed the plotting resolution
        # if numOfDataPoints>plotAndExportResolution:
        #    jumpSize = int(ceil(numOfDataPoints/plotAndExportResolution))
        #     self.channels[0] = self.timeList[0::jumpSize]
        #     self.channels[1] = self.channels[1][0::jumpSize]
        #     if self.channel2Selected:
        #         self.channels[2] = self.channels[2][0::jumpSize]
        # horizontally crop and calibrate the values

        # set up parameters for horizontal cropping.
        #   initially we set them to zero cropping, but if we are to plot LN2_counter or LHe_counter,
        #   the calibration function will return new boundaries which we will update these parameters
        #   with in order to crop.
        timeStampsCropStart1 = 0
        timeStampsCropStart2 = 0
        timeStampsCropEnd1 = len(self.channels[0])
        timeStampsCropEnd2 = len(self.channels[0])
        # calibrate data if required
        if self.ui.radioButtonCalibrated1.isChecked():
            if self.main.channelUnits[self.channel1Index]=="L/min":
                (self.channels[1] , horizontalCropStart1 , horizontalCropFinish1) = self.main.calibrate(int(self.channel1Index),self.channels[1])
            else:
                self.channels[1] = self.main.calibrate(int(self.channel1Index),self.channels[1])
        if self.channel2Selected and self.ui.radioButtonCalibrated2.isChecked():
            if self.main.channelUnits[self.channel2Index]=="L/min":
                (self.channels[2] , horizontalCropStart2 , horizontalCropFinish2) = self.main.calibrate(int(self.channel2Index),self.channels[2])
            else:
                self.channels[2] = self.main.calibrate(int(self.channel2Index),self.channels[2])
        # update the time stamp cropping boundaries in case they changed
        self.timeStampsCropStart = max(timeStampsCropStart1,timeStampsCropStart2)        
        self.timeStampsCropEnd = min(timeStampsCropEnd1,timeStampsCropEnd2)

        # fill time gaps - maybe no need and the plotting does that automatically? TODO

        # shift the timestamps such that they will start from 0 
        minTime = min(self.channels[0])
        self.timeStamps = [time-minTime for time in self.timeList] # make the first time point 0
        maxTimeDifference = (max(self.timeList)-min(self.timeList))
        timeUnit = "seconds"

        # scale time to the right units (todo: change the timestamps into date format)
        timeScaling = 60*60*24
        timeUnit = "days"
        if maxTimeDifference<self.timeConversionDict["days"]:
            timeScaling = 60*60
            timeUnit = "hours"
        if maxTimeDifference<self.timeConversionDict["hours"]:
            timeScaling = 60
            timeUnit = "minutes"
        if maxTimeDifference<self.timeConversionDict["minutes"]:
            timeScaling = 1
            timeUnit = "seconds"
        self.channels[0] = [timeStamp/timeScaling for timeStamp in self.channels[0]]

        # create the figure and the axes.
        fig, ax1 = plt.subplots()
        ax1.set_xlabel('time in '+timeUnit)
        ax1.plot(self.timeList, self.channels[1], 'b.')
        # Make the y-axis label and tick labels match the line color.
        ax1.set_ylabel(self.main.channelNames[int(self.channel1Index)] + " in "+self.main.channelUnits[int(self.channel1Index)], color='b')
        for tl in ax1.get_yticklabels():
            tl.set_color('b')
        if self.channel2Selected:
            ax2 = ax1.twinx()
            ax2.plot(self.timeList, self.channels[2], 'r.')
            ax2.set_ylabel(self.main.channelNames[int(self.channel2Index)] + " in "+self.main.channelUnits[int(self.channel2Index)], color='r')
            for tl in ax2.get_yticklabels():
                tl.set_color('r')
        # up until this point, the code contained in this function could have been also contained in "executeAction",
        #   it was just contained here for readability purposes. However, the next lines would not have worked, were they
        #   to be in "executeAction". See the comment at the end of "executeAction" for a possible explanation.
        canvas = FigureCanvasQTAgg(fig)
        canvas.setGeometry(40, 140, 851, 690)
        scene = QGraphicsScene(self.ui.graphicsViewPlot)
        scene.addWidget(canvas)
        self.ui.graphicsViewPlot.setScene(scene)
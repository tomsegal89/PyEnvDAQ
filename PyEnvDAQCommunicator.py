from PyQt5.QtCore import QObject,pyqtSignal
from numpy import ndarray
from matplotlib.figure import Figure
class PyEnvDAQCommunicator(QObject):
    signalNewData = pyqtSignal(ndarray,str) # signal for recording a new line of data into the env file

    signalProgress = pyqtSignal(int,str) # signal for updating the plot and export tab with messages regarding the plotting/exporting process
    signalPlotReady = pyqtSignal(Figure) # signal for plotting the completed figure
    #signalExportReady = pyqtSignal() # signal for writing the 
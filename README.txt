PyEnvDAQ is a Python program designed and built by Dr. Tom Segal for the THe (Tritum Helium) group in the Stored and Cooled Ions division of the Max Planck Institute of Nuclear Physics, Germany, under the supervision of Prof. Klaus Blaum.
See "PyEnvDAQ.png".


Modules used: numpy, PyQt5, threading, requests, struct

Features:
1. live data acquisiton of environmental parameters such as pressure, temperature, humidity, gas flow and magnetic flux. To acquire the data, the program connects directly with different measurement devices.
2. real-time display of the values of the different channels, including real-time calibration, display of upper and lower values and automatic telegram notifications in case of unstable values.
3. plotting of the different acquired values as functions of time.
4. message log of potential problems and alerts.


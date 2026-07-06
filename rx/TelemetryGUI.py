#!/usr/bin/env python2.7
#
#   Wenet IMU Data Viewer
#
#	Copyright (C) 2018  Mark Jessop <vk5qi@rfhead.net>
#	Released under GNU GPL v3 or later
#
#	NOTE: This is somewhat deprecated as we no longer fly IMUs on Wenet flights.
#	It may be re-visited in the future if/when required.
#

import argparse
import traceback
import socket
import json
import sys
import datetime
from WenetPackets import *
import numpy as np
from pyqtgraph.Qt import QtCore, QtGui
import pyqtgraph as pg
import pyqtgraph.opengl as gl
from threading import Thread

try:
    # Python 2
    from Queue import Queue
except ImportError:
    # Python 3
    from queue import Queue


parser = argparse.ArgumentParser()
parser.add_argument("--imu", action="store_true", help="Show IMU panels.")
parser.add_argument("--callsign", type=str, default="N0CALL", help="User callsign for Image Telemetry uploads.")
parser.add_argument("-v", "--verbose", action='store_true', default=False, help="Verbose output")
args = parser.parse_args()


# Various GUI Settings
imu_plot_history_size = 60 # Seconds.


user_callsign = args.callsign

app = QtGui.QApplication([])

# Configure PyQtGraph to use black plots on a transparent background.
pg.setConfigOption('background',(0,0,0,0))
pg.setConfigOption('foreground', 'k')

#
# GPS Telemetry Data Frame
#
gpsFrame = QtGui.QFrame()
gpsFrame.setFixedSize(250,250)
gpsFrame.setFrameStyle(QtGui.QFrame.Box)
gpsFrame.setLineWidth(2)
gpsFrameTitle = QtGui.QLabel("<b><u>GPS Data</u></b>")
gpsTime = QtGui.QLabel("<b>Time:</b>")
gpsTimeValue = QtGui.QLabel("00:00:00")
gpsLatitude = QtGui.QLabel("<b>Latitude:</b>")
gpsLatitudeValue = QtGui.QLabel("-00.00000")
gpsLongitude = QtGui.QLabel("<b>Longitude:</b>")
gpsLongitudeValue = QtGui.QLabel("000.00000")
gpsAltitude = QtGui.QLabel("<b>Altitude:</b>")
gpsAltitudeValue = QtGui.QLabel("00000m")
gpsSpeed = QtGui.QLabel("<b>Speed</b>")
gpsSpeedValue = QtGui.QLabel("H 000kph V 0.0m/s")
gpsHeading = QtGui.QLabel("<b>Heading:</b>")
gpsHeadingValue = QtGui.QLabel("-")
gpsSats = QtGui.QLabel("<b>Satellites:</b>")
gpsSatsValue = QtGui.QLabel("0")
gpsFixValid = QtGui.QLabel("<b>Fix Status:</b>")
gpsFixValidValue = QtGui.QLabel("-")

gpsFrameLayout = QtGui.QGridLayout()
gpsFrameLayout.addWidget(gpsFrameTitle,0,0,1,2)
gpsFrameLayout.addWidget(gpsTime,1,0)
gpsFrameLayout.addWidget(gpsTimeValue,1,1)
gpsFrameLayout.addWidget(gpsLatitude,2,0)
gpsFrameLayout.addWidget(gpsLatitudeValue,2,1)
gpsFrameLayout.addWidget(gpsLongitude,3,0)
gpsFrameLayout.addWidget(gpsLongitudeValue,3,1)
gpsFrameLayout.addWidget(gpsAltitude,4,0)
gpsFrameLayout.addWidget(gpsAltitudeValue,4,1)
gpsFrameLayout.addWidget(gpsSpeed,5,0)
gpsFrameLayout.addWidget(gpsSpeedValue,5,1)
gpsFrameLayout.addWidget(gpsHeading,6,0)
gpsFrameLayout.addWidget(gpsHeadingValue,6,1)
gpsFrameLayout.addWidget(gpsSats,7,0)
gpsFrameLayout.addWidget(gpsSatsValue,7,1)
gpsFrameLayout.addWidget(gpsFixValid,8,0)
gpsFrameLayout.addWidget(gpsFixValidValue,8,1)

gpsFrame.setLayout(gpsFrameLayout)

def updateGpsFrame(gps_data):
	""" Update GPS Data Frame with a WenetPackets GPS Data dictionary """
	try:
		gpsTimeValue.setText(gps_data['timestamp'])
		gpsLatitudeValue.setText("%.5f" % gps_data['latitude'])
		gpsLongitudeValue.setText("%.5f" % gps_data['longitude'])
		gpsAltitudeValue.setText("%d m" % int(gps_data['altitude']))
		gpsSpeedValue.setText("H %d kph V %.1f m/s" % ( int(gps_data['ground_speed']), gps_data['ascent_rate']))
		gpsHeadingValue.setText("%.1f deg" % gps_data['heading'])
		gpsSatsValue.setText("%d" % gps_data['numSV'])
		gpsFixValidValue.setText(gps_data['gpsFix_str'])
	except:
		traceback.print_exc()
		pass

#
# IMU Telemetry Data Frame
#
imuFrame = QtGui.QFrame()
imuFrame.setFixedSize(250,250)
imuFrame.setFrameStyle(QtGui.QFrame.Box)
imuFrame.setLineWidth(2)

imuFrameTitle = QtGui.QLabel("<b><u>IMU Data</u></b>")
imuTime = QtGui.QLabel("<b>Time:</b>")
imuTimeValue = QtGui.QLabel("00:00:00")
imuTemp = QtGui.QLabel("<b>Temp:</b>")
imuTempValue = QtGui.QLabel("0 deg C")
imuCalStatus = QtGui.QLabel("<b>Calibration Status</b>")
imuCalStatus_System = QtGui.QLabel("<u>System</u>")
imuCalStatus_System_OK = QtGui.QLabel("?")
imuCalStatus_Gyro = QtGui.QLabel("<u>Gyro</u>")
imuCalStatus_Gyro_OK = QtGui.QLabel("?")
imuCalStatus_Accel = QtGui.QLabel("<u>Accel</u>")
imuCalStatus_Accel_OK =QtGui.QLabel("?")
imuCalStatus_Magnet = QtGui.QLabel("<u>Mag</u>")
imuCalStatus_Magnet_OK = QtGui.QLabel("?")
imuEulerLabel = QtGui.QLabel("<b><u>Euler Angles</u></b>")
imuEulerHeadingLabel = QtGui.QLabel("<b>Heading</b>")
imuEulerHeadingValue = QtGui.QLabel("0 deg")
imuEulerRollLabel = QtGui.QLabel("<b>Roll</b>")
imuEulerRollValue = QtGui.QLabel("0 deg")
imuEulerPitchLabel = QtGui.QLabel("<b>Pitch</b>")
imuEulerPitchValue = QtGui.QLabel("0 deg")

imuFrameLayout = QtGui.QGridLayout()
imuFrameLayout.addWidget(imuFrameTitle,0,0,1,4)
imuFrameLayout.addWidget(imuTime,1,0,1,1)
imuFrameLayout.addWidget(imuTimeValue,1,2,1,3)
imuFrameLayout.addWidget(imuTemp,2,0,1,1)
imuFrameLayout.addWidget(imuTempValue,2,2,1,3)
imuFrameLayout.addWidget(imuCalStatus,3,0,1,4)
imuFrameLayout.addWidget(imuCalStatus_System,4,0,1,1)
imuFrameLayout.addWidget(imuCalStatus_Gyro,4,1,1,1)
imuFrameLayout.addWidget(imuCalStatus_Accel,4,2,1,1)
imuFrameLayout.addWidget(imuCalStatus_Magnet,4,3,1,1)
imuFrameLayout.addWidget(imuCalStatus_System_OK,5,0,1,1)
imuFrameLayout.addWidget(imuCalStatus_Gyro_OK,5,1,1,1)
imuFrameLayout.addWidget(imuCalStatus_Accel_OK,5,2,1,1)
imuFrameLayout.addWidget(imuCalStatus_Magnet_OK,5,3,1,1)
imuFrameLayout.addWidget(imuEulerLabel,6,0,1,4)
imuFrameLayout.addWidget(imuEulerHeadingLabel,7,0,1,2)
imuFrameLayout.addWidget(imuEulerHeadingValue,7,2,1,2)
imuFrameLayout.addWidget(imuEulerRollLabel,8,0,1,2)
imuFrameLayout.addWidget(imuEulerRollValue,8,2,1,2)
imuFrameLayout.addWidget(imuEulerPitchLabel,9,0,1,2)
imuFrameLayout.addWidget(imuEulerPitchValue,9,2,1,2)

imuFrame.setLayout(imuFrameLayout)

#
# IMU Plots.
#

buffer_size = 60

heading_values =[0]
roll_values = [0]
pitch_values = [0]
imu_times = [0]

imuPlot = pg.GraphicsLayoutWidget()
imuPlot_Heading = imuPlot.addPlot(title='Heading')
imuPlot_Roll = imuPlot.addPlot(title='Roll')
imuPlot_Pitch = imuPlot.addPlot(title='Pitch')
imuPlotLayout = imuPlot.ci.layout
imuPlotLayout.rowMaximumHeight(220)

# Configure Plots
imuPlot_Heading.setXRange(-1*imu_plot_history_size,0)
imuPlot_Heading.setYRange(0,360)
imuPlot_Roll.setXRange(-1*imu_plot_history_size,0)
imuPlot_Roll.setYRange(-180,180)
imuPlot_Pitch.setXRange(-1*imu_plot_history_size,0)
imuPlot_Pitch.setYRange(-180,180)

# Get curve objects so we can update them with new data.
heading_curve = imuPlot_Heading.plot(x=imu_times, y=heading_values, pen=pg.mkPen('k',width=2))
roll_curve = imuPlot_Roll.plot(x=imu_times, y=roll_values, pen=pg.mkPen('k',width=2))
pitch_curve = imuPlot_Pitch.plot(x=imu_times, y=pitch_values, pen=pg.mkPen('k',width=2))

def updateIMUFrame(imu_data):
	""" Update IMU Frame and Plots with new IMU data """
	global imu_times, heading_values, roll_values, pitch_values, heading_curve, roll_curve, pitch_curve
	try:
		imuTimeValue.setText(imu_data['timestamp'])
		imuTempValue.setText("%d" % imu_data['temp'])
		imuCalStatus_System_OK.setText("%d" % imu_data['sys_cal'])
		imuCalStatus_Gyro_OK.setText("%d" % imu_data['gyro_cal'])
		imuCalStatus_Accel_OK.setText("%d" % imu_data['accel_cal'])
		imuCalStatus_Magnet_OK.setText("%d" % imu_data['magnet_cal'])
		imuEulerHeadingValue.setText("%.1f" % imu_data['euler_heading'])
		imuEulerRollValue.setText("%.1f" % imu_data['euler_roll'])
		imuEulerPitchValue.setText("%.1f" % imu_data['euler_pitch'])

		latest_imu_time = imu_data['iTOW']
		latest_euler_heading = imu_data['euler_heading']
		latest_euler_roll = imu_data['euler_roll']
		latest_euler_pitch = imu_data['euler_pitch']

		if imu_times[0] == 0:
			# We need to initialise the arrays.
			imu_times[0] = latest_imu_time
			heading_values[0] = latest_euler_heading
			roll_values[0] = latest_euler_roll
			pitch_values[0] = latest_euler_pitch
		else:
			# Append, and crop arrays if they are too big.
			imu_times.append(latest_imu_time)
			heading_values.append(latest_euler_heading)
			roll_values.append(latest_euler_roll)
			pitch_values.append(latest_euler_pitch)

			if len(imu_times) > buffer_size:
				imu_times = imu_times[-1*buffer_size:]
				heading_values = heading_values[-1*buffer_size:]
				roll_values = roll_values[-1*buffer_size:]
				pitch_values = pitch_values[-1*buffer_size:]

			# Update plots
			heading_curve.setData(x=(np.array(imu_times)-latest_imu_time), y=heading_values)
			roll_curve.setData(x=(np.array(imu_times)-latest_imu_time), y = roll_values)
			pitch_curve.setData(x=(np.array(imu_times)-latest_imu_time), y=pitch_values)


	except:
		traceback.print_exc()
		pass


# Telemetry Log
packetSnifferFrame = QtGui.QFrame()
packetSnifferFrame.setFixedSize(1200,150)
packetSnifferFrame.setFrameStyle(QtGui.QFrame.Box)
packetSnifferTitle = QtGui.QLabel("<b><u>Telemetry Log</u></b>")
console = QtGui.QPlainTextEdit()
console.setReadOnly(True)
packetSnifferLayout = QtGui.QGridLayout()
packetSnifferLayout.addWidget(packetSnifferTitle)
packetSnifferLayout.addWidget(console)
packetSnifferFrame.setLayout(packetSnifferLayout)

# Habitat Upload Frame
uploadFrame = QtGui.QFrame()
uploadFrame.setFixedSize(200,150)
uploadFrame.setFrameStyle(QtGui.QFrame.Box)
uploadFrame.setLineWidth(1)
uploadFrameTitle = QtGui.QLabel("<b><u>Habitat Upload</u></b>")

uploadFrameHabitat = QtGui.QCheckBox("Habitat Upload")
uploadFrameHabitat.setChecked(True)
uploadFrameCallsignLabel = QtGui.QLabel("<b>Your Callsign:</b>")
uploadFrameCallsign = QtGui.QLineEdit(user_callsign)
uploadFrameCallsign.setMaxLength(10)
uploadFrameHabitatStatus = QtGui.QLabel("Last Upload: ")

uploadFrameLayout = QtGui.QGridLayout()
uploadFrameLayout.addWidget(uploadFrameTitle,0,0,1,1)
uploadFrameLayout.addWidget(uploadFrameCallsignLabel,1,0,1,1)
uploadFrameLayout.addWidget(uploadFrameCallsign,1,1,1,1)
uploadFrameLayout.addWidget(uploadFrameHabitat,2,0,1,2)
uploadFrameLayout.addWidget(uploadFrameHabitatStatus,3,0,1,2)

uploadFrame.setLayout(uploadFrameLayout)

def imageTelemetryHandler(packet):
	# Not using this anymore, just hacking around it 
	#(upload_ok, error) = image_telemetry_upload(packet, user_callsign = str(uploadFrameCallsign.text()))
	timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%SZ")

	upload_ok = True
	
	if upload_ok:
		uploadFrameHabitatStatus.setText("Last Upload: %s" % datetime.datetime.utcnow().strftime("%H:%M:%S"))
		console.appendPlainText("%s \tHabitat Upload: OK")
	else:
		uploadFrameHabitatStatus.setText("Last Upload: Failed!")
		console.appendPlainText("%s \tHabitat Upload: FAIL: %s" % (timestamp, error))


# Main Window
main_widget = QtGui.QWidget()
layout = QtGui.QGridLayout()
main_widget.setLayout(layout)

if args.imu:
	layout.addWidget(gpsFrame,0,0)
	layout.addWidget(imuFrame,0,1)
	layout.addWidget(imuPlot,0,2,1,2)
	layout.addWidget(packetSnifferFrame,1,0,1,3)
	layout.addWidget(uploadFrame,1,3,1,1)
else:
	layout.addWidget(gpsFrame,0,0)
	packetSnifferFrame.setFixedSize(800,250)
	layout.addWidget(packetSnifferFrame,0,1)


mainwin = QtGui.QMainWindow()
mainwin.setWindowTitle("Wenet Payload Telemetry Console")
mainwin.setCentralWidget(main_widget)

if args.imu:
	mainwin.resize(1300,400)
else:
	mainwin.resize(1050,250)
mainwin.show()


#
# UDP Packet Handling Functions.
#
rxqueue = Queue(32)

def process_udp(udp_packet):
	""" Process received UDP packets. """
	# Grab timestamp.
	timestamp = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%SZ")

	# Parse JSON, and extract packet.
	packet_dict = json.loads(udp_packet.decode('ascii'))
	# Discard all but Wenet packets
	if packet_dict['type'] == 'WENET':
		packet = packet_dict['packet']
	else:
		return

	# Decode GPS and IMU packets, and pass onto their respective GUI update functions.
	packet_type = decode_packet_type(packet)

	if packet_type == WENET_PACKET_TYPES.GPS_TELEMETRY:
		gps_data = gps_telemetry_decoder(packet)
		updateGpsFrame(gps_data)
	elif packet_type == WENET_PACKET_TYPES.ORIENTATION_TELEMETRY:
		orientation_data = orientation_telemetry_decoder(packet)
		updateIMUFrame(orientation_data)
	elif packet_type == WENET_PACKET_TYPES.IMAGE_TELEMETRY:
		# Print to console, then attempt to upload packet.
		console.appendPlainText("%s \t%s" % (timestamp,packet_to_string(packet)))
		imageTelemetryHandler(packet)
	else:
		# Convert to string, and print to terminal with timestamp.
		console.appendPlainText("%s \t%s" % (timestamp,packet_to_string(packet)))


udp_listener_running = False
def udp_rx_thread():
	""" Listen on a port for UDP broadcast packets, and pass them onto process_udp()"""
	global udp_listener_running
	s = socket.socket(socket.AF_INET,socket.SOCK_DGRAM)
	s.settimeout(1)
	s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
	try:
		s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)
	except:
		pass
	s.bind(('',WENET_TELEMETRY_UDP_PORT))
	print("Started UDP Listener Thread.")
	udp_listener_running = True
	while udp_listener_running:
		try:
			m = s.recvfrom(2048)
		except socket.timeout:
			m = None
		
		if m != None:
			try:
				rxqueue.put_nowait(m[0])
			except:
				traceback.print_exc()
				pass
	
	print("Closing UDP Listener")
	s.close()

t = Thread(target=udp_rx_thread)
t.start()

def read_queue():
	try:
		if rxqueue.qsize()>0:
			packet = rxqueue.get_nowait()
			process_udp(packet)
	except:
		traceback.print_exc()
		pass

# Start a timer to attempt to read a packet from the queue every 100ms.
timer = QtCore.QTimer()
timer.timeout.connect(read_queue)
timer.start(100)


## Start Qt event loop unless running in interactive mode.
if __name__ == '__main__':
	import sys
	if (sys.flags.interactive != 1) or not hasattr(QtCore, 'PYQT_VERSION'):
		QtGui.QApplication.instance().exec_()
		udp_listener_running = False

#!/usr/bin/env python2.7
#
#	Wenet PiCamera2 Wrapper Class.
#	Supports the 'new' libcamera / picamera2 API
#
#	Copyright (C) 2023  Mark Jessop <vk5qi@rfhead.net>
#	Released under GNU GPL v3 or later
#
# 	References:
#		https://github.com/raspberrypi/picamera2
#		https://datasheets.raspberrypi.com/camera/picamera2-manual.pdf

import glob
import os
import datetime
import subprocess
import time
import traceback

from picamera2 import Picamera2
from libcamera import controls, Transform
from time import sleep
from threading import Thread



class WenetPiCamera2(object):
    """ PiCamera2 Wrapper Class

    Raspberry Pi Camera 2 Image source for Wenet.
    Uses the new libcamera-based PiCamera2 library.
    Captures multiple images, picks the best, then 
    transmits it via a PacketTX object. 
    """

    # White balance text to enum lookup
    wb_lookup = {
        "auto": controls.AwbModeEnum.Auto,
        "incandescent": controls.AwbModeEnum.Incandescent,
        "fluorescent": controls.AwbModeEnum.Fluorescent,
        "tungsten": controls.AwbModeEnum.Tungsten,
        "indoor": controls.AwbModeEnum.Indoor,
        "daylight": controls.AwbModeEnum.Daylight,
        "cloudy": controls.AwbModeEnum.Cloudy
    }

    def __init__(self,
                callsign = "N0CALL",
                tx_resolution=0.5, 
                num_images=1,
                image_delay=0.0, 
                vertical_flip = False, 
                horizontal_flip = False,
                whitebalance = 'auto',
                lens_position = -1,
                temp_filename_prefix = 'picam_temp',
                debug_ptr = None,
                init_retries = 10
                ):

        """ Instantiate a WenetPiCam Object
            used to capture images from a PiCam using 'optimal' capture techniques.

            Keyword Arguments:
            callsign: The callsign to be used when converting images to SSDV. Must be <=6 characters in length.
            tx_resolution: Either a tuple (x,y) containing desired image *transmit* resolution, OR a scaling factor from full size.
                        NOTE: both x and y need to be multiples of 16 to be used with SSDV.
                        NOTE: If you manually specify a transmit resolution, this will resize with NO REGARD FOR ASPECT RATIO - it's up to you to get that right.

            num_images: Number of images to capture in sequence when the 'capture' function is called.
                        The 'best' (largest filesize) image is selected and saved.
            image_delay: Delay time (seconds) between each captured image.

            vertical_flip: Flip captured images vertically.
            horizontal_flip: Flip captured images horizontally.
                            Used to correct for picam orientation.
            whitebalance: White balance mode - allowed values: Auto, Incandescent, Tungesten, Fluorescent, Indoor, Daylight, Cloudy 
            lens_position: Lens Position setting (float), 0.0 = Infinity, 10 = very close.
                   Only usable on Pi Camera v3 modules.
                   Set to -1 to use continuous autofocus mode.

            temp_filename_prefix: prefix used for temporary files.

            debug_ptr:	'pointer' to a function which can handle debug messages.
                        This function needs to be able to accept a string.
                        Used to get status messages into the downlink.

        """

        self.debug_ptr = debug_ptr
        self.temp_filename_prefix = temp_filename_prefix
        self.num_images = num_images
        self.image_delay = image_delay
        self.callsign = callsign
        self.tx_resolution_init = tx_resolution
        self.horizontal_flip = horizontal_flip
        self.vertical_flip = vertical_flip
        self.lens_position = lens_position
        self.autofocus_mode = False

        if whitebalance.lower() in self.wb_lookup:
            self.whitebalance = self.wb_lookup[whitebalance.lower()]
        else:
            self.whitebalance = self.wb_lookup['auto']


        # If we startup too early, the camera is sometimes not available to us.
        # Try and initialise for a while with breaks in between until we can talk to it...
        while init_retries > 0:
            try: 
                self.init_camera()
                break
            except Exception as e:
                self.debug_message(f"Error initialising camera, retrying in 10 seconds: - {str(e)}")
            time.sleep(10)
            init_retries -= 1


    def init_camera(self):
        # Attempt to start picam.

        # Shutdown any previous instances of the camera object.
        # If we don't do this, we can end up with all sorts of fun errors.
        try:
            self.cam.close()
            self.debug_message("Closed broken instance of Picamera2")
        except:
            pass

        self.cam = Picamera2()

        self.camera_properties = self.cam.camera_properties

        self.debug_ptr("Camera Native Resolution: " + str(self.camera_properties['PixelArraySize']))

        # If the user has explicitly specified the transmit image resolution, use it.
        if type(self.tx_resolution_init) == tuple:
            self.tx_resolution = self.tx_resolution_init
            self.debug_ptr(f"Transmit Resolution set to {str(self.tx_resolution)}")
        # Otherwise, has the user provided a floating point scaling factor?
        elif type(self.tx_resolution_init) == float:
            res_x = 16*int(self.camera_properties['PixelArraySize'][0]*self.tx_resolution_init/16)
            res_y = 16*int(self.camera_properties['PixelArraySize'][1]*self.tx_resolution_init/16)
            self.tx_resolution = (res_x, res_y)
            self.debug_ptr(f"Transmit Resolution set to {str(self.tx_resolution)}, scaled {self.tx_resolution_init} from native.")

        # Configure camera, including flip settings.
        capture_config = self.cam.create_still_configuration(
            transform=Transform(hflip=self.horizontal_flip, vflip=self.vertical_flip)
        )
        self.cam.configure(capture_config)

        # Set other settings, White Balance, exposure metering, etc.

        self.cam.set_controls(
            {'AwbMode': self.whitebalance,
            'AeMeteringMode': controls.AeMeteringModeEnum.Matrix,
            'NoiseReductionMode': controls.draft.NoiseReductionModeEnum.Off}
            )

        # Set Pi Camera 3 lens position
        if 'LensPosition' in self.cam.camera_controls:
            if self.lens_position>=0.0:
                self.debug_ptr("Configured lens position to " + str(self.lens_position))
                self.cam.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": self.lens_position})
            else:
                self.cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})

        # In autofocus mode, we need to start the camera now, so it can start figuring out its focus.
        if 'LensPosition' in self.cam.camera_controls and self.lens_position<0.0:
            self.debug_message("Enabling camera for image capture")
            self.cam.start()

        # If we are not in autofocus mode, we start the camera only when we need it.
        # This may help deal with crashes after the camera is running for a long time, and also
        # may help decrease CPU usage a little.

    def debug_message(self, message):
        """ Write a debug message.
        If debug_ptr was set to a function during init, this will
        pass the message to that function, else it will just print it.
        This is used mainly to get updates on image capture into the Wenet downlink.

        """
        message = "PiCam Debug: " + message
        if self.debug_ptr != None:
            self.debug_ptr(message)
        else:
            print(message)

    def close(self):
        try:
            self.cam.stop()
        except:
            self.debug_message("Stopping camera object failed.")
        try:
            self.cam.close()
        except:
            self.debug_message("Closing camera object failed.")

    def capture(self, filename='picam.jpg', quality=90):
        """ Capture an image using the PiCam
            
            Keyword Arguments:
            filename:	destination filename.
        """

        # Ensure JPG quality is set as required.
        self.cam.options['quality'] = quality

        # Set other settings, White Balance, exposure metering, etc.
        # TODO - Maybe expose some of these settings?
        self.cam.set_controls(
            {'AwbMode': self.whitebalance,
            'AeMeteringMode': controls.AeMeteringModeEnum.Matrix,
            'NoiseReductionMode': controls.draft.NoiseReductionModeEnum.Off}
            )

        # Set Pi Camera 3 lens position, or ensure we are in continuous autofocus mode.
        if 'LensPosition' in self.cam.camera_controls:
            if self.lens_position>=0.0:
                self.debug_ptr("Configured lens position to " + str(self.lens_position))
                self.cam.set_controls({"AfMode": controls.AfModeEnum.Manual, "LensPosition": self.lens_position})
            else:
                self.cam.set_controls({"AfMode": controls.AfModeEnum.Continuous})


        # If we're not using autofocus, then camera would not have been started yet.
        # Start it now.
        if 'LensPosition' not in self.cam.camera_controls or self.lens_position>=0.0:
            try:
                self.debug_message("Enabling camera for image capture")
                self.cam.start()
            except Exception as e:
                self.debug_message("Could not enable camera! - " + str(e))
                sleep(1)
                return False

        sleep(3)

        # Attempt to capture a set of images.
        for i in range(self.num_images):
            self.debug_message("Capturing Image %d of %d" % (i+1,self.num_images))
            # Wrap this in error handling in case we lose the camera for some reason.

            try:
                self.cam.capture_file("%s_%d.jpg" % (self.temp_filename_prefix,i))
                print(f"Image captured: {time.time()}")
                if self.image_delay > 0:
                    sleep(self.image_delay)
            except Exception as e: # TODO: Narrow this down...
                self.debug_message("Capture Error: %s" % str(e))
                # Immediately return false. Not much point continuing to try and capture images.
                return False
        
        if 'LensPosition' not in self.cam.camera_controls or self.lens_position>=0.0:
            self.debug_message("Disabling camera.")
            self.cam.stop()

        # Otherwise, continue to pick the 'best' image based on filesize.
        self.debug_message("Choosing Best Image.")
        pic_list = glob.glob("%s_*.jpg" % self.temp_filename_prefix)
        pic_sizes = []
        # Iterate through list of images and get the file sizes.
        for pic in pic_list:
            pic_sizes.append(os.path.getsize(pic))
        largest_pic = pic_list[pic_sizes.index(max(pic_sizes))]

        # Copy best image to target filename.
        self.debug_message("Copying image to storage with filename %s" % filename)
        os.system("cp %s %s" % (largest_pic, filename))
        # Clean up temporary images.
        os.system("rm %s_*.jpg" % self.temp_filename_prefix)

        return True 

    def ssdvify(self, filename="output.jpg", image_id=0, quality=6):
        """ Convert a supplied JPEG image to SSDV.
        Returns the filename of the converted SSDV image.

        Keyword Arguments:
        filename:	Source JPEG filename.
                    Output SSDV image will be saved to to a temporary file (webcam_temp.jpg) which should be
                    transmitted immediately.
        image_id:	Image ID number. Must be incremented between images.
        quality:	JPEG quality level: 4 - 7, where 7 is 'lossless' (not recommended).
                    6 provides good quality at decent file-sizes.

        """

        # Wrap image ID field if it's >255.
        image_id = image_id % 256

        # Resize image to the desired resolution.
        self.debug_message("Resizing image.")
        return_code = os.system("timeout -k 5 180 convert %s -scale %dx%d\! picam_temp.jpg" % (filename, self.tx_resolution[0], self.tx_resolution[1]))
        if return_code != 0:
            self.debug_message("Resize operation failed! (Possible kernel Oops? Maybe set arm_freq to 700 MHz)")
            return "FAIL"

        # Get non-extension part of filename.
        file_basename = filename[:-4]

        # Construct SSDV command-line.
        ssdv_command = "ssdv -e -n -q %d -c %s -i %d picam_temp.jpg picam_temp.ssdv" % (quality, self.callsign, image_id)
        print(ssdv_command)
        # Update debug message.
        self.debug_message("Converting image to SSDV.")

        # Run SSDV converter.
        return_code = os.system(ssdv_command)

        if return_code != 0:
            self.debug_message("ERROR: Could not perform SSDV Conversion.")
            return "FAIL"
        else:
            return "picam_temp.ssdv"

    auto_capture_running = False
    def auto_capture(self, destination_directory, tx, post_process_ptr=None, delay = 0, start_id = 0):
        """ Automatically capture and transmit images in a loop.
        Images are automatically saved to a supplied directory, with file-names
        defined using a timestamp.

        Use the run() and stop() functions to start/stop this running.
        
        Keyword Arguments:
        destination_directory:	Folder to save images to. Both raw JPEG and SSDV images are saved here.
        tx:		A reference to a PacketTX Object, which is used to transmit packets, and interrogate the TX queue.
        post_process_ptr: An optional function which is called after the image is captured. This function
                          will be passed the path/filename of the captured image.
                          This can be used to add overlays, etc to the image before it is SSDVified and transmitted.
                          NOTE: This function need to modify the image in-place.
        delay:	An optional delay in seconds between capturing images. Defaults to 0.
                This delay is added on top of any delays caused while waiting for the transmit queue to empty.
        start_id: Starting image ID. Defaults to 0.
        """

        image_id = start_id

        while self.auto_capture_running:
            # Sleep before capturing next image.
            sleep(delay)

            # Grab current timestamp.
            capture_time = datetime.datetime.utcnow().strftime("%Y%m%d-%H%M%SZ")
            capture_filename = destination_directory + "/%s_picam.jpg" % capture_time

            # Attempt to capture.
            try:
                capture_successful = self.capture(capture_filename)
            except Exception as e:
                self.debug_message(f"Exception on capture - {str(e)}")
                capture_successful = False

            # If capture was unsuccessful, try again in a little bit
            if not capture_successful:
                sleep(5)

                self.debug_message("Capture failed! Attempting to reset camera...")

                # Try and stop, then close the camera object.
                try:
                    self.cam.stop()
                except:
                    self.debug_message("Stopping camera object failed.")
                
                try:
                    self.cam.close()
                except:
                    self.debug_message("Closing camera object failed.")

                try:
                    self.init_camera()
                except:
                    self.debug_message("Error initializing camera!")
                    sleep(1)

                continue

            # Otherwise, proceed to post-processing step.
            if post_process_ptr != None:
                try:
                    self.debug_message("Running Image Post-Processing")
                    post_process_ptr(capture_filename)
                except:
                    error_str = traceback.format_exc()
                    self.debug_message("Image Post-Processing Failed: %s" % error_str)

            # SSDV'ify the image.
            ssdv_filename = self.ssdvify(capture_filename, image_id=image_id)

            # Check the SSDV Conversion has completed properly. If not, continue
            if ssdv_filename == "FAIL":
                sleep(1)
                continue


            # Otherwise, read in the file and push into the TX buffer.
            file_size = os.path.getsize(ssdv_filename)

            # Wait until the transmit queue is empty before pushing in packets.
            self.debug_message("Waiting for SSDV TX queue to empty.")
            while tx.image_queue_empty() == False:
                sleep(0.05) # Sleep for a short amount of time.
                if self.auto_capture_running == False:
                    return

            # Inform ground station we are about to send an image.
            self.debug_message("Transmitting %d PiCam SSDV Packets." % (file_size//256))

            # Push SSDV file into transmit queue.
            tx.queue_image_file(ssdv_filename)

            # Increment image ID.
            image_id = (image_id + 1) % 256

            _cpu_temp = self.get_cpu_temperature()
            _cpu_freq = self.get_cpu_speed()
            self.debug_message(f"CPU State: Temperature: {_cpu_temp:.1f} degC, Frequency: {_cpu_freq} MHz")

        # Loop!

        self.debug_message("Uh oh, we broke out of the main thread. This is not good!")


    def run(self, destination_directory, tx, post_process_ptr=None, delay = 0, start_id = 0):
        """ Start auto-capturing images in a thread.

        Refer auto_capture function above.
        
        Keyword Arguments:
        destination_directory:	Folder to save images to. Both raw JPEG and SSDV images are saved here.
        tx:		A reference to a PacketTX Object, which is used to transmit packets, and interrogate the TX queue.
        post_process_ptr: An optional function which is called after the image is captured. This function
                          will be passed the path/filename of the captured image.
                          This can be used to add overlays, etc to the image before it is SSDVified and transmitted.
                          NOTE: This function need to modify the image in-place.
        delay:	An optional delay in seconds between capturing images. Defaults to 0.
                This delay is added on top of any delays caused while waiting for the transmit queue to empty.
        start_id: Starting image ID. Defaults to 0.
        """		

        self.auto_capture_running = True

        capture_thread = Thread(target=self.auto_capture, kwargs=dict(
            destination_directory=destination_directory,
            tx = tx,
            post_process_ptr=post_process_ptr,
            delay=delay,
            start_id=start_id))

        capture_thread.start()

    def stop(self):
        self.auto_capture_running = False

    # TODO: Non-blocking image capture.
    capture_finished = False
    def trigger_capture():
        pass

    def get_cpu_temperature(self):
        """ Grab the temperature of the RPi CPU """
        try:
            data = subprocess.check_output("/usr/bin/vcgencmd measure_temp", shell=True)
            temp = data.decode().split('=')[1].split('\'')[0]
            return float(temp)
        except Exception as e:
            self.debug_message("Error reading temperature - %s" % str(e))
            return -999

    def get_cpu_speed(self):
        """ Get the current CPU Frequency """
        try:
            data = subprocess.check_output("cat /sys/devices/system/cpu/cpu0/cpufreq/scaling_cur_freq", shell=True)
            freq = int(data.decode().strip())/1000
            return freq
        except Exception as e:
            self.debug_message("Error reading CPU Freq - %s" % str(e))
            return -1


# Basic transmission test script. TODO - Fix this, this is all incorrect..
if __name__ == "__main__":
    import PacketTX
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("callsign", default="N0CALL", help="Payload Callsign")
    parser.add_argument("--txport", default="/dev/ttyAMA0", type=str, help="Transmitter serial port. Defaults to /dev/ttyAMA0")
    parser.add_argument("--baudrate", default=115200, type=int, help="Transmitter baud rate. Defaults to 115200 baud.")
    args = parser.parse_args()

    callsign = args.callsign
    print("Using Callsign: %s" % callsign)

    def post_process(filename):
        print("Doing nothing with %s" % filename)

    tx = PacketTX.PacketTX(serial_port=args.txport, serial_baud=args.baudrate, callsign=callsign)
    tx.start_tx()


    picam = WenetPiCamera2(src_resolution=(1920,1088), 
        tx_resolution=(1920,1088), 
        callsign=callsign, 
        num_images=5, 
        debug_ptr=tx.transmit_text_message, 
        vertical_flip=False, 
        horizontal_flip=False)

    picam.run(destination_directory="./tx_images/", 
        tx = tx,
        post_process_ptr = post_process
        )
    try:
        while True:
            tx.transmit_text_message("Waiting...")
            sleep(5)
    except KeyboardInterrupt:
        print("Closing")
        picam.stop()
        tx.close()


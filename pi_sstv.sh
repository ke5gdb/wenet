#!/bin/bash

GPIO=22
PROTOCOL=r36
TXDELAY=0.5
CYCLE=60

COUNT=1
while [ TRUE ] ; do
	pinctrl set GPIO17 op dl

	TIME=`date +%s`

	timeout 9 convert /home/pi/wenet/tx/_latest.jpg -resize 320x240^ -gravity center -extent 320x240 /home/pi/ke5gdb_small.png -gravity SouthWest -geometry -0-16 -composite /tmp/image_small.jpg

	pisstv -r 44100 -p $PROTOCOL /tmp/image_small.jpg

	echo -n "Transmitting... "
	pinctrl set GPIO17 op dh
	sleep $TXDELAY
	espeak-ng -f /tmp/gps.txt
	aplay /tmp/image_small.jpg.wav
	pinctrl set GPIO17 op dl
	echo "done!"

	# Counter
	COUNT=$(($COUNT + 1))

	# Sleep
	TIME=$(($(date +%s) - $TIME))
	DELAY=$(($CYCLE - $TIME))
	echo Executing took $TIME seconds, iteration number $COUNT
	if [ $DELAY -gt 0 ] && [ $DELAY -lt $CYCLE ] ; then
		echo Sleeping $DELAY seconds...
		sleep $DELAY
	else
		echo Not sleeping...
	fi
done

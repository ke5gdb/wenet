#!/bin/bash
#
#	Wenet RX-side Initialisation Script - HEADLESS DOCKER VERSION
#	2022 Mark Jessop <vk5qi@rfhead.net>
#
#	This code mostly assumes an RTLSDR will be used for RX.
#
#	This version of the startup script is intended to be run as a Docker container
# on a headless Raspberry Pi 3B+ or newer.
#	A display of imagery and telemetry can be accessed at http://<pi_ip>:5003/
#

# Check that a callsign has been set.
if [ -z "$MYCALL" ]; then
  echo "ERROR: MYCALL has not been set."
	exit 1
fi

set -e
set -u
set -o pipefail
set -x

# Defaults
: "${RXFREQ:=443500000}"
: "${DEVICE:=0}"
: "${GAIN:=0}"
: "${BIAS:=0}"
: "${BAUD_RATE:=115177}"
: "${OVERSAMPLING:=8}"
: "${UDP_PORT:=0}"
: "${WEB_PORT:=5003}"
: "${IMAGE_PORT:=7890}"
: "${UPLOAD_ENABLE:=1}"

# Start up the SSDV Uploader script and push it into the background.
if [ "$UPLOAD_ENABLE" == "1" ] ; then
  python3 ssdvuploader.py --image_port "$IMAGE_PORT" "$MYCALL" &
  SSDV_UPLOAD_PID=$!
fi

# Start the Web Interface Server
NO_SONDEHUB=
if [ "$UPLOAD_ENABLE" != "1" ] ; then
  NO_SONDEHUB="--no_sondehub"
fi

if [ "$UDP_PORT" = "0" ]; then
  python3 wenetserver.py "$MYCALL" --image_port "$IMAGE_PORT" -l "$WEB_PORT" $NO_SONDEHUB &
else
  python3 wenetserver.py "$MYCALL" -u "$UDP_PORT" --image_port "$IMAGE_PORT" -l "$WEB_PORT" $NO_SONDEHUB &
fi
WEB_VIEWER_PID=$!

# Calculate the SDR sample rate required.
SDR_RATE=$(("$BAUD_RATE" * "$OVERSAMPLING"))

echo "Using SDR Sample Rate: $SDR_RATE Hz"
echo "Using SDR Centre Frequency: $RXFREQ Hz"

if [ "$SDR_TYPE" = "RTLSDR" ] ; then
  if [ "$BIAS" = "1" ]; then
    echo "Enabling Bias Tee"
    rtl_biast -d "$DEVICE" -b 1
  fi

  # Start up the receive chain.
  echo "Using Complex Samples."
  rtl_sdr -d "$DEVICE" -s "$SDR_RATE" -f "$RXFREQ" -g "$GAIN" - | \
  ./fsk_demod --cu8 -s --stats=100 -p "$OVERSAMPLING" -b -"$BAUD_RATE" -u "$BAUD_RATE" 2 "$SDR_RATE" "$BAUD_RATE" - - 2> >(python3 fskstatsudp.py --rate 1 --freq $RXFREQ --samplerate $SDR_RATE) | \
  ./drs232_ldpc - -  -vv 2> /dev/null | \
  python3 rx_ssdv.py --partialupdate 16 --headless & 
elif [ "$SDR_TYPE" = "KA9Q" ] ; then
  # Start receiver
  echo "Starting pcmrecord and demodulator"
  pcmrecord --catmode --raw "$DEVICE" --timeout 1 | \
  ./fsk_demod --cs16 -s --stats=100 -p "$OVERSAMPLING" -b -"$BAUD_RATE" -u "$BAUD_RATE" 2 "$SDR_RATE" "$BAUD_RATE" - - 2> >(python3 fskstatsudp.py --rate 1 --freq $RXFREQ --samplerate $SDR_RATE --image_port $IMAGE_PORT) | \
  ./drs232_ldpc - -  -vv 2> /dev/null | \
  python3 rx_ssdv.py --partialupdate 16 --headless --image_port $IMAGE_PORT & 
else
  echo "No valid SDR type specified! Please enter RTLSDR or KA9Q!"
fi

echo "Waiting for any failed processes"
wait -n 

# Kill off the SSDV Uploader and the GUIs
kill $SSDV_UPLOAD_PID
kill $WEB_VIEWER_PID
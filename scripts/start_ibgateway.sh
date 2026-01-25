#!/bin/bash
# IB Gateway Headless Startup Script
# Run with: ./start_ibgateway.sh

export JAVA_HOME=/usr/lib/jvm/java-17-openjdk-amd64
export IBGATEWAY_HOME=/root/Jts/ibgateway/1037

# Use Xvfb for headless operation
export DISPLAY=:99

# Start Xvfb in background
Xvfb :99 -screen 0 1024x768x24 &
XVFB_PID=$!
sleep 2

# Run IB Gateway in API-only mode
cd $IBGATEWAY_HOME
./ibgateway -mode=headless -apiport=7497 -papiuser=YOUR_IBKR_USERNAME -papipass=YOUR_IBKR_PASSWORD

# Cleanup Xvfb on exit
kill $XVFB_PID 2>/dev/null

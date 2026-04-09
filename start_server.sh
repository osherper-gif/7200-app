#!/bin/bash
echo "================================================"
echo " MDS Project System Server - Starting..."
echo "================================================"

# Check Python
if ! command -v python3 &> /dev/null; then
    echo "ERROR: python3 not found. Install with: sudo apt install python3 python3-pip"
    exit 1
fi

# Install dependencies
echo "Installing / verifying dependencies..."
pip3 install flask flask-cors --quiet

# Get local IP
LOCAL_IP=$(hostname -I | awk '{print $1}' 2>/dev/null || echo "YOUR-IP")

echo ""
echo "================================================"
echo " Server starting on http://localhost:5000"
echo " Share with colleagues: http://$LOCAL_IP:5000"
echo " Press Ctrl+C to stop"
echo "================================================"
echo ""

python3 server.py --port 5000 --data-dir ./data

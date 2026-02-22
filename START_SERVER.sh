#!/bin/bash
cd "$(dirname "$0")"
echo "Starting Flask server..."
echo "Open your browser and go to: http://localhost:5000"
echo "Press Ctrl+C to stop the server"
`python3 app.py`

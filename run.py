# run.py
# Only purpose of this file is to start Flask
# Run this from terminal: python run.py
# Never open this in Jupyter notebook

import os
import sys

# Add project folder to path
sys.path.insert(0, os.path.abspath("."))

from dotenv import load_dotenv
load_dotenv(override=True)

# Import the Flask app from app.py
from app import app, init_db

# Initialize database
print("── Initializing database ──")
init_db()

# Start Flask server
print("── Starting Flask server ──")
print("Open browser: http://localhost:5000")
app.run(debug=False, port=5000)

# run.py
# Production ready Flask starter

import os
from dotenv import load_dotenv
load_dotenv(override=True)

from app import app, init_db

# Initialize database on startup
init_db()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)
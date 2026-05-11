#%%
# config.py
# This file reads all secret keys from .env file
# Every other file will import from here

from dotenv import load_dotenv
import os

# Load the .env file
load_dotenv()
# %%
# ─── AI Config ────────────────────────────────────────────
# Groq API key for AI slot picking
GROQ_API_KEY = os.getenv("GROQ_API_KEY")
# %%
# ─── Google Calendar Config ───────────────────────────────
# Path to your downloaded credentials.json file
GOOGLE_CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE")

# primary = your main Google Calendar
CALENDAR_ID = os.getenv("CALENDAR_ID", "primary")
# %%
# ─── Gmail Config ─────────────────────────────────────────
GMAIL_ADDRESS      = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD = os.getenv("GMAIL_APP_PASSWORD")
# %%
# ─── Flask Config ─────────────────────────────────────────
SECRET_KEY = os.getenv("SECRET_KEY")
# %%
# ─── Database Config ──────────────────────────────────────
DATABASE_URL = os.getenv("DATABASE_URL")
# %%

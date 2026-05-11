#%%


from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from googleapiclient.discovery import build
from config import GOOGLE_CREDENTIALS_FILE, CALENDAR_ID
from datetime import datetime, timedelta
import os
# %%
# ─── Google Calendar Permission Scope ─────────────────────
# This tells Google what our app is allowed to do
# We need read AND write — read to check slots, write to book

SCOPES = ["https://www.googleapis.com/auth/calendar"]
# %%
# ─── Authenticate and Connect ─────────────────────────────
# First time → opens browser → you log in → saves token.json
# Every time after → uses saved token.json automatically
# No manual login needed after first time

def get_calendar_service():
    creds = None

    # Check if token.json already exists from previous login
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)

    # If no valid credentials found — start login flow
    if not creds or not creds.valid:

        # If token expired but refresh token exists — refresh it
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())

        # Otherwise open browser for fresh login
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE, SCOPES
            )
            # Opens browser on your machine for login
            creds = flow.run_local_server(port=0)

        # Save token for next time — no login needed again
        with open("token.json", "w") as token_file:
            token_file.write(creds.to_json())
            print("Login successful. Token saved.")

    # Return connected calendar service
    service = build("calendar", "v3", credentials=creds)
    return service
# %%
# ─── Get Busy Slots ───────────────────────────────────────
# Fetches all busy time blocks from your Google Calendar
# Looks ahead 7 days from today
# Returns list of busy periods with start and end times

def get_busy_slots():
    service = get_calendar_service()

    # Time range — now until 7 days from now
    now      = datetime.utcnow()
    end_time = now + timedelta(days=7)

    # Format time as Google Calendar expects
    time_min = now.isoformat()      + "Z"
    time_max = end_time.isoformat() + "Z"

    # Ask Google Calendar for all busy periods
    body = {
        "timeMin" : time_min,
        "timeMax" : time_max,
        "items"   : [{"id": CALENDAR_ID}]
    }

    result = service.freebusy().query(body=body).execute()

    # Extract busy periods from response
    busy_periods = result["calendars"][CALENDAR_ID]["busy"]

    print(f"Found {len(busy_periods)} busy periods in next 7 days.")
    return busy_periods
# %%
# ─── Get Free Slots ───────────────────────────────────────
# Calculates all free gaps in your calendar
# Only returns slots during working hours (9am to 6pm)
# Only returns gaps of 30 minutes or more
# This list goes to Groq AI to pick the best one

def get_free_slots():
    service     = get_calendar_service()
    busy_slots  = get_busy_slots()

    # Working hours — 9am to 6pm only
    WORK_START = 9   # 9:00 AM
    WORK_END   = 18  # 6:00 PM

    # Check next 7 days
    free_slots = []
    today      = datetime.utcnow().replace(
                    hour=0, minute=0, second=0, microsecond=0
                 )

    for day_offset in range(7):
        # Get current day
        current_day = today + timedelta(days=day_offset)

        # Skip weekends — Saturday=5, Sunday=6
        if current_day.weekday() in [5, 6]:
            continue

        # Set working hours for this day
        work_start = current_day.replace(hour=WORK_START)
        work_end   = current_day.replace(hour=WORK_END)

        # Start checking from work start time
        current_time = work_start

        # Go through each 30 minute block in the day
        while current_time + timedelta(minutes=30) <= work_end:
            slot_end = current_time + timedelta(minutes=30)

            # Check if this block overlaps with any busy period
            is_free = True

            for busy in busy_slots:
                # Parse busy period times
                busy_start = datetime.fromisoformat(
                    busy["start"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                busy_end   = datetime.fromisoformat(
                    busy["end"].replace("Z", "+00:00")
                ).replace(tzinfo=None)

                # Check for overlap
                if current_time < busy_end and slot_end > busy_start:
                    is_free = False
                    break

            # If slot is free add it to our list
            if is_free:
                slot_label = current_time.strftime("%A %I:%M %p")
                free_slots.append(slot_label)

            # Move to next 30 minute block
            current_time += timedelta(minutes=30)

    print(f"Found {len(free_slots)} free slots in next 7 days.")
    return free_slots
# %%
# ─── Book a Meeting ───────────────────────────────────────
# Creates a real event in your Google Calendar
# Called after Groq AI picks the best slot
# Returns the created event link

def book_meeting(name, email, purpose, slot_label):
    service = get_calendar_service()

    # Parse slot label back to datetime
    # slot_label example: "Monday 10:00 AM"
    today     = datetime.utcnow()
    days      = ["Monday","Tuesday","Wednesday",
                 "Thursday","Friday","Saturday","Sunday"]

    # Find which day of week the slot is on
    slot_day  = slot_label.split()[0]
    slot_time = " ".join(slot_label.split()[1:])

    # Calculate the actual date of that day
    today_weekday   = today.weekday()
    target_weekday  = days.index(slot_day)
    days_ahead      = (target_weekday - today_weekday) % 7
    if days_ahead == 0:
        days_ahead = 7
    slot_date       = today + timedelta(days=days_ahead)

    # Parse the time
    slot_datetime   = datetime.strptime(
        f"{slot_date.strftime('%Y-%m-%d')} {slot_time}",
        "%Y-%m-%d %I:%M %p"
    )
    slot_end        = slot_datetime + timedelta(minutes=30)

    # Build the calendar event
    event = {
        "summary"     : f"Meeting with {name}",
        "description" : purpose,
        "start"       : {
            "dateTime" : slot_datetime.isoformat(),
            "timeZone" : "UTC"
        },
        "end"         : {
            "dateTime" : slot_end.isoformat(),
            "timeZone" : "UTC"
        },
        # Send invite to the person who booked
        "attendees"   : [
            {"email": email}
        ],
    }

    # Create the event in Google Calendar
    created_event = service.events().insert(
        calendarId=CALENDAR_ID,
        body=event,
        sendUpdates="all"   # sends email invite automatically
    ).execute()

    print(f"Event created: {created_event.get('htmlLink')}")
    return created_event.get("htmlLink")
# %%
# ─── Test Calendar Service ────────────────────────────────
# Run: python calendar_service.py
# First run opens browser for Google login
# After login prints your free slots for next 7 days

if __name__ == "__main__":

    print("── Step 1: Connecting to Google Calendar ──")
    service = get_calendar_service()
    print("Connected successfully.")

    print("\n── Step 2: Fetching free slots ──")
    slots = get_free_slots()

    print("\n── Your free slots for next 7 days ──")
    for i, slot in enumerate(slots, 1):
        print(f"  {i}. {slot}")
# %%
# Add this function to get credentials from env variable
import json

def get_calendar_service():
    creds = None

    # Check for token first
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file(
            "token.json", SCOPES
        )

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # On server — read credentials from environment variable
            creds_json = os.getenv("GOOGLE_CREDENTIALS_JSON")

            if creds_json:
                # Write to temp file for OAuth flow
                creds_data = json.loads(creds_json)
                with open("temp_creds.json", "w") as f:
                    json.dump(creds_data, f)
                flow  = InstalledAppFlow.from_client_secrets_file(
                    "temp_creds.json", SCOPES
                )
            else:
                flow  = InstalledAppFlow.from_client_secrets_file(
                    GOOGLE_CREDENTIALS_FILE, SCOPES
                )
            creds = flow.run_local_server(port=0)

        with open("token.json", "w") as f:
            f.write(creds.to_json())

    return build("calendar", "v3", credentials=creds)
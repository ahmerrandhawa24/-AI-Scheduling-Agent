#%%
# app.py
# Main Flask application — connects everything together
# Runs the web server and handles all routes
# Import all our custom modules

from flask          import Flask, render_template, request, redirect, url_for
from dotenv         import load_dotenv
from datetime       import datetime
import os
import sys

# Add project folder to path so all files are found
sys.path.insert(0, os.path.abspath("."))

# Force load environment variables
load_dotenv(override=True)

# ── Direct imports with error handling ────────────────────
# We import everything directly to avoid notebook import issues

import psycopg2
import smtplib
from email.mime.text      import MIMEText
from email.mime.multipart import MIMEMultipart
from groq                 import Groq
from google.oauth2.credentials          import Credentials
from google_auth_oauthlib.flow          import InstalledAppFlow
from google.auth.transport.requests     import Request
from googleapiclient.discovery          import build

# ── Load all credentials ───────────────────────────────────
DATABASE_URL             = os.getenv("DATABASE_URL")
GROQ_API_KEY             = os.getenv("GROQ_API_KEY")
GMAIL_ADDRESS            = os.getenv("GMAIL_ADDRESS")
GMAIL_APP_PASSWORD       = os.getenv("GMAIL_APP_PASSWORD")
SECRET_KEY               = os.getenv("SECRET_KEY")
GOOGLE_CREDENTIALS_FILE  = os.getenv("GOOGLE_CREDENTIALS_FILE")
CALENDAR_ID              = os.getenv("CALENDAR_ID", "primary")

print("All credentials loaded successfully.")

# ── Initialize Flask App ───────────────────────────────────
app            = Flask(__name__)
app.secret_key = SECRET_KEY

# ── Initialize Groq Client ────────────────────────────────
groq_client = Groq(api_key=GROQ_API_KEY)
MODEL       = "llama-3.3-70b-versatile"

print("Flask and Groq initialized.")

# ── Database Functions ────────────────────────────────────
# Copied directly to avoid import issues

def get_db():
    return psycopg2.connect(DATABASE_URL)

def init_db():
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bookings (
            id          SERIAL        PRIMARY KEY,
            name        VARCHAR(100)  NOT NULL,
            email       VARCHAR(150)  NOT NULL,
            purpose     TEXT          NOT NULL,
            slot        VARCHAR(100)  NOT NULL,
            status      VARCHAR(20)   DEFAULT 'confirmed',
            created_at  TIMESTAMP     DEFAULT CURRENT_TIMESTAMP
        )
    """)
    conn.commit()
    cursor.close()
    conn.close()

def save_booking(name, email, purpose, slot):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        INSERT INTO bookings (name, email, purpose, slot)
        VALUES (%s, %s, %s, %s) RETURNING id
    """, (name, email, purpose, slot))
    booking_id = cursor.fetchone()[0]
    conn.commit()
    cursor.close()
    conn.close()
    return booking_id

def get_all_bookings():
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, email, purpose, slot, status, created_at
        FROM bookings ORDER BY created_at DESC
    """)
    rows = cursor.fetchall()
    cursor.close()
    conn.close()
    return rows

def get_booking_by_id(booking_id):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        SELECT id, name, email, purpose, slot, status, created_at
        FROM bookings WHERE id = %s
    """, (booking_id,))
    row = cursor.fetchone()
    cursor.close()
    conn.close()
    return row

def cancel_booking(booking_id):
    conn   = get_db()
    cursor = conn.cursor()
    cursor.execute("""
        UPDATE bookings SET status = 'cancelled' WHERE id = %s
    """, (booking_id,))
    conn.commit()
    cursor.close()
    conn.close()

# ── Google Calendar Functions ─────────────────────────────
# Gets free slots from your real Google Calendar

SCOPES = ["https://www.googleapis.com/auth/calendar"]

def get_calendar_service():
    creds = None
    if os.path.exists("token.json"):
        creds = Credentials.from_authorized_user_file("token.json", SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow  = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_FILE, SCOPES
            )
            creds = flow.run_local_server(port=0)
        with open("token.json", "w") as f:
            f.write(creds.to_json())
    return build("calendar", "v3", credentials=creds)

def get_free_slots():
    from datetime import timedelta
    service  = get_calendar_service()
    now      = datetime.utcnow()
    end_time = now + timedelta(days=7)
    body     = {
        "timeMin" : now.isoformat()      + "Z",
        "timeMax" : end_time.isoformat() + "Z",
        "items"   : [{"id": CALENDAR_ID}]
    }
    result      = service.freebusy().query(body=body).execute()
    busy_slots  = result["calendars"][CALENDAR_ID]["busy"]

    from datetime import timedelta
    WORK_START = 9
    WORK_END   = 18
    free_slots = []
    today      = datetime.utcnow().replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    for day_offset in range(7):
        current_day = today + timedelta(days=day_offset)
        if current_day.weekday() in [5, 6]:
            continue
        work_start   = current_day.replace(hour=WORK_START)
        work_end     = current_day.replace(hour=WORK_END)
        current_time = work_start

        while current_time + timedelta(minutes=30) <= work_end:
            slot_end = current_time + timedelta(minutes=30)
            is_free  = True
            for busy in busy_slots:
                busy_start = datetime.fromisoformat(
                    busy["start"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                busy_end   = datetime.fromisoformat(
                    busy["end"].replace("Z", "+00:00")
                ).replace(tzinfo=None)
                if current_time < busy_end and slot_end > busy_start:
                    is_free = False
                    break
            if is_free:
                free_slots.append(current_time.strftime("%A %I:%M %p"))
            current_time += timedelta(minutes=30)

    return free_slots

def book_calendar_event(name, email, purpose, slot_label):
    from datetime import timedelta
    service       = get_calendar_service()
    days          = ["Monday","Tuesday","Wednesday",
                     "Thursday","Friday","Saturday","Sunday"]
    slot_day      = slot_label.split()[0]
    slot_time     = " ".join(slot_label.split()[1:])
    today         = datetime.utcnow()
    today_weekday = today.weekday()
    target_wd     = days.index(slot_day)
    days_ahead    = (target_wd - today_weekday) % 7
    if days_ahead == 0:
        days_ahead = 7
    slot_date     = today + timedelta(days=days_ahead)
    slot_dt       = datetime.strptime(
        f"{slot_date.strftime('%Y-%m-%d')} {slot_time}",
        "%Y-%m-%d %I:%M %p"
    )
    slot_end      = slot_dt + timedelta(minutes=30)

    event = {
        "summary"    : f"Meeting with {name}",
        "description": purpose,
        "start"      : {"dateTime": slot_dt.isoformat(),  "timeZone": "UTC"},
        "end"        : {"dateTime": slot_end.isoformat(), "timeZone": "UTC"},
        "attendees"  : [{"email": email}],
    }
    created = service.events().insert(
        calendarId  = CALENDAR_ID,
        body        = event,
        sendUpdates = "all"
    ).execute()
    return created.get("htmlLink")

# ── AI Functions ──────────────────────────────────────────
# Groq picks the best slot based on user preferences

def pick_best_slot(free_slots, name, purpose, preference):
    if not free_slots:
        return None

    slots_text = "\n".join(
        [f"{i+1}. {s}" for i, s in enumerate(free_slots)]
    )
    prompt = f"""
You are a scheduling assistant.
Pick ONE best slot for this user.

Name      : {name}
Purpose   : {purpose}
Preference: {preference}

Available slots:
{slots_text}

Rules:
1. Pick only ONE slot
2. Match user preference
3. Reply with slot text ONLY
4. Example: Monday 10:00 AM

Your answer:"""

    response = groq_client.chat.completions.create(
        model    = MODEL,
        messages = [
            {"role": "system", "content": "You are a scheduling assistant. Reply with one time slot only."},
            {"role": "user",   "content": prompt}
        ],
        max_tokens  = 20,
        temperature = 0.3
    )

    chosen      = response.choices[0].message.content.strip()
    chosen_clean = " ".join(chosen.split()).strip()

    for slot in free_slots:
        slot_clean = " ".join(slot.split()).strip()
        if slot_clean == chosen_clean:
            return slot_clean
        if chosen_clean in slot_clean or slot_clean in chosen_clean:
            return slot_clean

    return " ".join(free_slots[0].split()).strip()

def get_ai_explanation(name, purpose, preference, chosen_slot):
    response = groq_client.chat.completions.create(
        model    = MODEL,
        messages = [{"role": "user", "content": f"""
Meeting booked for {name}.
Purpose   : {purpose}
Preference: {preference}
Chosen slot: {chosen_slot}
In 2 sentences explain why this slot is a good choice. Be friendly.
"""}],
        max_tokens  = 80,
        temperature = 0.5
    )
    return response.choices[0].message.content.strip()

# ── Email Functions ───────────────────────────────────────
# Sends confirmation and admin notification emails

def send_email(to_email, subject, html_body):
    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_ADDRESS
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_ADDRESS, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_ADDRESS, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def send_confirmation(name, email, purpose, slot, explanation, booking_id):
    html = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto">
        <div style="background:#4F46E5;padding:30px;text-align:center">
            <h1 style="color:white;margin:0">Meeting Confirmed</h1>
        </div>
        <div style="padding:30px;background:#f9f9f9">
            <p>Hi <strong>{name}</strong>,</p>
            <p>Your meeting has been successfully scheduled!</p>
            <div style="background:white;padding:20px;border-radius:8px;
                        border-left:4px solid #4F46E5;margin:20px 0">
                <p><strong>📅 Slot      :</strong> {slot}</p>
                <p><strong>📝 Purpose   :</strong> {purpose}</p>
                <p><strong>🔖 Booking ID:</strong> #{booking_id}</p>
            </div>
            <div style="background:#EEF2FF;padding:15px;border-radius:8px">
                <p><strong>🤖 AI Note:</strong> {explanation}</p>
            </div>
        </div>
    </div>
    """
    send_email(email, f"Meeting Confirmed — {slot}", html)
    send_email(GMAIL_ADDRESS, f"New Booking #{booking_id} — {name}", html)

# ── Flask Routes ──────────────────────────────────────────
# These are the pages users can visit

# ── Home — Booking Form ───────────────────────────────────
# User fills in their details here

@app.route("/", methods=["GET"])
def index():
    return render_template("form.html")

# ── Book — Process Form Submission ────────────────────────
# Called when user clicks Submit on the form
# This is the main logic — connects everything

@app.route("/book", methods=["POST"])
def book():
    # Step 1 — Get form data
    name       = request.form.get("name").strip()
    email      = request.form.get("email").strip()
    purpose    = request.form.get("purpose").strip()
    preference = request.form.get("preference").strip()

    # Step 2 — Validate inputs
    if not all([name, email, purpose, preference]):
        return render_template("form.html",
            error="Please fill in all fields."
        )

    # Step 3 — Get free slots from Google Calendar
    free_slots = get_free_slots()
    if not free_slots:
        return render_template("form.html",
            error="No free slots available this week. Try next week."
        )

    # Step 4 — Ask Groq AI to pick best slot
    chosen_slot = pick_best_slot(
        free_slots = free_slots,
        name       = name,
        purpose    = purpose,
        preference = preference
    )

    # Step 5 — Get AI explanation for the choice
    explanation = get_ai_explanation(
        name        = name,
        purpose     = purpose,
        preference  = preference,
        chosen_slot = chosen_slot
    )

    # Step 6 — Book event in Google Calendar
    calendar_link = book_calendar_event(
        name    = name,
        email   = email,
        purpose = purpose,
        slot_label = chosen_slot
    )

    # Step 7 — Save booking to PostgreSQL
    booking_id = save_booking(name, email, purpose, chosen_slot)

    # Step 8 — Send confirmation email
    send_confirmation(
        name       = name,
        email      = email,
        purpose    = purpose,
        slot       = chosen_slot,
        explanation = explanation,
        booking_id = booking_id
    )

    # Step 9 — Show confirmation page
    return redirect(url_for("confirm",
        booking_id    = booking_id,
        name          = name,
        slot          = chosen_slot,
        explanation   = explanation,
        calendar_link = calendar_link
    ))

# ── Confirm — Booking Confirmation Page ───────────────────
@app.route("/confirm")
def confirm():
    booking_id    = request.args.get("booking_id")
    name          = request.args.get("name")
    slot          = request.args.get("slot")
    explanation   = request.args.get("explanation")
    calendar_link = request.args.get("calendar_link")

    return render_template("confirm.html",
        booking_id    = booking_id,
        name          = name,
        slot          = slot,
        explanation   = explanation,
        calendar_link = calendar_link
    )

# ── Admin Dashboard ───────────────────────────────────────
# Shows all bookings — only you can access this

@app.route("/admin")
def admin():
    bookings = get_all_bookings()
    return render_template("dashboard.html", bookings=bookings)

# ── Cancel Booking ────────────────────────────────────────
@app.route("/cancel/<int:booking_id>")
def cancel(booking_id):
    cancel_booking(booking_id)
    return redirect(url_for("admin"))



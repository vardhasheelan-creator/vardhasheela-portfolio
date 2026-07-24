from flask import Flask, request, jsonify, render_template, redirect, session, send_file
from werkzeug.utils import secure_filename
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
from apscheduler.schedulers.background import BackgroundScheduler
from dotenv import load_dotenv
import atexit
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import json
import sqlite3
from datetime import datetime, timedelta, date
import pytz
from functools import wraps

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
CORS(app)

GMAIL_USER         = os.environ.get("GMAIL_USER", "vardhasheelan@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
CALENDAR_ID        = os.environ.get("CALENDAR_ID", "vardhasheelan@gmail.com")
ADMIN_PASSWORD     = os.environ.get("ADMIN_PASSWORD", "wenixai2026")
UPI_ID             = "9113259228@kotakbank"
UPI_NAME           = "Vardhasheela N"
IST                = pytz.timezone("Asia/Kolkata")
BOOKINGS_FILE      = "/data/bookings.json"
JOBS_DB_PATH       = "/data/jobs.db"
TESTIMONIALS_FILE  = "/data/testimonials.json"
SCOPES             = ["https://www.googleapis.com/auth/calendar"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

SESSION_DURATIONS = {
    "30min": {"label": "30-min Clarity Call", "duration": 30, "price": 2500},
    "1hr":   {"label": "1-hr Deep Dive",      "duration": 60, "price": 3000},
}

AVAILABILITY = {
    "days":       [0, 1, 2, 3, 4],
    "start_hour": 16,
    "end_hour":   21,
}

# ── BOOKINGS ─────────────────────────────────────────────────────

def load_bookings():
    if not os.path.exists(BOOKINGS_FILE):
        return []
    with open(BOOKINGS_FILE) as f:
        return json.load(f)

def save_bookings(bookings):
    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, indent=2)

def save_booking(booking):
    bookings = load_bookings()
    bookings.append(booking)
    save_bookings(bookings)

# ── DATABASE ─────────────────────────────────────────────────────

JOBS_SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    airline_name TEXT NOT NULL,
    category TEXT NOT NULL CHECK (category IN ('domestic', 'international')),
    role_type TEXT NOT NULL CHECK (role_type IN ('cabin_crew', 'ground_staff', 'other')),
    role_title TEXT NOT NULL,
    location TEXT,
    eligibility_summary TEXT,
    application_link TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closing_soon', 'closed')),
    last_verified_date TEXT NOT NULL,
    notes TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS job_alert_subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT,
    email TEXT NOT NULL UNIQUE,
    interested_category TEXT,
    interested_role TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_jobs_role_type ON jobs(role_type);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

RESOURCES_DIR = "/data/resources"
os.makedirs(RESOURCES_DIR, exist_ok=True)

RESOURCES_SCHEMA = """
CREATE TABLE IF NOT EXISTS resources (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL,
    description TEXT,
    category TEXT NOT NULL CHECK (category IN ('cabin_crew', 'ground_staff', 'all')),
    filename TEXT NOT NULL,
    sent_count INTEGER DEFAULT 0,
    uploaded_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE TABLE IF NOT EXISTS resource_sends (
    resource_id INTEGER NOT NULL,
    email TEXT NOT NULL,
    sent_at TEXT DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (resource_id, email)
);
"""

def get_jobs_db():
    conn = sqlite3.connect(JOBS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_jobs_db():
    conn = sqlite3.connect(JOBS_DB_PATH)
    conn.executescript(JOBS_SCHEMA)
    conn.executescript(RESOURCES_SCHEMA)
    # ── safely add name column to existing installs ──
    try:
        conn.execute("ALTER TABLE job_alert_subscribers ADD COLUMN name TEXT")
        conn.commit()
    except Exception:
        pass  # column already exists — safe to ignore
    conn.commit()
    conn.close()

init_jobs_db()

# ── FEEDBACK SCHEDULER ───────────────────────────────────────────

FEEDBACK_SEND_BUFFER_MINUTES = 30

def send_pending_feedback_emails():
    bookings = load_bookings()
    changed  = False
    now      = datetime.now(IST)
    for b in bookings:
        if b.get("status") != "confirmed":
            continue
        if b.get("feedback_email_sent"):
            continue
        try:
            d = datetime.strptime(b["date"], "%Y-%m-%d")
            h, m = map(int, b["time"].split(":"))
            stype = SESSION_DURATIONS.get(b.get("session_type", "1hr"), {"duration": 60, "label": "Session"})
            session_start = IST.localize(datetime(d.year, d.month, d.day, h, m))
            session_end   = session_start + timedelta(minutes=stype["duration"])
        except Exception as ex:
            print(f"Feedback scheduler — skipping {b.get('id')}: {ex}")
            continue
        if now >= session_end + timedelta(minutes=FEEDBACK_SEND_BUFFER_MINUTES):
            date_display = d.strftime("%d %B %Y")
            time_display = datetime(2000, 1, 1, h, m).strftime("%I:%M %p")
            sent = send_email(
                b["email"], b["name"],
                "How was your session? — Vardhasheela N",
                feedback_request_email(b["name"], stype.get("label", ""), date_display, time_display, b["id"])
            )
            if sent:
                b["feedback_email_sent"] = True
                changed = True
    if changed:
        save_bookings(bookings)

def start_feedback_scheduler():
    scheduler = BackgroundScheduler(timezone="Asia/Kolkata")
    scheduler.add_job(send_pending_feedback_emails, "interval", minutes=30,
                      next_run_time=datetime.now(IST))
    scheduler.start()
    atexit.register(lambda: scheduler.shutdown(wait=False))

# ── Only start scheduler in worker 0 to avoid duplicate emails ──
# Gunicorn runs multiple workers — APScheduler must only run in one.
# We use a file-based lock so only the first worker that boots runs it.
import fcntl, tempfile

def start_scheduler_once():
    lock_path = "/tmp/feedback_scheduler.lock"
    try:
        lock_file = open(lock_path, "w")
        fcntl.flock(lock_file, fcntl.LOCK_EX | fcntl.LOCK_NB)
        start_feedback_scheduler()
        # keep lock_file open so lock is held for process lifetime
        app._scheduler_lock = lock_file
    except (IOError, OSError):
        pass  # another worker already holds the lock — skip

if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    start_scheduler_once()

# ── GOOGLE CALENDAR ──────────────────────────────────────────────

def get_calendar_service():
    if "credentials" not in session:
        return None
    creds   = Credentials(**session["credentials"])
    service = build("calendar", "v3", credentials=creds)
    session["credentials"] = {
        "token":         creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri":     creds.token_uri,
        "client_id":     creds.client_id,
        "client_secret": creds.client_secret,
        "scopes":        creds.scopes,
    }
    return service

# ── EMAIL HELPER ─────────────────────────────────────────────────

def send_email(to_email, to_name, subject, body_html):
    try:
        msg            = MIMEMultipart("alternative")
        msg["Subject"] = subject
        msg["From"]    = GMAIL_USER
        msg["To"]      = to_email
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

# ── NAME HELPER ──────────────────────────────────────────────────

def greeting(name):
    """Returns 'Hi Priya,' if name exists, else 'Hi there,'"""
    n = (name or "").strip()
    return f"Hi {n.split()[0]}," if n else "Hi there,"

# ── SUBSCRIBER HELPERS ───────────────────────────────────────────

def get_matching_subscribers(category):
    """Returns list of (email, name) tuples."""
    conn = get_jobs_db()
    if category == "all":
        rows = conn.execute(
            "SELECT email, name FROM job_alert_subscribers"
        ).fetchall()
    else:
        rows = conn.execute(
            "SELECT email, name FROM job_alert_subscribers WHERE interested_role = ? OR interested_role = 'all'",
            (category,)
        ).fetchall()
    conn.close()
    return [(r["email"], r["name"]) for r in rows]

def get_already_sent_emails(resource_id):
    conn  = get_jobs_db()
    rows  = conn.execute(
        "SELECT email FROM resource_sends WHERE resource_id = ?", (resource_id,)
    ).fetchall()
    conn.close()
    return set(r["email"] for r in rows)

def mark_resource_sent(resource_id, email):
    conn = get_jobs_db()
    conn.execute(
        "INSERT OR IGNORE INTO resource_sends (resource_id, email) VALUES (?, ?)",
        (resource_id, email)
    )
    conn.commit()
    conn.close()

# ── EMAIL TEMPLATES ──────────────────────────────────────────────

def client_confirmation_email(name, session_type, date_str, time_str):
    stype = SESSION_DURATIONS[session_type]
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <div style="border-bottom:1px solid rgba(123,92,250,0.3);padding-bottom:20px;margin-bottom:28px">
        <h1 style="margin:0;font-size:22px;color:#fff">Booking received ✅</h1>
        <p style="margin:6px 0 0;color:#9997aa;font-size:13px">vardhasheela.com · awaiting confirmation</p>
      </div>
      <p>Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Your session request has been received! Vardhasheela will confirm within a few hours.</p>
      <div style="background:rgba(123,92,250,0.1);border:1px solid rgba(123,92,250,0.3);border-radius:8px;padding:20px;margin:20px 0">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:120px">Session</td><td style="color:#fff;font-weight:600">{stype['label']}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']:,}</td></tr>
        </table>
      </div>
      <div style="background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.25);border-radius:8px;padding:16px;margin:20px 0">
        <p style="color:#00FF88;font-weight:600;margin:0 0 8px;font-size:14px">💰 Payment details</p>
        <p style="color:#e8e6f0;margin:4px 0;font-size:14px">Amount: <strong>₹{stype['price']:,}</strong></p>
        <p style="color:#e8e6f0;margin:4px 0;font-size:14px">UPI ID: <strong>{UPI_ID}</strong></p>
        <p style="color:#e8e6f0;margin:4px 0;font-size:14px">Name: <strong>{UPI_NAME}</strong></p>
        <p style="color:#9997aa;margin:8px 0 0;font-size:12px">Please complete payment before your session. Share the screenshot via WhatsApp: +91 9113259228</p>
      </div>
      <p style="color:#9997aa;font-size:13px">A Microsoft Teams link will be shared once your booking is confirmed.</p>
      <div style="border-top:1px solid rgba(255,255,255,0.08);margin-top:28px;padding-top:16px">
        <p style="color:#5c5a6b;font-size:12px;margin:0">Vardhasheela N · vardhasheelan@gmail.com · +91 9113259228</p>
      </div>
    </div>
    """

def owner_notification_email(name, email, phone, session_type, date_str, time_str, goal, followup, topic, booking_id):
    stype    = SESSION_DURATIONS[session_type]
    base_url = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h2 style="color:#7b5cfa;margin:0 0 20px">🔔 New consultation booking</h2>
      <div style="background:rgba(0,245,255,0.08);border:1px solid rgba(0,245,255,0.2);border-radius:8px;padding:20px;margin-bottom:20px">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:120px">Name</td><td style="color:#fff;font-weight:600">{name}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Email</td><td style="color:#00f5ff">{email}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Phone</td><td style="color:#fff">{phone or 'Not provided'}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Session</td><td style="color:#fff">{stype['label']} ({stype['duration']} min)</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']:,}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Goal</td><td style="color:#fff">{goal or 'Not specified'}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Follow-up</td><td style="color:#fff">{followup or 'N/A'}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Notes</td><td style="color:#fff">{topic or 'None'}</td></tr>
        </table>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <a href="{base_url}/admin/action/{booking_id}/confirm" style="background:#22C55E;color:#000;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">✓ Confirm</a>
        <a href="{base_url}/admin/action/{booking_id}/decline" style="background:#EF4444;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">✗ Decline</a>
        <a href="{base_url}/admin" style="background:#7B5CFA;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">Admin panel</a>
      </div>
    </div>
    """

def client_confirmed_email(name, session_type, date_str, time_str, meet_link=""):
    stype        = SESSION_DURATIONS[session_type]
    meet_section = f'<p style="color:#9997aa">Teams Link: <a href="{meet_link}" style="color:#00f5ff">{meet_link}</a></p>' if meet_link else ''
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#22C55E;margin:0 0 20px">✅ Session confirmed!</h1>
      <p>Hi <strong>{name}</strong>, you're all set!</p>
      <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:20px;margin:20px 0">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:120px">Session</td><td style="color:#fff;font-weight:600">{stype['label']}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
        </table>
      </div>
      {meet_section}
      <p style="color:#9997aa;font-size:13px">See you then! To reschedule, please reply to this email at least 48 hours before your session. Last-minute cancellations are non-refundable.</p>
    </div>
    """

def client_declined_email(name, session_type, date_str, time_str):
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#EF4444;margin:0 0 20px">Session request update</h1>
      <p>Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Unfortunately the slot on <strong style="color:#fff">{date_str} at {time_str} IST</strong> is no longer available. Please visit <a href="https://consultation.vardhasheelan.com" style="color:#00f5ff">consultation.vardhasheelan.com</a> to book another slot.</p>
      <p style="color:#9997aa;font-size:13px">Sorry for the inconvenience! — Vardhasheela</p>
    </div>
    """

def feedback_request_email(name, session_type_label, date_str, time_str, booking_id):
    base_url = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#FF2CF3;margin:0 0 16px">How was your session?</h1>
      <p>Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Hope your <strong style="color:#fff">{session_type_label}</strong> on {date_str} at {time_str} IST was useful! I'd love to hear how it went — takes less than a minute.</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{base_url}/feedback/{booking_id}" style="background:#FF2CF3;color:#1a0518;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;display:inline-block">Leave feedback →</a>
      </div>
      <p style="color:#5c5a6b;font-size:12px;margin-top:20px">Thanks for your time — Vardhasheela</p>
    </div>
    """

def feedback_notification_email(booking, rating, comment):
    stars = "⭐" * int(rating) + "☆" * (5 - int(rating))
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h2 style="color:#FF2CF3;margin:0 0 20px">💬 New session feedback</h2>
      <div style="background:rgba(255,44,243,0.08);border:1px solid rgba(255,44,243,0.2);border-radius:8px;padding:20px;margin-bottom:20px">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:110px">From</td><td style="color:#fff;font-weight:600">{booking.get('name','')}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Email</td><td style="color:#00f5ff">{booking.get('email','')}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Session</td><td style="color:#fff">{SESSION_DURATIONS.get(booking.get('session_type','1hr'),{}).get('label','')}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Rating</td><td style="color:#FFD700;font-size:18px">{stars}</td></tr>
        </table>
        <p style="color:#9997aa;font-size:12px;margin:14px 0 4px">Comment:</p>
        <p style="color:#fff;font-size:14px;white-space:pre-wrap">{comment or '(no comment left)'}</p>
      </div>
    </div>
    """

def resource_email(title, description, download_url, name=None):
    hi = greeting(name)
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#FF2CF3;margin:0 0 16px">{title}</h1>
      <p style="color:#e8e6f0;margin-bottom:16px">{hi}</p>
      <p style="color:#e8e6f0;white-space:pre-wrap">{description}</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{download_url}" style="background:#FF2CF3;color:#1a0518;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;display:inline-block">Download PDF →</a>
      </div>
      <p style="color:#5c5a6b;font-size:12px;margin-top:20px">You're receiving this because you subscribed to job alerts on the aviation careers board.<br>Vardhasheela N — @vardhasheela.n</p>
    </div>
    """

def subscriber_welcome_email(name=None):
    hi       = greeting(name)
    base_url = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#FF2CF3;margin:0 0 16px">You're on the list! ✈️</h1>
      <p style="color:#e8e6f0;margin-bottom:12px">{hi}</p>
      <p style="color:#e8e6f0">Thanks for subscribing to the aviation jobs board alert.</p>
      <p style="color:#9997aa;margin-top:12px">I'll email you the moment a new cabin crew or ground staff role opens up matching your interest. No spam — just real openings, manually verified by me.</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{base_url}/jobs" style="background:#FF2CF3;color:#1a0518;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;display:inline-block">Browse current openings →</a>
      </div>
      <p style="color:#5c5a6b;font-size:12px;margin-top:20px">Vardhasheela N — @vardhasheela.n</p>
    </div>
    """

def announcement_email(name, subject, body_text, cta_text, cta_url):
    """Generic personalized announcement email for bulk sends from admin."""
    hi = greeting(name)
    # convert newlines to <br> for HTML
    body_html = body_text.replace("\n", "<br>")
    cta_section = f"""
      <div style="text-align:center;margin:28px 0">
        <a href="{cta_url}" style="background:#FF2CF3;color:#1a0518;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;display:inline-block">{cta_text}</a>
      </div>
    """ if cta_url and cta_text else ""
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <p style="color:#e8e6f0;font-size:16px;margin-bottom:20px">{hi}</p>
      <div style="color:#c8c6de;font-size:15px;line-height:1.8">{body_html}</div>
      {cta_section}
      <div style="border-top:1px solid rgba(255,255,255,0.07);margin-top:32px;padding-top:16px">
        <p style="color:#5c5a6b;font-size:12px;margin:0">Vardhasheela N · @vardhasheela.n on YouTube<br>
        You're receiving this because you subscribed to the aviation jobs board.</p>
      </div>
    </div>
    """

# ── ADMIN AUTH ───────────────────────────────────────────────────

def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect("/admin/login")
        return f(*args, **kwargs)
    return decorated

@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    error = ""
    if request.method == "POST":
        if request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect("/admin")
        error = "Wrong password"
    return f"""<!DOCTYPE html><html><head><title>Admin</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;}}
    .box{{background:#0f0f1a;border:1px solid rgba(123,92,250,0.3);border-radius:12px;padding:2.5rem;width:360px;}}
    h2{{color:#7b5cfa;margin-bottom:1.5rem;}}
    input{{width:100%;background:#070710;border:1px solid rgba(123,92,250,0.2);border-radius:6px;padding:0.75rem 1rem;color:#e8e6f0;font-size:0.9rem;margin-bottom:1rem;outline:none;}}
    button{{width:100%;background:#7b5cfa;color:#fff;border:none;border-radius:6px;padding:0.85rem;font-size:0.9rem;font-weight:600;cursor:pointer;}}
    .err{{color:#ff6b6b;font-size:0.8rem;margin-bottom:1rem;}}</style></head>
    <body><div class="box"><h2>Admin login</h2>
    <form method="POST">{'<p class="err">'+error+'</p>' if error else ''}
    <input type="password" name="password" placeholder="Password" autofocus/>
    <button type="submit">Login →</button></form></div></body></html>"""

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin/login")

@app.route("/admin")
@admin_required
def admin_panel():
    bookings = sorted(load_bookings(), key=lambda x: x.get("booked_at", ""), reverse=True)
    rows     = ""
    for b in bookings:
        bid    = b.get("id", "")
        status = b.get("status", "pending")
        stype  = SESSION_DURATIONS.get(b.get("session_type", "1hr"), {})
        sc     = {"pending":"#BA7517","confirmed":"#22C55E","declined":"#EF4444"}.get(status,"#888")
        actions = f'''
          <a href="/admin/action/{bid}/confirm" style="background:#22C55E;color:#000;padding:5px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:600;margin-right:6px">Confirm</a>
          <a href="/admin/action/{bid}/decline" style="background:#EF4444;color:#fff;padding:5px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:600">Decline</a>
        ''' if status == "pending" else f'<span style="color:{sc};font-size:12px;font-weight:600">{status.upper()}</span>'
        fb = b.get("feedback")
        if fb:
            stars_html = "★" * int(fb.get("rating",0)) + "☆" * (5-int(fb.get("rating",0)))
            fb_cell = f'<span style="color:#FFD700">{stars_html}</span><br><span style="color:#9997aa;font-size:11px">{(fb.get("comment","") or "—")[:60]}</span>'
        else:
            fb_cell = '<span style="color:#5c5a6b;font-size:11px">—</span>'
        rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.06)">
          <td style="padding:12px 8px;color:#fff;font-size:13px">{b.get('name','')}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{b.get('email','')}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{b.get('phone','') or '—'}</td>
          <td style="padding:12px 8px;color:#00f5ff;font-size:12px">{b.get('date','')} {b.get('time','')}</td>
          <td style="padding:12px 8px;color:#7b5cfa;font-size:12px">{stype.get('label','')}<br><span style="color:#9997aa">₹{stype.get('price','')}</span></td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{b.get('goal','—')}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px;max-width:140px">{(b.get('topic','') or '—')[:50]}</td>
          <td style="padding:12px 8px">{fb_cell}</td>
          <td style="padding:12px 8px">{actions}</td></tr>"""
    pending   = sum(1 for b in bookings if b.get("status","pending")=="pending")
    confirmed = sum(1 for b in bookings if b.get("status")=="confirmed")
    return f"""<!DOCTYPE html><html><head><title>Admin — Bookings</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:sans-serif;padding:2rem;}}
    .header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;flex-wrap:wrap;gap:1rem;}}
    h1{{color:#7b5cfa;font-size:1.4rem;}}
    .stats{{display:flex;gap:1.5rem;flex-wrap:wrap;}}
    .stat{{background:#0f0f1a;border:1px solid rgba(123,92,250,0.2);border-radius:8px;padding:0.75rem 1.25rem;text-align:center;}}
    .stat strong{{display:block;font-size:1.5rem;color:#fff;}}
    .stat span{{font-size:11px;color:#9997aa;}}
    table{{width:100%;border-collapse:collapse;background:#0f0f1a;border:1px solid rgba(123,92,250,0.15);border-radius:8px;overflow:hidden;}}
    th{{padding:12px 8px;text-align:left;font-size:11px;color:#9997aa;letter-spacing:0.08em;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.08);}}
    tr:hover{{background:rgba(123,92,250,0.04);}}
    .btn{{font-size:12px;text-decoration:none;border:1px solid rgba(255,255,255,0.1);padding:6px 14px;border-radius:4px;}}
    </style></head><body>
    <div class="header">
      <div><h1>Consultation bookings</h1><p style="color:#9997aa;font-size:13px;margin-top:4px">consultation.vardhasheelan.com</p></div>
      <div class="stats">
        <div class="stat"><strong>{len(bookings)}</strong><span>TOTAL</span></div>
        <div class="stat"><strong style="color:#BA7517">{pending}</strong><span>PENDING</span></div>
        <div class="stat"><strong style="color:#22C55E">{confirmed}</strong><span>CONFIRMED</span></div>
      </div>
      <a href="/admin/subscribers" class="btn" style="color:#00f5ff;border-color:rgba(0,245,255,0.3)">Jobs board subscribers</a>
      <a href="/admin/resources" class="btn" style="color:#22C55E;border-color:rgba(34,197,94,0.3)">Send freebies</a>
      <a href="/admin/announce" class="btn" style="color:#FF2CF3;border-color:rgba(255,44,243,0.3)">📢 Send announcement</a>
      <a href="/admin/send-feedback-emails-now" class="btn" style="color:#FF2CF3;border-color:rgba(255,44,243,0.3)">Send due feedback emails now</a>
      <a href="/admin/logout" class="btn" style="color:#9997aa">Logout</a>
    </div>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Name</th><th>Email</th><th>Phone</th><th>Date & Time</th><th>Session</th><th>Goal</th><th>Notes</th><th>Feedback</th><th>Action</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="9" style="padding:2rem;text-align:center;color:#9997aa">No bookings yet</td></tr>'}</tbody>
    </table></div></body></html>"""

@app.route("/admin/send-feedback-emails-now")
@admin_required
def admin_send_feedback_emails_now():
    send_pending_feedback_emails()
    return redirect("/admin")

# ── ANNOUNCEMENT BROADCASTER ─────────────────────────────────────

@app.route("/admin/announce", methods=["GET", "POST"])
@admin_required
def admin_announce():
    if request.method == "POST":
        subject    = request.form.get("subject", "").strip()
        body_text  = request.form.get("body", "").strip()
        cta_text   = request.form.get("cta_text", "").strip()
        cta_url    = request.form.get("cta_url", "").strip()
        audience   = request.form.get("audience", "all")

        if not subject or not body_text:
            return "Subject and body are required.", 400

        conn = get_jobs_db()
        if audience == "all":
            rows = conn.execute("SELECT email, name FROM job_alert_subscribers").fetchall()
        else:
            rows = conn.execute(
                "SELECT email, name FROM job_alert_subscribers WHERE interested_role = ? OR interested_role = 'all'",
                (audience,)
            ).fetchall()
        conn.close()

        # ── confirm step: show preview before sending ──
        confirmed = request.form.get("confirmed") == "yes"
        if not confirmed:
            # Show confirmation page with subscriber count
            preview_name = rows[0]["name"] if rows else None
            preview_greeting = greeting(preview_name)
            return f"""<!DOCTYPE html><html><head><title>Confirm Send</title>
            <style>*{{box-sizing:border-box;margin:0;padding:0;}}
            body{{background:#050508;color:#e8e6f0;font-family:sans-serif;padding:2rem;display:flex;align-items:center;justify-content:center;min-height:100vh;}}
            .box{{background:#0f0f1a;border:1px solid rgba(255,44,243,0.2);border-radius:12px;padding:2rem;max-width:560px;width:100%;}}
            h2{{color:#FF2CF3;margin-bottom:0.75rem;font-size:1.2rem;}}
            .preview{{background:#070710;border:1px solid rgba(255,255,255,0.07);border-radius:8px;padding:1.25rem;margin:1.25rem 0;font-size:0.85rem;color:#c8c6de;line-height:1.8;white-space:pre-wrap;}}
            .meta{{font-size:0.8rem;color:#9997aa;margin-bottom:1rem;}}
            .meta strong{{color:#fff;}}
            .btns{{display:flex;gap:10px;margin-top:1.25rem;}}
            .btn-send{{flex:1;background:#FF2CF3;color:#050508;border:none;border-radius:6px;padding:0.85rem;font-weight:700;font-size:0.85rem;cursor:pointer;}}
            .btn-back{{flex:1;background:transparent;color:#9997aa;border:1px solid rgba(255,255,255,0.1);border-radius:6px;padding:0.85rem;font-size:0.85rem;cursor:pointer;text-decoration:none;text-align:center;display:block;}}
            </style></head><body><div class="box">
            <h2>📋 Review before sending</h2>
            <div class="meta">
              <strong>Subject:</strong> {subject}<br>
              <strong>Audience:</strong> {len(rows)} subscriber{'s' if len(rows) != 1 else ''}<br>
              <strong>Preview greeting:</strong> {preview_greeting}
            </div>
            <div class="preview">{body_text[:400]}{'...' if len(body_text) > 400 else ''}</div>
            <form method="POST">
              <input type="hidden" name="subject" value="{subject}"/>
              <input type="hidden" name="body" value="{body_text}"/>
              <input type="hidden" name="cta_text" value="{cta_text}"/>
              <input type="hidden" name="cta_url" value="{cta_url}"/>
              <input type="hidden" name="audience" value="{audience}"/>
              <input type="hidden" name="confirmed" value="yes"/>
              <div class="btns">
                <a class="btn-back" href="/admin/announce">← Edit</a>
                <button class="btn-send" type="submit">✅ Yes, send to {len(rows)} subscribers</button>
              </div>
            </form>
            </div></body></html>"""

        sent = 0
        for row in rows:
            if send_email(
                row["email"], row["name"] or "",
                subject,
                announcement_email(row["name"], subject, body_text, cta_text, cta_url)
            ):
                sent += 1

        return f"""<!DOCTYPE html><html><head><title>Sent!</title>
        <style>body{{background:#050508;color:#e8e6f0;font-family:sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;text-align:center;}}
        .box{{background:#0f0f1a;border:1px solid rgba(34,197,94,0.3);border-radius:12px;padding:2.5rem;max-width:400px;}}
        h2{{color:#22C55E;margin-bottom:1rem;}} a{{color:#FF2CF3;}}</style></head>
        <body><div class="box">
        <h2>✅ Sent to {sent} subscribers!</h2>
        <p style="color:#9997aa;margin-bottom:1.5rem">Each email was personalized with their name automatically.</p>
        <a href="/admin">← Back to admin</a>
        </div></body></html>"""

    # GET — show the form
    conn       = get_jobs_db()
    sub_count  = conn.execute("SELECT COUNT(*) FROM job_alert_subscribers").fetchone()[0]
    cc_count   = conn.execute("SELECT COUNT(*) FROM job_alert_subscribers WHERE interested_role = 'cabin_crew'").fetchone()[0]
    gs_count   = conn.execute("SELECT COUNT(*) FROM job_alert_subscribers WHERE interested_role = 'ground_staff'").fetchone()[0]
    conn.close()

    return f"""<!DOCTYPE html><html><head><title>Send Announcement</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:sans-serif;padding:2rem;}}
    h1{{color:#FF2CF3;font-size:1.4rem;margin-bottom:0.5rem;}}
    .back{{display:inline-block;color:#9997aa;text-decoration:none;font-size:13px;margin-bottom:1.5rem;border:1px solid rgba(255,255,255,0.1);padding:8px 16px;border-radius:6px;}}
    .box{{background:#0f0f1a;border:1px solid rgba(255,44,243,0.2);border-radius:10px;padding:1.5rem;max-width:600px;}}
    label{{display:block;font-size:12px;color:#9997aa;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;margin-top:16px;}}
    input,select,textarea{{width:100%;background:#070710;border:1px solid rgba(123,92,250,0.2);border-radius:6px;padding:0.7rem 0.9rem;color:#e8e6f0;font-size:0.9rem;outline:none;}}
    textarea{{min-height:180px;resize:vertical;line-height:1.6;}}
    button{{margin-top:20px;width:100%;background:#FF2CF3;color:#1a0518;border:none;border-radius:6px;padding:0.9rem;font-size:0.95rem;font-weight:700;cursor:pointer;}}
    .counts{{display:flex;gap:12px;margin-bottom:1.5rem;flex-wrap:wrap;}}
    .count{{background:#0f0f1a;border:1px solid rgba(255,255,255,0.08);border-radius:8px;padding:10px 16px;font-size:13px;color:#9997aa;}}
    .count strong{{color:#fff;display:block;font-size:18px;}}
    .tip{{font-size:12px;color:#5c5a6b;margin-top:6px;}}
    </style></head><body>
    <a class="back" href="/admin">← Back to bookings</a>
    <h1>📢 Send announcement to subscribers</h1>
    <p style="color:#9997aa;font-size:13px;margin-bottom:1.5rem">Each email is automatically personalized with the subscriber's first name.</p>
    <div class="counts">
      <div class="count"><strong>{sub_count}</strong>Total subscribers</div>
      <div class="count"><strong>{cc_count}</strong>Cabin crew</div>
      <div class="count"><strong>{gs_count}</strong>Ground staff</div>
    </div>
    <div class="box">
      <form method="POST">
        <label>Email subject</label>
        <input type="text" name="subject" placeholder="e.g. I'm doing 1:1 sessions now — and I saved a spot for you ✈️" required/>

        <label>Who to send to</label>
        <select name="audience">
          <option value="all">Everyone ({sub_count} subscribers)</option>
          <option value="cabin_crew">Cabin crew only ({cc_count})</option>
          <option value="ground_staff">Ground staff only ({gs_count})</option>
        </select>

        <label>Email body</label>
        <textarea name="body" placeholder="Write your message here. Each email will start with 'Hi [Name],' automatically. Write naturally — no need to add a greeting." required></textarea>
        <div class="tip">💡 Just write the body. The greeting 'Hi Priya,' is added automatically for each subscriber.</div>

        <label>Call-to-action button text (optional)</label>
        <input type="text" name="cta_text" placeholder="e.g. Book your slot →"/>

        <label>Call-to-action URL (optional)</label>
        <input type="url" name="cta_url" placeholder="e.g. https://consultation.vardhasheelan.com"/>

        <button type="submit">Send to subscribers now →</button>
      </form>
    </div>
    </body></html>"""

# ── SUBSCRIBERS ──────────────────────────────────────────────────

@app.route("/admin/subscribers")
@admin_required
def admin_subscribers():
    conn = get_jobs_db()
    subs = conn.execute("SELECT * FROM job_alert_subscribers ORDER BY created_at DESC").fetchall()
    conn.close()
    rows = ""
    for s in subs:
        rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.06)">
          <td style="padding:12px 8px;color:#fff;font-size:13px">{s['name'] or '—'}</td>
          <td style="padding:12px 8px;color:#00f5ff;font-size:13px">{s['email']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{s['interested_category']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{s['interested_role']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{s['created_at']}</td></tr>"""
    return f"""<!DOCTYPE html><html><head><title>Subscribers</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:sans-serif;padding:2rem;}}
    h1{{color:#FF2CF3;font-size:1.4rem;margin-bottom:1.5rem;}}
    table{{width:100%;border-collapse:collapse;background:#0f0f1a;border:1px solid rgba(255,44,243,0.15);border-radius:8px;overflow:hidden;}}
    th{{padding:12px 8px;text-align:left;font-size:11px;color:#9997aa;letter-spacing:0.08em;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.08);}}
    .btn{{display:inline-block;background:#FF2CF3;color:#1a0518;padding:10px 20px;border-radius:6px;text-decoration:none;font-weight:700;font-size:13px;margin-bottom:1.5rem;margin-right:10px;}}
    .back{{display:inline-block;color:#9997aa;text-decoration:none;font-size:13px;margin-bottom:1.5rem;border:1px solid rgba(255,255,255,0.1);padding:10px 20px;border-radius:6px;}}
    </style></head><body>
    <h1>Jobs board subscribers ({len(subs)})</h1>
    <a class="btn" href="/admin/subscribers/export">Download as Excel</a>
    <a class="back" href="/admin">← Back to bookings</a>
    <table>
      <thead><tr><th>Name</th><th>Email</th><th>Category</th><th>Role</th><th>Subscribed</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="5" style="padding:2rem;text-align:center;color:#9997aa">No subscribers yet</td></tr>'}</tbody>
    </table></body></html>"""

@app.route("/admin/subscribers/export")
@admin_required
def admin_subscribers_export():
    from openpyxl import Workbook
    from io import BytesIO
    conn = get_jobs_db()
    subs = conn.execute("SELECT * FROM job_alert_subscribers ORDER BY created_at DESC").fetchall()
    conn.close()
    wb = Workbook()
    ws = wb.active
    ws.title = "Subscribers"
    ws.append(["Name", "Email", "Interested Category", "Interested Role", "Subscribed At"])
    for s in subs:
        ws.append([s["name"] or "", s["email"], s["interested_category"], s["interested_role"], s["created_at"]])
    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(buffer, as_attachment=True,
                     download_name="jobs_board_subscribers.xlsx",
                     mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# ── RESOURCES / FREEBIES ─────────────────────────────────────────

@app.route("/admin/resources")
@admin_required
def admin_resources():
    conn      = get_jobs_db()
    resources = conn.execute("SELECT * FROM resources ORDER BY uploaded_at DESC").fetchall()
    conn.close()
    rows = ""
    for r in resources:
        already   = get_already_sent_emails(r["id"])
        all_subs  = get_matching_subscribers(r["category"])
        new_count = len([e for e, n in all_subs if e not in already])
        new_badge = f'<span style="color:#22C55E;font-size:11px">({new_count} new)</span>' if new_count > 0 else '<span style="color:#5c5a6b;font-size:11px">(all sent)</span>'
        rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.06)">
          <td style="padding:12px 8px;color:#fff;font-size:13px">{r['title']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{r['category']}</td>
          <td style="padding:12px 8px;color:#00f5ff;font-size:12px">{r['sent_count']} sent</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{r['uploaded_at']}</td>
          <td style="padding:12px 8px">
            <a href="/resources/{r['filename']}" target="_blank" style="color:#7b5cfa;font-size:12px;margin-right:10px">View PDF</a>
            <a href="/admin/resources/{r['id']}/resend" style="color:#FF2CF3;font-size:12px">Resend to new</a>
            {new_badge}
          </td></tr>"""
    return f"""<!DOCTYPE html><html><head><title>Resources & Freebies</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:sans-serif;padding:2rem;}}
    h1{{color:#FF2CF3;font-size:1.4rem;margin-bottom:0.5rem;}}
    .back{{display:inline-block;color:#9997aa;text-decoration:none;font-size:13px;margin-bottom:1.5rem;border:1px solid rgba(255,255,255,0.1);padding:8px 16px;border-radius:6px;}}
    .upload-box{{background:#0f0f1a;border:1px solid rgba(255,44,243,0.2);border-radius:10px;padding:1.5rem;margin-bottom:2rem;max-width:500px;}}
    label{{display:block;font-size:12px;color:#9997aa;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:6px;margin-top:14px;}}
    input,select,textarea{{width:100%;background:#070710;border:1px solid rgba(123,92,250,0.2);border-radius:6px;padding:0.7rem 0.9rem;color:#e8e6f0;font-size:0.9rem;outline:none;}}
    textarea{{min-height:80px;resize:vertical;}}
    button{{margin-top:18px;width:100%;background:#FF2CF3;color:#1a0518;border:none;border-radius:6px;padding:0.85rem;font-size:0.9rem;font-weight:700;cursor:pointer;}}
    table{{width:100%;border-collapse:collapse;background:#0f0f1a;border:1px solid rgba(255,44,243,0.15);border-radius:8px;overflow:hidden;}}
    th{{padding:12px 8px;text-align:left;font-size:11px;color:#9997aa;letter-spacing:0.08em;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.08);}}
    .note{{background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.2);border-radius:8px;padding:12px 16px;margin-bottom:1.5rem;font-size:13px;color:#9997aa;}}
    .note strong{{color:#22C55E;}}
    </style></head><body>
    <a class="back" href="/admin">← Back to bookings</a>
    <h1>Send a freebie / resource</h1>
    <div class="note"><strong>Personalized:</strong> Each email greets the subscriber by their first name. Resend only goes to new subscribers who haven't received it yet.</div>
    <div class="upload-box">
      <form action="/admin/resources/upload" method="POST" enctype="multipart/form-data">
        <label>Title (used as email subject)</label>
        <input type="text" name="title" placeholder="e.g. 30-Day Cabin Crew Prep Plan" required/>
        <label>Short description (goes in the email body)</label>
        <textarea name="description" placeholder="A quick note about what's inside and why it's useful..." required></textarea>
        <label>Who is this for?</label>
        <select name="category" required>
          <option value="cabin_crew">Cabin crew subscribers</option>
          <option value="ground_staff">Ground staff subscribers</option>
          <option value="all">Everyone (all subscribers)</option>
        </select>
        <label>PDF file</label>
        <input type="file" name="file" accept="application/pdf" required/>
        <button type="submit">Upload and send now</button>
      </form>
    </div>
    <table>
      <thead><tr><th>Title</th><th>Category</th><th>Sent</th><th>Uploaded</th><th>Actions</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="5" style="padding:2rem;text-align:center;color:#9997aa">No resources uploaded yet</td></tr>'}</tbody>
    </table></body></html>"""

@app.route("/admin/resources/upload", methods=["POST"])
@admin_required
def admin_resources_upload():
    title       = request.form.get("title", "").strip()
    description = request.form.get("description", "").strip()
    category    = request.form.get("category", "all")
    file        = request.files.get("file")
    if not title or not file or file.filename == "":
        return "Title and PDF file are required.", 400
    filename = secure_filename(f"{int(datetime.now().timestamp())}_{file.filename}")
    file.save(os.path.join(RESOURCES_DIR, filename))
    conn = get_jobs_db()
    cur  = conn.execute(
        "INSERT INTO resources (title, description, category, filename) VALUES (?, ?, ?, ?)",
        (title, description, category, filename)
    )
    resource_id = cur.lastrowid
    conn.commit()
    conn.close()
    base_url     = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    download_url = f"{base_url}/resources/{filename}"
    recipients   = get_matching_subscribers(category)
    sent = 0
    for email, name in recipients:
        if send_email(email, name or "", title, resource_email(title, description, download_url, name)):
            sent += 1
            mark_resource_sent(resource_id, email)
    conn = get_jobs_db()
    conn.execute("UPDATE resources SET sent_count = ? WHERE id = ?", (sent, resource_id))
    conn.commit()
    conn.close()
    return redirect("/admin/resources")

@app.route("/admin/resources/<int:resource_id>/resend")
@admin_required
def admin_resources_resend(resource_id):
    conn = get_jobs_db()
    r    = conn.execute("SELECT * FROM resources WHERE id = ?", (resource_id,)).fetchone()
    conn.close()
    if not r:
        return "Resource not found", 404
    base_url       = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    download_url   = f"{base_url}/resources/{r['filename']}"
    all_recipients = get_matching_subscribers(r["category"])
    already_sent   = get_already_sent_emails(resource_id)
    new_recipients = [(e, n) for e, n in all_recipients if e not in already_sent]
    sent = 0
    for email, name in new_recipients:
        if send_email(email, name or "", r["title"], resource_email(r["title"], r["description"], download_url, name)):
            sent += 1
            mark_resource_sent(resource_id, email)
    if sent > 0:
        conn = get_jobs_db()
        conn.execute("UPDATE resources SET sent_count = sent_count + ? WHERE id = ?", (sent, resource_id))
        conn.commit()
        conn.close()
    return redirect("/admin/resources")

@app.route("/resources/<path:filename>")
def serve_resource(filename):
    return send_file(os.path.join(RESOURCES_DIR, filename))

# ── MAIN ROUTES ──────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("consult.html")

@app.route('/assets/<path:filename>')
def assets(filename):
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public', 'assets')
    from flask import send_from_directory
    return send_from_directory(assets_dir, filename)

@app.route("/authorize")
def authorize():
    if not os.path.exists("credentials.json"):
        return jsonify({"error":"credentials.json not found"}), 500
    flow = Flow.from_client_secrets_file("credentials.json", scopes=SCOPES,
        redirect_uri=request.url_root+"oauth2callback")
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true")
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    if not os.path.exists("credentials.json"):
        return jsonify({"error":"credentials.json not found"}), 500
    flow = Flow.from_client_secrets_file("credentials.json", scopes=SCOPES,
        state=session.get("state"), redirect_uri=request.url_root+"oauth2callback")
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["credentials"] = {
        "token": creds.token, "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri, "client_id": creds.client_id,
        "client_secret": creds.client_secret, "scopes": list(creds.scopes),
    }
    return redirect("/")

@app.route("/api/slots")
def get_slots():
    date_str     = request.args.get("date")
    session_type = request.args.get("session_type","1hr")
    if not date_str:
        return jsonify({"error":"date required"}), 400
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error":"invalid date"}), 400
    if date.weekday() not in AVAILABILITY["days"]:
        return jsonify({"slots": [], "reason": "unavailable_day"})
    duration   = SESSION_DURATIONS.get(session_type, SESSION_DURATIONS["1hr"])["duration"]
    start_hour = AVAILABILITY["start_hour"]
    end_hour   = AVAILABILITY["end_hour"]
    booked_slots = set()
    for b in load_bookings():
        if b.get("date") == date_str and b.get("status") != "declined":
            booked_slots.add(b.get("time"))
    service       = get_calendar_service()
    calendar_busy = set()
    if service:
        try:
            day_start = IST.localize(datetime(date.year,date.month,date.day,start_hour,0))
            day_end   = IST.localize(datetime(date.year,date.month,date.day,end_hour,0))
            events    = service.events().list(calendarId=CALENDAR_ID,
                timeMin=day_start.isoformat(), timeMax=day_end.isoformat(),
                singleEvents=True).execute()
            for event in events.get("items",[]):
                s = event.get("start",{}).get("dateTime")
                e = event.get("end",{}).get("dateTime")
                if s and e:
                    st = datetime.fromisoformat(s).astimezone(IST)
                    et = datetime.fromisoformat(e).astimezone(IST)
                    t  = st
                    while t < et:
                        calendar_busy.add(t.strftime("%H:%M"))
                        t += timedelta(minutes=30)
        except Exception as ex:
            print(f"Calendar error: {ex}")
    slots   = []
    current = datetime(date.year,date.month,date.day,start_hour,0)
    end_dt  = datetime(date.year,date.month,date.day,end_hour,0)
    while current + timedelta(minutes=duration) <= end_dt:
        time_str = current.strftime("%H:%M")
        booked   = time_str in booked_slots or time_str in calendar_busy
        slots.append({"time":time_str,"booked":booked,"display":current.strftime("%I:%M %p")})
        current += timedelta(minutes=30)
    return jsonify({"slots":slots,"date":date_str})

@app.route("/api/book", methods=["POST"])
def book():
    data = request.json
    for field in ["name","email","date","time","session_type"]:
        if not data.get(field):
            return jsonify({"error":f"{field} is required"}), 400
    try:
        d = datetime.strptime(data["date"],"%Y-%m-%d")
        if d.weekday() not in AVAILABILITY["days"]:
            return jsonify({"error":"Bookings are only available Mon–Fri."}), 400
    except ValueError:
        return jsonify({"error":"Invalid date"}), 400
    for b in load_bookings():
        if b.get("date")==data["date"] and b.get("time")==data["time"] and b.get("status")!="declined":
            return jsonify({"error":"This slot was just booked. Please choose another."}), 409
    stype = SESSION_DURATIONS.get(data["session_type"])
    if not stype:
        return jsonify({"error":"Invalid session type"}), 400
    import uuid
    booking_id = str(uuid.uuid4())[:8]
    meet_link  = ""
    service    = get_calendar_service()
    if service:
        try:
            h, m     = map(int, data["time"].split(":"))
            start_dt = IST.localize(datetime(d.year,d.month,d.day,h,m))
            end_dt   = start_dt + timedelta(minutes=stype["duration"])
            event    = {
                "summary": f"Consultation: {data['name']} — {stype['label']}",
                "description": f"Client: {data['name']}\nEmail: {data['email']}\nPhone: {data.get('phone','Not provided')}\nGoal: {data.get('goal','N/A')}\nNotes: {data.get('topic','N/A')}",
                "start": {"dateTime":start_dt.isoformat(),"timeZone":"Asia/Kolkata"},
                "end":   {"dateTime":end_dt.isoformat(),  "timeZone":"Asia/Kolkata"},
                "conferenceData": {"createRequest":{"requestId":booking_id}},
                "attendees": [{"email":data["email"]}],
            }
            created   = service.events().insert(calendarId=CALENDAR_ID, body=event,
                conferenceDataVersion=1, sendUpdates="all").execute()
            meet_link = created.get("hangoutLink","")
        except Exception as ex:
            print(f"Calendar event error: {ex}")
    date_display = d.strftime("%A, %d %B %Y")
    h, m         = map(int, data["time"].split(":"))
    time_display = datetime(2000,1,1,h,m).strftime("%I:%M %p")
    booking = {
        "id": booking_id,
        "name": data["name"], "email": data["email"], "phone": data.get("phone",""),
        "date": data["date"], "time": data["time"], "session_type": data["session_type"],
        "goal": data.get("goal",""), "followup": data.get("followup",""),
        "topic": data.get("topic",""), "txn_id": data.get("txn_id",""),
        "meet_link": meet_link, "status": "pending",
        "booked_at": datetime.now().isoformat(),
    }
    save_booking(booking)
    send_email(data["email"], data["name"],
               "Booking received — Vardhasheela N",
               client_confirmation_email(data["name"], data["session_type"], date_display, time_display))
    send_email(GMAIL_USER, "Vardhasheela",
               f"New booking: {data['name']} — {date_display} {time_display}",
               owner_notification_email(
                   data["name"], data["email"], data.get("phone",""),
                   data["session_type"], date_display, time_display,
                   data.get("goal",""), data.get("followup",""), data.get("topic",""), booking_id))
    return jsonify({
        "success": True,
        "message": "Booking received! Check your email for payment details. You'll get a confirmation once Vardhasheela accepts.",
        "upi_id":   UPI_ID,
        "upi_name": UPI_NAME,
        "amount":   stype["price"],
    })

@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.json
    if not data.get("email") or not data.get("message"):
        return jsonify({"error":"Email and message required"}), 400
    body = f"""<div style="font-family:sans-serif;background:#0a0a0b;color:#e8e6f0;padding:32px;border-radius:12px">
      <h3 style="color:#7b5cfa">New contact message</h3>
      <p><strong>From:</strong> {data.get('name','Anonymous')}</p>
      <p><strong>Email:</strong> {data['email']}</p>
      <p><strong>Message:</strong><br>{data['message']}</p></div>"""
    send_email(GMAIL_USER,"Vardhasheela",f"New message from {data.get('name',data['email'])}",body)
    return jsonify({"success":True})

@app.route("/admin/action/<booking_id>/<action>")
@admin_required
def admin_action(booking_id, action):
    bookings = load_bookings()
    booking  = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return "Booking not found", 404
    date_obj     = datetime.strptime(booking["date"], "%Y-%m-%d")
    date_display = date_obj.strftime("%A, %d %B %Y")
    h, m         = map(int, booking["time"].split(":"))
    time_display = datetime(2000,1,1,h,m).strftime("%I:%M %p")
    if action == "confirm":
        booking["status"] = "confirmed"
        send_email(booking["email"], booking["name"],
                   "Your session is confirmed — Vardhasheela N",
                   client_confirmed_email(booking["name"], booking["session_type"],
                                          date_display, time_display, booking.get("meet_link","")))
    elif action == "decline":
        booking["status"] = "declined"
        send_email(booking["email"], booking["name"],
                   "Session request update — Vardhasheela N",
                   client_declined_email(booking["name"], booking["session_type"], date_display, time_display))
    save_bookings(bookings)
    return redirect("/admin")

@app.route("/feedback/<booking_id>")
def feedback_form(booking_id):
    bookings = load_bookings()
    booking  = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return "This feedback link isn't valid.", 404
    stype        = SESSION_DURATIONS.get(booking.get("session_type", "1hr"), {})
    date_obj     = datetime.strptime(booking["date"], "%Y-%m-%d")
    date_display = date_obj.strftime("%d %B %Y")
    return render_template("feedback.html",
        booking_id=booking_id, name=booking.get("name",""),
        session_label=stype.get("label",""), date_display=date_display,
        already_submitted=bool(booking.get("feedback")), existing=booking.get("feedback"))

@app.route("/api/feedback/<booking_id>", methods=["POST"])
def submit_feedback(booking_id):
    data = request.json or {}
    try:
        rating = int(data.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        return jsonify({"error": "Please select a star rating."}), 400
    comment  = (data.get("comment") or "").strip()
    bookings = load_bookings()
    booking  = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return jsonify({"error": "Booking not found."}), 404
    booking["feedback"] = {"rating": rating, "comment": comment, "submitted_at": datetime.now().isoformat()}
    save_bookings(bookings)
    send_email(GMAIL_USER, "Vardhasheela",
               f"New feedback from {booking.get('name','')} — {rating}★",
               feedback_notification_email(booking, rating, comment))
    return jsonify({"success": True})

@app.route("/jobs")
def jobs_board():
    category  = request.args.get("category", "all")
    role_type = request.args.get("role", "all")
    query     = "SELECT * FROM jobs WHERE status != 'closed'"
    params    = []
    if category in ("domestic", "international"):
        query += " AND category = ?"
        params.append(category)
    if role_type in ("cabin_crew", "ground_staff", "other"):
        query += " AND role_type = ?"
        params.append(role_type)
    query += " ORDER BY status = 'closing_soon' DESC, airline_name ASC"
    conn = get_jobs_db()
    jobs = conn.execute(query, params).fetchall()
    conn.close()
    return render_template("jobs.html", jobs=jobs,
                           active_category=category, active_role=role_type,
                           today=date.today().isoformat())

@app.route("/jobs/alert-me", methods=["POST"])
def jobs_alert_me():
    email    = (request.form.get("email") or "").strip().lower()
    name     = (request.form.get("name") or "").strip()
    category = request.form.get("interested_category", "both")
    role     = request.form.get("interested_role", "all")

    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Enter a valid email."}), 400

    conn = get_jobs_db()
    try:
        conn.execute(
            """INSERT INTO job_alert_subscribers (name, email, interested_category, interested_role)
               VALUES (?, ?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                 name = excluded.name,
                 interested_category = excluded.interested_category,
                 interested_role = excluded.interested_role""",
            (name or None, email, category, role),
        )
        conn.commit()
    finally:
        conn.close()

    # Notify owner
    send_email(GMAIL_USER, "Vardhasheela",
               f"New jobs board subscriber: {name or email}",
               f"""<div style="font-family:sans-serif;background:#0a0a0b;color:#e8e6f0;padding:32px;border-radius:12px">
                 <h3 style="color:#7b5cfa">✈️ New jobs board alert subscriber</h3>
                 <p><strong>Name:</strong> {name or 'Not provided'}</p>
                 <p><strong>Email:</strong> {email}</p>
                 <p><strong>Interested in:</strong> {category} / {role}</p>
               </div>""")

    # Welcome email — personalized
    send_email(email, name, "You're on the list! — Aviation Jobs Board",
               subscriber_welcome_email(name))

    # Send existing matching resources — only ones not yet received
    base_url = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    conn     = get_jobs_db()
    existing_resources = conn.execute(
        "SELECT * FROM resources WHERE category = ? OR category = 'all'", (role,)
    ).fetchall()
    conn.close()

    for res in existing_resources:
        already_sent = get_already_sent_emails(res["id"])
        if email not in already_sent:
            download_url = f"{base_url}/resources/{res['filename']}"
            if send_email(email, name, res["title"],
                          resource_email(res["title"], res["description"], download_url, name)):
                mark_resource_sent(res["id"], email)

    return jsonify({"ok": True})

# ── PUBLIC FEEDBACK & TESTIMONIALS ───────────────────────────────
# Stored separately from booking-linked feedback so offline sessions
# (like Sumithra's) can also leave reviews that show on the site.



def load_testimonials():
    if not os.path.exists(TESTIMONIALS_FILE):
        return []
    with open(TESTIMONIALS_FILE) as f:
        return json.load(f)

def save_testimonials(t):
    with open(TESTIMONIALS_FILE, "w") as f:
        json.dump(t, f, indent=2)

def display_name(name, consent):
    """Return the name to show publicly based on consent choice."""
    name = (name or "").strip()
    if consent == "no":
        return None
    if consent == "anonymous":
        return "Anonymous"
    if consent == "initials":
        parts = name.split()
        return ".".join(p[0].upper() for p in parts if p) + "."
    return name.split()[0] if name else "Anonymous"  # first name only for 'yes'

@app.route("/feedback/public")
def public_feedback_form():
    return render_template("public_feedback.html")

@app.route("/api/feedback/public", methods=["POST"])
def submit_public_feedback():
    data    = request.json or {}
    name    = (data.get("name") or "").strip()
    comment = (data.get("comment") or "").strip()
    liked   = (data.get("liked") or "").strip()
    consent = data.get("consent", "yes")
    try:
        rating = int(data.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0

    if not name or rating < 1 or rating > 5:
        return jsonify({"error": "Please enter your name and select a rating."}), 400

    import uuid
    t_id = str(uuid.uuid4())[:8]
    testimonial = {
        "id":         t_id,
        "name":       name,
        "rating":     rating,
        "liked":      liked,
        "comment":    comment,
        "consent":    consent,
        "show_name":  display_name(name, consent),
        "visible":    consent != "no",   # private ones stored but not shown
        "submitted_at": datetime.now().isoformat(),
        "source":     "public_form",
    }
    testimonials = load_testimonials()
    testimonials.append(testimonial)
    save_testimonials(testimonials)

    # Notify Vardhasheela
    stars = "⭐" * rating + "☆" * (5 - rating)
    liked_display = liked.replace(",", " · ") if liked else "—"
    send_email(
        GMAIL_USER, "Vardhasheela",
        f"New testimonial from {name} — {rating}★",
        f"""<div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
          <h2 style="color:#FF2CF3;margin:0 0 20px">🌟 New public feedback</h2>
          <div style="background:rgba(255,44,243,0.08);border:1px solid rgba(255,44,243,0.2);border-radius:8px;padding:20px">
            <table style="width:100%;font-size:14px">
              <tr><td style="color:#9997aa;padding:5px 0;width:110px">From</td><td style="color:#fff;font-weight:600">{name}</td></tr>
              <tr><td style="color:#9997aa;padding:5px 0">Rating</td><td style="color:#FFD700;font-size:18px">{stars}</td></tr>
              <tr><td style="color:#9997aa;padding:5px 0">Liked most</td><td style="color:#fff">{liked_display}</td></tr>
              <tr><td style="color:#9997aa;padding:5px 0">Consent</td><td style="color:#fff">{consent}</td></tr>
            </table>
            <p style="color:#9997aa;font-size:12px;margin:14px 0 4px">Comment:</p>
            <p style="color:#fff;font-size:14px;white-space:pre-wrap">{comment or '(no comment)'}</p>
          </div>
          <p style="color:#5c5a6b;font-size:12px;margin-top:20px">
            {'✅ Will show on site as: ' + display_name(name, consent) if consent != 'no' else '🔒 Marked private — will not show on site'}
          </p>
        </div>"""
    )

    return jsonify({"success": True})

@app.route("/api/testimonials")
def get_testimonials():
    """Public API — returns only visible testimonials for the website."""
    testimonials = load_testimonials()
    # Also pull 5-star feedback from booking-linked reviews
    bookings = load_bookings()
    for b in bookings:
        fb = b.get("feedback")
        if fb and fb.get("rating", 0) >= 4:
            testimonials.append({
                "id":        b.get("id",""),
                "name":      b.get("name","").split()[0],  # first name only
                "rating":    fb["rating"],
                "liked":     "",
                "comment":   fb.get("comment",""),
                "visible":   True,
                "show_name": b.get("name","").split()[0],
                "submitted_at": fb.get("submitted_at",""),
                "source":    "booking",
            })
    visible = [t for t in testimonials if t.get("visible") and t.get("comment")]
    visible.sort(key=lambda x: x.get("submitted_at",""), reverse=True)
    return jsonify(visible[:10])  # return latest 10

@app.route("/admin/testimonials")
@admin_required
def admin_testimonials():
    testimonials = load_testimonials()
    testimonials.sort(key=lambda x: x.get("submitted_at",""), reverse=True)
    rows = ""
    for t in testimonials:
        stars_html = "★" * t.get("rating",0) + "☆" * (5 - t.get("rating",0))
        visibility = "✅ Visible" if t.get("visible") else "🔒 Private"
        toggle_action = "hide" if t.get("visible") else "show"
        toggle_label  = "Hide" if t.get("visible") else "Show"
        rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.06)">
          <td style="padding:12px 8px;color:#fff;font-size:13px">{t.get('name','')}</td>
          <td style="padding:12px 8px;color:#FFD700">{stars_html}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px;max-width:200px">{(t.get('comment','') or '—')[:80]}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{(t.get('liked','') or '—')[:60]}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{t.get('show_name','')}</td>
          <td style="padding:12px 8px;font-size:12px">{visibility}</td>
          <td style="padding:12px 8px">
            <a href="/admin/testimonials/{t['id']}/{toggle_action}"
               style="color:{'#EF4444' if t.get('visible') else '#22C55E'};font-size:12px;text-decoration:none;border:1px solid {'rgba(239,68,68,0.3)' if t.get('visible') else 'rgba(34,197,94,0.3)'};padding:4px 10px;border-radius:4px">
              {toggle_label}
            </a>
          </td>
        </tr>"""
    return f"""<!DOCTYPE html><html><head><title>Testimonials</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:sans-serif;padding:2rem;}}
    h1{{color:#FF2CF3;font-size:1.4rem;margin-bottom:1.5rem;}}
    table{{width:100%;border-collapse:collapse;background:#0f0f1a;border:1px solid rgba(255,44,243,0.15);border-radius:8px;overflow:hidden;}}
    th{{padding:12px 8px;text-align:left;font-size:11px;color:#9997aa;letter-spacing:0.08em;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.08);}}
    tr:hover{{background:rgba(123,92,250,0.04);}}
    .back{{display:inline-block;color:#9997aa;text-decoration:none;font-size:13px;margin-bottom:1.5rem;border:1px solid rgba(255,255,255,0.1);padding:8px 16px;border-radius:6px;}}
    .link-box{{background:rgba(255,44,243,0.08);border:1px solid rgba(255,44,243,0.2);border-radius:8px;padding:1rem 1.25rem;margin-bottom:1.5rem;font-size:13px;}}
    .link-box strong{{color:#FF2CF3;}}
    .link-box code{{color:#00F5FF;font-family:monospace;word-break:break-all;}}
    </style></head><body>
    <a class="back" href="/admin">← Back to bookings</a>
    <h1>Testimonials ({len(testimonials)})</h1>
    <div class="link-box">
      <strong>📋 Share this link with students for feedback:</strong><br>
      <code>https://consultation.vardhasheelan.com/feedback/public</code><br><br>
      <strong>📡 Testimonials API (used by your website):</strong><br>
      <code>https://consultation.vardhasheelan.com/api/testimonials</code>
    </div>
    <div style="overflow-x:auto"><table>
      <thead><tr><th>Name</th><th>Rating</th><th>Comment</th><th>Liked most</th><th>Shows as</th><th>Status</th><th>Action</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="7" style="padding:2rem;text-align:center;color:#9997aa">No testimonials yet</td></tr>'}</tbody>
    </table></div></body></html>"""

@app.route("/admin/testimonials/<t_id>/<action>")
@admin_required
def admin_testimonial_toggle(t_id, action):
    testimonials = load_testimonials()
    for t in testimonials:
        if t.get("id") == t_id:
            t["visible"] = (action == "show")
            break
    save_testimonials(testimonials)
    return redirect("/admin/testimonials")

if __name__ == "__main__":
    app.run(debug=True, port=5000)
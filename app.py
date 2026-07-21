from flask import Flask, request, jsonify, render_template, redirect, session, send_file
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

GMAIL_USER      = os.environ.get("GMAIL_USER", "vardhasheelan@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
CALENDAR_ID     = os.environ.get("CALENDAR_ID", "vardhasheelan@gmail.com")
ADMIN_PASSWORD  = os.environ.get("ADMIN_PASSWORD", "wenixai2026")
UPI_ID          = "9113259228@kotakbank"
UPI_NAME        = "Vardhasheela N"
IST             = pytz.timezone("Asia/Kolkata")
BOOKINGS_FILE   = "/data/bookings.json"
JOBS_DB_PATH    = "/data/jobs.db"
SCOPES          = ["https://www.googleapis.com/auth/calendar"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

# ── UPDATED: correct prices, Mon–Fri 4 PM–9 PM ──────────────────
SESSION_DURATIONS = {
    "30min": {"label": "30-min Clarity Call",  "duration": 30, "price": 2500},
    "1hr":   {"label": "1-hr Deep Dive",       "duration": 60, "price": 3000},
}

AVAILABILITY = {
    "days":       [0, 1, 2, 3, 4],   # Monday=0 … Friday=4
    "start_hour": 16,                 # 4 PM IST
    "end_hour":   21,                 # 9 PM IST  (last slot starts 8:30 PM for 30 min)
}
# ────────────────────────────────────────────────────────────────

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

# ── JOBS BOARD (aviation careers aggregator) ─────────────────────

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
    email TEXT NOT NULL UNIQUE,
    interested_category TEXT,
    interested_role TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_jobs_role_type ON jobs(role_type);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
"""

def get_jobs_db():
    conn = sqlite3.connect(JOBS_DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_jobs_db():
    conn = sqlite3.connect(JOBS_DB_PATH)
    conn.executescript(JOBS_SCHEMA)
    conn.commit()
    conn.close()

init_jobs_db()  # safe to call on every boot — CREATE TABLE IF NOT EXISTS

# ── AUTOMATIC POST-SESSION FEEDBACK EMAILS ───────────────────────
# Runs periodically in the background. For each confirmed booking whose
# session has finished (plus a small buffer), sends the feedback-request
# email once, then marks it so it's never sent twice.

FEEDBACK_SEND_BUFFER_MINUTES = 30  # wait this long after the session ends

def send_pending_feedback_emails():
    bookings = load_bookings()
    changed = False
    now = datetime.now(IST)

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
            session_end = session_start + timedelta(minutes=stype["duration"])
        except Exception as ex:
            print(f"Feedback scheduler — skipping booking {b.get('id')}: {ex}")
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

# Avoid double-starting the scheduler under Flask's debug auto-reloader,
# which spawns a second process — WERKZEUG_RUN_MAIN is only set in the
# real worker process, not the reloader's watcher process.
if not app.debug or os.environ.get("WERKZEUG_RUN_MAIN") == "true":
    start_feedback_scheduler()

def get_calendar_service():
    if "credentials" not in session:
        return None
    creds = Credentials(**session["credentials"])
    service = build("calendar", "v3", credentials=creds)
    session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": creds.scopes,
    }
    return service

def send_email(to_email, to_name, subject, body_html):
    try:
        msg = MIMEMultipart("alternative")
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

# ── EMAIL TEMPLATES ─────────────────────────────────────────────

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
    stype = SESSION_DURATIONS[session_type]
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
    stype = SESSION_DURATIONS[session_type]
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

def client_declined_email(name, session_type, date_str, time_str):
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#EF4444;margin:0 0 20px">Session request update</h1>
      <p>Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Unfortunately the slot on <strong style="color:#fff">{date_str} at {time_str} IST</strong> is no longer available. Please visit <a href="https://consultation.vardhasheelan.com" style="color:#00f5ff">consultation.vardhasheelan.com</a> to book another slot.</p>
      <p style="color:#9997aa;font-size:13px">Sorry for the inconvenience! — Vardhasheela</p>
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

def subscriber_welcome_email(email):
    base_url = os.environ.get("BASE_URL", "https://consultation.vardhasheelan.com")
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#FF2CF3;margin:0 0 16px">You're on the list!</h1>
      <p style="color:#e8e6f0">Thanks for subscribing to the aviation jobs board alert.</p>
      <p style="color:#9997aa">I'll email you the moment a new cabin crew or ground staff role opens up matching your interest. No spam — just real openings, manually verified.</p>
      <div style="text-align:center;margin:28px 0">
        <a href="{base_url}/jobs" style="background:#FF2CF3;color:#1a0518;padding:14px 28px;border-radius:6px;text-decoration:none;font-weight:700;font-size:14px;display:inline-block">Browse current openings →</a>
      </div>
      <p style="color:#5c5a6b;font-size:12px;margin-top:20px">Vardhasheela N — @vardhasheela.n</p>
    </div>
    """

# ── ADMIN ───────────────────────────────────────────────────────

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
    rows = ""
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
    .logout{{font-size:12px;color:#9997aa;text-decoration:none;border:1px solid rgba(255,255,255,0.1);padding:6px 14px;border-radius:4px;}}
    </style></head><body>
    <div class="header">
      <div><h1>Consultation bookings</h1><p style="color:#9997aa;font-size:13px;margin-top:4px">consultation.vardhasheelan.com</p></div>
      <div class="stats">
        <div class="stat"><strong>{len(bookings)}</strong><span>TOTAL</span></div>
        <div class="stat"><strong style="color:#BA7517">{pending}</strong><span>PENDING</span></div>
        <div class="stat"><strong style="color:#22C55E">{confirmed}</strong><span>CONFIRMED</span></div>
      </div>
      <a href="/admin/subscribers" class="logout" style="color:#00f5ff;border-color:rgba(0,245,255,0.3)">Jobs board subscribers</a>
      <a href="/admin/send-feedback-emails-now" class="logout" style="color:#FF2CF3;border-color:rgba(255,44,243,0.3)">Send due feedback emails now</a>
      <a href="/admin/logout" class="logout">Logout</a>
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

@app.route("/admin/subscribers")
@admin_required
def admin_subscribers():
    conn = get_jobs_db()
    subs = conn.execute("SELECT * FROM job_alert_subscribers ORDER BY created_at DESC").fetchall()
    conn.close()
    rows = ""
    for s in subs:
        rows += f"""<tr style="border-bottom:1px solid rgba(255,255,255,0.06)">
          <td style="padding:12px 8px;color:#00f5ff;font-size:13px">{s['email']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{s['interested_category']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{s['interested_role']}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{s['created_at']}</td></tr>"""
    return f"""<!DOCTYPE html><html><head><title>Jobs Board Subscribers</title>
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
      <thead><tr><th>Email</th><th>Category</th><th>Role</th><th>Subscribed</th></tr></thead>
      <tbody>{rows or '<tr><td colspan="4" style="padding:2rem;text-align:center;color:#9997aa">No subscribers yet</td></tr>'}</tbody>
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
    ws.append(["Email", "Interested Category", "Interested Role", "Subscribed At"])
    for s in subs:
        ws.append([s["email"], s["interested_category"], s["interested_role"], s["created_at"]])

    buffer = BytesIO()
    wb.save(buffer)
    buffer.seek(0)
    return send_file(
        buffer,
        as_attachment=True,
        download_name="jobs_board_subscribers.xlsx",
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

@app.route("/admin/action/<booking_id>/<action>")
@admin_required
def admin_action(booking_id, action):
    bookings = load_bookings()
    booking  = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return "Booking not found", 404
    stype       = SESSION_DURATIONS.get(booking.get("session_type","1hr"), {})
    date_obj    = datetime.strptime(booking["date"], "%Y-%m-%d")
    date_display = date_obj.strftime("%A, %d %B %Y")
    h, m        = map(int, booking["time"].split(":"))
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

# ── MAIN ROUTES ─────────────────────────────────────────────────

@app.route("/")
def index():
    return render_template("consult.html")

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

    # ── Mon–Fri only ──
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

    # ── weekday check ──
    try:
        d = datetime.strptime(data["date"],"%Y-%m-%d")
        if d.weekday() not in AVAILABILITY["days"]:
            return jsonify({"error":"Bookings are only available Mon–Fri."}), 400
    except ValueError:
        return jsonify({"error":"Invalid date"}), 400

    # ── double-booking check ──
    for b in load_bookings():
        if b.get("date")==data["date"] and b.get("time")==data["time"] and b.get("status")!="declined":
            return jsonify({"error":"This slot was just booked. Please choose another."}), 409

    stype = SESSION_DURATIONS.get(data["session_type"])
    if not stype:
        return jsonify({"error":"Invalid session type"}), 400

    import uuid
    booking_id = str(uuid.uuid4())[:8]

    meet_link = ""
    service   = get_calendar_service()
    if service:
        try:
            h, m       = map(int, data["time"].split(":"))
            start_dt   = IST.localize(datetime(d.year,d.month,d.day,h,m))
            end_dt     = start_dt + timedelta(minutes=stype["duration"])
            event      = {
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

@app.route('/assets/<path:filename>')
def assets(filename):
    import os
    from flask import send_from_directory
    assets_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'public', 'assets')
    return send_from_directory(assets_dir, filename)

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

@app.route("/feedback/<booking_id>")
def feedback_form(booking_id):
    bookings = load_bookings()
    booking = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return "This feedback link isn't valid. If you think that's a mistake, reply to your confirmation email.", 404

    stype = SESSION_DURATIONS.get(booking.get("session_type", "1hr"), {})
    date_obj = datetime.strptime(booking["date"], "%Y-%m-%d")
    date_display = date_obj.strftime("%d %B %Y")

    return render_template(
        "feedback.html",
        booking_id=booking_id,
        name=booking.get("name", ""),
        session_label=stype.get("label", ""),
        date_display=date_display,
        already_submitted=bool(booking.get("feedback")),
        existing=booking.get("feedback"),
    )

@app.route("/api/feedback/<booking_id>", methods=["POST"])
def submit_feedback(booking_id):
    data = request.json or {}
    try:
        rating = int(data.get("rating", 0))
    except (TypeError, ValueError):
        rating = 0
    if rating < 1 or rating > 5:
        return jsonify({"error": "Please select a star rating."}), 400

    comment = (data.get("comment") or "").strip()

    bookings = load_bookings()
    booking = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return jsonify({"error": "Booking not found."}), 404

    booking["feedback"] = {
        "rating": rating,
        "comment": comment,
        "submitted_at": datetime.now().isoformat(),
    }
    save_bookings(bookings)

    send_email(
        GMAIL_USER, "Vardhasheela",
        f"New feedback from {booking.get('name','')} — {rating}★",
        feedback_notification_email(booking, rating, comment)
    )

    return jsonify({"success": True})

@app.route("/jobs")
def jobs_board():
    category = request.args.get("category", "all")   # all | domestic | international
    role_type = request.args.get("role", "all")       # all | cabin_crew | ground_staff | other

    query = "SELECT * FROM jobs WHERE status != 'closed'"
    params = []

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

    return render_template(
        "jobs.html",
        jobs=jobs,
        active_category=category,
        active_role=role_type,
        today=date.today().isoformat(),
    )

@app.route("/jobs/alert-me", methods=["POST"])
def jobs_alert_me():
    email    = (request.form.get("email") or "").strip().lower()
    category = request.form.get("interested_category", "both")
    role     = request.form.get("interested_role", "all")

    if not email or "@" not in email:
        return jsonify({"ok": False, "error": "Enter a valid email."}), 400

    conn = get_jobs_db()
    try:
        conn.execute(
            """INSERT INTO job_alert_subscribers (email, interested_category, interested_role)
               VALUES (?, ?, ?)
               ON CONFLICT(email) DO UPDATE SET
                 interested_category = excluded.interested_category,
                 interested_role = excluded.interested_role""",
            (email, category, role),
        )
        conn.commit()
    finally:
        conn.close()

    # Notify Vardhasheela of the new lead — same pattern as booking notifications
    send_email(
        GMAIL_USER, "Vardhasheela",
        f"New jobs board subscriber: {email}",
        f"""<div style="font-family:sans-serif;background:#0a0a0b;color:#e8e6f0;padding:32px;border-radius:12px">
          <h3 style="color:#7b5cfa">✈️ New jobs board alert subscriber</h3>
          <p><strong>Email:</strong> {email}</p>
          <p><strong>Interested in:</strong> {category} / {role}</p>
        </div>"""
    )

    send_email(
        email, "",
        "You're on the list! — Aviation Jobs Board",
        subscriber_welcome_email(email)
    )

    return jsonify({"ok": True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
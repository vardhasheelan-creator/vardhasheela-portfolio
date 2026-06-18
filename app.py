from flask import Flask, request, jsonify, render_template, redirect, session
from flask_cors import CORS
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
import json
from datetime import datetime, timedelta
import pytz
from functools import wraps

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
CORS(app)

GMAIL_USER = os.environ.get("GMAIL_USER", "vardhasheelan@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "").replace(" ", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "vardhasheelan@gmail.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "wenixai2026")
UPI_ID = "9113259228@kotakbank"
UPI_NAME = "Vardhasheela N"
IST = pytz.timezone("Asia/Kolkata")
BOOKINGS_FILE = "bookings.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

SESSION_DURATIONS = {
    "30min": {"label": "Quick chat", "duration": 30, "price": 199},
    "1hr":   {"label": "Deep dive session",  "duration": 60, "price": 349},
    "1.5hr": {"label": "Full mentorship",    "duration": 90, "price": 499},
}

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
        msg["From"] = GMAIL_USER
        msg["To"] = to_email
        msg.attach(MIMEText(body_html, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(GMAIL_USER, GMAIL_APP_PASSWORD)
            server.sendmail(GMAIL_USER, to_email, msg.as_string())
        return True
    except Exception as e:
        print(f"Email error: {e}")
        return False

def client_confirmation_email(name, email, session_type, date_str, time_str, meet_link=""):
    stype = SESSION_DURATIONS[session_type]
    upi_section = f"""
    <div style='background:rgba(0,255,136,0.08);border:1px solid rgba(0,255,136,0.25);border-radius:8px;padding:16px;margin:20px 0'>
      <p style='color:#00FF88;font-weight:600;margin:0 0 8px;font-size:14px'>Payment details</p>
      <p style='color:#e8e6f0;margin:4px 0;font-size:14px'>Amount: <strong>₹{stype['price']}</strong></p>
      <p style='color:#e8e6f0;margin:4px 0;font-size:14px'>UPI ID: <strong>{UPI_ID}</strong></p>
      <p style='color:#e8e6f0;margin:4px 0;font-size:14px'>Name: <strong>{UPI_NAME}</strong></p>
      <p style='color:#9997aa;margin:8px 0 0;font-size:12px'>Please complete payment before your session. Share the screenshot on WhatsApp: +91 9113259228</p>
    </div>
    """
    meet_section = f'<p style="color:#9997aa">Google Meet: <a href="{meet_link}" style="color:#00f5ff">{meet_link}</a></p>' if meet_link else '<p style="color:#9997aa">A Google Meet link will be shared once your booking is confirmed.</p>'
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <div style="border-bottom:1px solid rgba(123,92,250,0.3);padding-bottom:20px;margin-bottom:28px">
        <h1 style="margin:0;font-size:22px;color:#fff">Booking received ✅</h1>
        <p style="margin:6px 0 0;color:#9997aa;font-size:13px">vardhasheelan.com — awaiting confirmation</p>
      </div>
      <p>Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Your session request has been received. Vardhasheela will confirm within a few hours.</p>
      <div style="background:rgba(123,92,250,0.1);border:1px solid rgba(123,92,250,0.3);border-radius:8px;padding:20px;margin:20px 0">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:100px">Session</td><td style="color:#fff;font-weight:600">{stype['label']}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Duration</td><td style="color:#fff">{stype['duration']} minutes</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']}</td></tr>
        </table>
      </div>
      {upi_section}
      {meet_section}
      <div style="border-top:1px solid rgba(255,255,255,0.08);margin-top:28px;padding-top:16px">
        <p style="color:#5c5a6b;font-size:12px;margin:0">Vardhasheela N · vardhasheelan@gmail.com · +91 9113259228</p>
      </div>
    </div>
    """

def owner_notification_email(name, email, phone, session_type, date_str, time_str, topic, booking_id):
    stype = SESSION_DURATIONS[session_type]
    base_url = os.environ.get("BASE_URL", "https://vardhasheelan.com")
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h2 style="color:#7b5cfa;margin:0 0 20px">🔔 New booking request</h2>
      <div style="background:rgba(0,245,255,0.08);border:1px solid rgba(0,245,255,0.2);border-radius:8px;padding:20px;margin-bottom:20px">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:100px">Name</td><td style="color:#fff;font-weight:600">{name}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Email</td><td style="color:#00f5ff">{email}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Phone</td><td style="color:#fff">{phone}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Session</td><td style="color:#fff">{stype['label']} ({stype['duration']} min)</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Topic</td><td style="color:#fff">{topic or 'Not specified'}</td></tr>
        </table>
      </div>
      <div style="display:flex;gap:12px;flex-wrap:wrap">
        <a href="{base_url}/admin/action/{booking_id}/confirm" style="background:#22C55E;color:#000;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">✓ Confirm booking</a>
        <a href="{base_url}/admin/action/{booking_id}/decline" style="background:#EF4444;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">✗ Decline</a>
        <a href="{base_url}/admin" style="background:#7B5CFA;color:#fff;padding:12px 24px;border-radius:6px;text-decoration:none;font-weight:600;font-size:14px">Open admin panel</a>
      </div>
    </div>
    """

def client_confirmed_email(name, session_type, date_str, time_str, meet_link=""):
    stype = SESSION_DURATIONS[session_type]
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#22C55E;margin:0 0 20px">✅ Booking confirmed!</h1>
      <p>Hi <strong>{name}</strong>, your session is confirmed.</p>
      <div style="background:rgba(34,197,94,0.08);border:1px solid rgba(34,197,94,0.3);border-radius:8px;padding:20px;margin:20px 0">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:5px 0;width:100px">Session</td><td style="color:#fff;font-weight:600">{stype['label']}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:5px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']}</td></tr>
        </table>
      </div>
      {'<p style="color:#9997aa">Google Meet: <a href="' + meet_link + '" style="color:#00f5ff">' + meet_link + '</a></p>' if meet_link else ''}
      <p style="color:#9997aa;font-size:13px">See you then! If you need to reschedule, reply to this email or WhatsApp +91 9113259228.</p>
    </div>
    """

def client_declined_email(name, session_type, date_str, time_str):
    stype = SESSION_DURATIONS[session_type]
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h1 style="color:#EF4444;margin:0 0 20px">Session request declined</h1>
      <p>Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Unfortunately the slot on <strong style="color:#fff">{date_str} at {time_str} IST</strong> is not available. Please visit <a href="https://vardhasheelan.com/#book" style="color:#00f5ff">vardhasheelan.com</a> to book another slot.</p>
      <p style="color:#9997aa;font-size:13px">Sorry for the inconvenience! — Vardhasheela</p>
    </div>
    """

# ─── ADMIN AUTH ────────────────────────────────────────────────
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
    return f"""
    <!DOCTYPE html><html><head><title>Admin Login</title>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:'Space Grotesk',sans-serif;display:flex;align-items:center;justify-content:center;min-height:100vh;}}
    .box{{background:#0f0f1a;border:1px solid rgba(123,92,250,0.3);border-radius:12px;padding:2.5rem;width:360px;}}
    h2{{color:#7b5cfa;margin-bottom:1.5rem;font-size:1.2rem;}}
    input{{width:100%;background:#070710;border:1px solid rgba(123,92,250,0.2);border-radius:6px;padding:0.75rem 1rem;color:#e8e6f0;font-size:0.9rem;margin-bottom:1rem;outline:none;}}
    input:focus{{border-color:#7b5cfa;}}
    button{{width:100%;background:#7b5cfa;color:#fff;border:none;border-radius:6px;padding:0.85rem;font-size:0.9rem;font-weight:600;cursor:pointer;}}
    .err{{color:#ff6b6b;font-size:0.8rem;margin-bottom:1rem;}}</style></head>
    <body><div class="box"><h2>Admin login</h2>
    <form method="POST">
    {'<p class="err">' + error + '</p>' if error else ''}
    <input type="password" name="password" placeholder="Password" autofocus/>
    <button type="submit">Login →</button>
    </form></div></body></html>
    """

@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect("/admin/login")

@app.route("/admin")
@admin_required
def admin_panel():
    bookings = load_bookings()
    bookings_sorted = sorted(bookings, key=lambda x: x.get("booked_at", ""), reverse=True)

    rows = ""
    for b in bookings_sorted:
        bid = b.get("id", "")
        status = b.get("status", "pending")
        stype = SESSION_DURATIONS.get(b.get("session_type", "1hr"), {})
        status_color = {"pending": "#BA7517", "confirmed": "#22C55E", "declined": "#EF4444"}.get(status, "#888")
        actions = ""
        if status == "pending":
            actions = f'''
            <a href="/admin/action/{bid}/confirm" style="background:#22C55E;color:#000;padding:5px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:600;margin-right:6px">Confirm</a>
            <a href="/admin/action/{bid}/decline" style="background:#EF4444;color:#fff;padding:5px 12px;border-radius:4px;text-decoration:none;font-size:12px;font-weight:600">Decline</a>
            '''
        else:
            actions = f'<span style="color:{status_color};font-size:12px;font-weight:600">{status.upper()}</span>'

        rows += f"""
        <tr style="border-bottom:1px solid rgba(255,255,255,0.06)">
          <td style="padding:12px 8px;color:#fff;font-size:13px">{b.get('name','')}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{b.get('email','')}</td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px">{b.get('phone','')}</td>
          <td style="padding:12px 8px;color:#00f5ff;font-size:12px">{b.get('date','')} {b.get('time','')}</td>
          <td style="padding:12px 8px;color:#7b5cfa;font-size:12px">{stype.get('label','')}<br><span style="color:#9997aa">₹{stype.get('price','')}</span></td>
          <td style="padding:12px 8px;color:#9997aa;font-size:12px;max-width:150px">{b.get('topic','—')[:60]}</td>
          <td style="padding:12px 8px">{actions}</td>
        </tr>
        """

    pending = sum(1 for b in bookings if b.get("status","pending") == "pending")
    confirmed = sum(1 for b in bookings if b.get("status") == "confirmed")

    return f"""
    <!DOCTYPE html><html><head><title>Admin — Bookings</title>
    <link href="https://fonts.googleapis.com/css2?family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet"/>
    <style>*{{box-sizing:border-box;margin:0;padding:0;}}
    body{{background:#050508;color:#e8e6f0;font-family:'Space Grotesk',sans-serif;padding:2rem;}}
    .header{{display:flex;align-items:center;justify-content:space-between;margin-bottom:2rem;flex-wrap:wrap;gap:1rem;}}
    h1{{color:#7b5cfa;font-size:1.4rem;}}
    .stats{{display:flex;gap:1.5rem;flex-wrap:wrap;}}
    .stat{{background:#0f0f1a;border:1px solid rgba(123,92,250,0.2);border-radius:8px;padding:0.75rem 1.25rem;text-align:center;}}
    .stat strong{{display:block;font-size:1.5rem;color:#fff;}}
    .stat span{{font-size:11px;color:#9997aa;letter-spacing:0.06em;}}
    table{{width:100%;border-collapse:collapse;background:#0f0f1a;border:1px solid rgba(123,92,250,0.15);border-radius:8px;overflow:hidden;}}
    th{{padding:12px 8px;text-align:left;font-size:11px;color:#9997aa;letter-spacing:0.08em;text-transform:uppercase;border-bottom:1px solid rgba(255,255,255,0.08);}}
    tr:hover{{background:rgba(123,92,250,0.04);}}
    .logout{{font-size:12px;color:#9997aa;text-decoration:none;border:1px solid rgba(255,255,255,0.1);padding:6px 14px;border-radius:4px;}}
    .logout:hover{{color:#ff6b6b;border-color:#ff6b6b;}}
    </style></head>
    <body>
    <div class="header">
      <div>
        <h1>Bookings admin</h1>
        <p style="color:#9997aa;font-size:13px;margin-top:4px">vardhasheelan.com</p>
      </div>
      <div class="stats">
        <div class="stat"><strong>{len(bookings)}</strong><span>TOTAL</span></div>
        <div class="stat"><strong style="color:#BA7517">{pending}</strong><span>PENDING</span></div>
        <div class="stat"><strong style="color:#22C55E">{confirmed}</strong><span>CONFIRMED</span></div>
      </div>
      <a href="/admin/logout" class="logout">Logout</a>
    </div>
    <div style="overflow-x:auto">
    <table>
      <thead><tr>
        <th>Name</th><th>Email</th><th>Phone</th><th>Date & Time</th><th>Session</th><th>Topic</th><th>Action</th>
      </tr></thead>
      <tbody>{rows if rows else '<tr><td colspan="7" style="padding:2rem;text-align:center;color:#9997aa">No bookings yet</td></tr>'}</tbody>
    </table>
    </div>
    </body></html>
    """

@app.route("/admin/action/<booking_id>/<action>")
@admin_required
def admin_action(booking_id, action):
    bookings = load_bookings()
    booking = next((b for b in bookings if b.get("id") == booking_id), None)
    if not booking:
        return "Booking not found", 404

    stype = SESSION_DURATIONS.get(booking.get("session_type", "1hr"), {})
    date_obj = datetime.strptime(booking["date"], "%Y-%m-%d")
    date_display = date_obj.strftime("%A, %d %B %Y")
    h, m = map(int, booking["time"].split(":"))
    time_display = datetime(2000, 1, 1, h, m).strftime("%I:%M %p")

    if action == "confirm":
        booking["status"] = "confirmed"
        send_email(
            booking["email"], booking["name"],
            "Your session is confirmed — vardhasheelan.com",
            client_confirmed_email(booking["name"], booking["session_type"],
                                   date_display, time_display, booking.get("meet_link", ""))
        )
    elif action == "decline":
        booking["status"] = "declined"
        send_email(
            booking["email"], booking["name"],
            "Session request update — vardhasheelan.com",
            client_declined_email(booking["name"], booking["session_type"], date_display, time_display)
        )

    save_bookings(bookings)
    return redirect("/admin")

# ─── MAIN ROUTES ───────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", sessions=SESSION_DURATIONS)

@app.route('/assets/<path:filename>')
def assets(filename):
    from flask import send_from_directory
    return send_from_directory('public/assets', filename)

@app.route('/consult')
def consult():
    return render_template("consult.html")

@app.route("/authorize")
def authorize():
    if not os.path.exists("credentials.json"):
        return jsonify({"error": "credentials.json not found"}), 500
    flow = Flow.from_client_secrets_file("credentials.json", scopes=SCOPES,
        redirect_uri=request.url_root + "oauth2callback")
    auth_url, state = flow.authorization_url(access_type="offline", include_granted_scopes="true")
    session["state"] = state
    return redirect(auth_url)

@app.route("/oauth2callback")
def oauth2callback():
    if not os.path.exists("credentials.json"):
        return jsonify({"error": "credentials.json not found"}), 500
    flow = Flow.from_client_secrets_file("credentials.json", scopes=SCOPES,
        state=session.get("state"), redirect_uri=request.url_root + "oauth2callback")
    flow.fetch_token(authorization_response=request.url)
    creds = flow.credentials
    session["credentials"] = {
        "token": creds.token,
        "refresh_token": creds.refresh_token,
        "token_uri": creds.token_uri,
        "client_id": creds.client_id,
        "client_secret": creds.client_secret,
        "scopes": list(creds.scopes),
    }
    return redirect("/")

@app.route("/api/slots")
def get_slots():
    date_str = request.args.get("date")
    session_type = request.args.get("session_type", "1hr")
    if not date_str:
        return jsonify({"error": "date required"}), 400
    try:
        date = datetime.strptime(date_str, "%Y-%m-%d")
    except ValueError:
        return jsonify({"error": "invalid date format"}), 400

    duration = SESSION_DURATIONS.get(session_type, SESSION_DURATIONS["1hr"])["duration"]
    start_hour, end_hour = 15, 22

    booked_slots = set()
    bookings = load_bookings()
    for b in bookings:
        if b.get("date") == date_str and b.get("status") != "declined":
            booked_slots.add(b.get("time"))

    service = get_calendar_service()
    calendar_busy = set()
    if service:
        try:
            day_start = IST.localize(datetime(date.year, date.month, date.day, start_hour, 0))
            day_end = IST.localize(datetime(date.year, date.month, date.day, end_hour, 0))
            events = service.events().list(
                calendarId=CALENDAR_ID,
                timeMin=day_start.isoformat(),
                timeMax=day_end.isoformat(),
                singleEvents=True,
            ).execute()
            for event in events.get("items", []):
                start = event.get("start", {}).get("dateTime")
                end = event.get("end", {}).get("dateTime")
                if start and end:
                    s = datetime.fromisoformat(start).astimezone(IST)
                    e = datetime.fromisoformat(end).astimezone(IST)
                    t = s
                    while t < e:
                        calendar_busy.add(t.strftime("%H:%M"))
                        t += timedelta(minutes=30)
        except Exception as ex:
            print(f"Calendar fetch error: {ex}")

    slots = []
    current = datetime(date.year, date.month, date.day, start_hour, 0)
    end_dt = datetime(date.year, date.month, date.day, end_hour, 0)
    while current + timedelta(minutes=duration) <= end_dt:
        time_str = current.strftime("%H:%M")
        booked = time_str in booked_slots or time_str in calendar_busy
        slots.append({"time": time_str, "booked": booked,
                      "display": current.strftime("%I:%M %p")})
        current += timedelta(minutes=30)

    return jsonify({"slots": slots, "date": date_str})

@app.route("/api/book", methods=["POST"])
def book():
    data = request.json
    required = ["name", "email", "phone", "date", "time", "session_type"]
    for field in required:
        if not data.get(field):
            return jsonify({"error": f"{field} is required"}), 400

    bookings = load_bookings()
    for b in bookings:
        if b.get("date") == data["date"] and b.get("time") == data["time"] and b.get("status") != "declined":
            return jsonify({"error": "This slot was just booked. Please choose another."}), 409

    stype = SESSION_DURATIONS.get(data["session_type"])
    if not stype:
        return jsonify({"error": "Invalid session type"}), 400

    import uuid
    booking_id = str(uuid.uuid4())[:8]

    meet_link = ""
    service = get_calendar_service()
    if service:
        try:
            date = datetime.strptime(data["date"], "%Y-%m-%d")
            h, m = map(int, data["time"].split(":"))
            start_dt = IST.localize(datetime(date.year, date.month, date.day, h, m))
            end_dt = start_dt + timedelta(minutes=stype["duration"])
            event = {
                "summary": f"Consultation: {data['name']} ({stype['label']})",
                "description": f"Client: {data['name']}\nEmail: {data['email']}\nPhone: {data['phone']}\nTopic: {data.get('topic', 'N/A')}",
                "start": {"dateTime": start_dt.isoformat(), "timeZone": "Asia/Kolkata"},
                "end": {"dateTime": end_dt.isoformat(), "timeZone": "Asia/Kolkata"},
                "conferenceData": {"createRequest": {"requestId": booking_id}},
                "attendees": [{"email": data["email"]}],
            }
            created = service.events().insert(
                calendarId=CALENDAR_ID, body=event,
                conferenceDataVersion=1, sendUpdates="all"
            ).execute()
            meet_link = created.get("hangoutLink", "")
        except Exception as ex:
            print(f"Calendar event error: {ex}")

    date_obj = datetime.strptime(data["date"], "%Y-%m-%d")
    date_display = date_obj.strftime("%A, %d %B %Y")
    h, m = map(int, data["time"].split(":"))
    time_display = datetime(2000, 1, 1, h, m).strftime("%I:%M %p")

    booking = {
        "id": booking_id,
        "name": data["name"], "email": data["email"], "phone": data["phone"],
        "date": data["date"], "time": data["time"], "session_type": data["session_type"],
        "topic": data.get("topic", ""), "meet_link": meet_link,
        "status": "pending",
        "booked_at": datetime.now().isoformat(),
    }
    save_booking(booking)

    # Email to client
    send_email(data["email"], data["name"],
               "Booking received — vardhasheelan.com",
               client_confirmation_email(data["name"], data["email"], data["session_type"],
                                         date_display, time_display, meet_link))

    # Email to owner with confirm/decline buttons
    send_email(GMAIL_USER, "Vardhasheela",
               f"New booking from {data['name']} — {date_display} {time_display}",
               owner_notification_email(data["name"], data["email"], data["phone"],
                                        data["session_type"], date_display, time_display,
                                        data.get("topic", ""), booking_id))

    stype_data = SESSION_DURATIONS[data["session_type"]]
    return jsonify({
        "success": True,
        "message": "Booking received! Check your email for payment details. You'll get a confirmation once Vardhasheela accepts.",
        "upi_id": UPI_ID,
        "upi_name": UPI_NAME,
        "amount": stype_data["price"],
    })

@app.route("/api/contact", methods=["POST"])
def contact():
    data = request.json
    if not data.get("email") or not data.get("message"):
        return jsonify({"error": "Email and message are required"}), 400
    body = f"""
    <div style="font-family:sans-serif;background:#0a0a0b;color:#e8e6f0;padding:32px;border-radius:12px">
      <h3 style="color:#7b5cfa">New contact message</h3>
      <p><strong>From:</strong> {data.get('name', 'Anonymous')}</p>
      <p><strong>Email:</strong> {data['email']}</p>
      <p><strong>Message:</strong><br>{data['message']}</p>
    </div>
    """
    send_email(GMAIL_USER, "Vardhasheela", f"New message from {data.get('name', data['email'])}", body)
    return jsonify({"success": True})

if __name__ == "__main__":
    app.run(debug=True, port=5000)
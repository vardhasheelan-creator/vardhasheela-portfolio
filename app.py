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

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "dev-secret-change-in-production")
CORS(app)

GMAIL_USER = os.environ.get("GMAIL_USER", "vardhasheelan@gmail.com")
GMAIL_APP_PASSWORD = os.environ.get("GMAIL_APP_PASSWORD", "")
CALENDAR_ID = os.environ.get("CALENDAR_ID", "vardhasheelan@gmail.com")
IST = pytz.timezone("Asia/Kolkata")
BOOKINGS_FILE = "bookings.json"
SCOPES = ["https://www.googleapis.com/auth/calendar"]
os.environ["OAUTHLIB_INSECURE_TRANSPORT"] = "1"

SESSION_DURATIONS = {
    "30min": {"label": "Quick clarity call", "duration": 30, "price": 299},
    "1hr":   {"label": "Deep dive session",  "duration": 60, "price": 499},
    "1.5hr": {"label": "Full mentorship",    "duration": 90, "price": 699},
}

def load_bookings():
    if not os.path.exists(BOOKINGS_FILE):
        return []
    with open(BOOKINGS_FILE) as f:
        return json.load(f)

def save_booking(booking):
    bookings = load_bookings()
    bookings.append(booking)
    with open(BOOKINGS_FILE, "w") as f:
        json.dump(bookings, f, indent=2)

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

def client_confirmation_email(name, email, session_type, date_str, time_str, meet_link):
    stype = SESSION_DURATIONS[session_type]
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <div style="border-bottom:1px solid rgba(123,92,250,0.3);padding-bottom:20px;margin-bottom:28px">
        <h1 style="margin:0;font-size:24px;color:#fff">Booking confirmed ✅</h1>
        <p style="margin:8px 0 0;color:#9997aa;font-size:14px">vardhasheelan.com</p>
      </div>
      <p style="color:#e8e6f0">Hi <strong>{name}</strong>,</p>
      <p style="color:#9997aa">Your consultation session has been booked. Here are the details:</p>
      <div style="background:rgba(123,92,250,0.1);border:1px solid rgba(123,92,250,0.3);border-radius:8px;padding:20px;margin:24px 0">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:6px 0">Session</td><td style="color:#fff;font-weight:600">{stype['label']}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Duration</td><td style="color:#fff">{stype['duration']} minutes</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']}</td></tr>
        </table>
      </div>
      {'<p style="color:#9997aa">Google Meet link: <a href="' + meet_link + '" style="color:#00f5ff">' + meet_link + '</a></p>' if meet_link else '<p style="color:#9997aa">You will receive a Google Meet link once the booking is confirmed.</p>'}
      <p style="color:#9997aa;font-size:13px;margin-top:32px">Payment can be made via UPI/bank transfer before the session. Details will be shared separately.</p>
      <div style="border-top:1px solid rgba(255,255,255,0.08);margin-top:32px;padding-top:20px">
        <p style="color:#5c5a6b;font-size:12px;margin:0">Vardhasheela N · vardhasheelan@gmail.com · +91 9113259228</p>
      </div>
    </div>
    """

def owner_notification_email(name, email, phone, session_type, date_str, time_str, topic):
    stype = SESSION_DURATIONS[session_type]
    return f"""
    <div style="font-family:sans-serif;max-width:600px;margin:0 auto;background:#0a0a0b;color:#e8e6f0;padding:40px;border-radius:12px">
      <h2 style="color:#7b5cfa;margin:0 0 20px">🔔 New booking request</h2>
      <div style="background:rgba(0,245,255,0.08);border:1px solid rgba(0,245,255,0.2);border-radius:8px;padding:20px">
        <table style="width:100%;font-size:14px">
          <tr><td style="color:#9997aa;padding:6px 0;width:120px">Name</td><td style="color:#fff;font-weight:600">{name}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Email</td><td style="color:#00f5ff">{email}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Phone</td><td style="color:#fff">{phone}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Session</td><td style="color:#fff">{stype['label']} ({stype['duration']} min)</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Date</td><td style="color:#fff">{date_str}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Time</td><td style="color:#fff">{time_str} IST</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Amount</td><td style="color:#7b5cfa;font-weight:600">₹{stype['price']}</td></tr>
          <tr><td style="color:#9997aa;padding:6px 0">Topic</td><td style="color:#fff">{topic or 'Not specified'}</td></tr>
        </table>
      </div>
      <p style="color:#9997aa;margin-top:20px;font-size:13px">Please confirm or reschedule by replying to <strong style="color:#fff">{email}</strong></p>
    </div>
    """

@app.route("/")
def index():
    return render_template("index.html", sessions=SESSION_DURATIONS)

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
    slots = []
    start_hour, end_hour = 15, 22

    booked_slots = set()
    bookings = load_bookings()
    for b in bookings:
        if b.get("date") == date_str:
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
        if b.get("date") == data["date"] and b.get("time") == data["time"]:
            return jsonify({"error": "This slot was just booked. Please choose another."}), 409

    stype = SESSION_DURATIONS.get(data["session_type"])
    if not stype:
        return jsonify({"error": "Invalid session type"}), 400

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
                "conferenceData": {"createRequest": {"requestId": f"{data['date']}-{data['time']}"}},
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
        "name": data["name"], "email": data["email"], "phone": data["phone"],
        "date": data["date"], "time": data["time"], "session_type": data["session_type"],
        "topic": data.get("topic", ""), "meet_link": meet_link,
        "booked_at": datetime.now().isoformat(),
    }
    save_booking(booking)

    send_email(data["email"], data["name"], "Your consultation is booked — vardhasheelan.com",
               client_confirmation_email(data["name"], data["email"], data["session_type"],
                                         date_display, time_display, meet_link))
    send_email(GMAIL_USER, "Vardhasheela", f"New booking: {data['name']} on {date_display}",
               owner_notification_email(data["name"], data["email"], data["phone"],
                                        data["session_type"], date_display, time_display,
                                        data.get("topic", "")))

    return jsonify({"success": True, "meet_link": meet_link,
                    "message": "Booking confirmed! Check your email for details."})

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
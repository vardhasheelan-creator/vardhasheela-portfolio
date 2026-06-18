# 🌐 vardhasheelan.com — AI Agency & Consultation Portfolio

Personal portfolio and agency website for **Vardhasheela N** — AI automation builder, technical support engineer, and content creator.

> Live at: **[vardhasheelan.com](https://vardhasheelan.com)**

---

## 🔥 What's on the site

### Agency (main page)
Built as the home for **Wenix AI** — an AI automation agency offering:
- Workflow automation (n8n, Make, Zapier)
- Custom AI agents (Python, Claude API)
- AI-powered websites (Flask, booking systems)
- AI workflow strategy & consulting

USD/INR currency toggle for pricing. Lead capture form with email notification.

### Consultations (`/consult`)
Separate page for YouTube community — 1-on-1 sessions on:
- Cabin crew & aviation career guidance
- English fluency & communication
- AI & tech basics for beginners
- Career planning & switching

Pricing: ₹199 / ₹349 / ₹499 — UPI payment inline.

---

## ⚙️ Tech stack

- **Python + Flask** — backend server
- **Google Calendar API** — real-time slot availability & booking
- **Gmail SMTP** — automatic confirmation emails to client + owner
- **Admin panel** at `/admin` — confirm/decline bookings with one click
- **Render.com** — hosting & deployment
- **GoDaddy** — custom domain `vardhasheelan.com`

---

## 🗂 Project structure

```
vardhasheela-portfolio/
├── app.py                  # Flask backend — routes, booking, emails
├── requirements.txt        # Python dependencies
├── render.yaml             # Render deployment config
├── .gitignore              # Excludes .env, credentials, bookings
├── templates/
│   ├── index.html          # Agency homepage (Wenix AI)
│   └── consult.html        # Consultation booking page
└── public/
    └── assets/             # Images (my pic.png, vardhasheela.jpeg, etc.)
```

---

## 🚀 Setup locally

```bash
git clone https://github.com/vardhasheelan-creator/vardhasheela-portfolio.git
cd vardhasheela-portfolio
py -m venv venv
venv\Scripts\Activate.ps1       # Windows
pip install -r requirements.txt
```

Create a `.env` file:
```
SECRET_KEY=your-secret-key
GMAIL_USER=your@gmail.com
GMAIL_APP_PASSWORD=your-app-password
CALENDAR_ID=your@gmail.com
ADMIN_PASSWORD=your-admin-password
```

Add `credentials.json` from Google Cloud Console (OAuth for Calendar API).

```bash
python app.py
# Visit http://localhost:5000
# First time: go to http://localhost:5000/authorize to connect Google Calendar
```

---

## 🔑 Environment variables (Render)

| Key | Description |
|---|---|
| `SECRET_KEY` | Flask session secret |
| `GMAIL_USER` | Gmail address for sending emails |
| `GMAIL_APP_PASSWORD` | Gmail app password (no spaces) |
| `CALENDAR_ID` | Google Calendar ID |
| `ADMIN_PASSWORD` | Password for `/admin` panel |

---

## 📋 Features

- Real-time slot availability (greyed out when booked)
- Email to client with UPI payment details
- Email to owner with Confirm / Decline buttons
- Admin panel at `/admin` — manage all bookings
- Google Calendar event created on booking
- Contact form for agency inquiries
- USD ↔ INR currency toggle on services

---

## 👩‍💻 Built by

**Vardhasheela N** — [vardhasheelan.com](https://vardhasheelan.com) · [YouTube](https://youtube.com/@vardhasheela.n) · [GitHub](https://github.com/vardhasheelan-creator)

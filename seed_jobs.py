"""
Seed the jobs table with starter listings.

Run manually 2-3x a week to refresh: check each airline's real careers page,
update dates/links/status, then re-run.

Usage: python seed_jobs.py
"""
import sqlite3
from datetime import date

DB_PATH = "/data/jobs.db"
TODAY = date.today().isoformat()

# Replace application_link values with the real, current careers-page URLs
# before going live. These are placeholders showing the data shape.
SAMPLE_JOBS = [
    dict(
        airline_name="IndiGo",
        category="domestic",
        role_type="cabin_crew",
        role_title="Cabin Crew - Fresher",
        location="Multiple bases across India",
        eligibility_summary="Class 12 pass, height 155-190cm, age 18-27, no visible tattoos.",
        application_link="https://careers.goindigo.in/",
        status="open",
        last_verified_date=TODAY,
        notes="Apply only through the official IndiGo careers portal.",
    ),
    dict(
        airline_name="Air India",
        category="domestic",
        role_type="cabin_crew",
        role_title="Cabin Crew - Domestic & International Routes",
        location="Delhi / Mumbai bases",
        eligibility_summary="Graduate preferred, height 155cm+, fluent English + one regional language.",
        application_link="https://careers.airindia.com/",
        status="open",
        last_verified_date=TODAY,
    ),
    dict(
        airline_name="Akasa Air",
        category="domestic",
        role_type="ground_staff",
        role_title="Airport Services Executive",
        location="Bengaluru, Mumbai, Ahmedabad",
        eligibility_summary="Graduate, prior airport/customer-facing experience preferred.",
        application_link="https://akasaair.com/careers",
        status="closing_soon",
        last_verified_date=TODAY,
    ),
    dict(
        airline_name="SpiceJet",
        category="domestic",
        role_type="cabin_crew",
        role_title="Trainee Cabin Crew",
        location="Delhi / Multiple bases",
        eligibility_summary="Class 12 pass, height 154cm+, age 18-26.",
        application_link="https://spicejet.com/careers/",
        status="open",
        last_verified_date=TODAY,
    ),
    dict(
        airline_name="Emirates",
        category="international",
        role_type="cabin_crew",
        role_title="Cabin Crew - India Open Day Hiring",
        location="Assessment held in major Indian cities, based Dubai",
        eligibility_summary="Age 21+, height 160cm+, arm reach 212cm, Class 12 pass.",
        application_link="https://www.emiratesgroupcareers.com/",
        status="open",
        last_verified_date=TODAY,
        notes="Watch for open-day announcements specific to Indian cities.",
    ),
    dict(
        airline_name="Qatar Airways",
        category="international",
        role_type="cabin_crew",
        role_title="Flight Attendant - India Recruitment",
        location="Assessment in India, based Doha",
        eligibility_summary="Age 21+, height 160cm+, Class 12 pass, no visible tattoos.",
        application_link="https://careers.qatarairways.com/",
        status="open",
        last_verified_date=TODAY,
    ),
    dict(
        airline_name="Etihad Airways",
        category="international",
        role_type="cabin_crew",
        role_title="Cabin Crew",
        location="Assessment in India, based Abu Dhabi",
        eligibility_summary="Age 21+, height 160cm+, swim test required.",
        application_link="https://careers.etihad.com/",
        status="open",
        last_verified_date=TODAY,
    ),
    dict(
        airline_name="Vistara / Air India",
        category="domestic",
        role_type="ground_staff",
        role_title="Customer Service Agent",
        location="Multiple metro airports",
        eligibility_summary="Graduate, good communication skills, shift flexibility.",
        application_link="https://careers.airindia.com/",
        status="open",
        last_verified_date=TODAY,
        notes="Vistara has merged into Air India; listings now route through Air India careers.",
    ),
]


def seed():
    conn = sqlite3.connect(DB_PATH)
    with open("schema.sql", "r") as f:
        conn.executescript(f.read())

    cur = conn.cursor()
    for job in SAMPLE_JOBS:
        cur.execute(
            """
            INSERT INTO jobs
                (airline_name, category, role_type, role_title, location,
                 eligibility_summary, application_link, status, last_verified_date, notes)
            VALUES (:airline_name, :category, :role_type, :role_title, :location,
                    :eligibility_summary, :application_link, :status, :last_verified_date, :notes)
            """,
            {**job, "notes": job.get("notes", "")},
        )
    conn.commit()
    conn.close()
    print(f"Seeded {len(SAMPLE_JOBS)} jobs into {DB_PATH}")


if __name__ == "__main__":
    seed()
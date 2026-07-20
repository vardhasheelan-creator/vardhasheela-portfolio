-- Job listings aggregator schema
-- One row = one open role at one airline/company, manually verified.

CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,

    airline_name TEXT NOT NULL,             -- e.g. "IndiGo"
    airline_logo_url TEXT,                  -- optional, can be left blank for now

    category TEXT NOT NULL CHECK (category IN ('domestic', 'international')),
    role_type TEXT NOT NULL CHECK (role_type IN ('cabin_crew', 'ground_staff', 'other')),

    role_title TEXT NOT NULL,               -- e.g. "Cabin Crew - Fresher"
    location TEXT,                          -- e.g. "Bengaluru / Multiple Bases"

    eligibility_summary TEXT,               -- 1-2 line plain-English summary
    application_link TEXT NOT NULL,         -- always the airline's real careers page

    status TEXT NOT NULL DEFAULT 'open' CHECK (status IN ('open', 'closing_soon', 'closed')),

    last_verified_date TEXT NOT NULL,       -- ISO date, e.g. "2026-07-18"
    notes TEXT,                             -- anything you want to flag to viewers

    created_at TEXT DEFAULT CURRENT_TIMESTAMP,
    updated_at TEXT DEFAULT CURRENT_TIMESTAMP
);

-- Email capture for "alert me about new postings"
CREATE TABLE IF NOT EXISTS job_alert_subscribers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    email TEXT NOT NULL UNIQUE,
    interested_category TEXT,   -- 'domestic', 'international', or 'both'
    interested_role TEXT,       -- 'cabin_crew', 'ground_staff', 'other', or 'all'
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_jobs_category ON jobs(category);
CREATE INDEX IF NOT EXISTS idx_jobs_role_type ON jobs(role_type);
CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status);
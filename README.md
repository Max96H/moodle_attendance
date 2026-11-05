# Moodle Attendance Automation (GitHub Actions)

Automatically checks in and out on a Moodle attendance page at fixed times, several days a week, using Selenium and GitHub Actions. It runs in the cloud, so no personal computer needs to be switched on.

Inspired by [CoViktor/Moodle_attendance_automation](https://github.com/CoViktor/Moodle_attendance_automation), which runs locally through a task scheduler. This version replaces the local scheduler with GitHub Actions and the local credentials file with GitHub Secrets.

> **Disclaimer:** only use this if your program allows automated attendance logging. The script reports a location ("at home" / "on campus") based on the weekday, not on where you actually are.

## How it works

1. A scheduled GitHub Actions workflow starts a fresh Linux runner at the configured times.
2. The runner installs Python and Selenium and launches headless Chrome.
3. `main.py` logs in to Moodle with credentials read from environment variables, opens the attendance page, and performs the requested action (`checkin` or `checkout`).
4. If something fails, a screenshot of the page is saved as a workflow artifact for debugging.

The workflow decides which action to run from the cron expression that triggered it, not from the clock, so late runs never pick the wrong action.

## Repository structure

```
.
├── .github/
│   └── workflows/
│       └── attendance.yml   # schedule + job definition
├── main.py                  # Selenium script
├── requirements.txt         # Python dependencies (selenium)
└── README.md
```

## Setup

### 1. Add your credentials as secrets

Credentials are never stored in the code. In your repository go to **Settings → Secrets and variables → Actions → New repository secret** and create:

| Secret | Value |
|---|---|
| `MOODLE_LOGIN` | your Moodle username |
| `MOODLE_PASSWORD` | your Moodle password |

### 2. Configure `main.py`

Edit the `SETUP` section at the top of the file:

| Setting | Purpose |
|---|---|
| `TIMEZONE` | Timezone used for dates and weekdays (runners use UTC). Default: `Europe/Brussels` |
| `HOLIDAYS` | List of `YYYY-MM-DD` dates on which nothing runs. **Keep it up to date.** |
| `CAMPUS_DAYS` | Weekdays spent on campus (`0` = Monday … `6` = Sunday). All other days are "at home" |
| `URL_ATTENDANCE` | URL of your Moodle attendance page. ***id* param differs by course.**|

### 3. Configure the schedule

The schedule lives in `.github/workflows/attendance.yml`. Cron times are in **UTC**, Monday to Friday:

| Cron | Action | Brussels time (winter, UTC+1) |
|---|---|---|
| `7 8 * * 1-5` | check-in | ~09:07 |
| `33 11 * * 1-5` | check-out | ~12:33 |
| `37 12 * * 1-5` | check-in | ~13:37 |
| `3 16 * * 1-5` | check-out | ~17:03 |

Things to know:

- **Daylight saving time:** in summer (UTC+2) the same local times need cron hours one hour earlier. Update the cron lines at each clock change.
- **Keep the `case` block in sync:** the run step in the workflow maps each cron string to an action. If you change a cron line, change it there too, otherwise the run fails with "Unknown schedule".
- **Delays:** GitHub may start scheduled runs 5 to 30 minutes late, especially on the hour and half-hour. That's why the times use odd minutes.
- **Default branch only:** scheduled workflows run from the repository's default branch.

## Usage

### Automatic

Once `attendance.yml` is on the default branch, runs start by themselves at the scheduled times. Check the **Actions** tab to see results.

### Manual

Go to **Actions → Moodle attendance → Run workflow**, pick `checkin` or `checkout`, and run it. Useful for testing.

### Locally (for development)

```bash
pip install -r requirements.txt
export MOODLE_LOGIN="your_username"
export MOODLE_PASSWORD="your_password"
python main.py checkin    # or: python main.py checkout
```

Requires Chrome installed locally.

## Behavior

- Skips weekends and dates listed in `HOLIDAYS`. It also does nothing on days that have no session in the attendance table.
- Picks the location from the weekday (`CAMPUS_DAYS`).
- Reads today's rows of the attendance table (date and time range, status cell) and only looks for the `Check in` / `Check out` link in those rows.
- If the action is already done (for example, checking in when already checked in), it logs "nothing to do" and exits successfully.
- A **check-out** with nothing to check out of is not an error. A **check-in** fails (on purpose) if a session has already started, still shows `?`, and no `Check in` link is available, so a missed check-in shows up as a failed run.
- After a click it reloads the page and verifies that the status really changed.
- Verifies that the login form is filled before submitting. A rejected login fails the run with Moodle's error message and is **not** retried, to avoid locking the account.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Unknown schedule '…'` | A cron line was changed without updating the `case` block in the workflow |
| `Login was not accepted: …` | Wrong credentials in the secrets, or Moodle is blocking the login. Check the message in the log |
| `Attendance table not found …` / `Could not read any session …` | The page layout, link texts or date format changed. Check the debug screenshot, then adjust the selectors/parsing in `main.py` |
| `Could not checkin: the session starting at … is still '?'` | No `Check in` link was available at run time (window not open yet, or missed). Check the run's schedule and the session's window |
| No runs happening | Workflow disabled, not on the default branch, or (public repos) disabled after 60 days without repository activity |

On failure, download the **debug-screenshot** artifact from the bottom of the workflow run page.

## Security notes

- Credentials are stored only as GitHub Secrets. GitHub masks them in logs, and the script never prints them.
- In a public repository, logs and artifacts are visible to others. A private repository is safer.
- Failed logins count as login attempts on your Moodle account. Avoid repeated test runs when something is broken.

## Stopping the automation

To stop it without deleting the project:

1. Go to **Actions → Moodle attendance → ⋯ → Disable workflow** (or remove the `schedule:` block from `attendance.yml`).
2. Delete the `MOODLE_LOGIN` and `MOODLE_PASSWORD` secrets under **Settings → Secrets and variables → Actions**.

The code and history stay in the repository as a reference.
# Moodle Attendance Automation (GitHub Actions)

Within a DATA & AI course at BeCode, I was given the challenge of automating my attendance checks using GitHub Actions. This is the result:  

Automatically checks in and out on a Moodle attendance page at fixed times, several days a week, using Selenium and GitHub Actions. It runs in the cloud, so no personal computer needs to be switched on.

Two independent triggers start the workflow: **GitHub's own scheduler** and an external scheduler, **cron-job.org** (a second layer added because GitHub's scheduler proved unreliable, see [Known issue](#known-issue-github-scheduler-delays)).

Inspired by [CoViktor/Moodle_attendance_automation](https://github.com/CoViktor/Moodle_attendance_automation), which runs locally through a task scheduler. This version replaces the local scheduler with GitHub Actions and the local credentials file with GitHub Secrets.

> **Disclaimer:** only use this if your program allows automated attendance logging. The script reports a location ("at home" / "on campus") based on the weekday, not on where you actually are.

## How it works

1. A GitHub Actions workflow run is started, either by GitHub's scheduler (cron) or by an HTTP call from cron-job.org (`workflow_dispatch`).
2. The runner installs Python and Selenium and launches headless Chrome.
3. `main.py` logs in to Moodle with credentials read from environment variables, opens the attendance page, and performs the requested action (`checkin` or `checkout`).
4. If something fails, a screenshot of the page is saved as a workflow artifact for debugging.

For scheduled runs, the workflow decides which action to run from the cron expression that triggered it, not from the clock, so late runs never pick the wrong action. For manual and cron-job.org runs, the action comes from the `action` input (`checkin` or `checkout`).

## Repository structure

```
.
├── .github/
│   └── workflows/
│       └── attendance.yml   # triggers + job definition
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

### 3. Configure the GitHub schedule

The schedule lives in `.github/workflows/attendance.yml`. Cron times are in **UTC**, Monday to Friday:

| Cron | Action | Brussels time (winter, UTC+1) |
|---|---|---|
| `52 7 * * 1-5` | check-in | ~08:52 |
| `33 11 * * 1-5` | check-out | ~12:33 |
| `22 12 * * 1-5` | check-in | ~13:22 |
| `3 16 * * 1-5` | check-out | ~17:03 |

Things to know:

- **Daylight saving time:** in summer (UTC+2) the same local times need cron hours one hour earlier. Update the cron lines at each clock change.
- **Keep the `case` block in sync:** the run step in the workflow maps each cron string to an action. If you change a cron line, change it there too, otherwise the run fails with "Unknown schedule". The lateness guard (below) reads the intended time from the cron string itself, so there is nothing else to edit.
- **Delays:** GitHub does not guarantee start times for scheduled runs. In theory delays of 5 to 30 minutes are normal (that's why the times use odd minutes instead of `:00` / `:30`), but in practice they have been much longer, see the next section.
- **Default branch only:** scheduled workflows run from the repository's default branch.

## Known issue: GitHub scheduler delays

During testing (November 2026), **every scheduled run started between 300 and 500 minutes late** (for example, a run planned for 17:03 started at 22:48). Other users have reported similar multi-hour delays and missing runs on GitHub's community forum. Hopefully this is temporary, but a scheduler this late cannot be relied on for check-ins that must happen in a narrow time window.

### Guardrail: skip scheduled runs that are too late

A check-out that arrives hours late could land in the middle of a session and check you out by mistake. To prevent this, scheduled runs **skip entirely if they start more than 20 minutes after their cron time**:

- The intended time is read from the cron expression that fired (UTC) and compared with the current time when the step starts. Time spent waiting in GitHub's queue and setting up the runner counts as lateness.
- A skipped run prints a yellow warning (`Skipped checkout: run started 345 min after its cron time (max 20)`) and ends successfully without touching Moodle.
- The limit is `MAX_LATE_MIN` in the `env` block of the "Run attendance action" step in `attendance.yml`.
- **Manual runs are never skipped**, whatever the time, so you can always test. Runs triggered by cron-job.org arrive as manual runs (`workflow_dispatch`) and are not checked either, because they are expected to be punctual.

In testing, all the late scheduled runs were skipped by this guardrail, as intended.

## Second layer: cron-job.org

Because of the scheduler delays, the real timing is now handled by **[cron-job.org](https://cron-job.org)**, a free external scheduler. At each planned time it sends an HTTP request to GitHub's API that starts the workflow immediately (`workflow_dispatch` with `checkin` or `checkout`). In testing, these runs started on time.

- It follows the **Europe/Brussels** timezone, so there are no daylight saving edits for these jobs.
- The GitHub schedule is kept as a backup. **Running both is safe:** the script always inspects the attendance page first and only acts when needed. If the action is already done (for example, a check-in when the "Check out" link is showing), or there is nothing to do (for example, a check-out when you are not checked in), it logs the status and exits successfully. The workflow's `concurrency` setting also queues runs one after the other instead of running them at the same time.
- Setting it up is described in the [guide at the end of this README](#guide-setting-up-cron-joborg).

## Usage

### Automatic

Runs start by themselves, from cron-job.org and from GitHub's scheduler, once `attendance.yml` is on the default branch. Check the **Actions** tab to see results. Runs show their trigger: `workflow_dispatch` (manual or cron-job.org) or `schedule` (GitHub's scheduler, possibly skipped as too late).

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
- Skips if the **schedule** run is more than **20 minutes late**. Manual runs (including those triggered by cron-job.org) go through regardless of time.  
- Picks the location from the weekday (`CAMPUS_DAYS`).  
- Wait between 0 and 6 minutes, at random, before acting to better match human behavior.  
- **Always inspects the attendance page status before acting.** It reads today's rows of the attendance table (date and time range, status cell) and only looks for the `Check in` / `Check out` link in those rows.
- If the action is already done (for example, checking in when already checked in), it logs "nothing to do" and exits successfully. This is what makes duplicate runs from the two triggers harmless.
- A **check-out** with nothing to check out of is not an error. A **check-in** fails (on purpose) if a session has already started, still shows `?`, and no `Check in` link is available, so a missed check-in shows up as a failed run.
- After a click it reloads the page and verifies that the status really changed.
- Verifies that the login form is filled before submitting. A rejected login fails the run with Moodle's error message and is **not** retried, to avoid locking the account.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Unknown schedule '…'` | A cron line was changed without updating the `case` block in the workflow |
| Scheduled run shows `Skipped …: run started N min after its cron time` | Expected: GitHub's scheduler started the run too late, and the guardrail skipped it. The cron-job.org layer handles the real timing |
| `Login was not accepted: …` | Wrong credentials in the secrets, or Moodle is blocking the login. Check the message in the log |
| `Attendance table not found …` / `Could not read any session …` | The page layout, link texts or date format changed. Check the debug screenshot, then adjust the selectors/parsing in `main.py` |
| `Could not checkin: the session starting at … is still '?'` | No `Check in` link was available at run time (window not open yet, or missed). Check the run's schedule and the session's window |
| No runs happening | Workflow disabled, not on the default branch, or (public repos) disabled after 60 days without repository activity |
| cron-job.org job shows HTTP `401` | Token wrong, expired or revoked: create a new one and update the job headers |
| cron-job.org job shows HTTP `403` or `404` | Token lacks **Actions: Read and write** or access to this repository, or the owner / repo / workflow file name in the URL is wrong |
| cron-job.org job shows HTTP `422` | Invalid body: check the branch name in `ref` and that `action` is exactly `checkin` or `checkout` |

A successful call returns HTTP `204` (no content). On failure of a run, download the **debug-screenshot** artifact from the bottom of the workflow run page.

## Security notes

- Credentials are stored only as GitHub Secrets. GitHub masks them in logs, and the script never prints them.
- In a public repository, logs and artifacts are visible to others. A private repository is safer.
- Failed logins count as login attempts on your Moodle account. Avoid repeated test runs when something is broken.
- The cron-job.org jobs use a **fine-grained GitHub token** limited to this repository and the *Actions* permission, with an expiry date. It is stored in the job headers at cron-job.org, so enable two-factor authentication on both accounts, and never paste the token in code, issues, chats or screenshots. If it leaks, revoke it immediately.

## Stopping the automation

To stop it without deleting the project:

1. Disable or delete the four jobs on **cron-job.org**.
2. Revoke the token: GitHub → **Settings → Developer settings → Personal access tokens → Fine-grained tokens** → delete it.
3. Go to **Actions → Moodle attendance → ⋯ → Disable workflow** (or remove the `schedule:` block from `attendance.yml`).
4. Delete the `MOODLE_LOGIN` and `MOODLE_PASSWORD` secrets under **Settings → Secrets and variables → Actions**.

The code and history stay in the repository as a reference.

## Guide: setting up cron-job.org

Menu labels may differ slightly from the current cron-job.org and GitHub interfaces.

### Part A: GitHub token

1. Note three things: your GitHub username (`OWNER` below), your repository name (`REPO`), and the default branch (probably `main`). The workflow file is `attendance.yml`.
2. On GitHub, click your profile picture → **Settings** → **Developer settings** (bottom of the left menu) → **Personal access tokens** → **Fine-grained tokens** → **Generate new token**.
3. Set:
   - **Token name:** `cron-job-attendance`
   - **Expiration:** long enough to cover your use   
   - **Repository access:** *Only select repositories* → pick this repository
   - **Permissions → Repository permissions → Actions: Read and write** (leave everything else as is; "Metadata: read-only" is added automatically)
4. Click **Generate token** and **copy it immediately**: GitHub shows it only once.
5. *(Optional but recommended)* Test the token from a terminal. This starts a real run, so do it only when it is safe for that action (for a `checkout`, when you are **not** checked in):

```bash
curl -i -X POST \
  -H "Accept: application/vnd.github+json" \
  -H "Authorization: Bearer YOUR_TOKEN" \
  -H "X-GitHub-Api-Version: 2022-11-28" \
  https://api.github.com/repos/OWNER/REPO/actions/workflows/attendance.yml/dispatches \
  -d '{"ref":"main","inputs":{"action":"checkout"}}'
```

Success is `HTTP/2 204` with no body, and a new `workflow_dispatch` run appears in the **Actions** tab.

### Part B: cron-job.org jobs

You need **four jobs**, one per time, because each action has its own request body and the minutes differ per time. Build the first one, test it, then use **Clone** for the others.

1. Create an account on [cron-job.org](https://cron-job.org), log in and open the console, then click **Create cronjob**.
2. **Common settings:**
   - **Title:** for example `Attendance check-in morning`
   - **URL:** `https://api.github.com/repos/OWNER/REPO/actions/workflows/attendance.yml/dispatches`  
   - **Enable job:** toggled ON  
   - **Execution schedule:** choose the *Custom* option: days of the week Monday to Friday, plus the hour and minute you want
   - **Timezone:** `Europe/Brussels` (this is in your account settings; make sure it is set)  
3. **Notifications:**  
   - Select notifications by email on failed executions, so an expired token doesn't go unnoticed  
4. **Advanced settings** :
   - **Request method:** `POST`
   - **Headers:**

| Header | Value |
|---|---|
| `Accept` | `application/vnd.github+json` |
| `Authorization` | `Bearer YOUR_TOKEN` |
| `X-GitHub-Api-Version` | `2022-11-28` |
| `Content-Type` | `application/json` |

   - **Request body:** `{"ref":"main","inputs":{"action":"checkin"}}`
5. **Test it** with the **Test run** button, at a safe moment for that action. The response should be status `204`. Then check the **Actions** tab for a new `workflow_dispatch` run and read its log.
5. **Create the other three** with **Clone**, changing the title, the time and the `action` in the body:

| Job | Time (Brussels) | `action` in the body |
|---|---|---|
| Check-in | 08:52 | `checkin` |
| Check-out | 12:33 | `checkout` |
| Check-in | 13:22 | `checkin` |
| Check-out | 17:03 | `checkout` |

Use the times that fit your own sessions. cron-job.org follows *your* time by itself, but the cron lines in `attendance.yml` stay in UTC, so remember to shift those when the clocks change.

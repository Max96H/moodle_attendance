import argparse
import os
import random
import re
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.common.exceptions import NoSuchElementException, StaleElementReferenceException, TimeoutException
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import Select, WebDriverWait


# ::::::::::::::::::SETUP::::::::::::::::::::
# GitHub runners use UTC, so always compute date/weekday in your own timezone.
TIMEZONE = ZoneInfo("Europe/Brussels")

# Days the script should not run (YYYY-MM-DD). Update this list regularly!
HOLIDAYS = [
    '2026-10-19', '2026-10-20', '2026-10-21', '2026-10-22', '2026-10-23', 
    '2026-07-13', '2026-07-14', '2026-07-15', '2026-07-16','2026-07-17', 
    '2026-07-21', '2026-11-11'
]

# Days you attend from campus (0 = Monday, 1 = Tuesday, ...). Other days = at home.
CAMPUS_DAYS = [1, 3]

URL_ATTENDANCE = 'https://moodle.becode.org/mod/attendance/view.php?id=1491'
TIMEOUT = 20  # seconds to wait for page elements

# What each action does on the attendance page.
# The page has a table with one row per half-day session; its "statuscol" cell shows
# "Checked out" (past), "?" (future), a "Check in" link (check-in window open) or a
# "Check out" link (while checked in).
# fail_if_no_link: what to do when today's rows offer neither link.
#   checkin  -> True : a session that already started but is still '?' = missed -> failed run
#   checkout -> False: nothing to check out of -> fine
ACTIONS = {
    "checkin":  {"link_text": "Check in",  "form_required": True,  "fail_if_no_link": True},
    "checkout": {"link_text": "Check out", "form_required": False, "fail_if_no_link": False},
}
# ::::::::::::::::::END SETUP::::::::::::::::::::
 
 
def get_credentials():
    """Reads the login and password from environment variables
    (set from GitHub Secrets in the workflow). Never stored in the repo."""
    # Strip stray whitespace/newlines that can sneak in when pasting a secret
    login = (os.environ.get("MOODLE_LOGIN") or "").strip()
    password = (os.environ.get("MOODLE_PASSWORD") or "").strip("\r\n")
    if not login or not password:
        print("ERROR: MOODLE_LOGIN and/or MOODLE_PASSWORD are not set.")
        sys.exit(1)
    return login, password
 
 
def build_driver():
    """Headless Chrome, configured to run on a GitHub Actions Linux runner."""
    options = Options()
    options.add_argument("--headless=new")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    return webdriver.Chrome(options=options)
 
 
def type_into(driver, element_id, text, tries=5):
    """Clears and fills a field, re-locating it on every try so that a page
    re-render (StaleElementReferenceException) doesn't break the run."""
    for _ in range(tries):
        try:
            field = WebDriverWait(driver, TIMEOUT).until(
                EC.element_to_be_clickable((By.ID, element_id))
            )
            field.clear()
            field.send_keys(text)
            return
        except StaleElementReferenceException:
            time.sleep(1)
    raise RuntimeError(f"Could not fill in the '{element_id}' field.")
 
 
def login_handling(driver):
    """Fills in the login form and waits until we're past the login page."""
    login, password = get_credentials()
    wait = WebDriverWait(driver, TIMEOUT)
 
    # The login page can re-render itself while loading (the old element then
    # goes "stale"), so elements are re-located for every action, the page is
    # given time to settle, and both fields are verified before submitting.
    for attempt in range(1, 4):
        try:
            wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            time.sleep(1)  # let page scripts finish
            type_into(driver, "username", login)
            type_into(driver, "password", password)
            time.sleep(0.5)
            if (driver.find_element(By.ID, "username").get_attribute("value") == login
                    and driver.find_element(By.ID, "password").get_attribute("value") == password):
                break
        except StaleElementReferenceException:
            pass
        print(f"Login form not filled correctly (attempt {attempt}), reloading...")
        driver.refresh()
    else:
        raise RuntimeError("Could not fill in the login form.")
 
    driver.find_element(By.ID, "password").send_keys(Keys.RETURN)
 
    # A rejected login keeps us on the login page. We do NOT retry the submit:
    # repeated bad logins can lock the account.
    try:
        wait.until(lambda d: 'login' not in d.current_url)
    except TimeoutException:
        error = driver.find_elements(By.ID, "loginerrormessage")
        message = error[0].text if error else "no error message found on the page"
        raise RuntimeError(f"Login was not accepted: {message}")
 
 
def fill_and_save_form(driver, location, form_required):
    """Selects the location and saves, if the form is shown.
 
    If form_required is False and no form appears shortly after the click,
    we assume the click alone was enough.
    """
    wait_time = TIMEOUT if form_required else 5
    try:
        select_element = WebDriverWait(driver, wait_time).until(
            EC.presence_of_element_located((By.ID, "id_location"))
        )
    except TimeoutException:
        if form_required:
            raise
        print("No location form shown; assuming the click was enough.")
        return
 
    Select(select_element).select_by_value(location)
    save_button = WebDriverWait(driver, TIMEOUT).until(
        EC.element_to_be_clickable((By.ID, "id_submitbutton"))
    )
    save_button.click()
    WebDriverWait(driver, TIMEOUT).until(EC.staleness_of(save_button))
 
 
MONTHS = {m: i for i, m in enumerate(
    ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], 1)}
DATE_RE = re.compile(r"(\d{1,2})\s+([A-Za-z]{3})\w*\s+(\d{4})")
TIME_RE = re.compile(r"(\d{1,2})(?::(\d{2}))?\s*([AaPp][Mm])")
 
 
def parse_session_start(text):
    """'Thu 5 Nov 2026 1:30PM - 5PM' -> datetime(2026, 11, 5, 13, 30), or None."""
    date_match = DATE_RE.search(text)
    if not date_match:
        return None
    month = MONTHS.get(date_match.group(2).title())
    if not month:
        return None
    hour, minute = 0, 0
    time_match = TIME_RE.search(text[date_match.end():])
    if time_match:
        hour = int(time_match.group(1)) % 12 + (12 if time_match.group(3).upper() == "PM" else 0)
        minute = int(time_match.group(2) or 0)
    return datetime(int(date_match.group(3)), month, int(date_match.group(1)),
                    hour, minute, tzinfo=TIMEZONE)
 
 
def open_attendance_page(driver):
    """Opens the attendance page (logging in if needed) and waits for its table."""
    driver.get(URL_ATTENDANCE)
    if 'login' in driver.current_url:
        login_handling(driver)
        # After login Moodle may not return us to the attendance page
        if 'attendance' not in driver.current_url:
            driver.get(URL_ATTENDANCE)
    try:
        WebDriverWait(driver, TIMEOUT).until(
            EC.presence_of_element_located((By.CSS_SELECTOR, "td.statuscol"))
        )
    except TimeoutException:
        print(f"Attendance table not found. URL: {driver.current_url} | title: {driver.title}")
        raise
 
 
def get_sessions(driver):
    """Reads the attendance table: one dict per row with start time, status text and row element."""
    sessions = []
    for row in driver.find_elements(By.XPATH, "//tr[td[contains(@class, 'statuscol')]]"):
        try:
            date_text = row.find_element(By.CSS_SELECTOR, "td.datecol").get_attribute("textContent")
            status_text = row.find_element(By.CSS_SELECTOR, "td.statuscol").get_attribute("textContent")
        except NoSuchElementException:
            continue
        start = parse_session_start(" ".join((date_text or "").split()))
        if start is None:
            continue
        sessions.append({"start": start, "status": " ".join((status_text or "").split()), "row": row})
    return sessions
 
 
def find_links(row, link_text):
    """Finds an attendance link (e.g. 'Check in') inside a row's status cell."""
    return row.find_elements(
        By.XPATH,
        f".//td[contains(@class, 'statuscol')]//a[contains(normalize-space(.), '{link_text}')]",
    )
 
 
def today_sessions(driver, now):
    return [s for s in get_sessions(driver) if s["start"].date() == now.date()]
 
 
def verify_done(driver, action, now):
    """Reloads the page and checks that the action really took effect."""
    open_attendance_page(driver)
    out_text = ACTIONS["checkout"]["link_text"]
    check_out_visible = any(find_links(s["row"], out_text) for s in today_sessions(driver, now))
    if action == "checkin" and not check_out_visible:
        raise RuntimeError("Check-in was submitted, but no 'Check out' link appeared afterwards.")
    if action == "checkout" and check_out_visible:
        raise RuntimeError("Check-out was clicked, but the 'Check out' link is still there.")
 
 
def run_action(driver, action, location, now):
    cfg = ACTIONS[action]
    other = ACTIONS["checkout" if action == "checkin" else "checkin"]
 
    open_attendance_page(driver)
 
    sessions = get_sessions(driver)
    if not sessions:
        raise RuntimeError(
            "Could not read any session from the attendance table "
            "(layout or date format changed?)."
        )
    today = [s for s in sessions if s["start"].date() == now.date()]
    if not today:
        print(f"No session listed for {now:%Y-%m-%d}, nothing to do.")
        return
    print("Today's sessions: " + ", ".join(f"{s['start']:%H:%M} -> {s['status']}" for s in today))
 
    # 1) The link we need is in one of today's rows: click it, then verify the result.
    for session in today:
        links = find_links(session["row"], cfg["link_text"])
        if links:
            links[0].click()
            fill_and_save_form(driver, location, cfg["form_required"])
            verify_done(driver, action, now)
            return
 
    # 2) The opposite link is there: the action is already done.
    if any(find_links(s["row"], other["link_text"]) for s in today):
        print(f"No '{cfg['link_text']}' link, but '{other['link_text']}' is shown: "
              f"the {action} looks already done, nothing to do.")
        return
 
    # 3) Neither link. A session that has already started but still shows '?' is a
    #    real problem for a check-in (missed or window not open); anything else is fine.
    pending = [s for s in today if s["start"] <= now and s["status"] == "?"]
    if cfg["fail_if_no_link"] and pending:
        raise RuntimeError(
            f"Could not {action}: the session starting at {pending[0]['start']:%H:%M} "
            f"is still '?' and no '{cfg['link_text']}' link is available."
        )
    print("Nothing to do.")
 
 
def main():
    parser = argparse.ArgumentParser(description="Moodle attendance check-in / check-out")
    parser.add_argument("action", choices=ACTIONS.keys(), help="What to do")
    args = parser.parse_args()
 
    now = datetime.now(TIMEZONE)
    today = now.strftime('%Y-%m-%d')
 
    if today in HOLIDAYS:
        print(f"{today} is a holiday, skipping.")
        return
    if now.weekday() >= 5:
        print(f"{today} is a weekend, skipping.")
        return
 
    location = "oncampus" if now.weekday() in CAMPUS_DAYS else "athome"
    print(f"{args.action} on {now:%Y-%m-%d %H:%M} ({TIMEZONE}), location: {location}")

    minutes_wait = random.randint(0, 6)
    print(f"Time delay of : {minutes_wait} minute(s).")
    time.sleep(minutes_wait * 60)
    driver = build_driver()
    try:
        run_action(driver, args.action, location, now)
        print(f"{args.action} done.")
    except Exception:
        # Screenshot is uploaded as an artifact by the workflow to help debugging
        driver.save_screenshot("debug.png")
        raise
    finally:
        driver.quit()
 
 
if __name__ == "__main__":
    main()

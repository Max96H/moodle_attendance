import argparse
import os
import sys
import time
from datetime import datetime
from zoneinfo import ZoneInfo

from selenium import webdriver
from selenium.common.exceptions import StaleElementReferenceException, TimeoutException
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

# What each action clicks on the attendance page.
# NOTE: the check-out flow is an assumption (see README/notes): we click the
# "Check out" link and, if a form with a location dropdown shows up, fill it in.
ACTIONS = {
    "checkin":  {"link_text": "Check in",  "form_required": True},
    "checkout": {"link_text": "Check out", "form_required": False},
}
# ::::::::::::::::::END SETUP::::::::::::::::::::


def get_credentials():
    """Reads the login and password from environment variables
    (set from GitHub Secrets in the workflow). Never stored in the repo."""
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


def run_action(driver, action, location):
    cfg = ACTIONS[action]
    wait = WebDriverWait(driver, TIMEOUT)

    driver.get(URL_ATTENDANCE)
    if 'login' in driver.current_url:
        login_handling(driver)
        # After login Moodle may not return us to the attendance page
        if 'attendance' not in driver.current_url:
            driver.get(URL_ATTENDANCE)

    other = ACTIONS["checkout" if action == "checkin" else "checkin"]
    wanted = f"//a[contains(text(), '{cfg['link_text']}')]"
    opposite = f"//a[contains(text(), '{other['link_text']}')]"
 
    # Wait for either link, so "already done" can be told apart from "page broken"
    try:
        wait.until(EC.presence_of_element_located((By.XPATH, f"{wanted} | {opposite}")))
    except TimeoutException:
        links = [a.text.strip() for a in driver.find_elements(By.TAG_NAME, "a")
                 if "check" in a.text.lower()]
        print(f"Neither link found. URL: {driver.current_url} | "
              f"title: {driver.title} | links containing 'check': {links}")
        raise
 
    if not driver.find_elements(By.XPATH, wanted):
        print(f"No '{cfg['link_text']}' link, but '{other['link_text']}' is shown: "
              f"the {action} looks already done, nothing to do.")
        return
 
    link = wait.until(EC.element_to_be_clickable((By.XPATH, wanted)))
    link.click()
    fill_and_save_form(driver, location, cfg["form_required"])


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

    driver = build_driver()
    try:
        run_action(driver, args.action, location)
        print(f"{args.action} done.")
    except Exception:
        # Screenshot is uploaded as an artifact by the workflow to help debugging
        driver.save_screenshot("debug.png")
        raise
    finally:
        driver.quit()


if __name__ == "__main__":
    main()
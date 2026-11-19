"""GrabCAD scraper — driver creation moved inside a function (brief #3).

Changes vs the recovered original:
- NO module-level side effect: importing this module no longer launches a
  browser (the original ran `driver = uc.Chrome(...)` at import).
- `create_driver(headless=True)` builds the driver on demand.
- Login credentials come from the environment (.env, never committed);
  login() raises a clear error when they are absent instead of failing
  obscurely.

GRABCAD LOGIN IS DEFERRED (brief #3 / owner decision): no live GrabCAD pull
is attempted in this build, and no login is performed. If a live pull is
wanted later, the owner does the login step himself (HUMAN STEP) or
authorizes a browser-agent session. The functions below are the ready
path for that step — they are not called by the default runner.
"""
from __future__ import annotations

import logging
import os
import time

logger = logging.getLogger(__name__)

LOGIN_URL = "https://grabcad.com/login"
LIBRARY_URL = "https://grabcad.com/library"

# Selectors from the recovered code — NOT live-verified (login deferred,
# no live GrabCAD attempt in this build). See SELECTORS.md.
SORT_BUTTON_SELECTOR = "button[data-sort='recent']"
MODEL_LINK_SELECTOR = "a.modelLink"
DOWNLOAD_BUTTON_SELECTOR = "a.download"


def load_credentials() -> tuple[str | None, str | None]:
    """Read GrabCAD credentials from the environment (via .env if present).
    Returns (username, password); either may be None — never hard-coded."""
    from dotenv import load_dotenv

    load_dotenv()
    return os.getenv("GRABCAD_USERNAME"), os.getenv("GRABCAD_PASSWORD")


def create_driver(headless: bool = True):
    """Build the undetected-Chrome driver on demand (lazy import)."""
    import undetected_chromedriver as uc

    options = uc.ChromeOptions()
    if headless:
        options.add_argument("--headless=new")
    return uc.Chrome(options=options)


def login(driver, username: str | None = None, password: str | None = None):
    """Log into GrabCAD with the given (or env) credentials.

    Raises RuntimeError when credentials are absent — login is a human /
    authorized-browser step, never attempted silently.
    """
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    username = username or load_credentials()[0]
    password = password or load_credentials()[1]
    if not username or not password:
        raise RuntimeError(
            "GrabCAD credentials not set (GRABCAD_USERNAME / GRABCAD_PASSWORD). "
            "Login is deferred: the owner performs it or authorizes a "
            "browser-agent session.")
    try:
        driver.get(LOGIN_URL)
        WebDriverWait(driver, 10).until(
            EC.presence_of_element_located((By.NAME, "email")))
        driver.find_element(By.NAME, "email").send_keys(username)
        driver.find_element(By.NAME, "password").send_keys(password)
        driver.find_element(By.CSS_SELECTOR, "button[type='submit']").click()
        WebDriverWait(driver, 10).until(EC.url_changes(LOGIN_URL))
        logging.info("Successfully logged in")
    except Exception as exc:
        logging.error("Login failed: %s", exc)
        raise


def scrape_models(driver, limit: int = 5) -> list[str]:
    """Scrape model links from the GrabCAD library (driver must be logged in)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    driver.get(LIBRARY_URL)
    try:
        sort_button = WebDriverWait(driver, 10).until(
            EC.element_to_be_clickable((By.CSS_SELECTOR, SORT_BUTTON_SELECTOR)))
        sort_button.click()
        time.sleep(3)
        logging.info("Sorting applied successfully")
    except Exception as exc:
        logging.warning("Could not apply sorting: %s", exc)
    models = driver.find_elements(By.CSS_SELECTOR, MODEL_LINK_SELECTOR)
    model_links = [m.get_attribute("href") for m in models[:limit]]
    logging.info("Scraped %d model links", len(model_links))
    return model_links


def download_models(driver, model_links: list[str]):
    """Download each model file (driver must be logged in)."""
    from selenium.webdriver.common.by import By
    from selenium.webdriver.support import expected_conditions as EC
    from selenium.webdriver.support.ui import WebDriverWait

    for link in model_links:
        try:
            driver.get(link)
            download_button = WebDriverWait(driver, 10).until(
                EC.element_to_be_clickable((By.CSS_SELECTOR, DOWNLOAD_BUTTON_SELECTOR)))
            download_button.click()
            logging.info("Download started for %s", link)
        except Exception as exc:
            logging.error("Could not download from %s: %s", link, exc)


if __name__ == "__main__":
    # Deliberately NOT executed: login is deferred (see module docstring).
    raise SystemExit(
        "GrabCAD login is deferred — run only after the owner performs the "
        "login step or authorizes a browser-agent session.")

"""
Selenium login helper for HomeSource export tools.

Drives the tenant /login page and submits credentials. Callers wait for the
Laravel session cookie (see homesource_common.LOGIN_SESSION_COOKIE_NAME)
before harvesting cookies into requests.
"""

from __future__ import annotations

from selenium.webdriver.common.by import By
from selenium.webdriver.remote.webdriver import WebDriver
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.support.ui import WebDriverWait

# CSS selector for the primary login button on the HomeSource login page.
LOGIN_BUTTON_CSS = "button.btn.btn-danger.login-btn"

LOGIN_FIELD_TIMEOUT_SECONDS = 10
LOGIN_BUTTON_TIMEOUT_SECONDS = 10


def login(driver: WebDriver, username: str, password: str, base_url: str) -> None:
    """
    Open {base_url}/login, fill email/password, and click Sign in.

    Does not wait for post-login navigation; callers should wait until the
    session cookie appears or the URL leaves /login.
    """
    login_url = f"{base_url.rstrip('/')}/login"
    driver.get(login_url)

    wait = WebDriverWait(driver, LOGIN_FIELD_TIMEOUT_SECONDS)

    email_input = wait.until(EC.presence_of_element_located((By.NAME, "email")))
    email_input.clear()
    email_input.send_keys(username)

    password_input = driver.find_element(By.NAME, "password")
    password_input.clear()
    password_input.send_keys(password)

    login_button = WebDriverWait(driver, LOGIN_BUTTON_TIMEOUT_SECONDS).until(
        EC.element_to_be_clickable((By.CSS_SELECTOR, LOGIN_BUTTON_CSS))
    )
    login_button.click()

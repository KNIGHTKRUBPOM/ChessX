
"""Chromium account journey against the isolated Supabase and Mailpit containers."""

import base64
from hashlib import sha1
import hmac
import json
import os
from pathlib import Path
import re
import struct
import time
from urllib.parse import urlencode, urlsplit
from urllib.request import ProxyHandler, build_opener
from uuid import uuid4

from playwright.sync_api import expect, sync_playwright


def loopback(name):
    value = os.environ[name].rstrip("/")
    url = urlsplit(value)
    if url.scheme != "http" or url.hostname not in ("localhost", "127.0.0.1", "::1") or url.username:
        raise RuntimeError("E2E requires loopback-only services")
    return value


APP = loopback("APP_ORIGIN")
MAIL = loopback("CHESS_QA_LOCAL_MAIL_URL")
HTTP = build_opener(ProxyHandler({}))
PASSWORD = "Local-QA:01-x1"
NEW_PASSWORD = "Local-QA:02-x2"
CHROME = Path(r"C:\Program Files\Google\Chrome\Application\chrome.exe")
OUTPUT = Path("test-results") / "local-auth"


def mail_api(path):
    with HTTP.open(MAIL + path, timeout=4) as response:
        return json.load(response)


def await_code(email, subject):
    query = urlencode({"query": "to:" + email, "limit": 20})
    for _ in range(40):
        messages = mail_api("/api/v1/search?" + query).get("messages") or []
        for message in messages:
            if subject not in message.get("Subject", ""):
                continue
            full = mail_api("/api/v1/message/" + message["ID"])
            body = (full.get("Text") or "") + " " + (full.get("HTML") or "")
            match = re.search(r"(?<![0-9])[0-9]{6,10}(?![0-9])", body)
            if match:
                return match.group()
        time.sleep(0.5)
    raise AssertionError("Expected OTP was not delivered to local Mailpit")


def totp(secret):
    key = base64.b32decode(secret.upper() + "=" * (-len(secret) % 8))
    counter = struct.pack(">Q", int(time.time() // 30))
    code = hmac.new(key, counter, sha1).digest()
    offset = code[-1] & 15
    return f"{(struct.unpack('>I', code[offset:offset+4])[0] & 0x7fffffff) % 1_000_000:06d}"


def fill_email(page, email):
    page.locator("#account-email").fill(email)


def login(page, email, password):
    expect(page.locator("#account-password")).to_be_visible()
    fill_email(page, email)
    page.locator("#account-password").fill(password)
    page.locator("#account-submit").click()


def session(page):
    response = page.request.get(APP + "/api/account")
    expect(response).to_be_ok()
    return response.json()


def journey(page, context):
    address = "browser-" + uuid4().hex[:12] + "@chessx.example.test"
    page.goto(APP + "/", wait_until="networkidle")
    page.locator("#account-trigger").click()
    page.locator("#account-show-register").click()
    page.locator("#account-display-name").fill("ผู้เล่นทดสอบ")
    fill_email(page, address)
    page.locator("#account-password").fill(PASSWORD)
    page.locator("#account-submit").click()
    expect(page.locator("#account-code")).to_be_visible()
    page.locator("#account-code").fill(await_code(address, "รหัสยืนยันบัญชี"))
    page.locator("#account-submit").click()
    expect(page.locator("#account-password")).to_be_visible()
    login(page, address, PASSWORD)
    expect(page.locator("#account-logout")).to_be_visible()
    assert session(page)["user"]["email"] == address
    auth_cookies = [item for item in context.cookies() if "chessmess" in item["name"]]
    assert auth_cookies and all(item["httpOnly"] for item in auth_cookies), "Account cookies must be HttpOnly"

    page.locator("#account-close").click()
    page.locator("input[name=mode][value=chess]").check()
    page.get_by_role("button", name="Play", exact=True).click()
    page.locator("#board canvas").wait_for(state="visible")
    page.locator("#account-trigger").click()
    page.locator("#account-logout").click()
    expect(page.locator("#account-password")).to_be_visible()
    assert session(page)["user"] is None

    page.locator("#account-show-recover").click()
    fill_email(page, address)
    page.locator("#account-submit").click()
    expect(page.locator("#account-code")).to_be_visible()
    page.locator("#account-code").fill(await_code(address, "รหัสตั้งรหัสผ่านใหม่"))
    page.locator("#account-submit").click()
    recovery_form = page.locator("#security-form")
    expect(recovery_form.locator('input[name="password"]')).to_be_visible()
    recovery_form.locator('input[name="password"]').fill(NEW_PASSWORD)
    recovery_form.get_by_role("button", name="ยืนยัน").click()
    expect(page.locator("#account-password")).to_be_visible()
    login(page, address, NEW_PASSWORD)
    expect(page.locator("#account-settings")).to_be_visible()

    page.locator("#account-settings").click()
    page.get_by_role("button", name="เพิ่ม Authenticator", exact=True).click()
    secret = page.locator("#security-enrollment code").inner_text()
    recovery_form.locator('input[name="code"]').fill(totp(secret))
    recovery_form.get_by_role("button", name="ยืนยัน").click()
    expect(page.locator("#security-level")).to_contain_text("ยืนยันสองขั้นตอนแล้ว")
    page.get_by_role("dialog", name="ตั้งค่าบัญชี").get_by_role("button", name="ปิด", exact=True).click()
    page.locator("#account-logout").click()
    expect(page.locator("#account-password")).to_be_visible()

    login(page, address, NEW_PASSWORD)
    expect(recovery_form.locator('input[name="code"]')).to_be_visible()
    # Use a fresh TOTP window after the verification used to activate the factor.
    time.sleep(31 - (time.time() % 30))
    recovery_form.locator('input[name="code"]').fill(totp(secret))
    recovery_form.get_by_role("button", name="ยืนยัน").click()
    expect(page.locator("#security-level")).to_contain_text("ยืนยันสองขั้นตอนแล้ว")
    page.get_by_role("button", name="ลบบัญชี", exact=True).click()
    recovery_form.locator('input[name="confirmation"]').fill("DELETE")
    recovery_form.get_by_role("button", name="ยืนยัน").click()
    expect(page.locator("#account-password")).to_be_visible()
    assert session(page)["user"] is None


def main():
    with sync_playwright() as playwright:
        executable = os.environ.get("CHESS_QA_CHROME") or (str(CHROME) if CHROME.is_file() else None)
        browser = playwright.chromium.launch(executable_path=executable, headless=True, args=[
            "--disable-background-networking", "--disable-component-update", "--disable-sync", "--no-first-run",
        ])
        try:
            context = browser.new_context(viewport={"width": 375, "height": 850})
            context.route("**/*", lambda route: route.continue_() if route.request.url.startswith(APP + "/") else route.abort())
            page = context.new_page()
            page.set_default_timeout(10_000)
            try:
                journey(page, context)
            except Exception:
                OUTPUT.mkdir(parents=True, exist_ok=True)
                page.screenshot(path=str(OUTPUT / "failure.png"), mask=[
                    page.locator("#account-form"), page.locator("#security-form"), page.locator("#security-enrollment"),
                    page.locator("#account-user-email"), page.locator("#account-user-name"), page.locator("#account-trigger"),
                ])
                raise
        finally:
            browser.close()
    print("PASS local Chromium signup, OTP, play, logout, recovery, TOTP and delete")


if __name__ == "__main__":
    main()

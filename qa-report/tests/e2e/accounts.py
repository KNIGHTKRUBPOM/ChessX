"""Exercise account forms in Chromium using local, intercepted API responses."""

from tempfile import TemporaryDirectory
from urllib.parse import urlsplit

from playwright.sync_api import expect, sync_playwright

from run_qa import E, record, report, server
from e2e.web import CHROME, args


EMAIL = "qa-player@example.test"
PASSWORD = "Test-password-123"
PROFILE = {"id": "qa-player", "email": EMAIL, "displayName": "ผู้เล่น QA"}


def account_contract(page, url):
    verified = False
    signed_in = False
    requests = []

    def local_requests(route):
        nonlocal verified, signed_in
        request = route.request
        if not request.url.startswith(url + "/"):
            route.abort()
            return
        path = urlsplit(request.url).path
        if not path.startswith("/api/account"):
            route.continue_()
            return
        if path == "/api/account" and request.method == "GET":
            route.fulfill(json={"enabled": True, "user": PROFILE if signed_in else None})
            return
        if request.method != "POST":
            route.fulfill(status=405, json={"detail": "method_not_allowed"})
            return

        data = request.post_data_json
        requests.append((path, data))
        if path == "/api/account/register":
            route.fulfill(status=202, json={"confirmationRequired": True})
        elif path == "/api/account/confirm":
            verified = data.get("code") == "112233"
            if verified:
                route.fulfill(status=204)
            else:
                route.fulfill(status=400, json={"detail": "invalid_code"})
        elif path == "/api/account/login":
            valid = data.get("password") == PASSWORD
            if verified and valid:
                signed_in = True
                route.fulfill(json={"enabled": True, "user": PROFILE})
            else:
                route.fulfill(status=401, json={"detail": "invalid_credentials"})
        elif path == "/api/account/logout":
            signed_in = False
            route.fulfill(status=204)
        else:
            route.fulfill(status=404)

    page.route("**/*", local_requests)
    page.goto(url + "/", wait_until="networkidle")
    trigger = page.locator("#account-trigger")
    dialog = page.locator("#account-dialog")
    email = page.locator("#account-email")
    password = page.locator("#account-password")
    name = page.locator("#account-display-name")
    code = page.locator("#account-code")
    submit = page.locator("#account-submit")
    status = page.locator("#account-status")
    signed_in_panel = page.locator("#account-signed-in")

    trigger.click()
    expect(dialog).to_be_visible()
    expect(email).to_be_focused()
    dialog_bounds = dialog.bounding_box()
    assert dialog_bounds and dialog_bounds["x"] >= 0
    assert dialog_bounds["x"] + dialog_bounds["width"] <= 375
    page.keyboard.press("Escape")
    expect(dialog).not_to_be_visible()
    expect(trigger).to_be_focused()
    trigger.click()

    page.locator("#account-show-register").click()
    expect(name).to_be_visible()
    name.fill(PROFILE["displayName"])
    email.fill(EMAIL)
    password.fill(PASSWORD)
    submit.click()
    expect(code).to_be_visible()
    expect(email).to_have_value(EMAIL)

    code.fill("000000")
    submit.click()
    expect(status).to_have_text("รหัสไม่ถูกต้องหรือหมดอายุ กรุณาตรวจรหัสอีกครั้ง")
    expect(code).to_be_visible()
    code.fill("112233")
    submit.click()
    expect(password).to_be_visible()
    expect(email).to_have_value(EMAIL)

    password.fill("wrong-password")
    submit.click()
    expect(status).to_contain_text("อีเมลหรือรหัสผ่านไม่ถูกต้อง")
    expect(password).to_be_visible()
    password.fill(PASSWORD)
    submit.click()
    expect(trigger).to_contain_text(PROFILE["displayName"])

    page.reload(wait_until="networkidle")
    expect(trigger).to_contain_text(PROFILE["displayName"])
    if not dialog.is_visible():
        trigger.click()
    expect(signed_in_panel).to_be_visible()
    page.locator("#account-logout").click()
    expect(trigger).to_contain_text("เข้าสู่ระบบ")
    assert [path.rsplit("/", 1)[1] for path, _ in requests] == [
        "register", "confirm", "confirm", "login", "login", "logout",
    ]
    assert requests[0][1] == {
        "email": EMAIL, "password": PASSWORD, "displayName": PROFILE["displayName"],
    }
    return "Register, verify, login, reload and logout succeeded through the account UI"


def guest_without_configuration(page, url):
    page.route("**/*", lambda route: route.continue_() if route.request.url.startswith(url + "/") else route.abort())
    page.goto(url + "/", wait_until="networkidle")
    response = page.request.get(url + "/api/account")
    assert response.json() == {"enabled": False, "user": None}
    page.locator('[name=mode][value=chess]').check()
    page.get_by_role("button", name="Play", exact=True).click()
    expect(page.locator("#board canvas")).to_be_visible()
    return "Local guest game starts while Supabase is disabled"


def suite():
    results = []
    with server("account-browser") as url, TemporaryDirectory(dir=E) as profile, sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            profile, headless=True, executable_path=CHROME, args=args,
            viewport={"width": 375, "height": 800},
        )
        try:
            page = context.new_page()
            page.set_default_timeout(6500)
            record("ACCOUNT-UI-FLOW", lambda: account_contract(page, url), results)
            if results[-1]["status"] != "PASS":
                page.screenshot(path=str(E / "account-browser-failure.png"), full_page=True)
            page.close()
            guest = context.new_page()
            guest.set_default_timeout(6500)
            record("ACCOUNT-UI-GUEST", lambda: guest_without_configuration(guest, url), results)
        finally:
            context.close()
    return report("account-browser", results)

"""Offline contract tests for the app's Supabase Auth adapter."""

from contextlib import contextmanager
import os
from unittest.mock import patch

from fastapi.testclient import TestClient

from run_qa import record, report


ORIGIN = "https://chessmess.example.test"
EMAIL = "qa-player@example.test"
PASSWORD = "Test-password-123"
DISPLAY_NAME = "ผู้เล่น QA"
PROVIDER_USER = {
    "id": "9c68fc6a-8972-4242-97af-14a8d4bffb20",
    "email": EMAIL,
    "user_metadata": {"display_name": DISPLAY_NAME, "unrelated_metadata": "private"},
}
PUBLIC_USER = {"id": PROVIDER_USER["id"], "email": EMAIL, "displayName": DISPLAY_NAME}
ACCOUNT_ENV = {
    "APP_ORIGIN": ORIGIN,
    "SUPABASE_URL": "https://offline-qa.supabase.co",
    "SUPABASE_PUBLISHABLE_KEY": "sb_publishable_offline_contract_fixture",
    "CHESS_ENV": "production",
}
REGISTER = {"email": EMAIL, "password": PASSWORD, "displayName": DISPLAY_NAME}
LOGIN = {"email": EMAIL, "password": PASSWORD}
ACCESS_COOKIE = "chessmess_access"
REFRESH_COOKIE = "chessmess_refresh"


def provider_session(revision):
    return {
        "access_token": f"fake-access-token-{revision}",
        "refresh_token": f"fake-refresh-token-{revision}",
        "expires_in": 3600,
        "user": PROVIDER_USER,
    }


@contextmanager
def app_client(upstream=None, *, env=None, base_url=ORIGIN):
    from backend import account
    from backend.app import app

    with patch.dict(os.environ, ACCOUNT_ENV if env is None else env):
        if upstream is None:
            upstream = AssertionError("Account handler called upstream unexpectedly")
        with patch.object(account, "_supabase_request", side_effect=upstream) as provider:
            with TestClient(app, base_url=base_url) as client:
                yield client, provider


def post(client, route, data):
    return client.post("/api/account/" + route, headers={"Origin": ORIGIN}, json=data)


def private_response(response):
    assert response.headers.get("cache-control") == "no-store"
    assert "fake-access-token-" not in response.text
    assert "fake-refresh-token-" not in response.text
    assert PASSWORD not in response.text


def cookie_flags(response):
    cookies = response.headers.get_list("set-cookie")
    assert len(cookies) == 2
    assert {value.split("=", 1)[0] for value in cookies} == {ACCESS_COOKIE, REFRESH_COOKIE}
    for value in cookies:
        parts = [part.strip().lower() for part in value.split(";")[1:]]
        assert {"secure", "httponly", "samesite=lax", "path=/api/account"} <= set(parts)


def disabled_config():
    disabled = dict(ACCOUNT_ENV, SUPABASE_URL="", SUPABASE_PUBLISHABLE_KEY="")
    with app_client(env=disabled) as (client, upstream):
        response = client.get("/api/account")
        assert response.status_code == 200
        assert response.json() == {"enabled": False, "user": None}
        private_response(response)
        response = post(client, "login", LOGIN)
        assert response.status_code == 503
        assert response.json() == {"detail": "auth_not_configured"}
        upstream.assert_not_called()
    return "Absent Supabase settings leave guest mode available"


def signup_and_verify():
    with app_client([
        (200, {"mailer_autoconfirm": False}),
        (200, PROVIDER_USER),
        (403, {"error_code": "otp_expired", "msg": "provider detail"}),
        (200, provider_session(1)),
    ]) as (client, upstream):
        response = post(client, "register", REGISTER)
        assert response.status_code == 202
        assert response.json() == {"confirmationRequired": True}
        private_response(response)
        assert not response.headers.get_list("set-cookie")

        response = post(client, "confirm", {"email": EMAIL, "code": "000000"})
        assert response.status_code == 400
        assert response.json() == {"detail": "invalid_code"}
        private_response(response)

        response = post(client, "confirm", {"email": EMAIL, "code": "112233"})
        assert response.status_code == 204
        assert not response.content and not response.headers.get_list("set-cookie")
        private_response(response)
        assert client.get("/api/account").json() == {"enabled": True, "user": None}

        settings, signup, invalid_otp, valid_otp = upstream.call_args_list
        assert settings.args[1:3] == ("GET", "/settings")
        assert signup.args[1:3] == ("POST", "/signup")
        signup_payload = signup.args[3] if len(signup.args) > 3 else signup.kwargs["payload"]
        assert signup_payload["data"]["display_name"] == DISPLAY_NAME
        for call, expected_code in [(invalid_otp, "000000"), (valid_otp, "112233")]:
            assert call.args[1:3] == ("POST", "/verify")
            payload = call.args[3] if len(call.args) > 3 else call.kwargs["payload"]
            assert payload == {"email": EMAIL, "token": expected_code, "type": "email"}
    return "Signup waits for OTP. Verification confirms email without signing in"


def reject_disabled_provider_confirmation():
    with app_client([(200, {"mailer_autoconfirm": True})]) as (client, upstream):
        response = post(client, "register", REGISTER)
        assert response.status_code == 503
        assert response.json() == {"detail": "auth_unavailable"}
        assert not response.headers.get_list("set-cookie")
        private_response(response)
        upstream.assert_called_once()
        assert upstream.call_args.args[1:3] == ("GET", "/settings")
    return "Provider settings are validated before creating an account"


def reject_unconfirmed_registration():
    with app_client([
        (200, {"mailer_autoconfirm": False}),
        (200, provider_session(1)),
    ]) as (client, upstream):
        response = post(client, "register", REGISTER)
        assert response.status_code == 503
        assert response.json() == {"detail": "auth_unavailable"}
        assert not response.headers.get_list("set-cookie")
        private_response(response)
        assert upstream.call_count == 2
    return "Instant provider session is discarded when confirmation is required"


def login_errors():
    with app_client([
        (400, {"error_code": "invalid_credentials", "msg": f"provider detail {EMAIL}"}),
        (400, {"error_code": "email_not_confirmed", "msg": f"provider detail {EMAIL}"}),
    ]) as (client, upstream):
        for status, detail in [(401, "invalid_credentials"), (403, "email_unconfirmed")]:
            response = post(client, "login", LOGIN)
            assert response.status_code == status
            assert response.json() == {"detail": detail}
            private_response(response)
            assert not response.headers.get_list("set-cookie")

        response = post(client, "login", {**LOGIN, "email": "invalid-email"})
        assert response.status_code == 422
        assert response.json() == {"detail": "invalid_input"}
        private_response(response)
        assert upstream.call_count == 2
    return "Credential, verification and validation errors are actionable and redacted"


def session_lifecycle():
    with app_client([
        (200, provider_session(1)),
        (200, PROVIDER_USER),
        (401, {"code": 401, "msg": "access expired"}),
        (200, provider_session(2)),
        (204, {}),
    ]) as (client, upstream):
        response = post(client, "login", LOGIN)
        assert response.status_code == 200
        assert response.json() == {"enabled": True, "user": PUBLIC_USER}
        private_response(response)
        cookie_flags(response)

        response = client.get("/api/account")
        assert response.status_code == 200
        assert response.json() == {"enabled": True, "user": PUBLIC_USER}
        private_response(response)

        response = client.get("/api/account")
        assert response.status_code == 200
        assert response.json() == {"enabled": True, "user": PUBLIC_USER}
        cookie_flags(response)
        assert client.cookies[ACCESS_COOKIE] == "fake-access-token-2"
        assert client.cookies[REFRESH_COOKIE] == "fake-refresh-token-2"

        response = post(client, "logout", {})
        assert response.status_code == 204
        assert not response.content
        assert not client.cookies
        private_response(response)
        assert client.get("/api/account").json() == {"enabled": True, "user": None}

        called_routes = [call.args[1:3] for call in upstream.call_args_list]
        assert called_routes == [
            ("POST", "/token?grant_type=password"),
            ("GET", "/user"),
            ("GET", "/user"),
            ("POST", "/token?grant_type=refresh_token"),
            ("POST", "/logout?scope=local"),
        ]
    return "Secure HttpOnly cookies survive status checks, rotate on refresh and clear on logout"


def origin_policy():
    with app_client() as (client, upstream):
        response = client.post("/api/account/login", json=LOGIN)
        assert response.status_code == 403
        assert response.json() == {"detail": "request_origin"}
        private_response(response)
        response = client.post(
            "/api/account/login", headers={"Origin": "https://unrelated.example.test"}, json=LOGIN,
        )
        assert response.status_code == 403
        assert response.json() == {"detail": "request_origin"}
        upstream.assert_not_called()
    return "Auth mutations require the configured same origin"


def suite():
    cases = [
        ("ACCOUNT-API-DISABLED", disabled_config),
        ("ACCOUNT-API-SIGNUP-VERIFY", signup_and_verify),
        ("ACCOUNT-API-REQUIRE-VERIFY", reject_disabled_provider_confirmation),
        ("ACCOUNT-API-UNCONFIRMED-SESSION", reject_unconfirmed_registration),
        ("ACCOUNT-API-LOGIN-ERRORS", login_errors),
        ("ACCOUNT-API-SESSION", session_lifecycle),
        ("ACCOUNT-API-ORIGIN", origin_policy),
    ]
    results = []
    for identifier, case in cases:
        record(identifier, case, results)
    return report("accounts", results)

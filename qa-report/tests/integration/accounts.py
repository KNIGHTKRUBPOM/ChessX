"""Offline contract tests for the app's Supabase Auth adapter."""

from contextlib import contextmanager
from base64 import urlsafe_b64encode
from hashlib import sha256
import json
import os
from time import time
from unittest.mock import patch
from urllib.parse import parse_qs, urlsplit

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
    "SUPABASE_SECRET_KEY": "",
    "AUTH_OAUTH_PROVIDERS": "",
    "AUTH_CAPTCHA_SITE_KEY": "",
    "CHESS_ACCOUNT_ENABLED": "1",
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
    from backend import account, account_security
    from backend.app import app

    with patch.dict(os.environ, ACCOUNT_ENV if env is None else env):
        if upstream is None:
            upstream = AssertionError("Account handler called upstream unexpectedly")
        with patch.object(account, "_supabase_request", side_effect=upstream) as provider:
            with patch.object(account_security, "_supabase_request", new=provider):
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
    active = [value for value in cookies if "max-age=0" not in value.lower()]
    assert len(active) == 2
    assert {value.split("=", 1)[0] for value in active} == {ACCESS_COOKIE, REFRESH_COOKIE}
    assert any(value.startswith(ACCESS_COOKIE + "=") and "max-age=0" in value.lower()
               and "path=/api/account" in value.lower() for value in cookies)
    for value in active:
        parts = [part.strip().lower() for part in value.split(";")[1:]]
        path = "/api" if value.startswith(ACCESS_COOKIE + "=") else "/api/account"
        assert {"secure", "httponly", "samesite=lax", "path=" + path} <= set(parts)


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


FACTOR_ID = "63159e11-7741-47c7-8b98-915337903192"
CHALLENGE_ID = "e90ea5c6-e2fb-4f3c-980a-b51c947b8ca1"
AUTH_CODE = "e34b63bb-f898-498f-a638-635edb4dbf42"
EMAIL_IDENTITY = "a231b9dc-ff3f-4bb9-aa1e-0d81e1a5f131"
GOOGLE_IDENTITY = "51ccd677-0523-44f6-bd3a-763a72d7129a"
VERIFIED_USER = {
    **PROVIDER_USER,
    "email_confirmed_at": "2026-11-01T00:00:00Z",
    "identities": [{"provider": "email", "identity_id": EMAIL_IDENTITY}],
}
TOTP_USER = {
    **VERIFIED_USER,
    "factors": [{"id": FACTOR_ID, "factor_type": "totp", "friendly_name": "QA key", "status": "verified"}],
}


def signed_provider_fixture(aal, method="password"):
    """Provider stub accepts only the test session used in each API case."""
    claims = {"sub": VERIFIED_USER["id"], "aal": aal, "amr": [{"method": method, "timestamp": int(time())}]}
    payload = urlsafe_b64encode(json.dumps(claims).encode()).rstrip(b"=").decode()
    return "fixture." + payload + ".provider-signature-fixture"


def lifecycle_session(user, aal="aal1", method="password"):
    return {
        "access_token": signed_provider_fixture(aal, method),
        "refresh_token": "provider-refresh-fixture",
        "expires_in": 3600,
        "user": user,
    }


def oauth_pkce():
    env = dict(ACCOUNT_ENV, AUTH_OAUTH_PROVIDERS="google, facebook, unsupported")
    with app_client([(200, lifecycle_session(VERIFIED_USER, method="oauth"))], env=env) as (client, upstream):
        assert client.get("/api/account/options").json() == {"providers": ["google", "facebook"], "captcha": None}
        response = post(client, "oauth", {"provider": "google"})
        assert response.status_code == 200
        private_response(response)
        destination = urlsplit(response.json()["url"])
        query = parse_qs(destination.query)
        assert destination.hostname == "offline-qa.supabase.co"
        assert destination.path == "/auth/v1/authorize"
        assert query["redirect_to"] == [ORIGIN + "/api/account/oauth/callback"]
        assert query["code_challenge_method"] == ["s256"]
        verifier = client.cookies["__Host-chessmess_oauth"].split(".")[0]
        assert verifier not in response.text
        assert query["code_challenge"] == [urlsafe_b64encode(sha256(verifier.encode()).digest()).rstrip(b"=").decode()]
        result = client.get("/api/account/oauth/callback", params={"code": AUTH_CODE}, follow_redirects=False)
        assert result.status_code == 303 and result.headers["location"] == "/?auth=oauth_ok"
        cookie_flags(result)
        assert "__Host-chessmess_oauth" not in client.cookies
        upstream.assert_called_once()
        assert upstream.call_args.args[2:] == (
            "/token?grant_type=pkce", {"auth_code": AUTH_CODE, "code_verifier": verifier},
        )
        assert client.get("/api/account/oauth/callback", follow_redirects=False).headers["location"] == "/?auth=oauth_failed"
        upstream.assert_called_once()
    return "Google OAuth fixes callback destination, exchanges server-side PKCE, and clears its flow cookie"


def verified_mfa_settings():
    upgraded = lifecycle_session(TOTP_USER, "aal2", "totp")
    with app_client([
        (200, TOTP_USER),
        (200, TOTP_USER),
        (200, TOTP_USER),
        (200, {"id": CHALLENGE_ID}),
        (200, upgraded),
        (200, TOTP_USER),
        (200, VERIFIED_USER),
    ]) as (client, upstream):
        client.cookies.set(ACCESS_COOKIE, signed_provider_fixture("aal1"), path="/api")
        security = client.get("/api/account/security")
        assert security.json()["mfaRequired"] is True
        assert security.json()["identities"] == []
        pending = post(client, "password", {"password": "New-password-123"})
        assert pending.status_code == 403 and pending.json()["detail"] == "mfa_required"
        completed = post(client, "mfa/verify", {"factorId": FACTOR_ID, "code": "332255"})
        assert completed.status_code == 200 and completed.json() == {"aal": "aal2"}
        cookie_flags(completed)
        change = post(client, "password", {"password": "New-password-123"})
        assert change.status_code == 204
        assert [record.args[2] for record in upstream.call_args_list] == [
            "/user", "/user", "/user", "/factors/" + FACTOR_ID + "/challenge",
            "/factors/" + FACTOR_ID + "/verify", "/user", "/user",
        ]
        assert upstream.call_args.args[1] == "PUT"
    return "Confirmed TOTP session gates password change and rotates to AAL2"


def recovery_isolated():
    with app_client([
        (200, {}),
        (404, {"error_code": "user_not_found"}),
        (200, lifecycle_session(VERIFIED_USER, method="otp")),
        (200, VERIFIED_USER),
        (200, VERIFIED_USER),
        (204, {}),
        (204, {}),
    ]) as (client, upstream):
        requested = post(client, "recover", {"email": EMAIL})
        unknown = post(client, "recover", {"email": "other@example.test"})
        assert requested.status_code == unknown.status_code == 202
        assert requested.json() == unknown.json() == {"confirmationRequired": True}
        recovery = post(client, "recover/confirm", {"email": EMAIL, "code": "123456"})
        assert recovery.status_code == 200 and recovery.json()["recovery"] is True
        assert not recovery.json()["identities"]
        assert ACCESS_COOKIE not in client.cookies and REFRESH_COOKIE not in client.cookies
        assert client.get("/api/account").json() == {"enabled": True, "user": None}
        assert client.get("/api/account/profile").status_code == 401
        assert client.get("/api/account/security", params={"recovery": True}).json()["recovery"] is True
        assert post(client, "password", {"password": "New-password-123", "recovery": True}).status_code == 204
        assert "chessmess_recovery_access" not in client.cookies
        assert upstream.call_args.args[2] == "/logout?scope=local"
    return "Recovery cookies authorize only password recovery and are cleared on completion"


def email_change_confirmation():
    pending = {**VERIFIED_USER, "new_email": "next@example.test"}
    changed = {**VERIFIED_USER, "email": pending["new_email"]}
    with app_client([
        (200, VERIFIED_USER), (200, pending),
        (200, pending), (200, {"code": "200"}),
        (200, pending), (200, lifecycle_session(changed, method="otp")),
    ]) as (client, upstream):
        token = signed_provider_fixture("aal1")
        client.cookies.set(ACCESS_COOKIE, token, path="/api")
        assert post(client, "email", {"email": changed["email"]}).status_code == 202
        first = post(client, "email/confirm", {"email": EMAIL, "code": "123456"})
        second = post(client, "email/confirm", {"email": changed["email"], "code": "123456"})
        assert first.json() == {"completed": False}
        assert second.json() == {"completed": True}
        assert client.cookies[ACCESS_COOKIE] == token and REFRESH_COOKIE not in client.cookies
        assert upstream.call_args.args[3]["type"] == "email_change"
    return "Secure email change handles two confirmations without replacing the normal session"


def captcha_and_provider_selection():
    env = dict(ACCOUNT_ENV, AUTH_CAPTCHA_SITE_KEY="qa_site_key")
    with app_client(env=env) as (client, upstream):
        assert client.get("/api/account/options").json()["captcha"] == {
            "provider": "turnstile", "siteKey": "qa_site_key",
        }
        response = post(client, "login", LOGIN)
        assert response.status_code == 400 and response.json()["detail"] == "captcha_required"
        response = post(client, "oauth", {"provider": "facebook"})
        assert response.status_code == 400 and response.json()["detail"] == "provider_unavailable"
        upstream.assert_not_called()
    return "Configured CAPTCHA and OAuth provider policy apply before upstream calls"


def own_profile_and_privacy():
    from backend import account, account_security
    env = dict(ACCOUNT_ENV, SUPABASE_SECRET_KEY="sb_secret_offline_fixture")
    user = {**VERIFIED_USER, "identities": [*VERIFIED_USER["identities"],
            {"provider": "google", "identity_id": GOOGLE_IDENTITY}]}
    owned_profile = {"id": user["id"], "username": "qa_player", "display_name": "QA"}
    with app_client([(200, user)] * 6, env=env) as (client, _):
        with patch.object(account_security, "_gateway_json", side_effect=[
            (200, [owned_profile]), (200, []), (204, {}),
            (200, [owned_profile]), (200, []), (200, []), (200, {}),
        ]) as gateway, patch.object(account, "_gateway_json", return_value=(200, {})):
            client.cookies.set(ACCESS_COOKIE, signed_provider_fixture("aal1"), domain=client.base_url.host, path="/api")
            assert client.get("/api/account/profile").json() == {"profile": owned_profile, "stats": None}
            assert post(client, "profile", {"displayName": "New QA Name"}).status_code == 204
            export = client.get("/api/account/export")
            assert export.status_code == 200 and export.headers.get("content-disposition", "").startswith("attachment")
            assert export.json()["profiles"] == [owned_profile] and export.json()["nextPage"] is None
            assert post(client, "identity/unlink", {"identityId": GOOGLE_IDENTITY}).status_code == 204
            assert post(client, "delete", {"confirmation": "DELETE"}).status_code == 204
            assert ACCESS_COOKIE not in client.cookies
            paths = [call.args[2] for call in gateway.call_args_list]
            assert all("eq." + user["id"] in p for p in paths[:-1])
            assert paths[-1] == "/auth/v1/admin/users/" + user["id"]
            assert gateway.call_args.kwargs["key"] == env["SUPABASE_SECRET_KEY"]
    return "Profile/PDPA export reads only the verified actor; delete uses the server adapter"


def suite():
    cases = [
        ("ACCOUNT-API-DISABLED", disabled_config),
        ("ACCOUNT-API-SIGNUP-VERIFY", signup_and_verify),
        ("ACCOUNT-API-REQUIRE-VERIFY", reject_disabled_provider_confirmation),
        ("ACCOUNT-API-UNCONFIRMED-SESSION", reject_unconfirmed_registration),
        ("ACCOUNT-API-LOGIN-ERRORS", login_errors),
        ("ACCOUNT-API-SESSION", session_lifecycle),
        ("ACCOUNT-API-ORIGIN", origin_policy),
        ("ACCOUNT-API-OAUTH-PKCE", oauth_pkce),
        ("ACCOUNT-API-MFA", verified_mfa_settings),
        ("ACCOUNT-API-RECOVERY", recovery_isolated),
        ("ACCOUNT-API-CHANGE-EMAIL", email_change_confirmation),
        ("ACCOUNT-API-CONFIG-GUARDS", captcha_and_provider_selection),
        ("ACCOUNT-API-PROFILE-EXPORT-DELETE", own_profile_and_privacy),
    ]
    results = []
    for identifier, case in cases:
        record(identifier, case, results)
    return report("accounts", results)

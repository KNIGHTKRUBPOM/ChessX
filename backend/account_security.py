"""Account lifecycle and MFA endpoints for the same-origin Auth BFF."""

from base64 import b64encode, urlsafe_b64encode
from dataclasses import dataclass, field
from hashlib import sha256
import os
import re
from secrets import token_urlsafe
from time import time
from typing import Literal
from urllib.parse import urlencode, urlsplit

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from fastapi.responses import JSONResponse, RedirectResponse
from pydantic import Field, field_validator

from .account import (
    _ACCESS_COOKIE, _ACCOUNT_PATH, _ACCESS_TOKEN, _RECOVERY_COOKIE, _AccountRoute, _AuthConfig,
    _Confirmation, _EmailInput, _audit, _canonical_uuid, _captcha_proof, _captcha_site_key,
    _clear_session, _config, _cookie_options, _display_name, _error_code, _gateway_json, _has_verified_factor,
    _profile, _provider_failure, _server_key, _session, _set_session, _supabase_request,
    _validated_user, _verified_claims, _write_config,
)
from .models import DataModel

account_security_router = APIRouter(
    prefix=_ACCOUNT_PATH, tags=["account security"], route_class=_AccountRoute,
)

_CALLBACK = _ACCOUNT_PATH + "/oauth/callback"
_VERIFIER = re.compile(r"[A-Za-z0-9_-]{43}")
_BASE32 = re.compile(r"[A-Z2-7]{16,128}=*")
# Supabase encodes QR modules as SVG elements, so enrollment responses are larger than other Auth responses.
_TOTP_RESPONSE_LIMIT = 2 * 1024 * 1024
_TOTP_SVG_LIMIT = 1536 * 1024
_PROVIDERS = {"google": "openid email profile", "facebook": "email public_profile"}
_PROVIDER_HOSTS = {"google": {"accounts.google.com"}, "facebook": {"www.facebook.com", "facebook.com"}}


class _OAuthStart(DataModel):
    provider: Literal["google", "facebook"]
    link: bool = False


class _RecoveryRequest(_EmailInput):
    captchaToken: str | None = Field(default=None, max_length=2048, repr=False)


class _PasswordUpdate(DataModel):
    password: str = Field(min_length=8, max_length=72, repr=False)
    currentPassword: str | None = Field(default=None, min_length=1, max_length=72, repr=False)
    nonce: str | None = Field(default=None, pattern=r"^[0-9]{6,10}$", repr=False)
    recovery: bool = False

    @field_validator("password", "currentPassword")
    @classmethod
    def check_byte_length(cls, value: str | None) -> str | None:
        if value is not None and (len(value.encode("utf-8")) > 72 or "\0" in value):
            raise ValueError("Invalid password length")
        return value


class _FactorEnrollment(DataModel):
    name: str = Field(default="ChessMess", pattern=r"^[^\x00-\x1f\x7f]{1,64}$")


class _FactorRequest(DataModel):
    factorId: str = Field(min_length=36, max_length=36)


class _FactorVerification(_FactorRequest):
    code: str = Field(pattern=r"^[0-9]{6}$", repr=False)
    recovery: bool = False


class _UnlinkRequest(DataModel):
    identityId: str = Field(min_length=36, max_length=36)


class _DeleteRequest(DataModel):
    confirmation: Literal["DELETE"]


class _ProfileUpdate(DataModel):
    username: str | None = Field(default=None, pattern=r"^[a-z0-9_]{3,34}$")
    displayName: str | None = Field(default=None, min_length=1, max_length=80)
    avatarUrl: str | None = Field(default=None, max_length=512)

    @field_validator("displayName")
    @classmethod
    def validate_display_name(cls, value: str | None) -> str:
        name = _display_name(value) if isinstance(value, str) else None
        if not name:
            raise ValueError("Invalid display name")
        return name

    @field_validator("avatarUrl")
    @classmethod
    def validate_avatar(cls, value: str | None) -> str | None:
        if value is None:
            return None
        parsed = urlsplit(value)
        if (
            parsed.scheme != "https" or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.port is not None
            or any(ord(character) <= 32 or ord(character) == 127 for character in value)
        ):
            raise ValueError("Expected HTTPS avatar URL")
        return value


@dataclass(frozen=True)
class _Actor:
    access: str = field(repr=False)
    user: dict = field(repr=False)
    claims: dict = field(repr=False)
    id: str

    @property
    def aal(self) -> str:
        return "aal2" if self.claims.get("aal") == "aal2" else "aal1"

    @property
    def mfa_required(self) -> bool:
        return _has_verified_factor(self.user) and self.aal != "aal2"


def _actor(request: Request, config: _AuthConfig, *, recovery: bool = False) -> _Actor:
    name = _RECOVERY_COOKIE if recovery else _ACCESS_COOKIE
    access = request.cookies.get(name, "")
    user = _validated_user(config, access)
    user_id = _canonical_uuid(user.get("id")) if user else None
    if not user_id or not user or not user.get("email_confirmed_at"):
        raise HTTPException(401, "recovery_expired" if recovery else "session_required")
    return _Actor(access, user, _verified_claims(access, user), user_id)


def _sensitive(actor: _Actor):
    if actor.mfa_required:
        raise HTTPException(403, "mfa_required")


def _recent(actor: _Actor):
    methods = actor.claims.get("amr")
    timestamp = int(time())
    if not isinstance(methods, list) or not any(
        isinstance(method, dict)
        and method.get("method") in {"password", "oauth", "otp", "totp"}
        and type(method.get("timestamp")) is int
        and 0 <= timestamp - method["timestamp"] <= 600
        for method in methods
    ):
        raise HTTPException(403, "recent_login_required")


def _public_factors(user: dict) -> list[dict]:
    factors = user.get("factors")
    if not isinstance(factors, list):
        return []
    return [
        {"id": _canonical_uuid(factor.get("id")),
         "name": str(factor.get("friendly_name") or "Authenticator")[:64],
         "status": factor["status"]}
        for factor in factors
        if isinstance(factor, dict) and factor.get("factor_type") == "totp"
        and _canonical_uuid(factor.get("id")) and factor.get("status") in {"verified", "unverified"}
    ]


def _public_identities(user: dict) -> list[dict]:
    identities = user.get("identities")
    if not isinstance(identities, list):
        return []
    return [
        {"id": _canonical_uuid(identity.get("identity_id")), "provider": identity["provider"]}
        for identity in identities
        if isinstance(identity, dict) and _canonical_uuid(identity.get("identity_id"))
        and isinstance(identity.get("provider"), str)
    ]


def _security_state(actor: _Actor, recovery: bool) -> dict:
    return {
        "aal": actor.aal,
        "mfaRequired": actor.mfa_required,
        "factors": _public_factors(actor.user),
        "identities": [] if recovery or actor.mfa_required else _public_identities(actor.user),
        "recovery": recovery,
    }


def _enabled_providers() -> list[str]:
    configured = {part.strip().lower() for part in os.getenv("AUTH_OAUTH_PROVIDERS", "").split(",")}
    return [provider for provider in _PROVIDERS if provider in configured]


def _provider_result(status: int, data: dict, invalid_code: str, *, accepted=(200, 204)):
    if status in accepted:
        return
    code = _error_code(data)
    if code in {"captcha_failed", "captcha_required"}:
        raise HTTPException(400, "captcha_invalid")
    if code in {"reauthentication_needed", "reauthentication_not_valid"}:
        raise HTTPException(403, "reauthenticate_required")
    if code == "manual_linking_disabled":
        raise HTTPException(409, "linking_unavailable")
    if status in (400, 401, 403, 404, 409, 422):
        raise HTTPException(400, invalid_code)
    _provider_failure(status)


def _oauth_cookie(config: _AuthConfig) -> str:
    return "__Host-chessmess_oauth" if config.secure_cookie else "chessmess_oauth"


def _external_redirect(value: object, provider: str) -> str:
    if isinstance(value, str) and len(value) <= 8192:
        try:
            parsed = urlsplit(value)
            if (
                parsed.scheme == "https" and parsed.hostname in _PROVIDER_HOSTS[provider]
                and parsed.username is None and parsed.password is None and parsed.port in (None, 443)
            ):
                return value
        except ValueError:
            pass
    raise HTTPException(503, "auth_unavailable")


@account_security_router.get("/options")
def account_options():
    site_key = _captcha_site_key()
    if not _config():
        return {"providers": [], "captcha": None}
    return {
        "providers": _enabled_providers(),
        "captcha": {"provider": "turnstile", "siteKey": site_key} if site_key else None,
    }


@account_security_router.post("/oauth")
def start_oauth(payload: _OAuthStart, request: Request, response: Response,
                config: _AuthConfig = Depends(_write_config)):
    if payload.provider not in _enabled_providers():
        raise HTTPException(400, "provider_unavailable")
    verifier = token_urlsafe(32)
    challenge = urlsafe_b64encode(sha256(verifier.encode("ascii")).digest()).rstrip(b"=").decode("ascii")
    query = {
        "provider": payload.provider,
        "redirect_to": config.origin + _CALLBACK,
        "scopes": _PROVIDERS[payload.provider],
        "code_challenge": challenge,
        "code_challenge_method": "s256",
    }
    owner = ""
    if payload.link:
        actor = _actor(request, config)
        _sensitive(actor)
        _recent(actor)
        owner = actor.id
        query["skip_http_redirect"] = "true"
        status, data = _supabase_request(
            config, "GET", "/user/identities/authorize?" + urlencode(query), token=actor.access,
        )
        _provider_result(status, data, "linking_unavailable", accepted=(200,))
        url = _external_redirect(data.get("url"), payload.provider)
    else:
        url = config.supabase_url + "/auth/v1/authorize?" + urlencode(query)
    response.set_cookie(_oauth_cookie(config), verifier + "." + owner, max_age=600, **_cookie_options(config, "/"))
    return {"url": url}


@account_security_router.get("/oauth/callback", include_in_schema=False)
def oauth_callback(request: Request):
    config = _config()
    response = RedirectResponse("/?auth=oauth_failed", status_code=303)
    if not config:
        return response
    name = _oauth_cookie(config)
    response.delete_cookie(name, **_cookie_options(config, "/"))
    verifier, separator, owner = request.cookies.get(name, "").partition(".")
    codes = request.query_params.getlist("code")
    if (
        not separator or not _VERIFIER.fullmatch(verifier) or len(codes) != 1
        or not _canonical_uuid(codes[0]) or (owner and not _canonical_uuid(owner))
        or "error" in request.query_params
    ):
        return response
    try:
        if owner:
            actor = _actor(request, config)
            _sensitive(actor)
            if actor.id != owner:
                return response
        status, data = _supabase_request(config, "POST", "/token?grant_type=pkce", {
            "auth_code": codes[0],
            "code_verifier": verifier,
        })
        if status != 200:
            return response
        session = _session(data)
        if not session.provider_user.get("email_confirmed_at") or (owner and session.user["id"] != owner):
            return response
        if not owner:
            _set_session(response, config, session)
        _audit(config, "identity_linked" if owner else "oauth_login", session.user["id"])
        response.headers["location"] = "/?auth=linked" if owner else "/?auth=oauth_ok"
    except HTTPException:
        return response
    return response


def _set_recovery(response: Response, config: _AuthConfig, access: str, expires: int):
    response.set_cookie(_RECOVERY_COOKIE, access, max_age=min(expires, 900), **_cookie_options(config))


@account_security_router.post("/recover", status_code=202)
def request_recovery(payload: _RecoveryRequest, config: _AuthConfig = Depends(_write_config)):
    status, data = _supabase_request(config, "POST", "/recover", {
        "email": payload.email, **_captcha_proof(payload.captchaToken),
    })
    if status not in (200, 202, 204) and _error_code(data) not in {"user_not_found", "email_not_confirmed"}:
        _provider_result(status, data, "invalid_input")
    return {"confirmationRequired": True}


@account_security_router.post("/recover/confirm")
def confirm_recovery(payload: _Confirmation, response: Response, config: _AuthConfig = Depends(_write_config)):
    status, data = _supabase_request(config, "POST", "/verify", {
        "type": "recovery", "email": payload.email, "token": payload.code,
    })
    _provider_result(status, data, "invalid_code", accepted=(200,))
    session = _session(data)
    user_id = _canonical_uuid(session.user["id"])
    if not user_id or not session.provider_user.get("email_confirmed_at"):
        raise HTTPException(400, "invalid_code")
    actor = _Actor(session.access, session.provider_user,
                   _verified_claims(session.access, session.provider_user), user_id)
    _set_recovery(response, config, session.access, session.expires_in)
    return _security_state(actor, True)


@account_security_router.get("/security")
def account_security(request: Request, recovery: bool = False):
    config = _config()
    if not config or request.headers.get("sec-fetch-site") in {"same-site", "cross-site"}:
        raise HTTPException(401, "session_required")
    return _security_state(_actor(request, config, recovery=recovery), recovery)


@account_security_router.post("/mfa/enroll")
def enroll_factor(payload: _FactorEnrollment, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    _recent(actor)
    status, data = _supabase_request(config, "POST", "/factors", {
        "factor_type": "totp", "friendly_name": payload.name, "issuer": "ChessMess",
    }, token=actor.access, response_limit=_TOTP_RESPONSE_LIMIT)
    _provider_result(status, data, "mfa_unavailable", accepted=(200, 201))
    factor_id = _canonical_uuid(data.get("id"))
    totp = data.get("totp")
    qr = totp.get("qr_code") if isinstance(totp, dict) else None
    qr_bytes = qr.encode("utf-8") if isinstance(qr, str) else b""
    secret = totp.get("secret") if isinstance(totp, dict) else None
    if (
        not factor_id or not 1 <= len(qr_bytes) <= _TOTP_SVG_LIMIT or b"<svg" not in qr_bytes[:256]
        or not isinstance(secret, str) or not _BASE32.fullmatch(secret)
    ):
        raise HTTPException(503, "auth_unavailable")
    # The client renders the SVG only as an image, never as document markup.
    return {"factorId": factor_id, "qrCode": "data:image/svg+xml;base64," + b64encode(qr_bytes).decode("ascii"),
            "secret": secret}


def _own_factor(actor: _Actor, value: str, *, verified_only: bool = False) -> dict:
    factor_id = _canonical_uuid(value)
    for factor in _public_factors(actor.user):
        if factor["id"] == factor_id and (not verified_only or factor["status"] == "verified"):
            return factor
    raise HTTPException(400, "invalid_factor")


@account_security_router.post("/mfa/verify")
def verify_factor(payload: _FactorVerification, request: Request, response: Response,
                  config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config, recovery=payload.recovery)
    factor = _own_factor(actor, payload.factorId, verified_only=payload.recovery)
    base = "/factors/" + factor["id"]
    status, challenge = _supabase_request(config, "POST", base + "/challenge", {}, token=actor.access)
    _provider_result(status, challenge, "invalid_code", accepted=(200,))
    identifier = _canonical_uuid(challenge.get("id"))
    if not identifier:
        raise HTTPException(503, "auth_unavailable")
    status, data = _supabase_request(config, "POST", base + "/verify", {
        "challenge_id": identifier, "code": payload.code,
    }, token=actor.access)
    _provider_result(status, data, "invalid_code", accepted=(200,))
    access = data.get("access_token")
    if not isinstance(access, str) or not _ACCESS_TOKEN.fullmatch(access):
        raise HTTPException(503, "auth_unavailable")
    if "user" not in data:
        data = {**data, "user": _validated_user(config, access)}
    session = _session(data)
    if session.user["id"] != actor.id or _verified_claims(session.access, session.provider_user).get("aal") != "aal2":
        raise HTTPException(503, "auth_unavailable")
    if payload.recovery:
        _set_recovery(response, config, session.access, session.expires_in)
    else:
        _set_session(response, config, session)
    if factor["status"] == "unverified":
        _audit(config, "mfa_enrolled", actor.id)
    return {"aal": "aal2"}


@account_security_router.post("/mfa/remove", status_code=204)
def remove_factor(payload: _FactorRequest, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    _recent(actor)
    factor = _own_factor(actor, payload.factorId)
    status, data = _supabase_request(config, "DELETE", "/factors/" + factor["id"], token=actor.access)
    _provider_result(status, data, "invalid_factor")
    if factor["status"] == "verified":
        _audit(config, "mfa_removed", actor.id)
    return Response(status_code=204)


@account_security_router.post("/reauthenticate", status_code=204)
def reauthenticate(request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    status, data = _supabase_request(config, "GET", "/reauthenticate", token=actor.access)
    _provider_result(status, data, "reauthenticate_unavailable")
    return Response(status_code=204)


@account_security_router.post("/password", status_code=204)
def update_password(payload: _PasswordUpdate, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config, recovery=payload.recovery)
    _sensitive(actor)
    changes = {"password": payload.password}
    if payload.nonce:
        changes["nonce"] = payload.nonce
    if payload.currentPassword and not payload.recovery:
        changes["current_password"] = payload.currentPassword
    status, data = _supabase_request(config, "PUT", "/user", changes, token=actor.access)
    _provider_result(status, data, "password_change_rejected")
    _audit(config, "password_changed", actor.id)
    response = Response(status_code=204)
    if payload.recovery:
        response.delete_cookie(_RECOVERY_COOKIE, **_cookie_options(config))
        try:
            _supabase_request(config, "POST", "/logout?scope=local", token=actor.access)
        except HTTPException:
            pass  # This short-lived upstream session is confined to the erased recovery cookie.
    return response


@account_security_router.post("/email", status_code=202)
def change_email(payload: _EmailInput, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    _recent(actor)
    status, data = _supabase_request(config, "PUT", "/user", {"email": payload.email}, token=actor.access)
    _provider_result(status, data, "invalid_input")
    return {"confirmationRequired": True}


@account_security_router.post("/email/confirm")
def confirm_email_change(payload: _Confirmation, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    pending = actor.user.get("new_email")
    if not isinstance(pending, str) or not pending or payload.email.casefold() not in {
        actor.user["email"].casefold(), pending.casefold(),
    }:
        raise HTTPException(400, "invalid_code")
    status, data = _supabase_request(config, "POST", "/verify", {
        "type": "email_change", "email": payload.email, "token": payload.code,
    })
    _provider_result(status, data, "invalid_code", accepted=(200,))
    if not data.get("access_token") and data.get("code") == "200":
        return {"completed": False}
    session = _session(data)
    if session.user["id"] != actor.id:
        raise HTTPException(400, "invalid_code")
    _audit(config, "email_changed", actor.id)
    return {"completed": True}


@account_security_router.post("/identity/unlink", status_code=204)
def unlink_identity(payload: _UnlinkRequest, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    _recent(actor)
    identities = _public_identities(actor.user)
    identity_id = _canonical_uuid(payload.identityId)
    if len(identities) < 2 or not any(
        identity["id"] == identity_id and identity["provider"] in _PROVIDERS for identity in identities
    ):
        raise HTTPException(400, "identity_unlink_rejected")
    status, data = _supabase_request(config, "DELETE", "/user/identities/" + identity_id, token=actor.access)
    _provider_result(status, data, "identity_unlink_rejected")
    _audit(config, "identity_unlinked", actor.id)
    return Response(status_code=204)


@account_security_router.post("/logout-all", status_code=204)
def logout_all(request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    status, data = _supabase_request(config, "POST", "/logout?scope=global", token=actor.access)
    _provider_result(status, data, "logout_rejected")
    _audit(config, "logout_all", actor.id)
    response = Response(status_code=204)
    _clear_session(response, config)
    return response


def _own_data(config: _AuthConfig, actor: _Actor, table: str, query: dict[str, str]) -> list:
    status, rows = _gateway_json(config, "GET", "/rest/v1/" + table + "?" + urlencode(query), token=actor.access)
    if status != 200 or not isinstance(rows, list):
        _provider_failure(status)
    return rows


def _own_profile(config: _AuthConfig, actor: _Actor) -> list:
    return _own_data(config, actor, "profiles", {
        "select": "id,username,display_name,avatar_url,created_at,updated_at", "id": "eq." + actor.id,
    })


@account_security_router.get("/profile")
def read_profile(request: Request):
    config = _config()
    if not config or request.headers.get("sec-fetch-site") in {"same-site", "cross-site"}:
        raise HTTPException(401, "session_required")
    actor = _actor(request, config)
    _sensitive(actor)
    profile = _own_profile(config, actor)
    stats = _own_data(config, actor, "player_stats", {
        "select": "player_id,games_played,wins,losses,draws,updated_at", "player_id": "eq." + actor.id,
    })
    return {"profile": profile[0] if profile else None, "stats": stats[0] if stats else None}


@account_security_router.post("/profile", status_code=204)
def update_profile(payload: _ProfileUpdate, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    values = payload.model_dump(exclude_unset=True)
    if not values or ("username" in values and values["username"] is None):
        raise HTTPException(422, "invalid_input")
    column = {"username": "username", "displayName": "display_name", "avatarUrl": "avatar_url"}
    status, data = _gateway_json(config, "PATCH", "/rest/v1/profiles?" + urlencode({
        "id": "eq." + actor.id,
    }), {column[key]: value for key, value in values.items()}, token=actor.access)
    _provider_result(status, data if isinstance(data, dict) else {}, "profile_change_rejected")
    return Response(status_code=204)


@account_security_router.get("/export")
def export_account(request: Request, page: int = Query(default=0, ge=0, le=10000)):
    config = _config()
    if not config or request.headers.get("sec-fetch-site") in {"same-site", "cross-site"}:
        raise HTTPException(401, "session_required")
    actor = _actor(request, config)
    _sensitive(actor)
    profile = _own_profile(config, actor)
    stats = _own_data(config, actor, "player_stats", {
        "select": "player_id,games_played,wins,losses,draws,updated_at", "player_id": "eq." + actor.id,
    })
    matches = _own_data(config, actor, "match_history", {
        "select": "match_id,player_id,mode,side,result,finished_at", "player_id": "eq." + actor.id,
        "order": "finished_at.desc,match_id.desc", "limit": "101", "offset": str(page * 100),
    })
    if page == 0:
        _audit(config, "account_exported", actor.id)
    return JSONResponse({
        "account": _profile(actor.user), "identities": _public_identities(actor.user),
        "profiles": profile, "stats": stats, "matches": matches[:100],
        "nextPage": page + 1 if len(matches) > 100 else None,
    }, headers={"Content-Disposition": f'attachment; filename="chessmess-account-{page + 1}.json"'})


@account_security_router.post("/delete", status_code=204)
def delete_account(payload: _DeleteRequest, request: Request, config: _AuthConfig = Depends(_write_config)):
    actor = _actor(request, config)
    _sensitive(actor)
    _recent(actor)
    key = _server_key()
    if key is None:
        raise HTTPException(503, "auth_unavailable")
    status, data = _gateway_json(config, "DELETE", "/auth/v1/admin/users/" + actor.id, {
        "should_soft_delete": False,
    }, key=key)
    _provider_result(status, data if isinstance(data, dict) else {}, "delete_rejected")
    response = Response(status_code=204)
    _clear_session(response, config)
    return response

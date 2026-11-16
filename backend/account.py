"""Same-origin account endpoints backed by Supabase Auth."""

from base64 import urlsafe_b64decode
from binascii import Error as Base64Error
from dataclasses import dataclass, field
from http.client import HTTPException as UpstreamHttpError
import json
import logging
import os
import re
from unicodedata import category, normalize
from urllib.error import HTTPError, URLError
from urllib.request import Request as UpstreamRequest
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import Field, field_validator

from .models import DataModel
from .supabase_http import opener as _auth_http, parse_origin


_ACCOUNT_PATH = "/api/account"
_ACCESS_COOKIE = "chessmess_access"
_REFRESH_COOKIE = "chessmess_refresh"
_RECOVERY_COOKIE = "chessmess_recovery_access"
_ACCESS_PATH = "/api"
_REFRESH_AGE = 30 * 24 * 60 * 60
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_ACCESS_TOKEN = re.compile(r"[A-Za-z0-9._-]{1,3800}")
_REFRESH_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,512}")
_PUBLISHABLE_KEY = re.compile(r"sb_publishable_[A-Za-z0-9_-]{1,128}")
_SECRET_KEY = re.compile(r"sb_secret_[A-Za-z0-9_-]{1,128}")
_SITE_KEY = re.compile(r"[A-Za-z0-9_-]{1,100}")
_UPSTREAM_BODY_LIMIT = 64 * 1024
_logger = logging.getLogger("uvicorn.error")


class _AccountRoute(APIRoute):
    def get_route_handler(self):
        handler = super().get_route_handler()

        async def account_route(request: Request):
            try:
                return await handler(request)
            except RequestValidationError:
                # FastAPI normally includes the rejected value in validation errors.
                return JSONResponse({"detail": "invalid_input"}, status_code=422)

        return account_route


account_router = APIRouter(prefix=_ACCOUNT_PATH, tags=["accounts"], route_class=_AccountRoute)


@dataclass(frozen=True)
class _AuthConfig:
    origin: str
    supabase_url: str
    publishable_key: str = field(repr=False)

    @property
    def secure_cookie(self):
        return self.origin.startswith("https://")


@dataclass(frozen=True)
class _Session:
    access: str = field(repr=False)
    refresh: str = field(repr=False)
    expires_in: int
    user: dict
    provider_user: dict = field(repr=False)


def _config() -> _AuthConfig | None:
    if os.getenv("CHESS_ACCOUNT_ENABLED", "1") == "0":
        return None
    production = os.getenv("CHESS_ENV", "").casefold() == "production"
    origin = parse_origin(os.getenv("APP_ORIGIN", ""), allow_http_loopback=not production)
    supabase_url = parse_origin(os.getenv("SUPABASE_URL", ""), allow_http_loopback=not production)
    key = os.getenv("SUPABASE_PUBLISHABLE_KEY", "").strip()
    if not origin or not supabase_url or not _PUBLISHABLE_KEY.fullmatch(key):
        return None
    return _AuthConfig(origin, supabase_url, key)


def _write_config(request: Request) -> _AuthConfig:
    config = _config()
    if config is None:
        raise HTTPException(503, "auth_not_configured")
    if request.headers.get("origin") != config.origin:
        raise HTTPException(403, "request_origin")
    return config


def _gateway_json(config, method, path, payload=None, token=None, *, key=None, timeout=5,
                  response_limit=_UPSTREAM_BODY_LIMIT):
    headers = {"Accept": "application/json", "apikey": key or config.publishable_key}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = UpstreamRequest(config.supabase_url + path, data=data, headers=headers, method=method)
    try:
        try:
            response = _auth_http.open(request, timeout=timeout)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            body = response.read(response_limit + 1)
    except (OSError, URLError, UpstreamHttpError, ValueError):
        raise HTTPException(503, "auth_unavailable") from None
    if len(body) > response_limit:
        raise HTTPException(503, "auth_unavailable")
    try:
        result = json.loads(body) if body else {}
    except (ValueError, UnicodeError):
        if 200 <= status < 300:
            raise HTTPException(503, "auth_unavailable") from None
        result = {}
    return status, result


def _supabase_request(config, method, path, payload=None, token=None, *, response_limit=_UPSTREAM_BODY_LIMIT):
    status, result = _gateway_json(config, method, "/auth/v1" + path, payload, token,
                                   response_limit=response_limit)
    if not isinstance(result, dict):
        if 200 <= status < 300:
            raise HTTPException(503, "auth_unavailable")
        return status, {}
    return status, result


def _provider_failure(status: int):
    if status == 429:
        raise HTTPException(429, "rate_limited")
    raise HTTPException(503, "auth_unavailable")


def _error_code(data: dict):
    return data.get("error_code") or data.get("code")


def _canonical_uuid(value: object) -> str | None:
    if isinstance(value, str) and len(value) == 36:
        try:
            return str(UUID(value))
        except ValueError:
            pass
    return None


def _server_key() -> str | None:
    key = os.getenv("SUPABASE_SECRET_KEY", "")
    return key if _SECRET_KEY.fullmatch(key) else None


def _audit(config: _AuthConfig, event: str, actor: str | None = None):
    # Logging remains available if remote audit storage is temporarily unreachable.
    _logger.info("%s", json.dumps({"event": event}, separators=(",", ":")))
    key = _server_key()
    if key is None:
        return
    try:
        status, _ = _gateway_json(config, "POST", "/rest/v1/rpc/chessmess_account_audit", {
            "p_event": event,
            "p_actor_id": _canonical_uuid(actor),
        }, key=key, timeout=2)
        if not 200 <= status < 300:
            _logger.warning("account audit storage unavailable")
    except HTTPException:
        _logger.warning("account audit storage unavailable")


def _captcha_site_key() -> str | None:
    key = os.getenv("AUTH_CAPTCHA_SITE_KEY", "")
    return key if _SITE_KEY.fullmatch(key) else None


def _captcha_proof(token: str | None) -> dict:
    if _captcha_site_key() and not token:
        raise HTTPException(400, "captcha_required")
    return {"gotrue_meta_security": {"captcha_token": token}} if token else {}


def _display_name(value: str) -> str | None:
    name = " ".join(normalize("NFKC", value).split())
    if 1 <= len(name) <= 24 and all(category(char)[0] != "C" for char in name):
        return name
    return None


def _profile(data: object) -> dict:
    if not isinstance(data, dict):
        raise HTTPException(503, "auth_unavailable")
    user_id, email = data.get("id"), data.get("email")
    if not (isinstance(user_id, str) and 1 <= len(user_id) <= 64 and
            isinstance(email, str) and len(email) <= 254 and _EMAIL.fullmatch(email)):
        raise HTTPException(503, "auth_unavailable")
    metadata = data.get("user_metadata")
    name = metadata.get("display_name") if isinstance(metadata, dict) else None
    return {"id": user_id, "email": email, "displayName": _display_name(name) if isinstance(name, str) else None}


def _session(data: dict) -> _Session:
    access, refresh = data.get("access_token"), data.get("refresh_token")
    if not (isinstance(access, str) and _ACCESS_TOKEN.fullmatch(access) and
            isinstance(refresh, str) and _REFRESH_TOKEN.fullmatch(refresh)):
        raise HTTPException(503, "auth_unavailable")
    expires_in = data.get("expires_in", 3600)
    if type(expires_in) is not int or not 1 <= expires_in <= 24 * 60 * 60:
        raise HTTPException(503, "auth_unavailable")
    provider_user = data.get("user")
    return _Session(access, refresh, expires_in, _profile(provider_user), provider_user)


def _cookie_options(config: _AuthConfig, path: str = _ACCOUNT_PATH):
    return {"httponly": True, "secure": config.secure_cookie, "samesite": "lax", "path": path}


def _set_session(response: Response, config: _AuthConfig, session: _Session):
    response.delete_cookie(_ACCESS_COOKIE, **_cookie_options(config))
    response.delete_cookie(_RECOVERY_COOKIE, **_cookie_options(config))
    response.set_cookie(_ACCESS_COOKIE, session.access, max_age=session.expires_in, **_cookie_options(config, _ACCESS_PATH))
    response.set_cookie(_REFRESH_COOKIE, session.refresh, max_age=_REFRESH_AGE, **_cookie_options(config))


def _clear_session(response: Response, config: _AuthConfig):
    response.delete_cookie(_ACCESS_COOKIE, **_cookie_options(config))
    response.delete_cookie(_ACCESS_COOKIE, **_cookie_options(config, _ACCESS_PATH))
    response.delete_cookie(_REFRESH_COOKIE, **_cookie_options(config))
    response.delete_cookie(_RECOVERY_COOKIE, **_cookie_options(config))


def _validated_user(config: _AuthConfig, access: str) -> dict | None:
    if not _ACCESS_TOKEN.fullmatch(access):
        return None
    status, data = _supabase_request(config, "GET", "/user", token=access)
    if status == 200:
        _profile(data)
        return data
    if status not in (401, 403):
        _provider_failure(status)
    return None


def _verified_claims(access: str, user: dict) -> dict:
    """Read assurance claims only after getting the same user from Supabase Auth."""
    try:
        _, payload, _ = access.split(".")
        claims = json.loads(urlsafe_b64decode(payload + "=" * (-len(payload) % 4)))
    except (ValueError, UnicodeError, Base64Error):
        return {}
    if not isinstance(claims, dict) or claims.get("sub") != user.get("id"):
        return {}
    return claims


def _has_verified_factor(user: dict) -> bool:
    factors = user.get("factors")
    return isinstance(factors, list) and any(
        isinstance(factor, dict) and factor.get("status") == "verified" for factor in factors
    )


def _account_state(access: str, user: dict) -> dict:
    state = {"enabled": True, "user": _profile(user)}
    if _has_verified_factor(user) and _verified_claims(access, user).get("aal") != "aal2":
        state["mfaRequired"] = True
    return state


def optional_player_id(request: Request) -> str | None:
    config = _config()
    access = request.cookies.get(_ACCESS_COOKIE, "")
    if not config or not access:
        return None
    user = _validated_user(config, access)
    if not user or not user.get("email_confirmed_at"):
        return None
    if _has_verified_factor(user) and _verified_claims(access, user).get("aal") != "aal2":
        return None
    return _canonical_uuid(user.get("id"))


def _refresh(config: _AuthConfig, token: str) -> _Session | None:
    status, data = _supabase_request(config, "POST", "/token?grant_type=refresh_token", {"refresh_token": token})
    if status == 200:
        return _session(data)
    if status in (400, 401, 403, 422):
        return None
    _provider_failure(status)


class _EmailInput(DataModel):
    email: str = Field(max_length=254)

    @field_validator("email")
    @classmethod
    def valid_email(cls, value: str) -> str:
        email = value.strip()
        if not _EMAIL.fullmatch(email) or any(category(char)[0] == "C" for char in email):
            raise ValueError("Invalid email")
        return email


class _LoginInput(_EmailInput):
    password: str = Field(min_length=1, max_length=72, repr=False)
    captchaToken: str | None = Field(default=None, max_length=2048, repr=False)

    @field_validator("password")
    @classmethod
    def valid_password(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72 or "\0" in value:
            raise ValueError("Invalid password")
        return value


class _Registration(_LoginInput):
    displayName: str = Field(max_length=80)

    @field_validator("password")
    @classmethod
    def minimum_password(cls, value: str) -> str:
        if len(value) < 8:
            raise ValueError("Password too short")
        return value

    @field_validator("displayName")
    @classmethod
    def valid_name(cls, value: str) -> str:
        name = _display_name(value)
        if name is None:
            raise ValueError("Invalid display name")
        return name


class _Confirmation(_EmailInput):
    code: str = Field(pattern=r"^[0-9]{6,10}$", repr=False)


@account_router.get("")
def read_account(request: Request, response: Response):
    config = _config()
    if config is None:
        return {"enabled": False, "user": None}
    if request.headers.get("sec-fetch-site") in {"same-site", "cross-site"}:
        return {"enabled": True, "user": None}
    access = request.cookies.get(_ACCESS_COOKIE, "")
    refresh = request.cookies.get(_REFRESH_COOKIE, "")
    user = _validated_user(config, access)
    if user is not None:
        return _account_state(access, user)
    if _REFRESH_TOKEN.fullmatch(refresh):
        session = _refresh(config, refresh)
        if session:
            _set_session(response, config, session)
            return _account_state(session.access, session.provider_user)
    if access or refresh:
        _clear_session(response, config)
    return {"enabled": True, "user": None}


@account_router.post("/register", status_code=202)
def register_account(payload: _Registration, config: _AuthConfig = Depends(_write_config)):
    proof = _captcha_proof(payload.captchaToken)
    status, settings = _supabase_request(config, "GET", "/settings")
    if status != 200 or settings.get("mailer_autoconfirm") is not False:
        _provider_failure(status)
    status, data = _supabase_request(config, "POST", "/signup", {
        "email": payload.email,
        "password": payload.password,
        "data": {"display_name": payload.displayName},
        **proof,
    })
    code = _error_code(data)
    if data.get("access_token") or data.get("refresh_token"):
        # Email confirmation must be enabled at Supabase.
        _provider_failure(status)
    if status in (200, 201) or code in ("user_already_exists", "email_exists"):
        return {"confirmationRequired": True}
    if code in ("weak_password", "validation_failed", "email_address_invalid"):
        raise HTTPException(422, "invalid_input")
    _provider_failure(status)


@account_router.post("/confirm", status_code=204, response_class=Response)
def confirm_account(payload: _Confirmation, config: _AuthConfig = Depends(_write_config)):
    status, _ = _supabase_request(config, "POST", "/verify", {
        "email": payload.email, "token": payload.code, "type": "email",
    })
    if status == 200:
        return Response(status_code=204)
    if status in (400, 401, 403, 404, 422):
        raise HTTPException(400, "invalid_code")
    _provider_failure(status)


@account_router.post("/login")
def login_account(payload: _LoginInput, response: Response, config: _AuthConfig = Depends(_write_config)):
    status, data = _supabase_request(config, "POST", "/token?grant_type=password", {
        "email": payload.email, "password": payload.password, **_captcha_proof(payload.captchaToken),
    })
    code = _error_code(data)
    if status == 200:
        session = _session(data)
        _set_session(response, config, session)
        _audit(config, "login_success", session.user["id"])
        return _account_state(session.access, session.provider_user)
    if code == "email_not_confirmed":
        raise HTTPException(403, "email_unconfirmed")
    if status in (400, 401, 403, 422):
        _audit(config, "login_failed")
        raise HTTPException(401, "invalid_credentials")
    _provider_failure(status)


@account_router.post("/logout", status_code=204, response_class=Response)
def logout_account(request: Request, config: _AuthConfig = Depends(_write_config)):
    response = Response(status_code=204)
    access = request.cookies.get(_ACCESS_COOKIE, "")
    refresh = request.cookies.get(_REFRESH_COOKIE, "")
    if _ACCESS_TOKEN.fullmatch(access):
        status, _ = _supabase_request(config, "POST", "/logout?scope=local", token=access)
        if status in (200, 204, 404):
            _clear_session(response, config)
            return response
        if status not in (400, 401, 403):
            _provider_failure(status)

    if _REFRESH_TOKEN.fullmatch(refresh):
        session = _refresh(config, refresh)
        if session:
            try:
                status, _ = _supabase_request(config, "POST", "/logout?scope=local", token=session.access)
                if status not in (200, 204, 404):
                    _provider_failure(status)
            except HTTPException as error:
                response = JSONResponse({"detail": error.detail}, status_code=error.status_code)
                _set_session(response, config, session)
                return response
    _clear_session(response, config)
    return response


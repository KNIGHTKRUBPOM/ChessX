"""Same-origin account endpoints backed by Supabase Auth."""

from dataclasses import dataclass
from http.client import HTTPException as UpstreamHttpError
import json
import os
import re
from unicodedata import category, normalize
from urllib.error import HTTPError, URLError
from urllib.request import Request as UpstreamRequest

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
_REFRESH_AGE = 30 * 24 * 60 * 60
_EMAIL = re.compile(r"[^@\s]+@[^@\s]+\.[^@\s]+")
_ACCESS_TOKEN = re.compile(r"[A-Za-z0-9._-]{1,3800}")
_REFRESH_TOKEN = re.compile(r"[A-Za-z0-9_-]{1,512}")
_PUBLISHABLE_KEY = re.compile(r"sb_publishable_[A-Za-z0-9_-]{1,128}")
_UPSTREAM_BODY_LIMIT = 64 * 1024


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
    publishable_key: str

    @property
    def secure_cookie(self):
        return self.origin.startswith("https://")


@dataclass(frozen=True)
class _Session:
    access: str
    refresh: str
    expires_in: int
    user: dict


def _config() -> _AuthConfig | None:
    if os.getenv("CHESS_ACCOUNT_ENABLED", "1") == "0":
        return None
    production = os.getenv("CHESS_ENV", "").casefold() == "production"
    origin = parse_origin(os.getenv("APP_ORIGIN", ""), allow_http_loopback=not production)
    supabase_url = parse_origin(os.getenv("SUPABASE_URL", ""))
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


def _supabase_request(config, method, path, payload=None, token=None):
    headers = {"Accept": "application/json", "apikey": config.publishable_key}
    if token is not None:
        headers["Authorization"] = f"Bearer {token}"
    if payload is not None:
        headers["Content-Type"] = "application/json"
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    request = UpstreamRequest(config.supabase_url + "/auth/v1" + path, data=data, headers=headers, method=method)
    try:
        try:
            response = _auth_http.open(request, timeout=5)
        except HTTPError as error:
            response = error
        with response:
            status = response.status
            body = response.read(_UPSTREAM_BODY_LIMIT + 1)
    except (OSError, URLError, UpstreamHttpError, ValueError):
        raise HTTPException(503, "auth_unavailable") from None
    if len(body) > _UPSTREAM_BODY_LIMIT:
        raise HTTPException(503, "auth_unavailable")
    try:
        result = json.loads(body) if body else {}
    except (ValueError, UnicodeError):
        result = None
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
    return _Session(access, refresh, expires_in, _profile(data.get("user")))


def _cookie_options(config: _AuthConfig):
    return {"httponly": True, "secure": config.secure_cookie, "samesite": "lax", "path": _ACCOUNT_PATH}


def _set_session(response: Response, config: _AuthConfig, session: _Session):
    options = _cookie_options(config)
    response.set_cookie(_ACCESS_COOKIE, session.access, max_age=session.expires_in, **options)
    response.set_cookie(_REFRESH_COOKIE, session.refresh, max_age=_REFRESH_AGE, **options)


def _clear_session(response: Response, config: _AuthConfig):
    options = _cookie_options(config)
    response.delete_cookie(_ACCESS_COOKIE, **options)
    response.delete_cookie(_REFRESH_COOKIE, **options)


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
    if _ACCESS_TOKEN.fullmatch(access):
        status, data = _supabase_request(config, "GET", "/user", token=access)
        if status == 200:
            return {"enabled": True, "user": _profile(data)}
        if status not in (401, 403):
            _provider_failure(status)
    if _REFRESH_TOKEN.fullmatch(refresh):
        session = _refresh(config, refresh)
        if session:
            _set_session(response, config, session)
            return {"enabled": True, "user": session.user}
    if access or refresh:
        _clear_session(response, config)
    return {"enabled": True, "user": None}


@account_router.post("/register", status_code=202)
def register_account(payload: _Registration, config: _AuthConfig = Depends(_write_config)):
    status, settings = _supabase_request(config, "GET", "/settings")
    if status != 200 or settings.get("mailer_autoconfirm") is not False:
        _provider_failure(status)
    status, data = _supabase_request(config, "POST", "/signup", {
        "email": payload.email,
        "password": payload.password,
        "data": {"display_name": payload.displayName},
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
    status, data = _supabase_request(config, "POST", "/token?grant_type=password", payload.model_dump())
    code = _error_code(data)
    if status == 200:
        session = _session(data)
        _set_session(response, config, session)
        return {"enabled": True, "user": session.user}
    if code == "email_not_confirmed":
        raise HTTPException(403, "email_unconfirmed")
    if status in (400, 401, 403, 422):
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


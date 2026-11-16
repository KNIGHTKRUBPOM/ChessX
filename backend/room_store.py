"""Shared online room persistence via server-only Supabase RPCs."""

from dataclasses import dataclass, field
from hmac import digest
import json
import os
import re
from urllib.error import URLError
from urllib.request import Request

from fastapi import HTTPException

from .supabase_http import opener, parse_origin

_SECRET_KEY = re.compile(r"sb_secret_[A-Za-z0-9_-]{1,128}")
_MAX_RPC_BODY = 256 * 1024


def rooms_unavailable():
    return HTTPException(503, "rooms_unavailable")


@dataclass(frozen=True)
class SupabaseRoomStore:
    origin: str
    secret_key: str = field(repr=False)

    def _rpc(self, operation: str, payload: dict):
        path = self.origin + "/rest/v1/rpc/chessmess_room_" + operation
        request = Request(
            path, data=json.dumps(payload).encode("utf-8"), method="POST",
            headers={"apikey": self.secret_key, "Accept": "application/json", "Content-Type": "application/json"},
        )
        try:
            with opener.open(request, timeout=4) as response:
                body = response.read(_MAX_RPC_BODY + 1)
            if len(body) <= _MAX_RPC_BODY:
                return json.loads(body)
        except (OSError, URLError, ValueError):
            pass
        # Transport failures on writes can occur after Postgres commits. Do not resend them.
        raise rooms_unavailable()

    def private_source_id(self, source: str) -> str:
        return digest(self.secret_key.encode("ascii"), ("rooms:" + source).encode("utf-8"), "sha256").hex()

    def health(self):
        if self._rpc("health", {}) is not True:
            raise rooms_unavailable()

    def create(self, code: str, room_id: str, source: str, payload: dict) -> dict:
        result = self._rpc("create", {
            "p_code": code, "p_room_id": room_id, "p_source": self.private_source_id(source), "p_payload": payload,
        })
        if not isinstance(result, dict):
            raise rooms_unavailable()
        return result

    def read(self, code: str) -> dict | None:
        result = self._rpc("read", {"p_code": code})
        if result is not None and not isinstance(result, dict):
            raise rooms_unavailable()
        return result

    def commit(self, code: str, room_id: str, revision: int, payload: dict | None, short_lived: bool) -> bool:
        result = self._rpc("commit", {
            "p_code": code, "p_room_id": room_id, "p_revision": revision,
            "p_payload": payload, "p_short_lived": short_lived,
        })
        if type(result) is not bool:
            raise rooms_unavailable()
        return result


def configured_room_store() -> SupabaseRoomStore | None:
    mode = os.getenv("CHESS_ROOM_STORE", "memory").strip().casefold()
    if mode == "memory":
        return None
    production = os.getenv("CHESS_ENV", "").casefold() == "production"
    origin = parse_origin(os.getenv("SUPABASE_URL", ""), allow_http_loopback=not production)
    secret_key = os.getenv("SUPABASE_SECRET_KEY", "").strip()
    if mode != "supabase" or not origin or not _SECRET_KEY.fullmatch(secret_key):
        raise rooms_unavailable()
    return SupabaseRoomStore(origin, secret_key)

"""Shared URL validation and HTTP transport for Supabase requests from FastAPI."""

import re
from urllib.parse import urlsplit
from urllib.request import HTTPRedirectHandler, build_opener


_HOST = re.compile(r"[A-Za-z0-9.-]+")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1"}


class _BlockRedirects(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


opener = build_opener(_BlockRedirects())


def parse_origin(value: str, *, allow_http_loopback: bool = False) -> str | None:
    try:
        url = urlsplit(value.strip())
        host = url.hostname
        port = url.port
    except ValueError:
        return None
    if (not host or (host != "::1" and not _HOST.fullmatch(host)) or
            url.username is not None or url.password is not None or
            url.path not in ("", "/") or url.query or url.fragment):
        return None
    if url.scheme != "https" and not (allow_http_loopback and url.scheme == "http" and host in _LOCAL_HOSTS):
        return None
    authority = "[::1]" if host == "::1" else host
    default_port = 443 if url.scheme == "https" else 80
    if port is not None and port != default_port:
        authority += f":{port}"
    return f"{url.scheme}://{authority}"

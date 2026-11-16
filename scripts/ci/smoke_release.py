"""Smoke-test the approved deployed top-level routes and OAuth initiation."""

from argparse import ArgumentParser
import json
import os
import re
import time
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlsplit
from urllib.request import Request

from release import HTTP, ReleaseError, target


def send(url, operation, payload=None, app_origin=None):
    headers = {"Accept": "application/json" if urlsplit(url).path.startswith("/api/") else "text/html"}
    data = None
    if payload is not None:
        data = json.dumps(payload).encode()
        headers.update({"Content-Type": "application/json", "Origin": app_origin})
    for attempt in range(4):
        try:
            with HTTP.open(Request(url, data=data, headers=headers), timeout=15) as response:
                limit = 524_288
                contents = response.read(limit + 1)
                if len(contents) > limit:
                    raise ReleaseError(f"{operation} returned an unexpectedly large response.")
                return response.headers, contents
        except HTTPError as error:
            code = error.code
            error.close()
            if code < 500 or attempt == 3:
                raise ReleaseError(f"{operation} responded HTTP {code}.") from None
        except (URLError, OSError):
            if attempt == 3:
                raise ReleaseError(f"{operation} could not be reached.") from None
        time.sleep(3)
    raise ReleaseError(f"{operation} could not be verified.")


def check_provider_url(start_url, ref, provider, app_origin):
    url = urlsplit(start_url)
    expected = f"{ref}.supabase.co"
    query = parse_qs(url.query)
    if (
        url.scheme != "https" or url.netloc != expected or url.path != "/auth/v1/authorize"
        or url.fragment or query.get("provider") != [provider]
        or query.get("redirect_to") != [app_origin + "/api/account/oauth/callback"]
        or [v.lower() for v in query.get("code_challenge_method", [])] != ["s256"]
        or not re.fullmatch(r"[A-Za-z0-9_-]{43}", "".join(query.get("code_challenge", [])))
    ):
        raise ReleaseError(f"{provider} redirect or PKCE challenge does not match the release environment.")


def run_smoke(environment):
    ref, _, app_origin = target(environment)
    headers, page = send(app_origin + "/", "Homepage")
    if b"<html" not in page.lower() or "text/html" not in headers.get("content-type", ""):
        raise ReleaseError("The deployment did not return the game homepage.")
    if "frame-ancestors 'none'" not in headers.get("content-security-policy", ""):
        raise ReleaseError("The deployed homepage is missing frame-ancestors protection.")

    _, body = send(app_origin + "/api/health", "Game API")
    if json.loads(body).get("engine") != "python":
        raise ReleaseError("The game API health check reported a failure.")
    _, body = send(app_origin + "/api/rooms/health", "Online rooms")
    if json.loads(body).get("online") is not True:
        raise ReleaseError("Online rooms did not confirm a database connection.")

    response_headers, body = send(app_origin + "/api/account", "Account health")
    if "no-store" not in response_headers.get("cache-control", ""):
        raise ReleaseError("Account responses should not be cached.")
    expected_enabled = os.environ.get("CHESS_ACCOUNT_ENABLED") == "1"
    if json.loads(body).get("enabled") is not expected_enabled:
        raise ReleaseError("Account health does not match its deployment flag.")
    if expected_enabled:
        for provider in ("google", "facebook"):
            _, body = send(
                app_origin + "/api/account/oauth", f"{provider} OAuth start",
                payload={"provider": provider}, app_origin=app_origin,
            )
            check_provider_url(json.loads(body).get("url", ""), ref, provider, app_origin)
    print("Homepage, game API, online database and configured OAuth initiation verified.")


if __name__ == "__main__":
    parser = ArgumentParser(description=__doc__)
    parser.add_argument("environment", choices=["staging", "production"])
    args = parser.parse_args()
    try:
        run_smoke(args.environment)
    except (ReleaseError, ValueError, TypeError, AttributeError) as error:
        explanation = str(error) if isinstance(error, ReleaseError) else type(error).__name__
        parser.exit(1, f"Smoke failed: {explanation}\n")

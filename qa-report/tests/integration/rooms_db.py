"""Offline integration suite for the Supabase room adapter."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from copy import deepcopy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import os
from pathlib import Path
import re
import shutil
import socket
import ssl
import subprocess
from tempfile import TemporaryDirectory
from threading import Barrier, Lock, Thread
from time import monotonic, sleep
from urllib.error import HTTPError, URLError
from urllib.request import ProxyHandler, Request, build_opener

from run_qa import E, ROOT, record, report


FIXTURE_KEY = "sb_secret_offline_room_fixture"
WHITE_PLACEMENTS = {"lock": 48, "revive": 51, "friendly": 50, "push": 49}
BLACK_PLACEMENTS = {"lock": 8, "revive": 1, "friendly": 12, "push": 17, "duel": 17}


class SharedRoomFixture:
    """Minimal RPC contract double shared by independent app processes."""

    def __init__(self):
        self.rooms = {}
        self.lock = Lock()
        self.online = True
        self.sources = []
        self.budget = None
        self.cas = None
        self.conflicts = 0
        self.opener = build_opener(ProxyHandler({}))

    def query(self, operation, data):
        if not self.online:
            return 503, {"message": "Offline fixture backend"}
        if operation == "commit":
            cas = self.cas
            if cas and data["p_revision"] == cas[0]:
                cas[1].wait(timeout=5)
        with self.lock:
            if operation == "health":
                return 200, True
            code = data["p_code"]
            stored = self.rooms.get(code)
            if operation == "read":
                return 200, deepcopy(stored)
            if operation == "create":
                if stored is not None:
                    return 200, {"status": "collision"}
                source = data["p_source"]
                assert re.fullmatch(r"[a-f0-9]{64}", source)
                assert data["p_room_id"] == data["p_payload"]["audit_id"]
                self.sources.append(source)
                if self.budget is not None and self.sources.count(source) > self.budget:
                    return 200, {"status": "rate", "retry_after": 9}
                self.rooms[code] = data["p_payload"]
                return 200, {"status": "ok"}
            if operation == "commit":
                if (stored is None or stored["revision"] != data["p_revision"] or
                        stored["audit_id"] != data["p_room_id"]):
                    self.conflicts += 1
                    return 200, False
                payload = data["p_payload"]
                assert isinstance(data["p_short_lived"], bool)
                if payload is None:
                    del self.rooms[code]
                else:
                    assert payload["revision"] == data["p_revision"] + 1
                    self.rooms[code] = payload
                return 200, True
            raise AssertionError("Unknown room RPC")


@contextmanager
def mock_supabase():
    executable = shutil.which("openssl")
    if not executable and os.name == "nt":
        bundled_git = Path(os.environ.get("ProgramFiles", "C:/Program Files")) / "Git/usr/bin/openssl.exe"
        executable = str(bundled_git) if bundled_git.is_file() else None
    if not executable:
        raise RuntimeError("OpenSSL is required to generate an isolated loopback certificate")

    fixture = SharedRoomFixture()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *_):
            pass

        def do_POST(self):
            namespace = "/rest/v1/rpc/chessmess_room_"
            if self.headers.get("apikey") != FIXTURE_KEY or not self.path.startswith(namespace):
                status, payload = 403, {"message": "Invalid fixture request"}
            else:
                operation = self.path.removeprefix(namespace)
                received = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                status, payload = fixture.query(operation, received)
            encoded = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(encoded)))
            self.end_headers()
            self.wfile.write(encoded)

    with TemporaryDirectory(prefix="rpc-https-", dir=E) as tmp:
        cert, key = Path(tmp) / "certificate.pem", Path(tmp) / "key.pem"
        subprocess.run([
            executable, "req", "-new", "-x509", "-newkey", "rsa:2048", "-nodes", "-days", "1",
            "-subj", "/CN=127.0.0.1", "-addext", "subjectAltName=IP:127.0.0.1",
            "-keyout", str(key), "-out", str(cert),
        ], check=True, capture_output=True, timeout=10)
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(cert, key)
        with ThreadingHTTPServer(("127.0.0.1", 0), Handler) as httpd:
            httpd.socket = context.wrap_socket(httpd.socket, server_side=True)
            thread = Thread(target=httpd.serve_forever, daemon=True)
            thread.start()
            try:
                yield fixture, f"https://127.0.0.1:{httpd.server_port}", cert
            finally:
                httpd.shutdown()
                thread.join(timeout=5)


def request(opener, origin, method, path, body=None, token=None, headers=None):
    data = json.dumps(body).encode("utf-8") if body is not None else None
    extra = dict(headers or {})
    if data is not None:
        extra["Content-Type"] = "application/json"
    if token:
        extra["Authorization"] = f"Bearer {token}"
    req = Request(origin + path, method=method, data=data, headers=extra)
    try:
        res = opener.open(req, timeout=12)
    except HTTPError as err:
        res = err
    with res:
        raw = res.read()
        return res.status, {key.lower(): val for key, val in res.headers.items()}, json.loads(raw) if raw else None


@contextmanager
def worker(name, fixture, upstream, cert, **overrides):
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        port = listener.getsockname()[1]
    origin = f"http://127.0.0.1:{port}"
    python = ROOT / (".venv/Scripts/python.exe" if os.name == "nt" else ".venv/bin/python")
    env = dict(
        os.environ,
        SUPABASE_URL=upstream,
        SUPABASE_SECRET_KEY=FIXTURE_KEY,
        SUPABASE_PUBLISHABLE_KEY="",
        CHESS_ROOM_STORE="supabase",
        CHESS_ENV="production",
        SSL_CERT_FILE=str(cert),
        APP_ORIGIN="",
        NO_PROXY="127.0.0.1",
        PYTHONDONTWRITEBYTECODE="1",
    )
    env.update(overrides)
    with (E / f"rooms-{name}-server.log").open("w", encoding="utf-8") as log:
        process = subprocess.Popen([
            str(python), "-B", "-m", "uvicorn", "backend.app:app", "--host", "127.0.0.1",
            "--port", str(port), "--workers", "1", "--no-access-log",
        ], cwd=ROOT, env=env, stdout=log, stderr=subprocess.STDOUT)
        try:
            def client(method, path, **kwargs):
                return request(fixture.opener, origin, method, path, **kwargs)

            deadline = monotonic() + 10
            while monotonic() < deadline and process.poll() is None:
                try:
                    if client("GET", "/api/health")[0] == 200:
                        break
                except URLError:
                    pass
                sleep(0.05)
            else:
                raise RuntimeError(f"QA worker {name} did not start")
            yield client
        finally:
            if process.poll() is None:
                process.terminate()
                try:
                    process.wait(timeout=8)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def create(client, mode="hybrid"):
    status, _, result = client("POST", "/api/rooms", body={"mode": mode, "name": "QA player"})
    assert status == 200 and result["snapshot"]["phase"] == "waiting", status
    return "/api/rooms/" + result["snapshot"]["code"], result["token"]


def join(client, room):
    return client("POST", room + "/join", body={"name": "QA challenger"})


def setup(client, room, token, revision, placements):
    return client("POST", room + "/action", token=token, body={
        "type": "setup", "revision": revision, "placements": placements,
    })


@contextmanager
def same_revision(fixture, revision):
    fixture.cas = revision, Barrier(2)
    try:
        yield
    finally:
        fixture.cas = None


def parallel(first, second):
    with ThreadPoolExecutor(max_workers=2) as pool:
        left, right = map(pool.submit, (first, second))
        return left.result(), right.result()


def game_persists(fixture, upstream, cert):
    with worker("creator", fixture, upstream, cert) as create_worker:
        status, _, health = create_worker("GET", "/api/rooms/health")
        assert status == 200 and health == {"online": True, "version": 1}
        room, white = create(create_worker)
    # Drop the original process before starting two clean workers.
    with worker("white", fixture, upstream, cert) as left, worker("black", fixture, upstream, cert) as right:
        status, _, waiting = left("GET", room, token=white)
        assert status == 200 and waiting["phase"] == "waiting"
        with same_revision(fixture, waiting["revision"]):
            joined = parallel(lambda: join(left, room), lambda: join(right, room))
        assert sorted(result[0] for result in joined) == [200, 409], [row[0] for row in joined]
        black = next(result[2]["token"] for result in joined if result[0] == 200)
        setup_rev = next(result[2]["snapshot"]["revision"] for result in joined if result[0] == 200)

        with same_revision(fixture, setup_rev):
            placed = parallel(
                lambda: setup(left, room, white, setup_rev, WHITE_PLACEMENTS),
                lambda: setup(right, room, black, setup_rev, BLACK_PLACEMENTS),
            )
        assert [result[0] for result in placed] == [200, 200], [row[0] for row in placed]
        _, white_headers, white_view = left("GET", room, token=white)
        _, black_headers, black_view = right("GET", room, token=black)
        assert white_view["phase"] == black_view["phase"] == "play"
        assert white_view["revision"] == black_view["revision"] == setup_rev + 2
        assert white_view["myPlacements"] == black_view["myPlacements"] == {}
        assert white_view["board"][49]["skills"] == ["push"]
        assert "skills" not in white_view["board"][17]
        assert black_view["board"][17]["skills"] == ["push", "duel"]
        assert "skills" not in black_view["board"][49]
        assert white_headers["cache-control"] == black_headers["cache-control"] == "no-store"
        assert white_headers["etag"] != black_headers["etag"]
        assert right("GET", room, token=white, headers={"If-None-Match": white_headers["etag"]})[0] == 304
        assert right("GET", room, headers={"If-None-Match": white_headers["etag"]})[0] == 401
        with fixture.lock:
            stored = fixture.rooms[room.rsplit("/", 1)[-1]]
            encoded = json.dumps(stored)
            assert white not in encoded and black not in encoded and FIXTURE_KEY not in encoded
            assert all(re.fullmatch(r"[a-f0-9]{64}", seat["secret_hash"]) for seat in stored["seats"].values())

        revision = white_view["revision"]
        action = {"type": "move", "revision": revision, "move": {"from": 49, "to": 33}}
        with same_revision(fixture, revision):
            moved = parallel(
                lambda: left("POST", room + "/action", token=white, body=action),
                lambda: right("POST", room + "/action", token=white, body=action),
            )
        assert sorted(result[0] for result in moved) == [200, 409], [row[0] for row in moved]
        status, _, next_view = right("GET", room, token=black)
        assert status == 200 and next_view["revision"] == revision + 1
        assert next_view["board"][49] is None and next_view["board"][33]["side"] == "w"

        assert fixture.conflicts >= 3

        def move(client, token, revision, start, end):
            return client("POST", room + "/action", token=token, body={
                "type": "move", "revision": revision, "move": {"from": start, "to": end},
            })

        assert move(right, black, next_view["revision"], 17, 24)[0] == 200
        status, _, duel_view = move(left, white, next_view["revision"] + 1, 33, 24)
        assert status == 200 and duel_view["phase"] == "duel"
        revision = duel_view["revision"]
        for client, token, cell in [
            (left, black, 0), (right, white, 3), (right, black, 1), (left, white, 4), (left, black, 2),
        ]:
            status, _, result = client("POST", room + "/action", token=token, body={
                "type": "duel", "revision": revision, "cell": cell,
            })
            assert status == 200, status
            revision += 1
        status, _, end_view = right("GET", room, token=white)
        assert status == 200 and end_view["phase"] == "play"
        assert end_view["lastDuel"]["board"]["winner"] == "b"
        assert end_view["board"][33] is None and end_view["board"][24]["side"] == "b"

        assert left("DELETE", room + "/seat", token=white)[0] == 204
        assert right("GET", room, token=white)[0] == 401
        assert right("GET", room, token=black)[0] == 410
        assert right("DELETE", room + "/seat", token=black)[0] == 204
        assert left("GET", room, token=black)[0] == 404
    return "Restart + two processes, parallel join/setup/move, private skills, and shared revocation"


def shared_create_quota(fixture, upstream, cert):
    fixture.budget = 1
    try:
        with worker("quota-a", fixture, upstream, cert) as left, worker("quota-b", fixture, upstream, cert) as right:
            endpoint = "/api/rooms"
            payload = {"mode": "chess", "name": "QA player"}
            responses = parallel(
                lambda: left("POST", endpoint, body=payload),
                lambda: right("POST", endpoint, body=payload),
            )
            assert sorted(row[0] for row in responses) == [200, 429], [row[0] for row in responses]
            limited = next(row for row in responses if row[0] == 429)
            assert limited[1]["retry-after"] == "9"
            assert fixture.sources[-1] == fixture.sources[-2]
    finally:
        fixture.budget = None
    return "Distributed create surfaces provider quota and Retry-After"


def provider_unavailable(fixture, upstream, cert):
    with worker("outage", fixture, upstream, cert) as client:
        room, token = create(client, "chess")
        fixture.online = False
        try:
            for method, path, kwargs in [
                ("GET", "/api/rooms/health", {}),
                ("GET", room, {"token": token}),
                ("POST", "/api/rooms", {"body": {"mode": "chess", "name": "QA player"}}),
            ]:
                status, headers, result = client(method, path, **kwargs)
                assert (status, result) == (503, {"detail": "rooms_unavailable"}), (status, result)
                assert headers["cache-control"] == "no-store"
            assert client("GET", "/api/health")[0] == 200
            assert client("POST", "/api/game/start", body={"mode": "chess"})[0] == 200
        finally:
            fixture.online = True
        assert client("GET", room, token=token)[0] == 200
    return "Database outage returns safe 503, disallows fallback, and leaves solo game available"


def missing_config(fixture, upstream, cert):
    with worker("missing-config", fixture, upstream, cert, SUPABASE_SECRET_KEY="") as client:
        status, _, result = client("GET", "/api/rooms/health")
        assert (status, result) == (503, {"detail": "rooms_unavailable"}), (status, result)
        assert client("POST", "/api/game/start", body={"mode": "chess"})[0] == 200
    return "Explicit persistent store requires configured credentials"


def suite():
    results = []
    for id, check in [
        ("ROOM-DB-CROSS-PROCESS", game_persists),
        ("ROOM-DB-SHARED-QUOTA", shared_create_quota),
        ("ROOM-DB-UNAVAILABLE", provider_unavailable),
        ("ROOM-DB-MISSING-CONFIG", missing_config),
    ]:
        def scenario(check=check):
            with mock_supabase() as (fixture, upstream, cert):
                return check(fixture, upstream, cert)
        record(id, scenario, results)
    return report("rooms-db", results)

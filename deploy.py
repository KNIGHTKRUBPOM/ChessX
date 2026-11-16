"""Run the one-worker production service or check its release on loopback."""

import argparse
import http.client
import json
import os
from pathlib import Path
import socket
from threading import Thread
import time

import uvicorn


APP = "backend.app:app"
LOOPBACK = "127.0.0.1"
DIST_INDEX = Path(__file__).resolve().parent / "dist" / "index.html"


def production_config(host, port):
    return uvicorn.Config(
        APP, host=host, port=port, workers=1, access_log=False, server_header=False,
    )


def check_http(port):
    connection = http.client.HTTPConnection(LOOPBACK, port, timeout=3)

    def expect(path, status):
        connection.request("GET", path)
        response = connection.getresponse()
        body = response.read()
        if response.status != status:
            raise RuntimeError(f"{path} returned {response.status}, expected {status}")
        return response.headers, body

    try:
        headers, _ = expect("/", 200)
        if not headers.get("Content-Type", "").startswith("text/html"):
            raise RuntimeError("The production index must be served as HTML")
        if "frame-ancestors 'none'" not in headers.get("Content-Security-Policy", ""):
            raise RuntimeError("The production index is missing frame restrictions")
        _, health = expect("/api/health", 200)
        if json.loads(health).get("engine") != "python":
            raise RuntimeError("Game API health returned an unexpected engine")
        expect("/api/rooms/health", 200)
        for path in ("/docs", "/redoc", "/openapi.json", "/docs/oauth2-redirect"):
            expect(path, 404)
    finally:
        connection.close()


def check_release():
    with socket.socket() as listener:
        listener.bind((LOOPBACK, 0))
        port = listener.getsockname()[1]
        server = uvicorn.Server(production_config(LOOPBACK, port))
        thread = Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
        thread.start()
        try:
            deadline = time.monotonic() + 8
            while not server.started and thread.is_alive() and time.monotonic() < deadline:
                time.sleep(0.05)
            if not server.started:
                raise RuntimeError("The production server did not start")
            check_http(port)
        finally:
            server.should_exit = True
            thread.join(timeout=5)
        if thread.is_alive():
            raise RuntimeError("The release check server did not shut down")
    print("Production release check passed")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="Check the built release on loopback")
    args = parser.parse_args()
    if not DIST_INDEX.is_file():
        parser.exit(1, "Build dist with npm run build before releasing.\n")
    os.environ["CHESS_ENV"] = "production"
    if args.check:
        check_release()
        return
    config = production_config("0.0.0.0", int(os.environ.get("PORT", "8000")))
    uvicorn.Server(config).run()


if __name__ == "__main__":
    main()


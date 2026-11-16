import argparse
import http.client
import socket
import threading
import time
import webbrowser

import uvicorn

HOST = "127.0.0.1"
PORT = 3210


def browser_url():
    # Vite can occupy the IPv6 loopback address while FastAPI uses IPv4.
    try:
        with socket.create_connection(("::1", PORT), timeout=0.25):
            print("Another service owns localhost on IPv6. Opening the IPv4 game URL instead.")
            return f"http://{HOST}:{PORT}/"
    except OSError:
        return f"http://localhost:{PORT}/"


def open_game(server):
    while not server.started:
        if server.should_exit:
            return
        time.sleep(0.05)
    webbrowser.open(browser_url())


def already_running():
    connection = http.client.HTTPConnection(HOST, PORT, timeout=0.5)
    try:
        connection.request("GET", "/api/health")
        response = connection.getresponse()
        return response.status == 200 and response.read(80) == b'{"engine":"python","version":1}'
    except (OSError, http.client.HTTPException):
        return False
    finally:
        connection.close()


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--open", action="store_true", help="Open the game in the default browser")
    args = parser.parse_args()

    if already_running():
        if args.open:
            webbrowser.open(browser_url())
        return

    # Invite codes may appear in API paths and page query strings.
    server = uvicorn.Server(uvicorn.Config("backend.app:app", host=HOST, port=PORT, access_log=False))
    if args.open:
        threading.Thread(target=open_game, args=(server,), daemon=True).start()
    server.run()


if __name__ == "__main__":
    main()

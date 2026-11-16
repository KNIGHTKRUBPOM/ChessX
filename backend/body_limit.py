from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

MAX_API_BODY_BYTES = 64 * 1024


class ApiBodyLimit:
    """Bound write bodies before FastAPI parses JSON, including streamed requests."""

    def __init__(self, app: ASGIApp, max_bytes: int = MAX_API_BODY_BYTES):
        self.app = app
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if (
            scope["type"] != "http"
            or not (scope["path"] == "/api" or scope["path"].startswith("/api/"))
            or scope["method"] not in {"POST", "PUT", "PATCH", "DELETE"}
        ):
            await self.app(scope, receive, send)
            return

        too_large = JSONResponse({"detail": "Request body is too large."}, status_code=413)
        for header, value in scope["headers"]:
            if header == b"content-length" and value.isdigit():
                length = value.lstrip(b"0")
                # Limit integer parsing to values with as many digits as the cap.
                cap = str(self.max_bytes).encode("ascii")
                if len(length) > len(cap) or (len(length) == len(cap) and length > cap):
                    await too_large(scope, receive, send)
                    return

        body = bytearray()
        while True:
            message = await receive()
            if message["type"] == "http.disconnect":
                return
            chunk = message.get("body", b"")
            if len(body) + len(chunk) > self.max_bytes:
                await too_large(scope, receive, send)
                return
            body.extend(chunk)
            if not message.get("more_body", False):
                break

        # Release the buffer after replaying a complete request to the framework.
        replay: Message | None = {"type": "http.request", "body": bytes(body), "more_body": False}
        del body

        async def replay_body() -> Message:
            nonlocal replay
            if replay is None:
                return await receive()
            message, replay = replay, None
            return message

        await self.app(scope, replay_body, send)

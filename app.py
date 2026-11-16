"""Expose the production FastAPI app to Vercel's Python runtime."""

import os


def _load_app():
    os.environ["CHESS_ENV"] = "production"
    os.environ["CHESS_ROOM_STORE"] = "supabase"

    from backend.app import app

    return app


app = _load_app()

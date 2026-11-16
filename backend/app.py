from collections import Counter
from os import getenv
from pathlib import Path
import re

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles

from . import duel_rules, hybrid_rules
from .account import account_router
from .body_limit import ApiBodyLimit
from .game import DECK, ENGINES, deck_for, outcome_for, uses_discs
from .rooms import room_router
from .models import (
    DuelRequest, FinishDuelRequest, MoveRequest, SetupRequest, StartRequest, StateRequest,
)

production = getenv("CHESS_ENV", "").casefold() == "production"
app = FastAPI(
    title="Hidden Command Chess",
    version="1",
    docs_url=None if production else "/docs",
    redoc_url=None if production else "/redoc",
    openapi_url=None if production else "/openapi.json",
)
app.include_router(room_router)
app.include_router(account_router)
app.add_middleware(ApiBodyLimit)

hashed_asset = re.compile(r"/assets/(?:[^/]+/)*[^/]+-[A-Za-z0-9_-]{8}\.[A-Za-z0-9]+")

game_csp = (
    "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)
docs_csp = (
    "default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; "
    "style-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net https://fonts.googleapis.com; "
    "font-src 'self' https://fonts.gstatic.com; img-src 'self' data: https://fastapi.tiangolo.com; "
    "connect-src 'self'; object-src 'none'; base-uri 'self'; "
    "form-action 'self'; frame-ancestors 'none'"
)


@app.middleware("http")
async def security_headers(request: Request, call_next):
    response = await call_next(request)
    docs_page = not production and request.url.path in {"/docs", "/redoc", "/docs/oauth2-redirect"}
    response.headers["Content-Security-Policy"] = docs_csp if docs_page else game_csp
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    path = request.url.path
    if path.startswith(("/api/rooms", "/api/account")):
        response.headers["Cache-Control"] = "no-store"
    elif request.method in {"GET", "HEAD"} and response.status_code in {200, 206, 304}:
        if hashed_asset.fullmatch(path):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif path in {"/", "/index.html"}:
            response.headers["Cache-Control"] = "no-cache"
    return response


def invalid_position():
    raise HTTPException(422, "Invalid position for this mode.")


def game_state(request):
    state = request.state.model_dump(exclude_unset=True)
    mode = request.mode
    if state["hybrid"] != (mode == "hybrid"):
        invalid_position()
    if (mode != "chess" and state["pending"] is not None) or (mode != "hybrid" and state["duelWin"] is not None):
        invalid_position()
    if mode != "chess" and state["enPassant"] is not None:
        invalid_position()
    chain = state["chain"]
    if chain is not None:
        actor = state["board"][chain["at"]]
        if not uses_discs(mode, state["turn"]) or not actor or actor["side"] != state["turn"]:
            invalid_position()
    resolution = state["resolution"]
    if resolution is not None and (mode == "chess" or (mode == "draughts" and resolution["kind"] != "draughts")):
        invalid_position()

    ids = set()
    for piece in state["board"]:
        if piece is None:
            continue
        side, kind, piece_id = piece["side"], piece["type"], piece["id"]
        if piece_id in ids or piece_id >= state["nextId"]:
            invalid_position()
        ids.add(piece_id)
        if (uses_discs(mode, side) and kind not in ("p", "h")) or (not uses_discs(mode, side) and kind == "h"):
            invalid_position()
        if mode == "hybrid":
            cards = piece.get("cards", [])
            if "card" in piece or (side == "w" and len(cards) > 1) or any(card not in deck_for(mode, side) for card in cards):
                invalid_position()
        elif "cards" in piece or ("card" in piece and piece["card"] not in DECK):
            invalid_position()
    return state


def snapshot(mode, state, options=None):
    if options is None:
        options = ENGINES[mode].turn_options(state)
    return {"state": state, "options": options, "outcome": outcome_for(mode, state, options)}


def matching_move(mode, state, choice):
    options = ENGINES[mode].turn_options(state)
    if outcome_for(mode, state, options):
        raise HTTPException(409, "The game is over.")
    for move in options["moves"]:
        if all(move.get(key) == choice.get(key) for key in ("from", "to", "promote")):
            return move, options
    raise HTTPException(422, "This move is not legal in the current position.")


def reachable_duel(target):
    def visit(board):
        if board == target:
            return True
        if board["done"]:
            return False
        return any(
            visit(duel_rules.play(board, index))
            for index, side in enumerate(target["cells"])
            if board["cells"][index] is None and side == board["turn"]
        )

    return visit(duel_rules.start())


def validate_duel(request):
    if request.mode != "hybrid":
        raise HTTPException(409, "Tic Tac Toe is available in the hybrid mode.")
    state = game_state(request)
    move = request.duel.move.model_dump(by_alias=True, exclude_unset=True)
    legal, options = matching_move(request.mode, state, move)
    if move != legal or not hybrid_rules.challenges(state, legal):
        raise HTTPException(422, "This capture does not start a duel.")
    board = request.duel.board.model_dump()
    if not reachable_duel(board):
        raise HTTPException(422, "Invalid Tic Tac Toe position.")
    return state, legal, options, board


@app.get("/api/health")
def health():
    return {"engine": "python", "version": 1}


@app.post("/api/game/start")
def start_game(request: StartRequest):
    return snapshot(request.mode, ENGINES[request.mode].start())


@app.post("/api/game/options")
def options(request: StateRequest):
    return snapshot(request.mode, game_state(request))


@app.post("/api/game/setup")
def setup(request: SetupRequest):
    mode, side = request.mode, request.side
    state = game_state(request)
    cards = deck_for(mode, side)
    placements = request.placements
    if placements.keys() != set(cards):
        raise HTTPException(422, "Place every command for this side.")
    counts = Counter(placements.values())
    if max(counts.values()) > (2 if mode == "hybrid" and side == "b" else 1):
        raise HTTPException(422, "Too many commands on one piece.")

    original = ENGINES[mode].start()
    if any(state[key] != value for key, value in original.items() if key != "board"):
        raise HTTPException(409, "Setup is available before the first move.")
    existing = []
    for piece, base in zip(state["board"], original["board"], strict=True):
        if piece:
            without_cards = {key: value for key, value in piece.items() if key not in ("card", "cards")}
            if without_cards != base:
                raise HTTPException(409, "Setup requires the opening position.")
            assigned = piece.get("cards", []) if mode == "hybrid" else [piece["card"]] if "card" in piece else []
            if assigned and (side == "w" or piece["side"] != "w" or piece["type"] == "k"):
                raise HTTPException(409, "This side already placed its commands.")
            existing.extend(assigned)
        elif base is not None:
            raise HTTPException(409, "Setup requires the opening position.")
    if side == "b" and Counter(existing) != Counter(DECK):
        raise HTTPException(409, "White must place its commands first.")

    for card in cards:
        piece = state["board"][placements[card]]
        if not piece or piece["side"] != side or piece["type"] == "k":
            raise HTTPException(422, "Place commands under your own pieces, except the king.")
        if mode == "hybrid":
            piece.setdefault("cards", []).append(card)
        else:
            piece["card"] = card
    return snapshot(mode, state)


@app.post("/api/game/move")
def play_move(request: MoveRequest):
    mode = request.mode
    state = game_state(request)
    choice = request.move.model_dump(by_alias=True)
    move, options = matching_move(mode, state, choice)
    if mode == "hybrid" and hybrid_rules.challenges(state, move):
        return {**snapshot(mode, state, options), "duel": {"move": move, "board": duel_rules.start()}}
    engine = ENGINES[mode]
    next_state = engine.play(state, move) if mode == "chess" else engine.play(state, move, options)
    return {**snapshot(mode, next_state), "duel": None}


@app.post("/api/game/duel")
def play_duel(request: DuelRequest):
    _, move, _, board = validate_duel(request)
    if board["done"] or board["cells"][request.cell]:
        raise HTTPException(409, "This Tic Tac Toe cell is unavailable.")
    return {"duel": {"move": move, "board": duel_rules.play(board, request.cell)}}


@app.post("/api/game/duel/finish")
def finish_duel(request: FinishDuelRequest):
    state, move, options, board = validate_duel(request)
    if not board["done"]:
        raise HTTPException(409, "Finish Tic Tac Toe before resolving the capture.")
    state = hybrid_rules.play(state, move, options, board["winner"])
    return {**snapshot(request.mode, state), "duel": None}


dist = Path(__file__).resolve().parent.parent / "dist"
if (dist / "index.html").is_file():
    # Compress public build artifacts only, never API responses with seat tokens.
    app.mount("/", GZipMiddleware(StaticFiles(directory=dist, html=True)), name="game")

"""Invite-only online matches backed by memory or shared Supabase storage."""

from collections import Counter, deque
from collections.abc import Mapping
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from hashlib import sha256
from hmac import compare_digest, digest as hmac_digest
from ipaddress import ip_address
import json
import logging
from math import ceil
import os
from secrets import choice, token_urlsafe
from threading import Lock
from time import monotonic
from typing import Annotated, Literal, NoReturn
from unicodedata import category, normalize
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from pydantic import Field, field_validator

from . import chess_rules, duel_rules, hybrid_rules
from .game import ENGINES, deck_for, outcome_for
from .models import Card, Cell, DataModel, Mode, MoveChoice, Side, Square
from .room_store import SupabaseRoomStore, configured_room_store, rooms_unavailable

CODE_ALPHABET = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
ROOM_LIMIT = 256
ROOM_LIFETIME = 6 * 60 * 60
WAITING_ROOM_LIFETIME = 15 * 60
SOURCE_ROOM_LIMIT = 16
CREATE_LIMIT = 12
CREATE_WINDOW = 60
HISTORY_LIMIT = 30
_logger = logging.getLogger("uvicorn.error")


class NoStoreResponse(JSONResponse):
    def __init__(self, content, status_code: int = 200, *, headers=None, **kwargs):
        super().__init__(
            content, status_code=status_code,
            headers={**(headers or {}), "Cache-Control": "no-store"}, **kwargs,
        )


room_router = APIRouter(
    prefix="/api/rooms", tags=["online rooms"], default_response_class=NoStoreResponse
)
bearer = HTTPBearer(auto_error=False)
Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(bearer)]


class PlayerRequest(DataModel):
    name: str = Field(max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        display_name = " ".join(normalize("NFKC", value).split())
        if not 1 <= len(display_name) <= 24 or any(category(char)[0] == "C" for char in display_name):
            raise ValueError("Use a display name of 1–24 characters.")
        return display_name


class CreateRoomRequest(PlayerRequest):
    mode: Mode


class Action(DataModel):
    revision: int = Field(ge=0)


class SetupAction(Action):
    type: Literal["setup"]
    placements: dict[Card, Square]


class MoveAction(Action):
    type: Literal["move"]
    move: MoveChoice


class DuelAction(Action):
    type: Literal["duel"]
    cell: Cell


RoomAction = Annotated[SetupAction | MoveAction | DuelAction, Field(discriminator="type")]


@dataclass
class Seat:
    name: str
    secret_hash: bytes | None


@dataclass
class Room:
    code: str
    mode: Mode
    state: chess_rules.GameState
    seats: dict[Side, Seat]
    created_by: str = ""
    audit_id: str = field(default_factory=lambda: uuid4().hex)
    revision: int = 0
    changed_at: float = field(default_factory=monotonic)
    placements: dict[Side, dict[Card, int]] = field(default_factory=dict)
    options: chess_rules.TurnOptions | None = None
    outcome: dict | None = None
    last_move: chess_rules.Move | None = None
    notice: dict | None = None
    duel: dict | None = None
    last_duel: dict | None = None
    history: list[dict] = field(default_factory=list)

    @property
    def phase(self):
        if "b" not in self.seats:
            return "waiting"
        if len(self.placements) < 2:
            return "setup"
        if self.duel is not None:
            return "duel"
        return "finished" if self.outcome is not None else "play"

    @property
    def has_departed_seat(self) -> bool:
        return any(seat.secret_hash is None for seat in self.seats.values())

    def advance(self):
        self.revision += 1
        self.changed_at = monotonic()

    def refresh_options(self):
        self.options = ENGINES[self.mode].turn_options(self.state)
        self.outcome = outcome_for(self.mode, self.state, self.options)


_rooms: dict[str, Room] = {}
_creations: deque[tuple[float, str]] = deque()
_rooms_lock = Lock()


def _audit(event: str, room: Room | None = None, **fields: str | int):
    record: dict[str, str | int] = {
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"), "event": event, **fields,
    }
    if room is not None:
        record["room_id"] = room.audit_id
        record["revision"] = room.revision
    _logger.info("%s", json.dumps(record, separators=(",", ":")))


def _remove_expired_rooms(now: float | None = None):
    if now is None:
        now = monotonic()
    expired = [
        code for code, room in _rooms.items()
        if now - room.changed_at >= (
            WAITING_ROOM_LIFETIME if room.phase == "waiting" or room.has_departed_seat else ROOM_LIFETIME
        )
    ]
    for code in expired:
        _audit("room_expired", _rooms[code])
        del _rooms[code]


def _enforce_creation_quota(source: str, now: float):
    while _creations and now - _creations[0][0] >= CREATE_WINDOW:
        _creations.popleft()
    recent_creations = [created for created, creator in _creations if creator == source]
    if len(recent_creations) >= CREATE_LIMIT:
        retry_after = max(1, ceil(CREATE_WINDOW - (now - recent_creations[0])))
        _audit("room_create_denied", reason="rate", status=429)
        raise HTTPException(
            429, "Too many recent rooms. Try again shortly.",
            headers={"Retry-After": str(retry_after)},
        )
    if sum(room.created_by == source for room in _rooms.values()) >= SOURCE_ROOM_LIMIT:
        _audit("room_create_denied", reason="active_quota", status=429)
        raise HTTPException(429, "Too many active rooms from this connection.")


def _new_seat(name: str) -> tuple[str, Seat]:
    token = token_urlsafe(32)
    return token, Seat(name, sha256(token.encode("ascii")).digest())


def _find_room(code: str) -> Room:
    room = _rooms.get(code.upper())
    if room is None:
        raise HTTPException(404, "Room not found or expired.")
    return room


def _unauthorized(room: Room) -> NoReturn:
    _audit("room_authorization_denied", room, status=401)
    raise HTTPException(
        401,
        "This room requires a seat token.",
        headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"},
    )


def _seat_for(room: Room, credentials: HTTPAuthorizationCredentials | None) -> Side:
    if not credentials or len(credentials.credentials) != 43:
        _unauthorized(room)
    digest = sha256(credentials.credentials.encode("utf-8")).digest()
    for side, seat in room.seats.items():
        if seat.secret_hash is not None and compare_digest(digest, seat.secret_hash):
            return side
    _unauthorized(room)


def _active_seat(room: Room, credentials: HTTPAuthorizationCredentials | None) -> Side:
    side = _seat_for(room, credentials)
    if room.has_departed_seat:
        raise HTTPException(410, "room_seat_departed")
    return side


def _board_for(room: Room, side: Side):
    locks = room.state["locks"]
    board = []
    for piece in room.state["board"]:
        if piece is None:
            board.append(None)
            continue
        view = {
            "id": piece["id"], "type": piece["type"], "side": piece["side"],
            "locked": locks[piece["side"]] == piece["id"],
        }
        if piece["side"] == side:
            # Skill identity, count and position stay private to the owning seat.
            card = piece.get("card")
            view["skills"] = list(piece.get("cards", [])) if card is None else [card]
        board.append(view)
    return board


def _snapshot(room: Room, side: Side) -> dict:
    phase = room.phase
    turn = room.state["turn"]
    chain = room.state["chain"]
    options = room.options
    if room.mode == "chess" and options and options["forced"]:
        options = {**options, "card": room.state["pending"]}
    return {
        "code": room.code,
        "mode": room.mode,
        "side": side,
        "players": {seat: room.seats[seat].name if seat in room.seats else None for seat in ("w", "b")},
        "ready": {seat: seat in room.placements for seat in ("w", "b")},
        "phase": phase,
        "revision": room.revision,
        "board": _board_for(room, side),
        "turn": turn,
        "options": options if phase == "play" and turn == side else None,
        "outcome": room.outcome,
        "lastMove": room.last_move,
        "notice": room.notice,
        "duel": room.duel,
        "lastDuel": room.last_duel,
        "myPlacements": room.placements.get(side, {}) if phase == "setup" else {},
        "chainAt": chain["at"] if chain else None,
        "checked": bool(options and options.get("checked")),
        "history": room.history,
    }


def _place_skills(room: Room, side: Side, placements: Mapping[Card, int]):
    if room.phase != "setup" or side in room.placements:
        raise HTTPException(409, "This seat cannot place commands now.")
    deck = deck_for(room.mode, side)
    if set(placements) != set(deck):
        raise HTTPException(422, "Place every command for this side.")
    limit = 2 if room.mode == "hybrid" and side == "b" else 1
    if any(count > limit for count in Counter(placements.values()).values()):
        raise HTTPException(422, "Too many commands on one piece.")
    board = room.state["board"]
    for square in placements.values():
        piece = board[square]
        if piece is None or piece["side"] != side or piece["type"] == "k":
            raise HTTPException(422, "Place commands under your own pieces, except the king.")
    # Copy the pieces being edited so previous snapshots remain independent.
    board = board.copy()
    for card in deck:
        square = placements[card]
        piece = board[square]
        assert piece is not None
        if room.mode == "hybrid":
            board[square] = {**piece, "cards": [*piece.get("cards", []), card]}
        else:
            board[square] = {**piece, "card": card}
    room.state = {**room.state, "board": board}
    room.placements[side] = dict(placements)
    if len(room.placements) == 2:
        room.refresh_options()


def _commit_move(room: Room, move: chess_rules.Move, duel_result: duel_rules.DuelState | None = None):
    state = room.state
    actor = chess_rules.piece_at(state["board"], move.get("from"))
    captured = chess_rules.piece_at(state["board"], move.get("capture"))
    side = state["turn"]
    cards = []
    revealed_side = chess_rules.other(side)
    reversed_capture = False
    if room.mode == "chess":
        if captured and captured["side"] == revealed_side and captured.get("card"):
            cards = [captured["card"]]
        updated_state = chess_rules.play(state, move)
    else:
        engine = ENGINES[room.mode]
        if duel_result is not None:
            updated_state = hybrid_rules.play(state, move, room.options, duel_result["winner"])
        else:
            updated_state = engine.play(state, move, room.options)
        resolution = updated_state["resolution"]
        if resolution is not None:
            cards = resolution["cards"]
            reversed_capture = resolution.get("reversed", False)
            revealed_side = resolution.get("revealedSide", revealed_side)
    room.state = updated_state
    room.last_move = move
    room.notice = (
        {"cards": cards, "side": revealed_side, "revision": room.revision + 1}
        if cards else None
    )
    entry = {
        "side": side, "move": move, "actor": actor["type"] if actor else None,
        "captured": captured["type"] if captured else None, "cards": cards,
        "reversed": reversed_capture,
    }
    if duel_result is not None:
        entry["duelWinner"] = duel_result["winner"]
    room.history = [entry, *room.history[:HISTORY_LIMIT - 1]]
    room.refresh_options()


def _make_move(room: Room, side: Side, choice: MoveChoice):
    if room.phase != "play" or side != room.state["turn"]:
        raise HTTPException(409, "It is not this player's turn on the main board.")
    assert room.options is not None
    for move in room.options["moves"]:
        if (move.get("from"), move["to"], move.get("promote")) == (choice.source, choice.to, choice.promote):
            if room.mode == "hybrid" and hybrid_rules.challenges(room.state, move):
                room.duel = {"move": move, "board": duel_rules.start()}
                room.notice = None
            else:
                _commit_move(room, move)
            return
    raise HTTPException(422, "This move is not legal in the current position.")


def _play_duel(room: Room, side: Side, cell: int):
    duel = room.duel
    if duel is None or duel["board"]["turn"] != side:
        raise HTTPException(409, "It is not this player's Tic Tac Toe turn.")
    if duel["board"]["cells"][cell] is not None:
        raise HTTPException(422, "This Tic Tac Toe cell is unavailable.")
    board = duel_rules.play(duel["board"], cell)
    move = duel["move"]
    if board["done"]:
        _commit_move(room, move, board)
        room.last_duel = {"move": move, "board": board, "revision": room.revision + 1}
        room.duel = None
    else:
        room.duel = {"move": move, "board": board}


def _stored_payload(room: Room) -> dict:
    payload = asdict(room)
    del payload["created_by"], payload["changed_at"]
    payload["schema_version"] = 1
    for side, seat in room.seats.items():
        payload["seats"][side]["secret_hash"] = seat.secret_hash.hex() if seat.secret_hash is not None else None
    return payload


def _load_stored_room(store: SupabaseRoomStore, code: str) -> Room:
    code = code.upper()
    if len(code) != 8 or any(char not in CODE_ALPHABET for char in code):
        raise HTTPException(404, "Room not found or expired.")
    payload = store.read(code)
    if payload is None:
        raise HTTPException(404, "Room not found or expired.")
    data = payload.copy()
    if data.pop("schema_version", None) != 1 or data.get("code") != code:
        raise rooms_unavailable()
    try:
        data["seats"] = {
            side: Seat(seat["name"], None if seat["secret_hash"] is None else bytes.fromhex(seat["secret_hash"]))
            for side, seat in data["seats"].items()
        }
        return Room(**data)
    except (AttributeError, KeyError, TypeError, ValueError):
        raise rooms_unavailable() from None


def _request_source(request: Request) -> str:
    # Only the Vercel ingress supplies this trusted header. Otherwise use the ASGI client.
    if os.getenv("VERCEL") == "1":
        source = request.headers.get("x-vercel-forwarded-for", "")
        try:
            return str(ip_address(source))
        except ValueError:
            pass
    return request.client.host if request.client else "unknown"


def _new_room(mode: Mode, seat: Seat, source: str) -> Room:
    code = "".join(choice(CODE_ALPHABET) for _ in range(8))
    return Room(code, mode, ENGINES[mode].start(), {"w": seat}, created_by=source)


def _deny_room_creation(reason: str, retry_after: int = 1) -> NoReturn:
    if reason == "rate":
        _audit("room_create_denied", reason=reason, status=429)
        raise HTTPException(429, "Too many recent rooms. Try again shortly.", headers={"Retry-After": str(retry_after)})
    if reason == "source_limit":
        _audit("room_create_denied", reason="active_quota", status=429)
        raise HTTPException(429, "Too many active rooms from this connection.")
    if reason == "capacity":
        _audit("room_create_denied", reason=reason, status=503)
        raise HTTPException(503, "The server has no available rooms. Please try again later.")
    raise rooms_unavailable()


def _create_shared_room(store: SupabaseRoomStore, mode: Mode, seat: Seat, source: str) -> Room:
    for _ in range(8):
        room = _new_room(mode, seat, source)
        result = store.create(room.code, room.audit_id, source, _stored_payload(room))
        reason = result.get("status")
        if reason == "ok":
            return room
        if reason != "collision":
            retry_after = result.get("retry_after", 1)
            _deny_room_creation(reason, retry_after if type(retry_after) is int and retry_after > 0 else 1)
    raise rooms_unavailable()


def _mutate_room(code: str, mutate, *, audit_event: str | None = None, include_snapshot: bool = True):
    def apply(room: Room, store: SupabaseRoomStore | None):
        revision = room.revision
        side = mutate(room)
        room.advance()
        empty = all(seat.secret_hash is None for seat in room.seats.values())
        if store:
            payload = None if empty else _stored_payload(room)
            if not store.commit(room.code, room.audit_id, revision, payload, room.phase == "waiting" or room.has_departed_seat):
                return False, None
        elif empty:
            del _rooms[room.code]
        if audit_event:
            _audit(audit_event, room, side=side)
        return True, _snapshot(room, side) if include_snapshot else None

    store = configured_room_store()
    if store is None:
        with _rooms_lock:
            _remove_expired_rooms()
            return apply(_find_room(code), None)[1]
    room = _load_stored_room(store, code)
    for _ in range(4):
        committed, result = apply(room, store)
        if committed:
            return result
        fresh = _load_stored_room(store, code)
        if fresh.audit_id != room.audit_id:
            raise HTTPException(404, "Room not found or expired.")
        room = fresh
    raise HTTPException(409, "stale_revision")


@room_router.get("/health")
def rooms_health():
    store = configured_room_store()
    if store:
        store.health()
    return {"online": True, "version": 1}


@room_router.post("")
def create_room(request: CreateRoomRequest, http_request: Request):
    store = configured_room_store()
    source = _request_source(http_request)
    token, seat = _new_seat(request.name)
    if store:
        room = _create_shared_room(store, request.mode, seat, source)
    else:
        with _rooms_lock:
            now = monotonic()
            _remove_expired_rooms(now)
            _enforce_creation_quota(source, now)
            if len(_rooms) >= ROOM_LIMIT:
                _deny_room_creation("capacity")
            room = _new_room(request.mode, seat, source)
            while room.code in _rooms:
                room.code = "".join(choice(CODE_ALPHABET) for _ in range(8))
            _rooms[room.code] = room
            _creations.append((now, source))
            # Build the waiting snapshot before another request can join.
            result = _snapshot(room, "w")
            _audit("room_created", room, mode=room.mode)
            return {"token": token, "snapshot": result}
    _audit("room_created", room, mode=room.mode)
    return {"token": token, "snapshot": _snapshot(room, "w")}


@room_router.post("/{code}/join")
def join_room(code: str, request: PlayerRequest):
    token, seat = _new_seat(request.name)

    def join(room: Room) -> Side:
        if "b" in room.seats:
            _audit("room_join_denied", room, status=409)
            raise HTTPException(409, "This room already has two players.")
        room.seats["b"] = seat
        return "b"

    return {"token": token, "snapshot": _mutate_room(code, join, audit_event="room_joined")}


@room_router.get("/{code}")
def read_room(code: str, credentials: Credentials, request: Request, response: Response):
    def seat_snapshot(room: Room):
        side = _active_seat(room, credentials)
        secret_hash = room.seats[side].secret_hash
        assert secret_hash is not None
        # Representations differ by seat because the board carries private skills.
        checksum = hmac_digest(secret_hash, str(room.revision).encode("ascii"), "sha256").hex()
        tag = f'"{checksum}"'
        if request.headers.get("if-none-match") == tag:
            return Response(status_code=304, headers={"ETag": tag, "Cache-Control": "no-store"})
        response.headers["ETag"] = tag
        return _snapshot(room, side)

    store = configured_room_store()
    if store:
        return seat_snapshot(_load_stored_room(store, code))
    with _rooms_lock:
        _remove_expired_rooms()
        return seat_snapshot(_find_room(code))


@room_router.delete("/{code}/seat", status_code=204, response_class=Response)
def leave_room(code: str, credentials: Credentials):
    def leave(room: Room) -> Side:
        side = _seat_for(room, credentials)
        room.seats[side].secret_hash = None
        return side

    _mutate_room(code, leave, audit_event="room_seat_left", include_snapshot=False)
    return Response(status_code=204, headers={"Cache-Control": "no-store"})


@room_router.post("/{code}/action")
def room_action(code: str, request: RoomAction, credentials: Credentials):
    def act(room: Room) -> Side:
        side = _active_seat(room, credentials)
        try:
            if isinstance(request, SetupAction):
                # The two independent layouts may be submitted against the same revision.
                if request.revision != room.revision and not (
                    len(room.placements) == 1 and side not in room.placements
                    and request.revision == room.revision - 1
                ):
                    raise HTTPException(409, "stale_revision")
                _place_skills(room, side, request.placements)
            else:
                if request.revision != room.revision:
                    raise HTTPException(409, "stale_revision")
                if isinstance(request, MoveAction):
                    _make_move(room, side, request.move)
                else:
                    _play_duel(room, side, request.cell)
        except HTTPException as error:
            _audit("room_action_denied", room, side=side, action=request.type, status=error.status_code)
            raise
        return side

    return _mutate_room(code, act)

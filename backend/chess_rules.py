"""Move generation and hidden commands for the chess side of the game."""

from typing import Any

Piece = dict[str, Any]
Board = list[Piece | None]
GameState = dict[str, Any]
Move = dict[str, Any]
TurnOptions = dict[str, Any]

BACK_RANK = ("r", "n", "b", "q", "k", "b", "n", "r")
PROMOTIONS = ("q", "r", "b", "n")
ORTHOGONAL = ((1, 0), (-1, 0), (0, 1), (0, -1))
DIAGONAL = ((1, 1), (1, -1), (-1, 1), (-1, -1))
ADJACENT = ORTHOGONAL + DIAGONAL
KNIGHT = ((1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2))
DIRECTIONS = {"n": KNIGHT, "k": ADJACENT, "q": ADJACENT, "b": DIAGONAL, "r": ORTHOGONAL}
TURN_CARDS = ("revive", "friendly", "push")


def other(side: str) -> str:
    return "b" if side == "w" else "w"


def piece_at(board: Board, square: int | None) -> Piece | None:
    return board[square] if square is not None and 0 <= square < len(board) else None


def empty_state(board: Board, turn: str) -> GameState:
    return {
        "board": board, "turn": turn, "nextId": 64, "enPassant": None, "pending": None,
        "reserve": {"w": 0, "b": 0}, "locks": {"w": None, "b": None},
        "queue": {"w": [], "b": []}, "chain": None, "resolution": None,
        "hybrid": False, "duelWin": None,
    }


def _pawn_row(side: str) -> int:
    return 6 if side == "w" else 1


def _pawn_step(side: str) -> int:
    return -1 if side == "w" else 1


def _offset(square: int, dx: int, dy: int) -> int | None:
    row, column = divmod(square, 8)
    x, y = column + dx, row + dy
    return y * 8 + x if 0 <= x < 8 and 0 <= y < 8 else None


def start() -> GameState:
    board: Board = [None] * 64
    for side in ("w", "b"):
        home = 56 if side == "w" else 0
        for column, piece_type in enumerate(BACK_RANK):
            back = home + column
            pawn = _pawn_row(side) * 8 + column
            board[back] = {"type": piece_type, "side": side, "id": back, "moved": False}
            board[pawn] = {"type": "p", "side": side, "id": pawn, "moved": False}
    return empty_state(board, "w")


def _is_attacked(board: Board, square: int, side: str) -> bool:
    for dx in (-1, 1):
        piece = piece_at(board, _offset(square, dx, -_pawn_step(side)))
        if piece and piece["side"] == side and piece["type"] == "p":
            return True
    for dx, dy in KNIGHT:
        piece = piece_at(board, _offset(square, dx, dy))
        if piece and piece["side"] == side and piece["type"] == "n":
            return True
    for dx, dy in ADJACENT:
        distance = 1
        target = _offset(square, dx, dy)
        sliding_types = ("b", "q", "h") if dx and dy else ("r", "q")
        while target is not None:
            piece = board[target]
            if piece:
                if piece["side"] == side and (
                    piece["type"] in sliding_types or (distance == 1 and piece["type"] == "k")
                ):
                    return True
                break
            distance += 1
            target = _offset(target, dx, dy)
    return False


def in_check(board: Board, side: str) -> bool:
    king = next((square for square, piece in enumerate(board)
                 if piece and piece["type"] == "k" and piece["side"] == side), None)
    return king is not None and _is_attacked(board, king, other(side))


def _castle_moves(board: Board, origin: int, king: Piece) -> list[Move]:
    side = king["side"]
    home = 56 if side == "w" else 0
    if origin != home + 4 or king.get("moved") or in_check(board, side):
        return []
    moves = []
    for step, rook_column, between in ((-1, 0, (1, 2, 3)), (1, 7, (5, 6))):
        rook_origin = home + rook_column
        rook = board[rook_origin]
        if not rook or rook["side"] != side or rook["type"] != "r" or rook.get("moved"):
            continue
        if any(board[home + column] for column in between):
            continue
        crossing = board.copy()
        crossing[origin] = None
        crossing[origin + step] = king
        if not in_check(crossing, side):
            moves.append({
                "from": origin, "to": origin + 2 * step,
                "rookFrom": rook_origin, "rookTo": origin + step,
            })
    return moves


def _piece_moves(state: GameState, origin: int, piece: Piece, allied: bool) -> list[Move]:
    board = state["board"]
    piece_type, side = piece["type"], piece["side"]
    moves: list[Move] = []

    def can_capture(target: Piece | None) -> bool:
        if not target:
            return False
        if allied:
            return target["side"] == side and target["type"] == "p"
        return target["side"] != side and target["type"] != "k"

    def add(destination: int, **details: Any) -> None:
        move = {"from": origin, "to": destination, **details}
        if piece_type == "p" and destination // 8 in (0, 7):
            moves.extend({**move, "promote": promotion} for promotion in PROMOTIONS)
        else:
            moves.append(move)

    if piece_type == "p":
        step = _pawn_step(side)
        forward = _offset(origin, 0, step)
        if not allied and forward is not None and not board[forward]:
            add(forward)
            double = _offset(origin, 0, 2 * step)
            if origin // 8 == _pawn_row(side) and double is not None and not board[double]:
                add(double, enPassant=forward)
        for dx in (-1, 1):
            destination = _offset(origin, dx, step)
            if destination is None:
                continue
            if can_capture(board[destination]):
                add(destination, capture=destination)
            if not allied and destination == state["enPassant"]:
                add(destination, capture=_offset(origin, dx, 0))
        return moves

    sliding = piece_type not in ("k", "n")
    for dx, dy in DIRECTIONS.get(piece_type, ()):
        destination = _offset(origin, dx, dy)
        while destination is not None:
            target = board[destination]
            if target:
                if can_capture(target):
                    add(destination, capture=destination)
                break
            if not allied:
                add(destination)
            if not sliding:
                break
            destination = _offset(destination, dx, dy)
    if piece_type == "k" and not allied:
        moves.extend(_castle_moves(board, origin, piece))
    return moves


def moved_board(state: GameState, move: Move) -> Board:
    board = state["board"].copy()
    destination = move["to"]
    if move.get("revive"):
        board[destination] = {
            "type": "p", "side": state["turn"], "id": state["nextId"], "moved": False,
        }
        return board
    origin = move["from"]
    piece = board[origin]
    if not piece:
        raise ValueError("The move must start on a piece.")
    board[origin] = None
    if "capture" in move:
        board[move["capture"]] = None
    board[destination] = {**piece, "type": move.get("promote", piece["type"]), "moved": True}
    if "rookFrom" in move and "rookTo" in move:
        rook = board[move["rookFrom"]]
        if not rook:
            raise ValueError("Castling requires a rook.")
        board[move["rookTo"]] = {**rook, "moved": True}
        board[move["rookFrom"]] = None
    return board


def legal_moves(state: GameState, allied: bool = False) -> list[Move]:
    side = state["turn"]
    return [
        move for origin, piece in enumerate(state["board"])
        if piece and piece["side"] == side
        for move in _piece_moves(state, origin, piece, allied)
        if not in_check(moved_board(state, move), side)
    ]


def revival_moves(state: GameState) -> list[Move]:
    side = state["turn"]
    if state["reserve"][side] == 0:
        return []
    moves = []
    for column in range(8):
        destination = _pawn_row(side) * 8 + column
        move = {"to": destination, "revive": True}
        if not state["board"][destination] and not in_check(moved_board(state, move), side):
            moves.append(move)
    return moves


def turn_options(state: GameState) -> TurnOptions:
    board, side = state["board"], state["turn"]
    checked = in_check(board, side)
    normal = legal_moves(state)
    required = []
    pending = state["pending"]
    if pending == "revive":
        required = revival_moves(state)
    elif pending == "friendly":
        required = legal_moves(state, allied=True)
    elif pending == "push":
        required = [
            move for move in normal if board[move["from"]]["type"] == "p"
            and abs(move["to"] - move["from"]) == 8
        ]
    locked = state["locks"][side]
    if locked is not None:
        def unlocked(move: Move) -> bool:
            origin = piece_at(board, move.get("from"))
            rook = piece_at(board, move.get("rookFrom"))
            return not ((origin and origin["id"] == locked) or (rook and rook["id"] == locked))

        normal_without_lock = [move for move in normal if unlocked(move)]
        required_without_lock = [move for move in required if unlocked(move)]
        if not checked or normal_without_lock or required_without_lock:
            normal = normal_without_lock
            required = required_without_lock
    return {"checked": checked, "forced": bool(required), "moves": required or normal}


def play(state: GameState, move: Move) -> GameState:
    side = state["turn"]
    turn = other(side)
    captured = piece_at(state["board"], move.get("capture"))
    card = captured.get("card") if captured and captured["side"] == turn else None
    board = moved_board(state, move)
    reserve = state["reserve"].copy()
    locks = {**state["locks"], side: None}
    if captured and captured["type"] == "p":
        reserve[captured["side"]] += 1
    revive = bool(move.get("revive"))
    if revive:
        reserve[side] -= 1
    if card == "lock":
        locks[side] = board[move["to"]]["id"]
    return {
        **state, "board": board, "turn": turn, "reserve": reserve, "locks": locks,
        "nextId": state["nextId"] + int(revive), "enPassant": move.get("enPassant"),
        "pending": card if card in TURN_CARDS else None,
    }

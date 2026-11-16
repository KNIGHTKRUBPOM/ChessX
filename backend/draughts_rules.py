"""Thai draughts movement, captures, promotions, and hidden commands."""

from .chess_rules import (
    TURN_CARDS, Board, GameState, Move, Piece, TurnOptions, empty_state, other, piece_at,
)

_DIAGONALS = ((-1, -1), (1, -1), (-1, 1), (1, 1))


def _dark(square: int) -> bool:
    row, column = divmod(square, 8)
    return (row + column) % 2 == 1


def _offset(square: int, dx: int, dy: int) -> int | None:
    row, column = divmod(square, 8)
    x, y = column + dx, row + dy
    return y * 8 + x if 0 <= x < 8 and 0 <= y < 8 else None


def start(ranks: int = 2) -> GameState:
    board: Board = [None] * 64
    for square in range(64):
        if not _dark(square):
            continue
        row = square // 8
        side = "b" if row < ranks else "w" if row >= 8 - ranks else None
        if side:
            board[square] = {"type": "p", "side": side, "id": square}
    return empty_state(board, "b")


def _directions(piece: Piece):
    if piece["type"] == "h":
        return _DIAGONALS
    forward = -1 if piece["side"] == "w" else 1
    return ((dx, dy) for dx, dy in _DIAGONALS if dy == forward)


def _steps(board: Board, origin: int) -> list[Move]:
    piece = board[origin]
    moves = []
    for dx, dy in _directions(piece):
        destination = _offset(origin, dx, dy)
        while destination is not None and board[destination] is None:
            moves.append({"from": origin, "to": destination})
            if piece["type"] != "h":
                break
            destination = _offset(destination, dx, dy)
    return moves


def _jumps(board: Board, origin: int, friendly: bool = False) -> list[Move]:
    piece = board[origin]
    moves = []
    for dx, dy in _directions(piece):
        capture = _offset(origin, dx, dy)
        if piece["type"] == "h":
            while capture is not None and board[capture] is None:
                capture = _offset(capture, dx, dy)
        target = piece_at(board, capture)
        if target is None:
            continue
        same_side = target["side"] == piece["side"]
        if same_side != friendly or (friendly and target["type"] != "p"):
            continue
        destination = _offset(capture, dx, dy)
        if destination is not None and board[destination] is None:
            moves.append({
                "from": origin, "to": destination, "capture": capture, "friendly": friendly,
            })
    return moves


def _opponent_jumps(board: Board, origin: int, hybrid: bool) -> list[Move]:
    return [
        move for move in _jumps(board, origin)
        if not hybrid or board[move["capture"]]["type"] != "k"
    ]


def _revival_moves(state: GameState) -> list[Move]:
    side = state["turn"]
    if not state["reserve"][side]:
        return []
    home = range(48, 64) if side == "w" else range(16)
    return [
        {"to": square, "revive": True}
        for square in home if state["board"][square] is None and _dark(square)
    ]


def turn_options(state: GameState) -> TurnOptions:
    board, turn, chain = state["board"], state["turn"], state["chain"]
    hybrid = state["hybrid"]
    base = {"forced": False, "mustCapture": False, "card": None, "skipped": [], "consumed": 0}
    if chain:
        return {**base, "mustCapture": True, "moves": _opponent_jumps(board, chain["at"], hybrid)}

    def own_moves(generate):
        return [
            move
            for origin, piece in enumerate(board) if piece is not None and piece["side"] == turn
            for move in generate(board, origin)
        ]

    def unlocked(moves):
        return [move for move in moves if board[move["from"]]["id"] != state["locks"][turn]]

    captures = own_moves(lambda board, origin: _opponent_jumps(board, origin, hybrid))
    if captures:
        return {**base, "mustCapture": True, "moves": unlocked(captures) or captures}

    quiet = own_moves(_steps)
    unlocked_quiet = unlocked(quiet)
    skipped = []
    for card in state["queue"][turn]:
        if card == "revive":
            moves = _revival_moves(state)
        else:
            candidates = (
                own_moves(lambda board, origin: _jumps(board, origin, friendly=True))
                if card == "friendly"
                else [move for move in quiet if board[move["from"]]["type"] == "p"]
            )
            available = unlocked(candidates)
            moves = available if available or unlocked_quiet else candidates
        if moves:
            return {
                **base, "moves": moves, "forced": True, "card": card,
                "skipped": skipped, "consumed": len(skipped) + 1,
            }
        skipped.append(card)
    return {
        **base, "skipped": skipped, "consumed": len(skipped), "moves": unlocked_quiet or quiet,
    }


def play(state: GameState, move: Move, options: TurnOptions | None = None) -> GameState:
    if options is None:
        options = turn_options(state)
    turn, chain = state["turn"], state["chain"]
    opponent = other(turn)
    board = state["board"].copy()
    reserve = state["reserve"].copy()
    origin, destination, capture = move.get("from"), move["to"], move.get("capture")
    actor = piece_at(board, origin)
    captured = piece_at(board, capture)
    reviving = move.get("revive", False)
    found = []
    if captured and captured["side"] == opponent:
        found = captured.get("cards")
        if found is None:
            found = [captured["card"]] if captured.get("card") else []
    crowned = bool(actor and actor["type"] == "p" and destination // 8 == (0 if turn == "w" else 7))
    route = [destination]
    if chain:
        route = [*chain["route"], destination]
    elif not reviving:
        route = [origin, destination]
    cards = (chain["cards"] if chain else []) + found

    if reviving:
        board[destination] = {"type": "p", "side": turn, "id": state["nextId"]}
        reserve[turn] -= 1
    else:
        if actor is None:
            raise ValueError("The move must start on a piece.")
        board[origin] = None
        board[destination] = {**actor, "type": "h"} if crowned else actor
        if captured:
            board[capture] = None
            if captured["type"] == "p":
                reserve[captured["side"]] += 1

    if captured and not move.get("friendly") and not crowned and _opponent_jumps(board, destination, state["hybrid"]):
        return {
            **state, "board": board, "reserve": reserve,
            "chain": {"at": destination, "route": route, "cards": cards}, "resolution": None,
        }

    locks = {**state["locks"], turn: actor["id"] if actor and "lock" in cards else None}
    queue = {
        turn: state["queue"][turn][options.get("consumed", 0):],
        opponent: state["queue"][opponent] + [card for card in cards if card in TURN_CARDS],
    }
    return {
        **state, "board": board, "reserve": reserve, "locks": locks, "queue": queue,
        "turn": opponent, "chain": None, "nextId": state["nextId"] + int(reviving),
        "resolution": {"kind": "draughts", "route": route, "cards": cards, "crowned": crowned},
    }

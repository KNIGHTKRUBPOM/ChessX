"""Combined chess and Thai draughts, including Tic Tac Toe counter-captures."""

from . import chess_rules as chess
from . import draughts_rules as draughts

_UNRESOLVED = object()


def start() -> chess.GameState:
    state = chess.start()
    black_ranks = 3
    state["board"][:black_ranks * 8] = draughts.start(black_ranks)["board"][:black_ranks * 8]
    state["hybrid"] = True
    return state


def turn_options(state: chess.GameState) -> chess.TurnOptions:
    if state["duelWin"]:
        return {"moves": [], "skipped": [], "forced": False}
    if state["turn"] == "b":
        return draughts.turn_options(state)

    board = state["board"]
    checked = chess.in_check(board, "w")
    normal = chess.legal_moves(state)
    locked = state["locks"]["w"]

    def unlocked(moves):
        return [
            move for move in moves
            if not any(
                piece is not None and piece["id"] == locked
                for piece in (chess.piece_at(board, move.get("from")), chess.piece_at(board, move.get("rookFrom")))
            )
        ]

    unlocked_normal = unlocked(normal)
    skipped = []
    for card in state["queue"]["w"]:
        if card == "revive":
            candidates = chess.revival_moves(state)
        elif card == "friendly":
            candidates = chess.legal_moves(state, allied=True)
        else:
            candidates = [
                move for move in normal
                if board[move["from"]]["type"] == "p" and move["from"] - move["to"] == 8
            ]
        available = unlocked(candidates)
        moves = candidates if checked and not unlocked_normal and not available else available
        if moves:
            return {
                "checked": checked, "moves": moves, "forced": True,
                "card": card, "skipped": skipped, "consumed": len(skipped) + 1,
            }
        skipped.append(card)
    return {
        "checked": checked, "moves": normal if checked and not unlocked_normal else unlocked_normal,
        "forced": False, "skipped": skipped, "consumed": len(skipped),
    }


def challenges(state: chess.GameState, move: chess.Move) -> bool:
    target = chess.piece_at(state["board"], move.get("capture"))
    return state["turn"] == "w" and bool(target and target["side"] == "b" and "duel" in target.get("cards", []))


def play(
    state: chess.GameState, move: chess.Move,
    options: chess.TurnOptions | None = None, duel_winner=_UNRESOLVED,
) -> chess.GameState:
    if options is None:
        options = turn_options(state)
    if state["turn"] == "b":
        return draughts.play(state, move, options)

    duel = challenges(state, move)
    if duel and duel_winner is _UNRESOLVED:
        raise ValueError("Resolve Tic Tac Toe before committing the capture.")
    origin, capture = move.get("from"), move.get("capture")
    actor = chess.piece_at(state["board"], origin)
    captured = chess.piece_at(state["board"], capture)
    reversed_capture = duel and duel_winner == "b"
    board = state["board"].copy() if reversed_capture else chess.moved_board(state, move)
    reserve = state["reserve"].copy()
    locks = {**state["locks"], "w": None}
    queue = {**state["queue"], "w": state["queue"]["w"][options.get("consumed", 0):]}
    revealed_side = "w" if reversed_capture else "b"
    revealed_piece = actor if reversed_capture else captured
    if revealed_piece and revealed_piece["side"] != revealed_side:
        revealed_piece = None
    cards = [card for card in revealed_piece.get("cards", []) if card != "duel"] if revealed_piece else []
    queue[revealed_side] = queue[revealed_side] + [card for card in cards if card in chess.TURN_CARDS]

    if reversed_capture:
        if not captured or origin is None or capture is None:
            raise ValueError("A duel requires a capture.")
        board[origin] = None
        board[capture] = {**captured, "cards": [card for card in captured["cards"] if card != "duel"]}
    if "lock" in cards:
        locked = captured if reversed_capture else actor
        locks[chess.other(revealed_side)] = locked["id"] if locked else None
    fallen = actor if reversed_capture else captured
    if fallen and fallen["type"] == "p":
        reserve[fallen["side"]] += 1
    reviving = move.get("revive", False)
    if reviving:
        reserve["w"] -= 1
    duel_win = "b" if reversed_capture and (actor["type"] == "k" or chess.in_check(board, "w")) else None
    resolution = {
        "kind": "hybrid", "cards": cards, "revealedSide": revealed_side,
        "reversed": reversed_capture, "duel": duel,
    }
    if duel_winner is not _UNRESOLVED:
        resolution["duelWinner"] = duel_winner
    return {
        **state, "board": board, "reserve": reserve, "locks": locks, "queue": queue,
        "turn": "b", "duelWin": duel_win, "nextId": state["nextId"] + int(reviving),
        "resolution": resolution,
    }

from . import chess_rules, draughts_rules, hybrid_rules


ENGINES = {"chess": chess_rules, "draughts": draughts_rules, "hybrid": hybrid_rules}
DECK = ("lock", "revive", "friendly", "push")


def uses_discs(mode, side):
    return mode == "draughts" or (mode == "hybrid" and side == "b")


def deck_for(mode, side):
    return (*DECK, "duel") if mode == "hybrid" and side == "b" else DECK


def outcome_for(mode, state, options):
    turn = state["turn"]
    board = state["board"]
    if state["duelWin"]:
        has_king = any(piece and piece["type"] == "k" for piece in board)
        return {"winner": "b", "reason": "duel_check" if has_king else "duel_king"}
    if not options["moves"]:
        winner = chess_rules.other(turn)
        if uses_discs(mode, turn):
            has_pieces = any(piece and piece["side"] == turn for piece in board)
            return {"winner": winner, "reason": "no_moves" if has_pieces else "no_pieces"}
        if options.get("checked"):
            return {"winner": winner, "reason": "checkmate"}
        return {"winner": None, "reason": "stalemate"}
    if mode == "chess" and not options["forced"] and all(not piece or piece["type"] == "k" for piece in board):
        return {"winner": None, "reason": "kings_only"}
    return None

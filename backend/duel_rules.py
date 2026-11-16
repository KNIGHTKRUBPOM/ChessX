"""Tic Tac Toe duel where black plays X and white plays O."""

from typing import TypedDict

from .chess_rules import other


class DuelState(TypedDict):
    cells: list[str | None]
    turn: str
    line: list[int] | None
    winner: str | None
    done: bool


_LINES = (
    (0, 1, 2), (3, 4, 5), (6, 7, 8),
    (0, 3, 6), (1, 4, 7), (2, 5, 8),
    (0, 4, 8), (2, 4, 6),
)


def start() -> DuelState:
    return {"cells": [None] * 9, "turn": "b", "line": None, "winner": None, "done": False}


def play(state: DuelState, cell: int) -> DuelState:
    if state["done"] or type(cell) is not int or not 0 <= cell < 9 or state["cells"][cell]:
        return state
    cells = state["cells"].copy()
    turn = state["turn"]
    cells[cell] = turn
    line = next((list(line) for line in _LINES if all(cells[index] == turn for index in line)), None)
    return {
        "cells": cells, "turn": other(turn), "line": line,
        "winner": turn if line else None, "done": line is not None or all(cells),
    }

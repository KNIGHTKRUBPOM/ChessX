from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field

Mode = Literal["chess", "draughts", "hybrid"]
Side = Literal["w", "b"]
Promotion = Literal["q", "r", "b", "n"]
TurnCard = Literal["revive", "friendly", "push"]
Card = Literal["lock", "revive", "friendly", "push", "duel"]
Square = Annotated[int, Field(ge=0, le=63)]
Cell = Annotated[int, Field(ge=0, le=8)]
PieceId = Annotated[int, Field(ge=0, le=10_000_000)]
CardList = Annotated[list[Card], Field(max_length=24)]
CommandQueue = Annotated[list[TurnCard], Field(max_length=24)]
Route = Annotated[list[Square], Field(min_length=1, max_length=64)]


class DataModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class Piece(DataModel):
    type: Literal["k", "p", "h", "q", "r", "b", "n"]
    side: Side
    id: PieceId
    moved: bool = False
    card: Card | None = None
    cards: list[Card] = Field(default_factory=list, max_length=2)


class Reserves(DataModel):
    w: PieceId
    b: PieceId


class Locks(DataModel):
    w: PieceId | None
    b: PieceId | None


class Queues(DataModel):
    w: CommandQueue
    b: CommandQueue


class Chain(DataModel):
    at: Square
    route: Route
    cards: CardList


class DraughtsResolution(DataModel):
    kind: Literal["draughts"]
    route: Route
    cards: CardList
    crowned: bool


class HybridResolution(DataModel):
    kind: Literal["hybrid"]
    cards: CardList
    revealedSide: Side
    reversed: bool
    duel: bool
    duelWinner: Side | None = None


class GameState(DataModel):
    board: list[Piece | None] = Field(min_length=64, max_length=64)
    turn: Side
    nextId: PieceId = Field(ge=64)
    enPassant: Square | None
    pending: TurnCard | None
    reserve: Reserves
    locks: Locks
    queue: Queues
    chain: Chain | None
    resolution: Annotated[DraughtsResolution | HybridResolution, Field(discriminator="kind")] | None
    hybrid: bool
    duelWin: Literal["b"] | None


class StartRequest(DataModel):
    mode: Mode


class StateRequest(StartRequest):
    state: GameState


class SetupRequest(StateRequest):
    side: Side
    placements: dict[Card, Square]


class MoveChoice(DataModel):
    source: Square | None = Field(default=None, alias="from")
    to: Square
    promote: Promotion | None = None


class BoardMove(MoveChoice):
    capture: Square | None = None
    enPassant: Square | None = None
    rookFrom: Square | None = None
    rookTo: Square | None = None
    friendly: bool | None = None
    revive: bool | None = None


class MoveRequest(StateRequest):
    move: MoveChoice


class DuelBoard(DataModel):
    cells: list[Side | None] = Field(min_length=9, max_length=9)
    turn: Side
    line: list[Cell] | None = Field(min_length=3, max_length=3)
    winner: Side | None
    done: bool


class Duel(DataModel):
    move: BoardMove
    board: DuelBoard


class FinishDuelRequest(StateRequest):
    duel: Duel


class DuelRequest(FinishDuelRequest):
    cell: Cell

import {
  Hybrid, MODES, PIECE_NAMES, pieceAt, type CardId, type DuelState,
  type GameState, type ModeId, type Move, type Piece, type Side,
} from './rules';

export type MatchPhase = 'setup' | 'handoff' | 'play';
export type Placements = Partial<Record<CardId, number>>;
export interface HistoryEntry { move: string; effect: string }
export interface Result { title: string; detail: string }
export interface Notice {
  name: string;
  side: Side;
  description: string;
  note: string;
  revealed: boolean;
  required: boolean;
}
export interface Duel { move: Move; board: DuelState }

export interface MatchSave {
  version: 1;
  modeId: ModeId;
  game: GameState;
  phase: MatchPhase;
  setupSide: Side;
  placements: Placements;
  selectedCard: CardId;
  lastMove: Move | null;
  notices: Notice[];
  commandOpen: boolean;
  result: Result | null;
  history: HistoryEntry[];
  duel: Duel | null;
}

export function isModeId(value: unknown): value is ModeId {
  return typeof value === 'string' && Object.hasOwn(MODES, value);
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return value !== null && typeof value === 'object' && !Array.isArray(value);
}

function isSide(value: unknown): value is Side {
  return value === 'w' || value === 'b';
}

function isCount(value: unknown): value is number {
  return typeof value === 'number' && Number.isSafeInteger(value) && value >= 0;
}

function isSquare(value: unknown): value is number {
  return isCount(value) && value < 64;
}

function isTurnCard(value: unknown): boolean {
  return value === 'revive' || value === 'friendly' || value === 'push';
}

function isCardId(value: unknown): boolean {
  return isTurnCard(value) || value === 'lock' || value === 'duel';
}

function isCardList(value: unknown): boolean {
  return Array.isArray(value) && value.every(isCardId);
}

function isPiece(value: unknown, mode: ModeId): value is Piece {
  if (!isRecord(value) || !isSide(value.side) || !isCount(value.id) ||
      typeof value.type !== 'string' || !Object.hasOwn(PIECE_NAMES, value.type)) return false;
  const checkers = mode === 'draughts' || (mode === 'hybrid' && value.side === 'b');
  if (checkers ? value.type !== 'p' && value.type !== 'h' : value.type === 'h') return false;
  if (value.moved !== undefined && typeof value.moved !== 'boolean') return false;
  const deck = value.side === 'b' ? MODES[mode].blackCards ?? MODES[mode].cards : MODES[mode].cards;
  const inDeck = (card: unknown) => typeof card === 'string' && Object.hasOwn(deck, card);
  if (mode !== 'hybrid') return value.cards === undefined && (value.card === undefined || inDeck(value.card));
  const limit = value.side === 'b' ? 2 : 1;
  return value.card === undefined && (value.cards === undefined ||
    (Array.isArray(value.cards) && value.cards.length <= limit && value.cards.every(inDeck)));
}

function isRoute(value: unknown): boolean {
  return Array.isArray(value) && value.length > 0 && value.every(isSquare);
}

function isResolution(value: unknown, mode: ModeId): boolean {
  if (value === null) return true;
  if (!isRecord(value) || !isCardList(value.cards)) return false;
  if (value.kind === 'draughts') return mode !== 'chess' && isRoute(value.route) && typeof value.crowned === 'boolean';
  return mode === 'hybrid' && value.kind === 'hybrid' && isSide(value.revealedSide) &&
    typeof value.reversed === 'boolean' && typeof value.duel === 'boolean' &&
    (value.duelWinner === undefined || value.duelWinner === null || isSide(value.duelWinner));
}

function isGameState(value: unknown, mode: ModeId): value is GameState {
  if (!isRecord(value)) return false;
  const { board, turn, nextId, reserve, locks, queue, chain, pending, enPassant, hybrid, duelWin, resolution } = value;
  if (!isSide(turn) || !isCount(nextId) || nextId < 64 || hybrid !== (mode === 'hybrid') ||
      (pending !== null && (mode !== 'chess' || !isTurnCard(pending))) ||
      (enPassant !== null && !isSquare(enPassant)) ||
      (duelWin !== null && (mode !== 'hybrid' || duelWin !== 'b')) ||
      !isResolution(resolution, mode)) return false;
  if (!Array.isArray(board) || board.length !== 64 ||
      !board.every(piece => piece === null || (isPiece(piece, mode) && piece.id < nextId))) return false;
  if (!isRecord(reserve) || !isRecord(locks) || !isRecord(queue)) return false;
  for (const side of ['w', 'b']) {
    const lock = locks[side];
    const cards = queue[side];
    if (!isCount(reserve[side]) || (lock !== null && (!isCount(lock) || lock >= nextId)) ||
        !Array.isArray(cards) || !cards.every(isTurnCard)) return false;
  }
  if (chain === null) return true;
  return mode !== 'chess' && (mode !== 'hybrid' || turn === 'b') && isRecord(chain) &&
    isSquare(chain.at) && board[chain.at]?.side === turn && isRoute(chain.route) && isCardList(chain.cards);
}

function isMove(value: unknown): value is Move {
  if (!isRecord(value) || !isSquare(value.to)) return false;
  const { from, capture, promote, enPassant, rookFrom, rookTo, friendly, revive } = value;
  if (revive === true) return [from, capture, promote, enPassant, rookFrom, rookTo, friendly].every(field => field === undefined);
  return (revive === undefined || revive === false) && isSquare(from) &&
    [capture, enPassant].every(square => square === undefined || isSquare(square)) &&
    ((rookFrom === undefined && rookTo === undefined) || (isSquare(rookFrom) && isSquare(rookTo))) &&
    (friendly === undefined || typeof friendly === 'boolean') &&
    (promote === undefined || promote === 'q' || promote === 'r' || promote === 'b' || promote === 'n');
}

function isDuelBoard(value: unknown): boolean {
  if (!isRecord(value)) return false;
  const { cells, turn, line, winner, done } = value;
  return Array.isArray(cells) && cells.length === 9 && cells.every(cell => cell === null || isSide(cell)) &&
    isSide(turn) && (winner === null || isSide(winner)) && typeof done === 'boolean' &&
    (line === null || (Array.isArray(line) && line.length === 3 && line.every(cell => isCount(cell) && cell < 9)));
}

export function readMatchSave(value: unknown): MatchSave | null {
  if (!isRecord(value) || value.version !== 1 || !isModeId(value.modeId)) return null;
  if (value.phase !== 'setup' && value.phase !== 'handoff' && value.phase !== 'play') return null;
  const { game, duel, placements, selectedCard } = value;
  if (!isSide(value.setupSide) || !isGameState(game, value.modeId)) return null;
  if (value.lastMove !== null && !isMove(value.lastMove)) return null;
  if (value.result !== null && (!isRecord(value.result) || typeof value.result.title !== 'string' ||
      typeof value.result.detail !== 'string')) return null;
  if (typeof value.commandOpen !== 'boolean') return null;

  const mode = MODES[value.modeId];
  const deck = value.setupSide === 'b' ? mode.blackCards ?? mode.cards : mode.cards;
  if (!isRecord(placements) || typeof selectedCard !== 'string' || !Object.hasOwn(deck, selectedCard)) return null;
  if (!Object.entries(placements).every(([id, square]) =>
    value.phase === 'setup' && Object.hasOwn(deck, id) && isSquare(square) &&
    game.board[square]?.side === value.setupSide && game.board[square]?.type !== 'k')) return null;
  if (!Array.isArray(value.history) || !value.history.every(item => isRecord(item) &&
      typeof item.move === 'string' && typeof item.effect === 'string')) return null;
  if (!Array.isArray(value.notices) || !value.notices.every(item => isRecord(item) && isSide(item.side) &&
      typeof item.name === 'string' && typeof item.description === 'string' && typeof item.note === 'string' &&
      typeof item.revealed === 'boolean' && typeof item.required === 'boolean')) return null;
  if (duel !== null) {
    if (value.modeId !== 'hybrid' || value.phase !== 'play' || !isRecord(duel) ||
        !isMove(duel.move) || !isDuelBoard(duel.board) || !Hybrid.challenges(game, duel.move) ||
        pieceAt(game.board, duel.move.from)?.side !== game.turn) return null;
    const move = duel.move;
    if (!Hybrid.turnOptions(game).moves.some(option => option.from === move.from && option.to === move.to &&
        option.capture === move.capture && option.promote === move.promote && option.rookFrom === move.rookFrom &&
        option.rookTo === move.rookTo && option.enPassant === move.enPassant)) return null;
  }
  return value as unknown as MatchSave;
}

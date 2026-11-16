export type Side = 'w' | 'b';
export type Promotion = 'q' | 'r' | 'b' | 'n';
export type PieceType = 'k' | 'p' | 'h' | Promotion;
export type TurnCardId = 'revive' | 'friendly' | 'push';
export type CardId = TurnCardId | 'lock' | 'duel';

export interface Piece {
  type: PieceType;
  side: Side;
  id: number;
  moved?: boolean;
  card?: CardId;
  cards?: CardId[];
}

export type Board = Array<Piece | null>;

export function pieceAt(board: Board, square: number | undefined): Piece | null {
  return square === undefined ? null : board[square] ?? null;
}

interface BoardMove {
  from: number;
  to: number;
  capture?: number;
  promote?: Promotion;
  enPassant?: number;
  rookFrom?: number;
  rookTo?: number;
  friendly?: boolean;
  revive?: false;
}

interface RevivalMove {
  to: number;
  revive: true;
  from?: never;
  capture?: never;
  promote?: never;
  enPassant?: never;
  rookFrom?: never;
  rookTo?: never;
  friendly?: never;
}

export type Move = BoardMove | RevivalMove;

interface CaptureChain {
  at: number;
  route: number[];
  cards: CardId[];
}

interface DraughtsResolution {
  kind: 'draughts';
  route: number[];
  cards: CardId[];
  crowned: boolean;
}

interface HybridResolution {
  kind: 'hybrid';
  cards: CardId[];
  revealedSide: Side;
  reversed: boolean;
  duel: boolean;
  duelWinner?: Side | null;
}

export interface GameState {
  board: Board;
  turn: Side;
  nextId: number;
  enPassant: number | null;
  pending: TurnCardId | null;
  reserve: Record<Side, number>;
  locks: Record<Side, number | null>;
  queue: Record<Side, TurnCardId[]>;
  chain: CaptureChain | null;
  resolution: DraughtsResolution | HybridResolution | null;
  hybrid: boolean;
  duelWin: Side | null;
}

export interface TurnOptions {
  moves: Move[];
  forced: boolean;
  checked?: boolean;
  mustCapture?: boolean;
  card?: TurnCardId | null;
  skipped?: TurnCardId[];
  consumed?: number;
}

export interface Engine {
  start(): GameState;
  turnOptions(state: GameState): TurnOptions;
  play(state: GameState, move: Move, options?: TurnOptions): GameState;
}

export interface DuelState {
  cells: Array<Side | null>;
  turn: Side;
  line: number[] | null;
  winner: Side | null;
  done: boolean;
}

export interface Card {
  name: string;
  summary: string;
  detail: string;
  prompt?: string;
}

export type CardSet = Record<Exclude<CardId, 'duel'>, Card> & { duel?: Card };
export type ModeId = 'chess' | 'draughts' | 'hybrid';

export interface Mode {
  name: string;
  engine: Engine;
  cards: CardSet;
  blackCards?: CardSet;
}

function emptyState(board: Board, turn: Side): GameState {
  return {
    board, turn, nextId: 64, enPassant: null, pending: null,
    reserve: { w: 0, b: 0 }, locks: { w: null, b: null }, queue: { w: [], b: [] },
    chain: null, resolution: null, hybrid: false, duelWin: null,
  };
}

function queuesCommand(card: CardId): card is TurnCardId {
  return card === 'revive' || card === 'friendly' || card === 'push';
}

export const Chess = (() => {
  const BACK_RANK: PieceType[] = ['r', 'n', 'b', 'q', 'k', 'b', 'n', 'r'];
  const PROMOTIONS: Promotion[] = ['q', 'r', 'b', 'n'];
  const ORTHOGONAL = [[1, 0], [-1, 0], [0, 1], [0, -1]];
  const DIAGONAL = [[1, 1], [1, -1], [-1, 1], [-1, -1]];
  const ADJACENT = [...ORTHOGONAL, ...DIAGONAL];
  const KNIGHT = [[1, 2], [2, 1], [2, -1], [1, -2], [-1, -2], [-2, -1], [-2, 1], [-1, 2]];

  const other = (side: Side): Side => side === 'w' ? 'b' : 'w';
  const row = (square: number) => Math.floor(square / 8);
  const file = (square: number) => square % 8;
  const name = (square: number) => 'abcdefgh'[file(square)] + (8 - row(square));
  const pawnRow = (side: Side) => side === 'w' ? 6 : 1;
  const pawnStep = (side: Side) => side === 'w' ? -1 : 1;

  function offset(square: number, dx: number, dy: number) {
    const x = file(square) + dx;
    const y = row(square) + dy;
    return x >= 0 && x < 8 && y >= 0 && y < 8 ? y * 8 + x : -1;
  }

  function start(): GameState {
    const board = Array<Piece | null>(64).fill(null);
    for (const side of ['w', 'b'] as const) {
      const home = side === 'w' ? 56 : 0;
      for (let col = 0; col < 8; col++) {
        const back = home + col;
        const pawn = pawnRow(side) * 8 + col;
        board[back] = { type: BACK_RANK[col], side, id: back, moved: false };
        board[pawn] = { type: 'p', side, id: pawn, moved: false };
      }
    }
    return emptyState(board, 'w');
  }

  function isAttacked(board: Board, square: number, side: Side) {
    for (const dx of [-1, 1]) {
      const piece = board[offset(square, dx, -pawnStep(side))];
      if (piece?.side === side && piece.type === 'p') return true;
    }
    for (const [dx, dy] of KNIGHT) {
      const piece = board[offset(square, dx, dy)];
      if (piece?.side === side && piece.type === 'n') return true;
    }
    for (const [dx, dy] of ADJACENT) {
      let distance = 1;
      let target = offset(square, dx, dy);
      while (target !== -1) {
        const piece = board[target];
        if (piece) {
          const slider = dx && dy ? 'b' : 'r';
          if (piece.side === side && (piece.type === slider || piece.type === 'q' || (slider === 'b' && piece.type === 'h') ||
              (distance === 1 && piece.type === 'k'))) return true;
          break;
        }
        distance++;
        target = offset(target, dx, dy);
      }
    }
    return false;
  }

  function inCheck(board: Board, side: Side) {
    const king = board.findIndex(piece => piece?.type === 'k' && piece.side === side);
    return isAttacked(board, king, other(side));
  }

  function castleMoves(board: Board, from: number, piece: Piece): BoardMove[] {
    if (piece.moved || inCheck(board, piece.side)) return [];
    const home = piece.side === 'w' ? 56 : 0;
    if (from !== home + 4) return [];
    const moves: BoardMove[] = [];
    for (const step of [-1, 1]) {
      const rookFrom = home + (step < 0 ? 0 : 7);
      const rook = board[rookFrom];
      if (rook?.side !== piece.side || rook.type !== 'r' || rook.moved) continue;
      const between = step < 0 ? [1, 2, 3] : [5, 6];
      if (between.some(col => board[home + col])) continue;
      const crossing = board.slice();
      crossing[from] = null;
      crossing[from + step] = piece;
      if (inCheck(crossing, piece.side)) continue;
      moves.push({ from, to: from + 2 * step, rookFrom, rookTo: from + step });
    }
    return moves;
  }

  function pieceMoves(state: GameState, from: number, piece: Piece, allied: boolean): BoardMove[] {
    const { board } = state;
    const { type, side } = piece;
    const moves: BoardMove[] = [];
    const canCapture = (target: Piece | null) => target && (allied
      ? target.side === side && target.type === 'p'
      : target.side !== side && target.type !== 'k');

    function add(to: number, details: Omit<BoardMove, 'from' | 'to'> = {}) {
      const move = { from, to, ...details };
      if (type === 'p' && (row(to) === 0 || row(to) === 7)) {
        moves.push(...PROMOTIONS.map(promote => ({ ...move, promote })));
      } else {
        moves.push(move);
      }
    }

    if (type === 'p') {
      const step = pawnStep(side);
      const forward = offset(from, 0, step);
      if (!allied && forward !== -1 && !board[forward]) {
        add(forward);
        const double = offset(from, 0, 2 * step);
        if (row(from) === pawnRow(side) && !board[double]) add(double, { enPassant: forward });
      }
      for (const dx of [-1, 1]) {
        const to = offset(from, dx, step);
        if (to === -1) continue;
        if (canCapture(board[to])) add(to, { capture: to });
        if (!allied && to === state.enPassant) add(to, { capture: offset(from, dx, 0) });
      }
      return moves;
    }

    if (type === 'h') return moves;
    const directions = { n: KNIGHT, k: ADJACENT, q: ADJACENT, b: DIAGONAL, r: ORTHOGONAL }[type];
    const sliding = type !== 'k' && type !== 'n';
    for (const [dx, dy] of directions) {
      let to = offset(from, dx, dy);
      while (to !== -1) {
        const target = board[to];
        if (canCapture(target)) add(to, { capture: to });
        if (target) break;
        if (!allied) add(to);
        if (!sliding) break;
        to = offset(to, dx, dy);
      }
    }
    if (type === 'k' && !allied) moves.push(...castleMoves(board, from, piece));
    return moves;
  }

  function movedBoard(state: GameState, move: Move): Board {
    const board = state.board.slice();
    if (move.revive) {
      board[move.to] = { type: 'p', side: state.turn, id: state.nextId, moved: false };
      return board;
    }
    const piece = board[move.from];
    if (!piece) throw Error('The move must start on a piece.');
    board[move.from] = null;
    if (move.capture !== undefined) board[move.capture] = null;
    board[move.to] = { ...piece, type: move.promote ?? piece.type, moved: true };
    if (move.rookFrom !== undefined && move.rookTo !== undefined) {
      const rook = board[move.rookFrom];
      if (!rook) throw Error('Castling requires a rook.');
      board[move.rookTo] = { ...rook, moved: true };
      board[move.rookFrom] = null;
    }
    return board;
  }

  function legalMoves(state: GameState, allied = false): BoardMove[] {
    return state.board.flatMap((piece, from) => piece?.side === state.turn
      ? pieceMoves(state, from, piece, allied) : [])
      .filter(move => !inCheck(movedBoard(state, move), state.turn));
  }

  function revivalMoves(state: GameState): RevivalMove[] {
    if (state.reserve[state.turn] === 0) return [];
    const moves: RevivalMove[] = [];
    for (let col = 0; col < 8; col++) {
      const to = pawnRow(state.turn) * 8 + col;
      const move: RevivalMove = { to, revive: true };
      if (!state.board[to] && !inCheck(movedBoard(state, move), state.turn)) moves.push(move);
    }
    return moves;
  }

  function turnOptions(state: GameState): TurnOptions {
    const checked = inCheck(state.board, state.turn);
    let normal: Move[] = legalMoves(state);
    let required: Move[] = [];
    if (state.pending === 'revive') required = revivalMoves(state);
    if (state.pending === 'friendly') required = legalMoves(state, true);
    if (state.pending === 'push') {
      required = normal.filter(move => !move.revive && state.board[move.from]?.type === 'p' &&
        Math.abs(move.to - move.from) === 8);
    }

    const locked = state.locks[state.turn];
    if (locked !== null) {
      const usesLocked = (move: Move) => pieceAt(state.board, move.from)?.id === locked ||
        pieceAt(state.board, move.rookFrom)?.id === locked;
      const normalWithoutLock = normal.filter(move => !usesLocked(move));
      const requiredWithoutLock = required.filter(move => !usesLocked(move));
      if (!checked || normalWithoutLock.length || requiredWithoutLock.length) {
        normal = normalWithoutLock;
        required = requiredWithoutLock;
      }
    }
    return { checked, forced: required.length > 0, moves: required.length ? required : normal };
  }

  function play(state: GameState, move: Move): GameState {
    const captured = pieceAt(state.board, move.capture);
    const turn = other(state.turn);
    const card = captured?.side === turn ? captured.card : null;
    const board = movedBoard(state, move);
    const reserve = { ...state.reserve };
    const locks = { ...state.locks, [state.turn]: null };
    if (captured?.type === 'p') reserve[captured.side]++;
    if (move.revive) reserve[state.turn]--;
    if (card === 'lock') locks[state.turn] = board[move.to]?.id ?? null;
    return {
      ...state, board, turn, reserve, locks,
      nextId: state.nextId + Number(!!move.revive),
      enPassant: move.enPassant ?? null,
      pending: card && queuesCommand(card) ? card : null
    };
  }

  return { start, play, turnOptions, name, other, legalMoves, movedBoard, revivalMoves, inCheck };
})();

export const Draughts = (() => {
  const DIAGONALS = [[-1, -1], [1, -1], [-1, 1], [1, 1]];
  const row = (square: number) => Math.floor(square / 8);
  const dark = (square: number) => (row(square) + square % 8) % 2 === 1;
  const home = (square: number, side: Side) => side === 'w' ? row(square) >= 6 : row(square) <= 1;

  function offset(square: number, dx: number, dy: number) {
    const x = square % 8 + dx;
    const y = row(square) + dy;
    return x >= 0 && x < 8 && y >= 0 && y < 8 ? y * 8 + x : -1;
  }

  function start(ranks = 2): GameState {
    const board = Array.from({ length: 64 }, (_, square): Piece | null => {
      if (!dark(square)) return null;
      const rank = row(square);
      const side = rank < ranks ? 'b' : rank >= 8 - ranks ? 'w' : null;
      return side ? { type: 'p', side, id: square } : null;
    });
    return emptyState(board, 'b');
  }

  function directions(piece: Piece) {
    return piece.type === 'h' ? DIAGONALS : DIAGONALS.filter(([, dy]) => dy === (piece.side === 'w' ? -1 : 1));
  }

  function steps(board: Board, from: number): BoardMove[] {
    const piece = board[from];
    if (!piece) return [];
    const moves: BoardMove[] = [];
    for (const [dx, dy] of directions(piece)) {
      let to = offset(from, dx, dy);
      while (to !== -1 && !board[to]) {
        moves.push({ from, to });
        if (piece.type !== 'h') break;
        to = offset(to, dx, dy);
      }
    }
    return moves;
  }

  function jumps(board: Board, from: number, friendly = false): Array<BoardMove & { capture: number }> {
    const piece = board[from];
    if (!piece) return [];
    const moves: Array<BoardMove & { capture: number }> = [];
    for (const [dx, dy] of directions(piece)) {
      let capture = offset(from, dx, dy);
      if (piece.type === 'h') {
        while (capture !== -1 && !board[capture]) capture = offset(capture, dx, dy);
      }
      const target = board[capture];
      if (!target || (friendly ? target.side !== piece.side || target.type !== 'p' : target.side === piece.side)) continue;
      const to = offset(capture, dx, dy);
      if (to !== -1 && !board[to]) moves.push({ from, to, capture, friendly });
    }
    return moves;
  }

  function opponentJumps(board: Board, from: number, hybrid: boolean) {
    return jumps(board, from).filter(move => !hybrid || board[move.capture]?.type !== 'k');
  }

  function reviveMoves(state: GameState): RevivalMove[] {
    if (state.reserve[state.turn] === 0) return [];
    return state.board.flatMap((piece, to) => !piece && dark(to) && home(to, state.turn) ? [{ to, revive: true }] : []);
  }

  function turnOptions(state: GameState): TurnOptions {
    const { board, turn, chain } = state;
    const base = { forced: false, mustCapture: false, card: null, skipped: [], consumed: 0 };
    if (chain) return { ...base, mustCapture: true, moves: opponentJumps(board, chain.at, state.hybrid) };
    const ownMoves = (generate: (board: Board, from: number) => BoardMove[]) => board.flatMap((piece, from) => piece?.side === turn ? generate(board, from) : []);
    const unlocked = (moves: BoardMove[]) => moves.filter(move => board[move.from]?.id !== state.locks[turn]);
    const captures = ownMoves((board, from) => opponentJumps(board, from, state.hybrid));
    if (captures.length) {
      const available = unlocked(captures);
      return { ...base, mustCapture: true, moves: available.length ? available : captures };
    }

    const quiet = ownMoves(steps);
    const unlockedQuiet = unlocked(quiet);
    const skipped: TurnCardId[] = [];
    for (const card of state.queue[turn]) {
      let moves: Move[];
      if (card === 'revive') {
        moves = reviveMoves(state);
      } else {
        const candidates = card === 'friendly'
          ? ownMoves((board, from) => jumps(board, from, true))
          : quiet.filter(move => board[move.from]?.type === 'p');
        const available = unlocked(candidates);
        moves = available.length || unlockedQuiet.length ? available : candidates;
      }
      if (moves.length) return { ...base, moves, forced: true, card, skipped, consumed: skipped.length + 1 };
      skipped.push(card);
    }
    return { ...base, skipped, consumed: skipped.length, moves: unlockedQuiet.length ? unlockedQuiet : quiet };
  }

  function play(state: GameState, move: Move, options = turnOptions(state)): GameState {
    const { turn, chain } = state;
    const other = Chess.other(turn);
    const board = state.board.slice();
    const reserve = { ...state.reserve };
    const actor = pieceAt(board, move.from);
    const captured = pieceAt(board, move.capture);
    const found = captured?.side === other ? captured.cards ?? (captured.card ? [captured.card] : []) : [];
    const crowned = actor?.type === 'p' && row(move.to) === (turn === 'w' ? 0 : 7);
    const route = chain ? [...chain.route, move.to] : move.revive ? [move.to] : [move.from, move.to];
    const cards = [...(chain?.cards ?? []), ...found];

    if (move.revive) {
      board[move.to] = { type: 'p', side: turn, id: state.nextId };
      reserve[turn]--;
    } else {
      if (!actor) throw Error('The move must start on a piece.');
      board[move.from] = null;
      board[move.to] = crowned ? { ...actor, type: 'h' } : actor;
      if (captured && move.capture !== undefined) {
        board[move.capture] = null;
        if (captured.type === 'p') reserve[captured.side]++;
      }
    }

    if (captured && !move.friendly && !crowned && opponentJumps(board, move.to, state.hybrid).length) {
      return { ...state, board, reserve, chain: { at: move.to, route, cards }, resolution: null };
    }
    const locks = { ...state.locks, [turn]: cards.includes('lock') ? actor?.id ?? null : null };
    const queue = {
      ...state.queue,
      [turn]: state.queue[turn].slice(options.consumed ?? 0),
      [other]: [...state.queue[other], ...cards.filter(queuesCommand)]
    };
    return {
      ...state, board, reserve, locks, queue, turn: other, chain: null,
      nextId: state.nextId + Number(!!move.revive),
      resolution: { kind: 'draughts', route, cards, crowned }
    };
  }

  return { start, play, turnOptions };
})();

export const Hybrid = (() => {
  function start(): GameState {
    const state = Chess.start();
    const ranks = 3;
    const blackSetup = Draughts.start(ranks).board.slice(0, ranks * 8);
    state.board.splice(0, blackSetup.length, ...blackSetup);
    return { ...state, hybrid: true };
  }

  function turnOptions(state: GameState): TurnOptions {
    if (state.duelWin) return { moves: [], skipped: [], forced: false };
    if (state.turn === 'b') return Draughts.turnOptions(state);
    const checked = Chess.inCheck(state.board, 'w');
    const normal = Chess.legalMoves(state);
    const locked = state.locks.w;
    const unlocked = (moves: Move[]) => moves.filter(move => pieceAt(state.board, move.from)?.id !== locked &&
      pieceAt(state.board, move.rookFrom)?.id !== locked);
    const unlockedNormal = unlocked(normal);
    const skipped: TurnCardId[] = [];
    for (const card of state.queue.w) {
      let candidates: Move[];
      if (card === 'revive') candidates = Chess.revivalMoves(state);
      else if (card === 'friendly') candidates = Chess.legalMoves(state, true);
      else candidates = normal.filter(move => state.board[move.from]?.type === 'p' && move.from - move.to === 8);
      const available = unlocked(candidates);
      const moves = checked && !unlockedNormal.length && !available.length ? candidates : available;
      if (moves.length) return { checked, moves, forced: true, card, skipped, consumed: skipped.length + 1 };
      skipped.push(card);
    }
    const moves = checked && !unlockedNormal.length ? normal : unlockedNormal;
    return { checked, moves, forced: false, skipped, consumed: skipped.length };
  }

  function challenges(state: GameState, move: Move) {
    const target = pieceAt(state.board, move.capture);
    return state.turn === 'w' && target?.side === 'b' && !!target.cards?.includes('duel');
  }

  function play(state: GameState, move: Move, options = turnOptions(state), duelWinner?: Side | null): GameState {
    if (state.turn === 'b') return Draughts.play(state, move, options);
    const duel = challenges(state, move);
    if (duel && duelWinner === undefined) throw Error('Resolve Tic Tac Toe before committing the capture.');
    const actor = pieceAt(state.board, move.from);
    const captured = pieceAt(state.board, move.capture);
    const reversed = duel && duelWinner === 'b';
    const board = reversed ? state.board.slice() : Chess.movedBoard(state, move);
    const reserve = { ...state.reserve };
    const locks: GameState['locks'] = { ...state.locks, w: null };
    const queue = { ...state.queue, w: state.queue.w.slice(options.consumed ?? 0) };
    const revealedSide = reversed ? 'w' : 'b';
    const cards = (reversed ? actor?.cards ?? [] : captured?.side === 'b' ? captured.cards ?? [] : [])
      .filter(card => card !== 'duel');
    queue[revealedSide] = [...queue[revealedSide], ...cards.filter(queuesCommand)];

    if (reversed) {
      if (!captured || move.from === undefined || move.capture === undefined) throw Error('A duel requires a capture.');
      board[move.from] = null;
      board[move.capture] = { ...captured, cards: captured.cards?.filter(card => card !== 'duel') };
    }
    if (cards.includes('lock')) locks[Chess.other(revealedSide)] = (reversed ? captured : actor)?.id ?? null;
    const fallen = reversed ? actor : captured;
    if (fallen?.type === 'p') reserve[fallen.side]++;
    if (move.revive) reserve.w--;
    const duelWin = reversed && (actor?.type === 'k' || Chess.inCheck(board, 'w')) ? 'b' : null;
    return {
      ...state, board, reserve, locks, queue, turn: 'b', duelWin,
      nextId: state.nextId + Number(!!move.revive),
      resolution: { kind: 'hybrid', cards, revealedSide, reversed, duel, duelWinner }
    };
  }

  return { start, play, turnOptions, challenges };
})();

export const TicTacToe = (() => {
  const LINES = [[0, 1, 2], [3, 4, 5], [6, 7, 8], [0, 3, 6], [1, 4, 7], [2, 5, 8], [0, 4, 8], [2, 4, 6]];

  function start(): DuelState {
    return { cells: Array<Side | null>(9).fill(null), turn: 'b', line: null, winner: null, done: false };
  }

  function play(state: DuelState, cell: number): DuelState {
    if (state.done || !Number.isInteger(cell) || cell < 0 || cell > 8 || state.cells[cell]) return state;
    const cells = state.cells.slice();
    cells[cell] = state.turn;
    const line = LINES.find(indices => indices.every(index => cells[index] === state.turn)) ?? null;
    return { cells, turn: Chess.other(state.turn), line, winner: line ? state.turn : null, done: !!line || cells.every(Boolean) };
  }

  return { start, play };
})();

const CHESS_CARDS = {
  lock: {
    name: 'กับดักขังตัว', summary: 'ขังตัวที่กินเราในตาถัดไปของคู่แข่ง',
    detail: 'ตัวที่เพิ่งกินหมากของคุณจะเดินไม่ได้ในตาถัดไปของคู่แข่ง เว้นแต่ต้องใช้ตัวนั้นแก้เช็ก',
  },
  revive: {
    name: 'เรียกเบี้ยกลับ', summary: 'เอาเบี้ยที่เสียกลับมาลงแทนการเดิน',
    detail: 'เลือกช่องเริ่มต้นของเบี้ยฝั่งคุณที่ว่างอยู่ เพื่อนำเบี้ยที่เสียไปกลับมาหนึ่งตัวโดยไม่มีคำสั่งติดมาด้วย',
    prompt: 'เลือกช่องที่มีจุดบนแถวเริ่มต้น เพื่อวางเบี้ยที่เสียไปกลับลงกระดาน 1 ตัว',
  },
  friendly: {
    name: 'กินพวกเดียวกัน', summary: 'ใช้หมากของเรากินเบี้ยฝ่ายตัวเอง',
    detail: 'ใช้หมากของคุณกินเบี้ยของตัวเองหนึ่งตัวตามรูปแบบการกินของหมากนั้น และย้ายเข้าไปแทนที่เบี้ย',
    prompt: 'เลือกหมากของคุณ แล้วคลิกเบี้ยฝ่ายตัวเองที่หมากนั้นกินได้ เบี้ยตัวนั้นจะถูกนำออกจากกระดาน',
  },
  push: {
    name: 'เดินเปิดทาง', summary: 'บังคับเดินเบี้ยตัวเองขึ้นหนึ่งช่อง',
    detail: 'เลือกเบี้ยของคุณหนึ่งตัวแล้วเดินไปข้างหน้าหนึ่งช่อง',
    prompt: 'เลือกเบี้ยของคุณ 1 ตัว แล้วคลิกจุดบนช่องด้านหน้าเพื่อเดินหนึ่งช่อง',
  },
};
const DRAUGHTS_CARDS = {
  lock: {
    ...CHESS_CARDS.lock,
    detail: 'ตัวที่เพิ่งกินหมากของคุณจะถูกขังในตาถัดไปของคู่แข่ง ถ้าเป็นตัวเดียวที่ใช้เดินหรือกินได้ ยังใช้ตัวนั้นได้',
  },
  revive: {
    ...CHESS_CARDS.revive,
    detail: 'นำเบี้ยที่เสียไปกลับมาหนึ่งตัวโดยวางบนช่องเข้มที่ว่างในสองแถวหลังของคุณ',
    prompt: 'เลือกช่องที่มีจุดในสองแถวหลัง เพื่อวางเบี้ยที่เสียไปกลับลงกระดาน 1 ตัว',
  },
  friendly: {
    ...CHESS_CARDS.friendly,
    detail: 'กระโดดข้ามเบี้ยฝ่ายตัวเองหนึ่งตัวตามทางกินของหมากที่เลือก แล้วเอาเบี้ยตัวนั้นออกจากกระดาน',
    prompt: 'เลือกหมากของคุณ แล้วคลิกช่องลงหลังเบี้ยฝ่ายตัวเองเพื่อกระโดดกินเบี้ยตัวนั้น',
  },
  push: {
    ...CHESS_CARDS.push,
    detail: 'เลือกเบี้ยฝ่ายตัวเองหนึ่งตัว แล้วเดินเฉียงไปข้างหน้าหนึ่งช่อง',
    prompt: 'เลือกเบี้ยของคุณ 1 ตัว แล้วคลิกช่องเฉียงด้านหน้าที่มีจุดเพื่อเดินหนึ่งช่อง',
  },
};
const HYBRID_WHITE_CARDS = {
  ...CHESS_CARDS,
  lock: {
    ...DRAUGHTS_CARDS.lock,
    summary: 'ขังหมากฮอสที่กินหมากของคุณในตาถัดไป',
    detail: 'ตัวที่เพิ่งกินหมากของคุณจะถูกขังในตาถัดไปของฝ่ายหมากฮอส ถ้ามีทางกิน ให้เลือกตัวอื่นที่กินได้ก่อน ถ้าตัวที่ถูกขังเป็นตัวเดียวที่กินได้หรือเป็นตัวเดียวที่เดินได้ในตาที่ไม่มีทางกิน ยังใช้ตัวนั้นได้',
  },
};
const HYBRID_BLACK_CARDS = {
  ...DRAUGHTS_CARDS,
  lock: {
    ...CHESS_CARDS.lock,
    summary: 'ขังหมากรุกที่กินหมากของคุณในตาถัดไป',
    detail: 'ตัวที่เพิ่งกินหมากของคุณจะถูกขังในตาถัดไปของฝ่ายหมากรุก ยังใช้ตัวนั้นได้เมื่อคิงถูกเช็กและไม่มีทางแก้เช็กโดยใช้หมากตัวอื่น',
  },
  duel: {
    name: 'ดวล Tic Tac Toe', summary: 'ถูกกินเมื่อไร เปิดเกม XO เพื่อลุ้นสวนกิน',
    detail: 'หมากฮอสเล่น X และเริ่มก่อน ถ้าชนะจะอยู่ช่องเดิมและกินตัวที่เข้ามาแทน ถ้าเสมอหรือแพ้จะถูกกินตามเดิม ใช้สกิลนี้ได้ครั้งเดียว',
  },
};
export const MODES: Record<ModeId, Mode> = {
  chess: { name: 'หมากรุก', engine: Chess, cards: CHESS_CARDS },
  draughts: { name: 'หมากฮอสไทย', engine: Draughts, cards: DRAUGHTS_CARDS },
  hybrid: { name: 'Chess vs หมากฮอส', engine: Hybrid, cards: HYBRID_WHITE_CARDS, blackCards: HYBRID_BLACK_CARDS },
};
export const SYMBOLS: Record<PieceType, string> = { k: '♚', q: '♛', r: '♜', b: '♝', n: '♞', p: '♟', h: '♟' };
export const PIECE_NAMES: Record<PieceType, string> = { k: 'คิง', q: 'ควีน', r: 'เรือ', b: 'บิชอป', n: 'ม้า', p: 'เบี้ย', h: 'ฮอส' };
export const SIDE_NAMES: Record<Side, string> = { w: 'ฝ่ายขาว', b: 'ฝ่ายดำ' };

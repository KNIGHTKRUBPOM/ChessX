import {
  Chess, Draughts, Hybrid, MODES, TicTacToe, pieceAt,
  type CardId, type GameState, type ModeId, type Move, type Side, type TurnOptions,
} from './rules';
import type { Duel, Placements } from './save';

export interface Outcome {
  winner: Side | null;
  reason: 'duel_king' | 'duel_check' | 'no_moves' | 'no_pieces' | 'checkmate' | 'stalemate' | 'kings_only';
}

export interface Snapshot {
  state: GameState;
  options: TurnOptions;
  outcome: Outcome | null;
}

export interface MoveSnapshot extends Snapshot {
  duel: Duel | null;
}

interface GameRuntime {
  start(mode: ModeId): Promise<Snapshot>;
  inspect(mode: ModeId, state: GameState): Promise<Snapshot>;
  setup(mode: ModeId, state: GameState, side: Side, placements: Placements): Promise<Snapshot>;
  move(mode: ModeId, state: GameState, move: Move): Promise<MoveSnapshot>;
  duel(mode: ModeId, state: GameState, duel: Duel, cell: number): Promise<{ duel: Duel }>;
  finishDuel(mode: ModeId, state: GameState, duel: Duel): Promise<MoveSnapshot>;
}

function isDiscTurn(mode: ModeId, side: Side) {
  return mode === 'draughts' || (mode === 'hybrid' && side === 'b');
}

function localSnapshot(mode: ModeId, state: GameState): Snapshot {
  const options = MODES[mode].engine.turnOptions(state);
  const { board, turn } = state;
  const winner = Chess.other(turn);
  let outcome: Outcome | null = null;
  if (state.duelWin) {
    outcome = { winner: 'b', reason: board.some(piece => piece?.type === 'k') ? 'duel_check' : 'duel_king' };
  } else if (!options.moves.length) {
    if (isDiscTurn(mode, turn)) {
      outcome = { winner, reason: board.some(piece => piece?.side === turn) ? 'no_moves' : 'no_pieces' };
    } else {
      outcome = options.checked ? { winner, reason: 'checkmate' } : { winner: null, reason: 'stalemate' };
    }
  } else if (mode === 'chess' && !options.forced && board.every(piece => !piece || piece.type === 'k')) {
    outcome = { winner: null, reason: 'kings_only' };
  }
  return { state, options, outcome };
}

const browserRuntime: GameRuntime = {
  async start(mode) {
    return localSnapshot(mode, MODES[mode].engine.start());
  },
  async inspect(mode, state) {
    return localSnapshot(mode, state);
  },
  async setup(mode, state, side, placements) {
    const updated = structuredClone(state);
    const definition = MODES[mode];
    const deck = side === 'b' ? definition.blackCards ?? definition.cards : definition.cards;
    for (const card of Object.keys(deck) as CardId[]) {
      const piece = pieceAt(updated.board, placements[card]);
      if (!piece || piece.side !== side || piece.type === 'k') throw new Error('Invalid command placement.');
      if (mode === 'hybrid') (piece.cards ??= []).push(card);
      else piece.card = card;
    }
    return localSnapshot(mode, updated);
  },
  async move(mode, state, move) {
    if (mode === 'hybrid' && Hybrid.challenges(state, move)) {
      return { ...localSnapshot(mode, state), duel: { move, board: TicTacToe.start() } };
    }
    const options = MODES[mode].engine.turnOptions(state);
    const updated = isDiscTurn(mode, state.turn) ? Draughts.play(state, move, options)
      : mode === 'hybrid' ? Hybrid.play(state, move, options)
      : Chess.play(state, move);
    return { ...localSnapshot(mode, updated), duel: null };
  },
  async duel(_mode, _state, duel, cell) {
    return { duel: { move: duel.move, board: TicTacToe.play(duel.board, cell) } };
  },
  async finishDuel(mode, state, duel) {
    const updated = Hybrid.play(state, duel.move, Hybrid.turnOptions(state), duel.board.winner);
    return { ...localSnapshot(mode, updated), duel: null };
  },
};

const api = new URL('./api/', window.location.href);

async function post<T>(path: string, data: unknown): Promise<T> {
  const response = await fetch(new URL('game/' + path, api), {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(data),
    signal: AbortSignal.timeout(8_000),
  });
  if (!response.ok) throw new Error('Game API returned ' + response.status);
  return response.json() as Promise<T>;
}

const pythonRuntime: GameRuntime = {
  start: mode => post('start', { mode }),
  inspect: (mode, state) => post('options', { mode, state }),
  setup: (mode, state, side, placements) => post('setup', { mode, state, side, placements }),
  move: (mode, state, move) => post('move', { mode, state, move: { from: move.from, to: move.to, promote: move.promote } }),
  duel: (mode, state, duel, cell) => post('duel', { mode, state, duel, cell }),
  finishDuel: (mode, state, duel) => post('duel/finish', { mode, state, duel }),
};

async function detectRuntime(): Promise<GameRuntime> {
  try {
    const health = await fetch(new URL('health', api), { cache: 'no-store', signal: AbortSignal.timeout(2_000) });
    if (health.ok && health.headers.get('Content-Type')?.includes('application/json')) {
      const payload = await health.json();
      if (payload?.engine === 'python' && payload.version === 1) {
        document.documentElement.dataset.rulesEngine = 'python';
        return pythonRuntime;
      }
    }
  } catch {
    // The same dist can be hosted on an ordinary static server.
  }
  document.documentElement.dataset.rulesEngine = 'browser';
  return browserRuntime;
}

export const gameRuntime = detectRuntime();

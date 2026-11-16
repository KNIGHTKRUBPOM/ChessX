import './theme.css';
import {
  Chess, Draughts, Hybrid, MODES, PIECE_NAMES, SIDE_NAMES, SYMBOLS, pieceAt,
  type CardId, type CardSet, type GameState, type ModeId, type Move, type Piece, type Side, type TurnOptions,
} from './game/rules';
import { mountGameBoard, mountDuelBoard, type BoardSquareView, type DuelCellView } from './game/board-scene';
import { mountProfiles } from './profile';
import { mountAccount } from './account';
import { mountOnlineLobby, type OnlineAction, type OnlineSnapshot } from './online-lobby';
import { mountThemePicker } from './theme-picker';
import { gameRuntime, type Snapshot, type Outcome } from './game/runtime';
import {
  isModeId, readMatchSave, type Duel, type HistoryEntry, type MatchPhase, type MatchSave,
  type Notice, type Placements, type Result,
} from './game/save';

function $<T extends HTMLElement = HTMLElement>(id: string): T {
  const element = document.getElementById(id);
  if (!element) throw new Error('Missing game element: ' + id);
  return element as T;
}

const sidebar = $('sidebar');
const board = $('board');
const modeForm = $<HTMLFormElement>('mode-form');
const commandDialog = $<HTMLDialogElement>('command-dialog');
const duelDialog = $<HTMLDialogElement>('duel-dialog');
const restartDialog = $<HTMLDialogElement>('restart');
const resumeButton = $<HTMLButtonElement>('resume-button');
const saveSlot = 'match';
const gameView = $('game-view');
const profileControls = $('profile-controls');
const onlineControls = $('online-controls');
let busy = false;

async function runRequest(work: (runtime: Awaited<typeof gameRuntime>) => Promise<void>) {
  if (busy) return;
  busy = true;
  gameView.setAttribute('aria-busy', 'true');
  profileControls.inert = true;
  for (const id of ['engine-message', 'duel-error']) $(id).hidden = true;
  try {
    await work(await gameRuntime);
  } catch (error) {
    console.error('Game rules request failed', error);
    const status = $(duelDialog.open ? 'duel-error' : 'engine-message');
    status.textContent = 'ประมวลผลตานี้ไม่ได้ กรุณาลองอีกครั้ง';
    status.hidden = false;
  } finally {
    busy = false;
    profileControls.inert = false;
    gameView.removeAttribute('aria-busy');
  }
}

const gameBoard = mountGameBoard(board, selectSquare);
const duelBoard = mountDuelBoard($('duel-grid'), playDuel);
mountThemePicker($<HTMLDialogElement>('theme-dialog'), () => {
  gameBoard.refreshTheme();
  duelBoard.refreshTheme();
});
const profiles = mountProfiles(profileControls, () => showMenu(false));
const account = mountAccount($<HTMLButtonElement>('account-trigger'), $<HTMLDialogElement>('account-dialog'));
let onlineRoom: OnlineSnapshot | null = null;
let onlineBusy = false;
let activeDuelCaption = '';
let lastDuelSeen = -1;
let noticeSeen = -1;
let pendingOnlineNotice = false;
const onlineLobby = mountOnlineLobby(onlineControls, {
  getMode() {
    const value = new FormData(modeForm).get('mode');
    return isModeId(value) ? value : 'chess';
  },
  getPreferredName: account.getDisplayName,
  onSnapshot: renderOnlineRoom,
  onConnectionStatus(message) {
    const status = $('duel-connection-status');
    if (status.textContent !== message) status.textContent = message;
  },
  onLeave: exitOnlineRoom,
});
let modeId: ModeId = 'chess';
let mode = MODES[modeId];
let game: GameState;
let phase: MatchPhase | 'menu' = 'menu';
let setupSide: Side = 'w';
let placements: Placements = {};
let selectedCard: CardId = 'lock';
let setupTip = '';
let selectedSquare: number | null = null;
let inspectedPieceId: number | null = null;
let lastMove: Move | null = null;
let options: TurnOptions;
let notices: Notice[] = [];
let result: Result | null = null;
let history: HistoryEntry[] = [];
let duel: Duel | null = null;

const cardsFor = (side: Side) => side === 'b' ? mode.blackCards ?? mode.cards : mode.cards;
const cardIds = (deck: CardSet) => Object.keys(deck) as CardId[];
const setupCards = () => cardIds(cardsFor(setupSide));
const setupLimit = () => mode.engine === Hybrid && setupSide === 'b' ? 2 : 1;
const usesDiscs = (side: Side, selectedMode = mode) =>
  selectedMode.engine === Draughts || (selectedMode.engine === Hybrid && side === 'b');
const darkSquare = (square: number) => (Math.floor(square / 8) + square % 8) % 2 === 1;
const sideName = (side: Side) => mode.engine === Hybrid
  ? SIDE_NAMES[side] + ' (' + (side === 'w' ? 'หมากรุก' : 'หมากฮอส') + ')'
  : SIDE_NAMES[side];

function escapeHtml(text: string) {
  return text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('>', '&gt;');
}

function setMode(value: ModeId) {
  modeId = value;
  mode = MODES[value];
}

function showGame() {
  $('menu').hidden = true;
  $('game-toolbar').hidden = false;
  $('game-view').hidden = false;
  $('mode-label').textContent = mode.name + (onlineRoom ? ' · เล่นออนไลน์' : ' · เล่นสองคนบนเครื่องเดียว');
  $('menu-button').hidden = Boolean(onlineRoom);
  $('restart-button').hidden = Boolean(onlineRoom);
  profileControls.hidden = Boolean(onlineRoom);
  onlineControls.hidden = !onlineRoom;
  $('board-section').setAttribute('aria-label', 'กระดาน' + mode.name);
}

function exitOnlineRoom() {
  onlineRoom = null;
  inspectedPieceId = null;
  pendingOnlineNotice = false;
  duel = null;
  $('duel-leave').hidden = true;
  $('duel-leave-permanently').hidden = true;
  $('duel-connection-status').textContent = '';
  if (duelDialog.open) duelDialog.close();
  if (commandDialog.open) commandDialog.close();
  showMenu();
}

async function submitOnline(action: OnlineAction) {
  if (onlineBusy) return;
  onlineBusy = true;
  gameView.setAttribute('aria-busy', 'true');
  $('duel-error').hidden = true;
  try {
    const sent = await onlineLobby.submit(action);
    if (!sent && duelDialog.open) {
      $('duel-error').textContent = 'ส่งตานี้ไม่สำเร็จ กรุณาลองอีกครั้ง';
      $('duel-error').hidden = false;
    }
  } finally {
    onlineBusy = false;
    gameView.removeAttribute('aria-busy');
  }
}

function renderOnlineRoom(snapshot: OnlineSnapshot) {
  const previous = onlineRoom;
  const joined = previous?.code !== snapshot.code;
  if (joined) {
    if (commandDialog.open) commandDialog.close();
    if (duelDialog.open) duelDialog.close();
    if (restartDialog.open) restartDialog.close('');
    const promotion = $<HTMLDialogElement>('promotion');
    if (promotion.open) promotion.close();
    setMode(snapshot.mode);
    setupSide = snapshot.side;
    game = mode.engine.start();
    placements = { ...snapshot.myPlacements };
    selectedCard = setupCards()[0];
    setupTip = '';
    inspectedPieceId = null;
    notices = [];
    duel = null;
    lastDuelSeen = -1;
    noticeSeen = -1;
    activeDuelCaption = '';
    pendingOnlineNotice = false;
  }
  onlineRoom = snapshot;
  game.board = snapshot.board;
  game.turn = snapshot.turn;
  game.chain = snapshot.chainAt === null ? null : { at: snapshot.chainAt, cards: [], route: [] };
  options = snapshot.options ?? { moves: [], forced: false, checked: snapshot.checked };
  lastMove = snapshot.lastMove;
  phase = snapshot.phase === 'setup' || snapshot.phase === 'waiting' ? 'setup' : 'play';
  if (joined || previous?.revision !== snapshot.revision) selectedSquare = snapshot.chainAt;
  beginTurn(snapshot.outcome, snapshot.notice?.cards, snapshot.notice?.side);
  history = snapshot.history.map(entry => {
    const actor = entry.actor ? PIECE_NAMES[entry.actor] : 'หมาก';
    const origin = entry.move.from === undefined ? '' : Chess.name(entry.move.from);
    const destination = Chess.name(entry.move.to);
    const move = entry.move.revive ? 'นำเบี้ยกลับที่ ' + destination
      : entry.reversed ? actor + 'ที่ช่อง ' + origin + ' ถูกสวนกิน'
      : actor + ' ' + origin + (entry.captured ? ' × ' : ' → ') + destination;
    const effects = entry.cards.map(id => cardsFor(entry.reversed ? 'w' : Chess.other(entry.side))[id]?.name).filter(Boolean);
    if (entry.duelWinner !== undefined) {
      effects.unshift(entry.duelWinner === 'b' ? 'หมากฮอสชนะ XO' : entry.duelWinner === 'w' ? 'หมากรุกชนะ XO' : 'เสมอ XO');
    }
    return { move: sideName(entry.side) + ' · ' + move, effect: effects.join(' · ') };
  });

  $('duel-leave').hidden = false;
  $('duel-leave-permanently').hidden = false;
  showGame();
  render();

  const noticeRevision = snapshot.notice?.revision ?? snapshot.revision;
  if (noticeSeen !== noticeRevision && notices.some(notice => notice.revealed || notice.required)) {
    noticeSeen = noticeRevision;
    pendingOnlineNotice = true;
  }
  if (snapshot.duel) {
    duel = snapshot.duel;
    if (commandDialog.open) commandDialog.close();
    if (duelDialog.open) renderDuel();
    else openDuelDialog(duel.move);
  } else if (snapshot.lastDuel && lastDuelSeen !== snapshot.lastDuel.revision &&
    (previous?.phase === 'duel' || snapshot.lastDuel.revision === snapshot.revision)) {
    lastDuelSeen = snapshot.lastDuel.revision;
    duel = { move: snapshot.lastDuel.move ?? snapshot.lastMove!, board: snapshot.lastDuel.board };
    if (!duelDialog.open) {
      if (commandDialog.open) commandDialog.close();
      $('duel-capture').textContent = activeDuelCaption || '';
      duelDialog.showModal();
    }
    renderDuel();
    $('duel-continue').focus({ preventScroll: true });
  } else if (!duelDialog.open && pendingOnlineNotice && !commandDialog.open) {
    pendingOnlineNotice = false;
    showCommandDialog();
  }
}

function newGame(nextMode = modeId) {
  return runRequest(async runtime => {
    const next = await runtime.start(nextMode);
    if (onlineRoom) return;
    setMode(nextMode);
    ({ state: game, options } = next);
    phase = 'setup';
    setupSide = 'w';
    placements = {};
    selectedCard = setupCards()[0];
    setupTip = '';
    selectedSquare = null;
    inspectedPieceId = null;
    lastMove = null;
    notices = [];
    result = null;
    history = [];
    duel = null;
    showGame();
    render();
  });
}

function showMenu(restoreFocus = true) {
  phase = 'menu';
  inspectedPieceId = null;
  profileControls.hidden = false;
  onlineControls.hidden = false;
  $('menu-button').hidden = false;
  $('restart-button').hidden = false;
  $('menu').hidden = false;
  $('game-toolbar').hidden = true;
  $('game-view').hidden = true;
  $('mode-label').textContent = 'เล่นสองคนบนเครื่องเดียว';
  $('storage-message').hidden = true;
  $('engine-message').hidden = true;
  resumeButton.hidden = !readMatchSave(profiles.loadGame<unknown>(saveSlot));
  renderModePreview();
  if (restoreFocus) modeForm.querySelector<HTMLInputElement>('input:checked')?.focus();
}

function saveCurrent() {
  if (phase === 'menu' || onlineRoom) return;
  const save: MatchSave = {
    version: 1, modeId, game, phase, setupSide, placements, selectedCard, lastMove, notices,
    commandOpen: commandDialog.open, result, history, duel,
  };
  const stored = profiles.saveGame(saveSlot, save);
  const status = $('storage-message');
  status.hidden = stored;
  status.textContent = stored ? '' : 'บันทึกเกมในเบราว์เซอร์ไม่ได้ เกมยังเล่นต่อได้ในหน้านี้';
}

function resumeGame() {
  const saved = readMatchSave(profiles.loadGame<unknown>(saveSlot));
  if (!saved) return showMenu();
  return runRequest(async runtime => {
    const next = await runtime.inspect(saved.modeId, saved.game);
    if (onlineRoom) return;
    setMode(saved.modeId);
    const radio = modeForm.querySelector<HTMLInputElement>('input[value="' + modeId + '"]');
    if (radio) radio.checked = true;
    ({ phase, setupSide, placements, selectedCard, lastMove, notices, history, duel } = saved);
    ({ state: game, options } = next);
    result = phase === 'play' ? describeOutcome(next.outcome) : null;
    setupTip = '';
    selectedSquare = game.chain?.at ?? null;
    inspectedPieceId = null;
    showGame();
    render();
    if (duel) openDuelDialog(duel.move);
    else if (saved.commandOpen) showCommandDialog();
  });
}

function sideLabel(side: Side, text = sideName(side)) {
  return `<div class="side-label"><i class="side-dot ${side === 'b' ? 'black' : ''}" aria-hidden="true"></i>${text}</div>`;
}

function privateSkills(piece: Piece | null, square: number): CardId[] {
  if (!piece || piece.side !== (onlineRoom?.side ?? game.turn)) return [];
  if (onlineRoom) return onlineRoom.board[square]?.skills ?? [];
  return piece.cards ?? (piece.card ? [piece.card] : []);
}

function markerCount(piece: Piece | null, square: number) {
  if (phase === 'setup') return Object.values(placements).filter(placed => placed === square).length;
  return privateSkills(piece, square).length;
}

function renderPieceSkills() {
  const panel = $('piece-skills');
  const square = phase === 'play' && inspectedPieceId !== null
    ? game.board.findIndex(piece => piece?.id === inspectedPieceId && piece.side === (onlineRoom?.side ?? game.turn))
    : -1;
  const piece = game.board[square];
  panel.hidden = !piece;
  if (!piece) {
    inspectedPieceId = null;
    $('piece-skills-title').textContent = '';
    $('piece-skills-content').replaceChildren();
    return;
  }
  $('piece-skills-title').textContent = 'สกิลของ' + PIECE_NAMES[piece.type] + ' · ' + Chess.name(square);
  const skills = privateSkills(piece, square);
  $('piece-skills-content').innerHTML = skills.length ? skills.map(id => {
    const card = cardsFor(piece.side)[id]!;
    return `<div class="notice"><strong>${escapeHtml(card.name)}</strong><p>${escapeHtml(card.detail)}</p></div>`;
  }).join('') : '<p>ตัวนี้ไม่มีสกิล</p>';
}

function pieceGraphic(piece: Piece, selectedMode = mode) {
  if (usesDiscs(piece.side, selectedMode)) {
    return `<span class="disc ${piece.side}${piece.type === 'h' ? ' king' : ''}" aria-hidden="true"></span>`;
  }
  return `<span class="piece ${piece.side}" aria-hidden="true">${SYMBOLS[piece.type]}</span>`;
}

function renderModePreview() {
  const value = new FormData(modeForm).get('mode');
  const selectedMode = isModeId(value) ? MODES[value] : MODES.chess;
  const pieces = selectedMode.engine.start().board;
  $('menu-preview').innerHTML = pieces.map((piece, square) =>
    `<div class="preview-square${darkSquare(square) ? ' dark' : ''}">${piece ? pieceGraphic(piece, selectedMode) : ''}</div>`).join('');
}

function renderBoard() {
  const flipped = onlineRoom ? onlineRoom.side === 'b' : phase === 'setup' && setupSide === 'b';
  const hybridSetup = phase === 'setup' && mode.engine === Hybrid;
  const assignedSquare = hybridSetup ? placements[selectedCard] : undefined;
  const playStatus = options.checked ? ' · ถูกเช็ก' : options.mustCapture ? ' · บังคับกิน' : '';
  const setupCaption = hybridSetup ? 'วาง ' + cardsFor(setupSide)[selectedCard]?.name : sideName(setupSide) + ' · วางคำสั่ง';
  const caption = phase === 'play' ? sideName(game.turn) + playStatus :
    phase === 'setup' ? setupCaption : 'ส่งเครื่อง';
  $('board-caption').textContent = result ? 'จบเกม' : caption;
  $('skill-legend').hidden = phase !== 'play';
  $('privacy').hidden = phase !== 'handoff';
  board.inert = phase === 'handoff';

  const allowed = phase === 'play' && !result ? options.moves : [];
  const targets = new Set(allowed.filter(move => move.revive || move.from === selectedSquare).map(move => move.to));
  const origins = new Set(allowed.map(move => move.from));
  const squares: BoardSquareView[] = game.board.map((_, viewIndex) => {
    const square = flipped ? 63 - viewIndex : viewIndex;
    const coordinate = Chess.name(square);
    const piece = phase === 'handoff' ? null : game.board[square];
    const marks = markerCount(piece, square);
    const locked = phase === 'play' && piece !== null && (onlineRoom
      ? Boolean(onlineRoom.board[square]?.locked)
      : game.locks[piece.side] === piece.id);
    const assigned = assignedSquare === square;
    const target = targets.has(square);
    const label = [coordinate, piece ? PIECE_NAMES[piece.type] + SIDE_NAMES[piece.side] : 'ช่องว่าง'];
    if (marks) label.push(marks > 1 ? 'ซ่อน ' + marks + ' คำสั่ง' : 'มีคำสั่งซ่อนอยู่');
    if (assigned) label.push('วาง ' + cardsFor(setupSide)[selectedCard]?.name + ' ที่นี่');
    if (locked) label.push('ติดกับดักขังตัว');
    if (target) label.push('ช่องที่เลือกได้');
    return {
      square, coordinate, label: label.join(' '), marks, locked, target, assigned,
      last: lastMove?.from === square || lastMove?.to === square,
      selected: selectedSquare === square,
      checked: phase === 'play' && options.checked === true && piece?.type === 'k' && piece.side === game.turn,
      canMove: target || origins.has(square),
      canPlace: phase === 'setup' && piece?.side === setupSide && piece.type !== 'k',
      piece: piece ? { side: piece.side, symbol: SYMBOLS[piece.type], disc: usesDiscs(piece.side), king: piece.type === 'h' } : undefined,
    };
  });
  gameBoard.render(squares);
}



function openDuelDialog(move: Move) {
  const actor = pieceAt(game.board, move.from);
  const target = pieceAt(game.board, move.capture);
  if (!actor || !target || move.from === undefined) return;
  activeDuelCaption = PIECE_NAMES[actor.type] + ' ' + Chess.name(move.from) +
    ' กำลังจะกิน' + PIECE_NAMES[target.type] + ' ' + Chess.name(move.to);
  $('duel-capture').textContent = activeDuelCaption;
  duelDialog.showModal();
  renderDuel();
  if (duel?.board.done) $('duel-continue').focus();
  else duelBoard.focus();
  saveCurrent();
}

function renderDuel() {
  if (!duel) return;
  const { cells, turn, line, winner, done } = duel.board;
  $('duel-status').textContent = done ? (winner === 'b' ? 'หมากฮอสชนะ · สวนกินตัวที่เข้ามา' :
    winner === 'w' ? 'หมากรุกชนะ · หมากฮอสถูกกิน' : 'เสมอ · หมากฮอสถูกกิน') :
    turn === 'b' ? 'ตาหมากฮอส · ลง X' : 'ตาหมากรุก · ลง O';
  const views: DuelCellView[] = cells.map((cell, index) => {
    const mark = cell === 'b' ? 'X' : cell === 'w' ? 'O' : undefined;
    return {
      mark, winning: line?.includes(index), disabled: Boolean(mark) || done || Boolean(onlineRoom && onlineRoom.side !== turn),
      label: 'แถว ' + (Math.floor(index / 3) + 1) + ' ช่อง ' + (index % 3 + 1) + ' ' + (mark ?? 'ว่าง'),
    };
  });
  duelBoard.render(views);
  $('duel-actions').hidden = !done;
}

function playDuel(index: number) {
  if (!duel || duel.board.done || duel.board.cells[index]) return;
  if (onlineRoom) {
    if (duel.board.turn === onlineRoom.side) void submitOnline({ type: 'duel', cell: index });
    return;
  }
  const activeDuel = duel;
  return runRequest(async runtime => {
    ({ duel } = await runtime.duel(modeId, game, activeDuel, index));
    renderDuel();
    if (duel.board.done) $('duel-continue').focus({ preventScroll: true });
    else duelBoard.focus(undefined, { preventScroll: true });
    saveCurrent();
  });
}

function renderSetup() {
  const count = Object.keys(placements).length;
  const ids = setupCards();
  const instruction = setupLimit() > 1 ? 'เลือกสกิลแล้วคลิกหมากของคุณ ซ้อนได้ตัวละ 2 ใบ' :
    `เลือกคำสั่ง แล้วคลิกหมากฝ่ายตัวเอง ตัวละหนึ่งใบ${usesDiscs(setupSide) ? '' : ' ยกเว้นคิง'}`;
  sidebar.innerHTML = `<section class="panel" aria-labelledby="phase-title">
    <h2 id="phase-title">ซ่อนคำสั่งใต้หมาก</h2>
    ${sideLabel(setupSide)}
    <p>${instruction}</p>
    <div class="deck">${ids.map(id => {
      const card = cardsFor(setupSide)[id]!;
      const active = id === selectedCard;
      const placed = placements[id] === undefined ? '—' : Chess.name(placements[id]!);
      return `<button type="button" class="card ${active ? 'active' : ''}" data-card="${id}" aria-pressed="${active}">
        <span><strong class="card-name">${card.name}</strong><span class="card-summary">${card.summary}</span></span>
        <span class="card-square">${placed}</span>
      </button>`;
    }).join('')}</div>
    <p class="tip" role="status">${setupTip || `วางแล้ว ${count} / ${ids.length} ใบ`}</p>
    <div class="panel-actions">
      <button type="button" class="ghost" data-action="clear" ${count ? '' : 'disabled'}>ล้างการวาง</button>
      <button type="button" class="primary" data-action="confirm" ${count < ids.length ? 'disabled' : ''}>${onlineRoom ? 'ยืนยันการวางสกิล' : setupSide === 'w' ? 'ยืนยันและส่งเครื่อง' : 'เริ่มเล่น'}</button>
    </div>
  </section>`;
}

function renderHandoff() {
  sidebar.innerHTML = `<section class="panel" aria-labelledby="phase-title">
    <h2 id="phase-title">ถึงตาวางของฝ่ายดำ</h2>
    <p>เมื่อรับเครื่องแล้ว กดปุ่มเพื่อเลือกที่ซ่อนคำสั่งของคุณ</p>
    <button type="button" class="primary wide" data-action="black">ฝ่ายดำพร้อมแล้ว</button>
  </section>`;
}

function noticeText(notice: Notice) {
  return `<p>${escapeHtml(notice.description)}</p>${notice.note ? `<p class="command-note">${escapeHtml(notice.note)}</p>` : ''}`;
}

function showCommandDialog() {
  const displayed = notices.filter(notice => notice.revealed || notice.required);
  if (!displayed.length) return;
  const single = displayed.length === 1;
  const event = displayed.some(notice => notice.revealed) ? 'เปิดคำสั่ง' : 'ถึงเวลาทำคำสั่ง';
  const side = single ? displayed[0].side : game.turn;
  $('command-meta').textContent = `${event} · ${result || side !== game.turn ? '' : 'ตา'}${sideName(side)}`;
  $('command-title').textContent = single ? displayed[0].name : 'คำสั่งที่เปิดขึ้น';
  $('command-body').innerHTML = single ? noticeText(displayed[0]) : displayed.map(notice =>
    `<section><h3>${escapeHtml(notice.name)}</h3>${noticeText(notice)}</section>`).join('');
  $('command-dismiss').textContent = result ? 'ดูผลเกม' : options.forced ? 'ไปทำคำสั่ง' : 'เล่นต่อ';
  commandDialog.showModal();
  saveCurrent();
}

function renderPlay() {
  const locked = onlineRoom
    ? onlineRoom.board.find(piece => piece?.side === game.turn && piece.locked)
    : game.board.find(piece => piece?.side === game.turn && piece.id === game.locks[game.turn]);
  let hint = 'กดหมากของคุณเพื่อดูสกิล แล้วเลือกช่องที่จะเดิน';
  if (onlineRoom && onlineRoom.side !== game.turn) hint = 'ตาของคู่แข่ง คุณยังดูสกิลของหมากตัวเองได้';
  if (options.mustCapture) hint = game.chain ? 'เลือกช่องลงเพื่อกระโดดกินต่อด้วยตัวเดิม' : 'เลือกหมากที่กระโดดกินได้ แล้วเลือกช่องลง';
  const title = result?.title ?? (options.forced ? 'ทำคำสั่งในตานี้' : game.chain ? 'กระโดดกินต่อ' :
    options.mustCapture ? 'ต้องกินหมากคู่แข่ง' : onlineRoom ? (onlineRoom.side === game.turn ? 'ตาของคุณ' : 'รอคู่แข่งเดิน') : options.checked ? 'คิงถูกเช็ก' : 'เลือกตาเดิน');
  const messages = notices.map(notice => `<div class="notice"><strong>${escapeHtml(notice.name)}</strong>${noticeText(notice)}</div>`).join('');
  sidebar.innerHTML = `<section class="panel" aria-labelledby="phase-title">
    <h2 id="phase-title">${escapeHtml(title)}</h2>
    ${sideLabel(game.turn, result ? 'จบเกม' : `ตา${sideName(game.turn)}`)}
    ${messages}
    ${options.forced ? '' : `<p role="status">${escapeHtml(result?.detail ?? hint)}</p>`}
    ${!result && locked ? `<p>${PIECE_NAMES[locked.type]}ที่มีรูปกุญแจติดกับดักในตานี้</p>` : ''}
    ${result && !onlineRoom ? '<button type="button" class="primary wide" data-action="new">เล่นอีกครั้ง</button>' : ''}
  </section>`;
  const historyPanel = $('game-history');
  historyPanel.hidden = false;
  historyPanel.innerHTML = `
    <h3 id="history-title">ประวัติการเดิน</h3>
    ${history.length ? `<ol class="history" reversed>${history.map(entry =>
      `<li>${escapeHtml(entry.move)}${entry.effect ? `<span>${escapeHtml(entry.effect)}</span>` : ''}</li>`).join('')}</ol>` : `<p>${sideName(game.turn)}เดินก่อน</p>`}`;
}

function render() {
  renderPieceSkills();
  $('game-history').hidden = phase !== 'play';
  if (onlineRoom?.phase === 'waiting' || (onlineRoom?.phase === 'setup' && onlineRoom.ready[onlineRoom.side])) {
    renderBoard();
    board.inert = true;
    const waitingForPlayer = onlineRoom.phase === 'waiting';
    $('board-caption').textContent = waitingForPlayer ? 'รอเพื่อนเข้าห้อง' : 'รอเพื่อนวางสกิล';
    sidebar.innerHTML = waitingForPlayer
      ? '<section class="panel"><h2>รอเพื่อนเข้าห้อง</h2><p>ส่งลิงก์เชิญหรือรหัสห้องให้เพื่อน</p></section>'
      : '<section class="panel"><h2>รอเพื่อนวางสกิล</h2><p>ทั้งสองฝ่ายจะเริ่มเล่นเมื่อวางสกิลครบ</p></section>';
    return;
  }
  renderBoard();
  if (phase === 'setup') renderSetup();
  if (phase === 'handoff') renderHandoff();
  if (phase === 'play') renderPlay();
  saveCurrent();
}

function placeCard(square: number) {
  const piece = game.board[square];
  if (piece?.side !== setupSide || piece.type === 'k') {
    setupTip = usesDiscs(setupSide) ? 'เลือกเบี้ยฝ่ายตัวเอง' : 'เลือกหมากฝ่ายตัวเองที่ไม่ใช่คิง';
  } else if (placements[selectedCard] === square) {
    delete placements[selectedCard];
    setupTip = '';
  } else if (markerCount(piece, square) >= setupLimit()) {
    setupTip = 'ตัวนี้ใส่คำสั่งเต็มแล้ว เลือกหมากตัวอื่น';
  } else {
    placements[selectedCard] = square;
    selectedCard = setupCards().find(id => placements[id] === undefined) ?? selectedCard;
    setupTip = '';
  }
  render();
}

function confirmSetup() {
  if (Object.keys(placements).length !== setupCards().length) return;
  if (onlineRoom) return submitOnline({ type: 'setup', placements: { ...placements } });
  return runRequest(async runtime => {
    const next = await runtime.setup(modeId, game, setupSide, placements);
    ({ state: game, options } = next);
    placements = {};
    setupTip = '';
    if (setupSide === 'w') {
      phase = 'handoff';
      render();
      sidebar.querySelector<HTMLButtonElement>('[data-action="black"]')?.focus();
    } else {
      phase = 'play';
      beginTurn(next.outcome);
      render();
      const firstMove = options.moves[0];
      gameBoard.focus(firstMove?.from ?? firstMove?.to);
    }
  });
}

function beginTurn(outcome: Outcome | null, revealed: CardId[] = [], revealedSide = game.turn) {
  const required = options.forced ? options.card ?? game.pending : null;
  const skipped: CardId[] = options.skipped ?? (game.pending && !options.forced ? [game.pending] : []);
  const shown = revealed.map(id => ({ id, side: revealedSide, revealed: true }));
  for (const id of [...skipped, required]) {
    if (id === null) continue;
    if (!shown.some(notice => notice.id === id && notice.side === game.turn)) shown.push({ id, side: game.turn, revealed: false });
  }
  notices = shown.map(({ id, side, revealed }) => {
    const card = cardsFor(side)[id]!;
    const isRequired = id === required && side === game.turn;
    let note = '';
    if (id === 'lock' && lastMove) {
      const piece = game.board[lastMove.to];
      if (piece) note = `${PIECE_NAMES[piece.type]}${SIDE_NAMES[piece.side]}ที่ช่อง ${Chess.name(lastMove.to)} ติดกับดัก`;
    } else if (side !== game.turn) {
      note = `เก็บคำสั่งนี้ไว้ใช้ในตาของ${sideName(side)}`;
    } else if (skipped.includes(id)) {
      note = 'ข้ามคำสั่งใบนี้ เพราะตานี้ไม่มีทางทำได้';
    } else if (!isRequired) {
      note = options.mustCapture ? 'เก็บคำสั่งไว้ก่อน ตานี้ต้องกินหมากคู่แข่ง' : 'รอใช้ในตาถัดไปหลังคำสั่งก่อนหน้า';
    }
    return { name: card.name, side, description: isRequired ? card.prompt ?? card.detail : card.detail, note, revealed, required: isRequired };
  });

  result = describeOutcome(outcome);
}

function describeOutcome(outcome: Outcome | null): Result | null {
  if (!outcome) return null;
  const title = outcome.winner ? sideName(outcome.winner) + 'ชนะ' : 'เสมอ';
  const descriptions: Record<Outcome['reason'], string> = {
    duel_king: 'ชนะดวล Tic Tac Toe กับคิง',
    duel_check: 'สวนกินหมากในจังหวะที่คิงยังถูกรุก',
    no_moves: sideName(game.turn) + 'ไม่มีตาเดิน',
    no_pieces: sideName(game.turn) + 'เสียหมากหมดกระดาน',
    checkmate: 'รุกฆาต' + SIDE_NAMES[game.turn],
    stalemate: SIDE_NAMES[game.turn] + 'ไม่มีตาเดินและคิงไม่ถูกเช็ก',
    kings_only: 'เหลือเพียงคิงทั้งสองฝ่าย',
  };
  return { title, detail: descriptions[outcome.reason] };
}

function describeMove(move: Move, actor: Piece | null, captured: Piece | null) {
  const destination = Chess.name(move.to);
  if (move.revive) return `นำเบี้ยกลับที่ ${destination}`;
  if (move.rookFrom !== undefined && move.from !== undefined) return `เข้าป้อม ${Chess.name(move.from)} → ${destination}`;
  if (!actor || move.from === undefined) throw new Error('Move has no piece');
  const action = `${PIECE_NAMES[actor.type]} ${Chess.name(move.from)} ${captured ? '×' : '→'} ${destination}`;
  return move.promote ? `${action} เป็น${PIECE_NAMES[move.promote]}` : action;
}

function finishMove(move: Move) {
  if (onlineRoom) {
    const { from, to, promote } = move;
    return submitOnline({ type: 'move', move: { from, to, promote } });
  }
  return runRequest(async runtime => {
    const next = await runtime.move(modeId, game, move);
    if (next.duel) {
      duel = next.duel;
      openDuelDialog(duel.move);
    } else if (usesDiscs(game.turn)) {
      finishDraughtsMove(move, next);
    } else if (modeId === 'hybrid') {
      finishHybridMove(move, next);
    } else {
      finishChessMove(move, next);
    }
  });
}

function finishChessMove(move: Move, next: Snapshot) {
  const actor = pieceAt(game.board, move.from);
  const captured = pieceAt(game.board, move.capture);
  const card = captured?.side === Chess.other(game.turn) ? captured.card : null;
  const line = `${SIDE_NAMES[game.turn]} · ${describeMove(move, actor, captured)}`;
  ({ state: game, options } = next);
  lastMove = move;
  selectedSquare = null;
  beginTurn(next.outcome, card ? [card] : []);
  history.unshift({ move: line, effect: card ? `เปิดคำสั่ง ${mode.cards[card]!.name}` : '' });
  render();
  showCommandDialog();
}

function finishDraughtsMove(move: Move, next: Snapshot) {
  const side = game.turn;
  const actor = pieceAt(game.board, move.from);
  ({ state: game, options } = next);
  lastMove = move;
  if (game.chain) {
    selectedSquare = game.chain.at;
    notices = [];
    render();
    return;
  }
  selectedSquare = null;
  if (game.resolution?.kind !== 'draughts') return;
  const { route, cards, crowned } = game.resolution;
  const jump = move.capture !== undefined;
  const path = route.map(Chess.name).join(jump ? ' × ' : ' → ');
  const label = move.revive ? 'นำเบี้ยกลับที่' : move.friendly ? 'กินพวกเดียวกัน' : actor ? PIECE_NAMES[actor.type] : 'หมาก';
  history.unshift({
    move: `${sideName(side)} · ${label} ${path}${crowned ? ' ขึ้นฮอส' : ''}`,
    effect: cards.length ? `เปิดคำสั่ง ${cards.map(id => cardsFor(game.turn)[id]!.name).join(' · ')}` : '',
  });
  beginTurn(next.outcome, cards);
  render();
  showCommandDialog();
}

function finishHybridMove(move: Move, next: Snapshot) {
  const actor = pieceAt(game.board, move.from);
  const captured = pieceAt(game.board, move.capture);
  ({ state: game, options } = next);
  lastMove = move;
  selectedSquare = null;
  const resolution = game.resolution;
  if (resolution?.kind !== 'hybrid') return;
  const effects = [];
  if (resolution.duel) effects.push(resolution.reversed ? 'หมากฮอสชนะ XO และสวนกิน' :
    resolution.duelWinner === 'w' ? 'หมากรุกชนะ XO' : 'เสมอ XO · หมากฮอสถูกกิน');
  if (resolution.cards.length) effects.push(`เปิดคำสั่ง ${resolution.cards.map(id => cardsFor(resolution.revealedSide)[id]!.name).join(' · ')}`);
  const line = resolution.reversed && actor && move.from !== undefined ? `${PIECE_NAMES[actor.type]}ที่ช่อง ${Chess.name(move.from)} ถูกสวนกิน` : describeMove(move, actor, captured);
  history.unshift({ move: `${sideName('w')} · ${line}`, effect: effects.join(' · ') });
  beginTurn(next.outcome, resolution.cards, resolution.revealedSide);
  render();
  showCommandDialog();
}

function selectPromotion(moves: Move[]) {
  const promotions = $('promotions');
  promotions.replaceChildren();
  for (const move of moves) {
    if (!move.promote) continue;
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost';
    button.innerHTML = `<span class="piece ${game.turn}" aria-hidden="true">${SYMBOLS[move.promote]}</span>${PIECE_NAMES[move.promote]}`;
    button.addEventListener('click', () => {
      $<HTMLDialogElement>('promotion').close();
      finishMove(move);
    });
    promotions.append(button);
  }
  $<HTMLDialogElement>('promotion').showModal();
}

function selectSquare(square: number) {
  if (busy || onlineBusy) return;
  if (onlineRoom && phase === 'setup' && (onlineRoom.phase === 'waiting' || onlineRoom.ready[onlineRoom.side])) return;
  if (phase === 'setup') return placeCard(square);
  if (phase !== 'play' || duel) return;
  const piece = pieceAt(game.board, square);
  inspectedPieceId = piece?.side === (onlineRoom?.side ?? game.turn) ? piece.id : null;
  renderPieceSkills();
  if (result) return;
  const chosen = options.moves.filter(move => move.to === square && (move.revive || move.from === selectedSquare));
  if (chosen.length > 1) return selectPromotion(chosen);
  if (chosen.length === 1) return finishMove(chosen[0]);
  if (game.chain) return;
  selectedSquare = selectedSquare !== square && options.moves.some(move => move.from === square) ? square : null;
  renderBoard();
}
function openRules() {
  const draughts = mode.engine === Draughts;
  const hybrid = mode.engine === Hybrid;
  $('rules-title').textContent = `กติกา${mode.name}`;
  $('rules-summary').textContent = hybrid
    ? 'ฝ่ายขาวใช้หมากรุก 16 ตัวและเริ่มก่อน ฝ่ายดำวางหมากฮอส 12 ตัวบนช่องเข้มแถว 6–8 เมื่อมีทางกินต้องกระโดดกิน และถ้ากินต่อได้ให้ใช้ตัวเดิม ฮอสเดินทแยงไกลได้ เวลารุกคิงให้นับช่องที่เบี้ยโจมตีเฉียงหน้าและแนวทแยงโล่งของฮอส'
    : draughts
    ? 'ฝ่ายดำเริ่มก่อน ฝั่งละ 8 เบี้ย เดินและกินเฉียงไปข้างหน้า มีทางกินต้องกิน และถ้ากินต่อได้ให้ใช้ตัวเดิมจนหมดทาง เมื่อถึงแถวสุดท้ายให้จบตาและขึ้นฮอส ฮอสเดินไกลได้ทั้งสี่ทแยง และตอนกินต้องลงช่องถัดจากตัวที่ถูกกิน'
    : 'แต่ละฝ่ายซ่อนคำสั่งคนละ 4 ใบ ใต้หมากของตัวเองได้ตัวละใบ ยกเว้นคิง คลิกหมากของตัวเองเพื่อดูสกิล เมื่อหมากที่ซ่อนสกิลถูกกิน คำสั่งจะเปิดขึ้นให้เจ้าของหมากทำตาม';
  const deck = cardsFor('b');
  const ids: CardId[] = hybrid ? ['duel', 'lock', 'revive', 'friendly', 'push'] : cardIds(deck);
  $('rules-list').innerHTML = ids.map(id => {
    const card = deck[id]!;
    const cost = id === 'lock' || id === 'duel' ? '' : ' ใช้ตาเดินของคุณ';
    return `<li><strong>${card.name}</strong> · ${hybrid && id !== 'duel' && id !== 'revive' ? card.summary : card.detail}${cost}</li>`;
  }).join('');
  $('rules-note').textContent = hybrid
    ? 'หมากรุกซ่อน 4 คำสั่ง ตัวละ 1 ใบ ยกเว้นคิง หมากฮอสซ่อน 5 สกิล ตัวละสูงสุด 2 ใบ คำสั่งเดินใช้ตามกติกาของฝั่งตัวเองทีละใบ หมากฮอสต้องกินคู่แข่งก่อนถ้ามีทาง หมากรุกชนะเมื่อหมากฮอสไม่มีตาเดิน หมากฮอสชนะเมื่อรุกฆาต หรือเมื่อสวนกินในดวลแล้วคิงถูกกินหรือยังถูกรุก'
    : draughts
    ? 'ซ่อนคำสั่งคนละ 4 ใบ ถ้าถูกกินหลายตัวในตาเดียว จะเปิดคำสั่งหลังจบการกระโดด แล้วใช้ตามลำดับทีละใบต่อหนึ่งตา ถ้ามีทางกินคู่แข่ง ให้กินก่อนและเก็บคำสั่งไว้ ถ้าทำใบไหนไม่ได้ให้ข้ามใบนั้น การกินพวกเดียวกันไม่เปิดคำสั่งของเบี้ยที่เสีย'
    : 'ถ้าทำคำสั่งไม่ได้โดยที่คิงยังปลอดภัย ให้เดินตามปกติ คำสั่งใช้ครั้งเดียว และการกินพวกเดียวกันจะไม่เปิดคำสั่งของเบี้ยที่ถูกกิน';
  $<HTMLDialogElement>('rules').showModal();
}

function confirmRestart() {
  $('restart-title').textContent = 'เริ่มกระดานใหม่หรือไม่';
  $('restart-note').textContent = 'ทั้งสองฝ่ายจะได้วางคำสั่งใหม่ตั้งแต่ต้น';
  const confirm = $<HTMLButtonElement>('restart-confirm');
  confirm.value = 'restart';
  confirm.textContent = 'เริ่มใหม่';
  restartDialog.returnValue = '';
  restartDialog.showModal();
}

duelDialog.addEventListener('cancel', event => event.preventDefault());
$('duel-continue').addEventListener('click', () => {
  if (!duel?.board.done) return;
  if (onlineRoom) {
    duel = null;
    duelDialog.close();
    if (pendingOnlineNotice) {
      pendingOnlineNotice = false;
      showCommandDialog();
    }
    return;
  }
  const activeDuel = duel;
  void runRequest(async runtime => {
    const next = await runtime.finishDuel(modeId, game, activeDuel);
    duel = null;
    duelDialog.close();
    finishHybridMove(activeDuel.move, next);
  });
});
commandDialog.addEventListener('close', () => {
  if (onlineRoom && pendingOnlineNotice && !duelDialog.open) {
    pendingOnlineNotice = false;
    showCommandDialog();
  }
  saveCurrent();
});
$('duel-leave').addEventListener('click', () => onlineLobby.leave());
$('duel-leave-permanently').addEventListener('click', () => onlineLobby.confirmLeave());

sidebar.addEventListener('click', event => {
  if (busy || onlineBusy) return;
  if (!(event.target instanceof Element)) return;
  const button = event.target.closest('button');
  if (!button) return;
  const { card, action } = button.dataset;
  if (card && setupCards().includes(card as CardId)) {
    const id = card as CardId;
    selectedCard = id;
    setupTip = placements[id] === undefined ? '' : 'เลือกช่องใหม่เพื่อย้าย หรือคลิกช่องเดิมเพื่อนำออก';
    render();
    sidebar.querySelector<HTMLButtonElement>('[data-card="' + id + '"]')?.focus();
  } else if (action === 'clear') {
    placements = {};
    selectedCard = setupCards()[0];
    setupTip = '';
    render();
    sidebar.querySelector<HTMLButtonElement>('[data-card="' + selectedCard + '"]')?.focus();
  } else if (action === 'confirm') {
    confirmSetup();
  } else if (action === 'black') {
    setupSide = 'b';
    phase = 'setup';
    selectedCard = setupCards()[0];
    render();
    sidebar.querySelector<HTMLButtonElement>('.card')?.focus();
  } else if (action === 'new') {
    newGame();
  }
});

modeForm.addEventListener('submit', event => {
  event.preventDefault();
  const value = new FormData(modeForm).get('mode');
  if (busy || onlineRoom || !isModeId(value)) return;
  if (readMatchSave(profiles.loadGame<unknown>(saveSlot))) {
    pendingMode = value;
    $('restart-title').textContent = 'เริ่มเกมใหม่แทนเซฟเดิมหรือไม่';
    $('restart-note').textContent = 'เซฟของโปรไฟล์นี้จะถูกแทนที่ด้วยเกมใหม่';
    const confirm = $<HTMLButtonElement>('restart-confirm');
    confirm.value = 'replace';
    confirm.textContent = 'เริ่มใหม่';
    restartDialog.returnValue = '';
    restartDialog.showModal();
    return;
  }
  void newGame(value);
});
let pendingMode: ModeId = 'chess';
modeForm.addEventListener('change', renderModePreview);
resumeButton.addEventListener('click', resumeGame);
$('rules-button').addEventListener('click', openRules);
$('menu-button').addEventListener('click', () => {
  if (busy) return;
  if (onlineRoom) return onlineLobby.leave();
  saveCurrent();
  showMenu();
});
$('restart-button').addEventListener('click', () => {
  if (!busy && !onlineRoom) confirmRestart();
});
restartDialog.addEventListener('close', () => {
  if (restartDialog.returnValue === 'replace') {
    void newGame(pendingMode);
  } else if (restartDialog.returnValue === 'restart') {
    newGame();
  }
});
showMenu(false);


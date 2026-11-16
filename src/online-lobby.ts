import './online-lobby.css';
import { MODES, SIDE_NAMES, type CardId, type DuelState, type ModeId, type Move, type PieceType, type Promotion, type Side, type TurnOptions } from './game/rules';
import type { Outcome } from './game/runtime';
import type { Duel, Placements } from './game/save';

export interface OnlinePiece {
  side: Side;
  type: PieceType;
  id: number;
  skills?: CardId[];
  locked: boolean;
}

export interface OnlineHistoryEntry {
  side: Side;
  move: Move;
  actor: PieceType | null;
  captured: PieceType | null;
  cards: CardId[];
  reversed: boolean;
  duelWinner?: Side | null;
}

export interface OnlineSnapshot {
  code: string;
  mode: ModeId;
  side: Side;
  players: Record<Side, string | null>;
  ready: Record<Side, boolean>;
  phase: 'waiting' | 'setup' | 'play' | 'duel' | 'finished';
  revision: number;
  board: Array<OnlinePiece | null>;
  turn: Side;
  options: TurnOptions | null;
  outcome: Outcome | null;
  lastMove: Move | null;
  checked: boolean;
  chainAt: number | null;
  history: OnlineHistoryEntry[];
  notice: { cards: CardId[]; side: Side; revision: number } | null;
  duel: Duel | null;
  lastDuel: { board: DuelState; revision: number; move?: Move } | null;
  myPlacements: Placements;
}

export type OnlineAction =
  | { type: 'setup'; placements: Placements }
  | { type: 'move'; move: { from?: number; to: number; promote?: Promotion } }
  | { type: 'duel'; cell: number };

interface LobbyOptions {
  getMode(): ModeId;
  getPreferredName(): string;
  onSnapshot(snapshot: OnlineSnapshot): void;
  onConnectionStatus(message: string): void;
  onLeave(): void;
}

interface RoomSeat {
  code: string;
  token: string;
  paused: boolean;
}

interface EntryResponse {
  token: string;
  snapshot: OnlineSnapshot;
}

type EntryMode = 'create' | 'join';

const legacySeatKey = 'hidden-orders:online-seat';
const savedRoomsKey = 'hidden-orders:online-seats:v2';
const maxSavedRooms = 24;
const api = new URL('./api/rooms', location.href);
const pollInterval = 1000;
const hiddenPollInterval = 10000;

class RoomError extends Error {
  constructor(readonly status: number, readonly detail: unknown) {
    super('Room request failed');
  }
}

function roomResponse(path = '', payload?: unknown, token?: string, options?: { etag?: string; method?: 'DELETE' }) {
  const headers = new Headers({ Accept: 'application/json' });
  if (payload !== undefined) headers.set('Content-Type', 'application/json');
  if (token) headers.set('Authorization', 'Bearer ' + token);
  if (options?.etag) headers.set('If-None-Match', options.etag);
  return fetch(api.href + path, {
    method: options?.method ?? (payload === undefined ? 'GET' : 'POST'),
    body: payload === undefined ? undefined : JSON.stringify(payload),
    headers,
    cache: 'no-store',
    credentials: 'omit',
    mode: 'same-origin',
    redirect: 'error',
    referrerPolicy: 'no-referrer',
    signal: AbortSignal.timeout(5_000),
  });
}

async function responseData<T>(response: Response): Promise<T> {
  const data = response.headers.get('Content-Type')?.includes('application/json') ? await response.json() : null;
  if (!response.ok || !data) throw new RoomError(response.status, data?.detail);
  return data as T;
}

async function roomsRequest<T>(path = '', payload?: unknown, token?: string): Promise<T> {
  return responseData<T>(await roomResponse(path, payload, token));
}

function validCode(code: string) {
  return /^[A-Z0-9]{4,12}$/.test(code);
}

function normalizeCode(input: string) {
  const raw = input.trim();
  if (!raw.includes('://')) return raw.toUpperCase();
  try {
    return (new URL(raw).searchParams.get('room') ?? '').trim().toUpperCase();
  } catch {
    return '';
  }
}

function parseSeat(data: unknown): RoomSeat | undefined {
  if (typeof data !== 'object' || data === null ||
      !('code' in data) || typeof data.code !== 'string' || !validCode(data.code) ||
      !('token' in data) || typeof data.token !== 'string' || !/^[A-Za-z0-9_-]{20,128}$/.test(data.token) ||
      !('paused' in data) || typeof data.paused !== 'boolean') return undefined;
  return { code: data.code, token: data.token, paused: data.paused };
}

function readSeats(): RoomSeat[] {
  try {
    const saved: unknown = JSON.parse(sessionStorage.getItem(savedRoomsKey) ?? 'null');
    if (Array.isArray(saved)) {
      const seats = new Map<string, RoomSeat>();
      for (const item of saved.slice(0, maxSavedRooms)) {
        const seat = parseSeat(item);
        if (seat && !seats.has(seat.code)) seats.set(seat.code, seat);
      }
      return [...seats.values()];
    }
    const previous = parseSeat(JSON.parse(sessionStorage.getItem(legacySeatKey) ?? 'null'));
    return previous ? [previous] : [];
  } catch {
    // A blocked store still allows online play until this page is reloaded.
    return [];
  }
}

function saveSeats(seats: RoomSeat[]) {
  try {
    sessionStorage.setItem(savedRoomsKey, JSON.stringify(seats));
    sessionStorage.removeItem(legacySeatKey);
  } catch {
    // The saved seats remain available in memory.
  }
}

function roomUrl(code: string | null) {
  const url = new URL(location.href);
  if (code) url.searchParams.set('room', code);
  else url.searchParams.delete('room');
  url.hash = '';
  return url;
}

function inviteUrl(code: string) {
  const url = roomUrl(code);
  url.search = '';
  url.searchParams.set('room', code);
  return url;
}

function normalizeName(name: string) {
  return name.normalize('NFKC').split(/[\p{White_Space}\u001c-\u001f]+/u).filter(Boolean).join(' ');
}

function unavailableRoomMessage(error: unknown) {
  if (!(error instanceof RoomError) || ![401, 403, 404, 410].includes(error.status)) return null;
  if (error.status === 410 && error.detail === 'room_seat_departed') {
    return 'คู่เล่นออกจากห้องถาวรแล้ว กรุณาสร้างห้องใหม่';
  }
  if (error.status === 404) {
    return 'ไม่พบห้องนี้ ห้องอาจหมดอายุหรือเซิร์ฟเวอร์เริ่มใหม่ กรุณาสร้างห้องใหม่';
  }
  return 'สิทธิ์เข้าห้องนี้สิ้นสุดแล้ว กรุณาสร้างห้องใหม่';
}

export function mountOnlineLobby(host: HTMLElement, { getMode, getPreferredName, onSnapshot, onConnectionStatus, onLeave }: LobbyOptions) {
  host.innerHTML = `
    <div class="online-entry" id="online-entry">
      <button type="button" class="ghost" id="online-open" aria-haspopup="dialog" aria-controls="online-dialog">เล่นออนไลน์</button>
      <select class="ghost" id="online-saved-room" aria-label="เลือกห้องเดิม" hidden></select>
      <button type="button" class="ghost" id="online-resume" hidden>กลับเข้าห้อง</button>
    </div>
    <section class="online-room" id="online-room" aria-label="ห้องออนไลน์" hidden>
      <div>
        <div class="online-identification">
          <strong>ห้อง <span id="online-room-code"></span></strong>
          <span id="online-seat"></span>
        </div>
        <p id="online-opponent"></p>
      </div>
      <div class="online-actions">
        <button type="button" class="ghost" id="online-copy">คัดลอกลิงก์เชิญ</button>
        <button type="button" class="ghost" id="online-leave">กลับเมนู</button>
        <button type="button" class="ghost" id="online-leave-permanently" aria-haspopup="dialog" aria-controls="online-leave-dialog">ออกถาวร</button>
      </div>
      <input type="url" id="online-invite" aria-label="ลิงก์เชิญเข้าห้อง" readonly hidden>
    </section>
    <p class="online-status" id="online-status" role="status" hidden></p>
    <dialog id="online-dialog" class="online-dialog" aria-labelledby="online-title">
      <div class="online-heading">
        <h2 id="online-title">เล่นออนไลน์</h2>
        <button type="button" class="ghost" id="online-close">ปิด</button>
      </div>
      <div class="online-tabs" role="group" aria-label="วิธีเข้าห้อง">
        <button type="button" class="ghost" id="online-show-create" aria-pressed="true">สร้างห้อง</button>
        <button type="button" class="ghost" id="online-show-join" aria-pressed="false">เข้าห้อง</button>
      </div>
      <form id="online-form" class="online-form" novalidate>
        <label for="online-name">ชื่อที่เพื่อนจะเห็น</label>
        <input type="text" id="online-name" maxlength="160" autocomplete="nickname" required>
        <div class="online-field" id="online-mode-field">
          <label for="online-mode">โหมดเกม</label>
          <select id="online-mode"></select>
        </div>
        <div class="online-field" id="online-code-field" hidden>
          <label for="online-code">รหัสห้องหรือลิงก์เชิญ</label>
          <input type="text" id="online-code" maxlength="512" autocapitalize="characters" spellcheck="false" autocomplete="off">
        </div>
        <button type="submit" class="primary" id="online-create">สร้างห้อง</button>
        <button type="submit" class="primary" id="online-join" hidden>เข้าห้อง</button>
      </form>
      <p class="online-status" id="online-dialog-status" role="status" hidden></p>
    </dialog>
    <dialog id="online-leave-dialog" aria-labelledby="online-leave-title" aria-describedby="online-leave-note">
      <h2 id="online-leave-title">ออกจากห้องถาวร?</h2>
      <p id="online-leave-note">เกมในห้องนี้จะจบ และคุณกับคู่เล่นจะเล่นต่อจากห้องนี้ไม่ได้</p>
      <p class="online-status" id="online-leave-status" role="status"></p>
      <div class="dialog-actions">
        <button type="button" class="ghost" id="online-leave-cancel" autofocus>ยกเลิก</button>
        <button type="button" class="primary" id="online-leave-confirm">ออกถาวร</button>
      </div>
    </dialog>
  `;

  function element<T extends HTMLElement = HTMLElement>(selector: string) {
    return host.querySelector<T>('#' + selector)!;
  }

  const openButton = element<HTMLButtonElement>('online-open');
  const savedRoom = element<HTMLSelectElement>('online-saved-room');
  const resumeButton = element<HTMLButtonElement>('online-resume');
  const dialog = element<HTMLDialogElement>('online-dialog');
  const closeButton = element<HTMLButtonElement>('online-close');
  const form = element<HTMLFormElement>('online-form');
  const modeInput = element<HTMLSelectElement>('online-mode');
  const nameInput = element<HTMLInputElement>('online-name');
  const codeInput = element<HTMLInputElement>('online-code');
  const inviteInput = element<HTMLInputElement>('online-invite');
  const createButton = element<HTMLButtonElement>('online-create');
  const joinButton = element<HTMLButtonElement>('online-join');
  const copyButton = element<HTMLButtonElement>('online-copy');
  const leaveButton = element<HTMLButtonElement>('online-leave');
  const permanentLeaveButton = element<HTMLButtonElement>('online-leave-permanently');
  const leaveDialog = element<HTMLDialogElement>('online-leave-dialog');
  const cancelLeaveButton = element<HTMLButtonElement>('online-leave-cancel');
  const confirmLeaveButton = element<HTMLButtonElement>('online-leave-confirm');
  const leaveStatus = element('online-leave-status');
  const showCreateButton = element<HTMLButtonElement>('online-show-create');
  const showJoinButton = element<HTMLButtonElement>('online-show-join');
  const room = element('online-room');
  const status = element('online-status');
  const dialogStatus = element('online-dialog-status');
  const connectionControls = [showCreateButton, showJoinButton, nameInput, codeInput, modeInput, createButton, joinButton];
  for (const [id, mode] of Object.entries(MODES)) modeInput.add(new Option(mode.name, id));

  let entryMode: EntryMode = 'create';
  let seats = readSeats();
  let active: RoomSeat | null = null;
  let snapshot: OnlineSnapshot | null = null;
  let snapshotTag: string | undefined;
  let pollId: number | undefined;
  let pollBusy = false;
  let sending: 'action' | 'leave' | null = null;
  let entering = false;
  let reconnecting = false;
  let supported: boolean | undefined;
  let healthRequest: Promise<boolean> | undefined;
  let invalidInput: HTMLInputElement | undefined;

  function message(target: HTMLElement, value: string) {
    target.textContent = value;
    target.hidden = !value;
  }

  function clearEntryFeedback() {
    invalidInput?.removeAttribute('aria-invalid');
    invalidInput?.removeAttribute('aria-describedby');
    invalidInput = undefined;
    message(dialogStatus, '');
  }

  function showEntryError(input: HTMLInputElement, text: string) {
    invalidInput = input;
    message(dialogStatus, text);
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-describedby', dialogStatus.id);
    input.focus();
  }

  function showEntryMode(mode: EntryMode, focus = true) {
    entryMode = mode;
    const joining = mode === 'join';
    showCreateButton.setAttribute('aria-pressed', String(!joining));
    showJoinButton.setAttribute('aria-pressed', String(joining));
    element('online-mode-field').hidden = joining;
    element('online-code-field').hidden = !joining;
    codeInput.required = joining;
    createButton.hidden = joining;
    joinButton.hidden = !joining;
    if (focus) (joining && !codeInput.value ? codeInput : nameInput).focus();
  }

  function renderEntry(selectedCode = savedRoom.value) {
    const selectedSeat = seats.find(seat => seat.code === selectedCode) ?? seats[0];
    savedRoom.replaceChildren(...seats.map(seat => new Option('ห้อง ' + seat.code, seat.code)));
    savedRoom.value = selectedSeat?.code ?? '';
    savedRoom.hidden = Boolean(active) || seats.length < 2;
    openButton.hidden = Boolean(active);
    resumeButton.hidden = !selectedSeat || Boolean(active);
    if (selectedSeat) resumeButton.textContent = 'กลับเข้าห้อง ' + selectedSeat.code;
    room.hidden = !active;
  }

  function accept(next: OnlineSnapshot) {
    if (!active || next.code !== active.code || (snapshot && next.revision <= snapshot.revision)) return;
    snapshot = next;
    element('online-room-code').textContent = next.code;
    element('online-seat').textContent = SIDE_NAMES[next.side];
    const opponent = next.players[next.side === 'w' ? 'b' : 'w'];
    element('online-opponent').textContent = opponent ? 'คู่เล่น ' + opponent : 'รอเพื่อนเข้าห้อง';
    copyButton.hidden = next.phase !== 'waiting';
    inviteInput.hidden = true;
    onSnapshot(next);
  }

  function setConnectionControls() {
    for (const control of connectionControls) control.disabled = entering || supported !== true;
    closeButton.disabled = entering;
    form.setAttribute('aria-busy', String(entering));
  }

  function checkOnlineSupport() {
    if (!healthRequest) {
      healthRequest = roomsRequest<{ online: boolean; version: number }>('/health')
        .then(result => result.online === true && result.version === 1, () => false)
        .then(available => {
          supported = available;
          setConnectionControls();
          return available;
        })
        .finally(() => { healthRequest = undefined; });
    }
    return healthRequest;
  }

  let lastSuggestedName = '';

  function openEntry(code = '') {
    if (dialog.open) return;
    const preferredName = normalizeName(getPreferredName());
    if (!nameInput.value || nameInput.value === lastSuggestedName) {
      lastSuggestedName = [...preferredName].length <= 24 && !/\p{C}/u.test(preferredName) ? preferredName : '';
      nameInput.value = lastSuggestedName;
    }
    modeInput.value = getMode();
    codeInput.value = code;
    clearEntryFeedback();
    showEntryMode(code ? 'join' : 'create', false);
    dialog.showModal();
    if (supported === true) nameInput.focus();
    else {
      message(dialogStatus, 'กำลังเชื่อมต่อห้องออนไลน์');
      void checkOnlineSupport().then(available => {
        if (!dialog.open) return;
        message(dialogStatus, available ? '' : 'เชื่อมต่อระบบห้องออนไลน์ไม่ได้ กรุณาลองใหม่ภายหลัง');
        if (available) nameInput.focus();
      });
    }
  }

  function schedulePoll(delay = document.hidden ? hiddenPollInterval : pollInterval) {
    window.clearTimeout(pollId);
    if (active && snapshot?.phase !== 'finished') pollId = window.setTimeout(() => { void poll(); }, delay);
  }

  function rememberSeat(seat: RoomSeat) {
    seats = [seat, ...seats.filter(saved => saved.code !== seat.code).map(saved => ({ ...saved, paused: true }))]
      .slice(0, maxSavedRooms);
    saveSeats(seats);
  }

  function dropSeat(text: string) {
    if (leaveDialog.open) leaveDialog.close();
    seats = seats.filter(seat => seat.code !== active?.code);
    active = null;
    snapshot = null;
    snapshotTag = undefined;
    reconnecting = false;
    window.clearTimeout(pollId);
    saveSeats(seats);
    history.replaceState(history.state, '', roomUrl(null));
    renderEntry();
    onLeave();
    message(status, text);
  }

  async function sync(current: RoomSeat) {
    try {
      const response = await roomResponse('/' + current.code, undefined, current.token, { etag: snapshotTag });
      const next = response.status === 304 ? null : await responseData<OnlineSnapshot>(response);
      if (active !== current || sending === 'leave') return false;
      if (reconnecting) {
        reconnecting = false;
        message(status, 'เชื่อมต่อกับห้องแล้ว');
        onConnectionStatus('');
      }
      if (next && (!snapshot || next.revision >= snapshot.revision)) {
        snapshotTag = response.headers.get('etag') ?? undefined;
        accept(next);
      }
      return true;
    } catch (error) {
      if (active !== current || sending === 'leave') return false;
      const unavailable = unavailableRoomMessage(error);
      if (unavailable) {
        dropSeat(unavailable);
      } else {
        reconnecting = true;
        const text = 'การเชื่อมต่อขัดข้อง กำลังลองเชื่อมต่อใหม่';
        if (status.textContent !== text) message(status, text);
        onConnectionStatus(text);
      }
      return false;
    }
  }

  async function poll() {
    const current = active;
    if (!current || snapshot?.phase === 'finished') return;
    if (pollBusy || sending) {
      schedulePoll();
      return;
    }
    pollBusy = true;
    try {
      await sync(current);
    } finally {
      pollBusy = false;
      schedulePoll();
    }
  }

  function activate(nextSeat: RoomSeat, first?: OnlineSnapshot) {
    const current = { ...nextSeat, paused: false };
    onConnectionStatus('');
    active = current;
    snapshot = null;
    snapshotTag = undefined;
    reconnecting = false;
    rememberSeat(current);
    history.replaceState(history.state, '', roomUrl(current.code));
    element('online-room-code').textContent = current.code;
    element('online-seat').textContent = '';
    element('online-opponent').textContent = '';
    inviteInput.value = inviteUrl(current.code).href;
    inviteInput.hidden = true;
    copyButton.hidden = !first;
    renderEntry(current.code);
    if (dialog.open) dialog.close();
    if (first) {
      message(status, '');
      accept(first);
    } else {
      message(status, 'กำลังกลับเข้าห้อง');
      reconnecting = true;
    }
    if (first) schedulePoll();
    else schedulePoll(0);
  }

  function leave() {
    if (!active || sending) return;
    rememberSeat({ ...active, paused: true });
    active = null;
    snapshot = null;
    snapshotTag = undefined;
    reconnecting = false;
    window.clearTimeout(pollId);
    history.replaceState(history.state, '', roomUrl(null));
    renderEntry();
    message(status, '');
    onLeave();
    resumeButton.focus({ preventScroll: true });
  }

  function setSending(next: typeof sending) {
    sending = next;
    leaveButton.disabled = permanentLeaveButton.disabled = Boolean(next);
    cancelLeaveButton.disabled = confirmLeaveButton.disabled = next === 'leave';
  }

  function confirmLeave() {
    if (!active || sending || leaveDialog.open) return;
    message(leaveStatus, '');
    leaveDialog.showModal();
  }

  async function leavePermanently() {
    const current = active;
    if (!current || sending || !leaveDialog.open) return;
    setSending('leave');
    message(leaveStatus, 'กำลังออกจากห้อง');
    try {
      const response = await roomResponse('/' + current.code + '/seat', undefined, current.token, { method: 'DELETE' });
      if (![204, 401, 404].includes(response.status)) throw new RoomError(response.status, null);
      if (active === current) {
        dropSeat('ออกจากห้องถาวรแล้ว');
        openButton.focus({ preventScroll: true });
      }
    } catch {
      message(leaveStatus, 'ออกจากห้องไม่ได้ กรุณาลองใหม่ หรือกดยกเลิกเพื่อกลับไปที่เกม');
    } finally {
      setSending(null);
      schedulePoll(0);
      if (leaveDialog.open) confirmLeaveButton.focus({ preventScroll: true });
    }
  }

  async function submit(action: OnlineAction) {
    const current = active;
    if (!current || !snapshot || sending) return false;
    setSending('action');
    message(status, '');
    try {
      const send = (revision: number) => roomsRequest<OnlineSnapshot>(
        '/' + current.code + '/action', { ...action, revision }, current.token,
      );
      const revision = snapshot.revision;
      let next: OnlineSnapshot;
      try {
        next = await send(revision);
      } catch (error) {
        if (!(error instanceof RoomError) || error.status !== 409 || error.detail !== 'stale_revision') throw error;
        const synced = await sync(current);
        if (!synced || active !== current || !snapshot) return false;
        if (action.type !== 'setup' || snapshot.phase !== 'setup' || snapshot.ready[snapshot.side] || snapshot.revision === revision) throw error;
        // The other player can confirm setup at the same moment.
        next = await send(snapshot.revision);
      }
      if (active !== current) return false;
      accept(next);
      return true;
    } catch (error) {
      if (active !== current) return false;
      const unavailable = unavailableRoomMessage(error);
      if (unavailable) {
        dropSeat(unavailable);
      } else {
        message(status, error instanceof RoomError && error.status < 500
          ? 'ห้องมีข้อมูลล่าสุดแล้ว กรุณาตรวจตาเดินแล้วลองอีกครั้ง'
          : 'ส่งคำสั่งไม่ได้ กำลังตรวจสถานะห้อง');
      }
      return false;
    } finally {
      setSending(null);
      schedulePoll(0);
    }
  }

  showCreateButton.addEventListener('click', () => {
    clearEntryFeedback();
    showEntryMode('create');
  });
  showJoinButton.addEventListener('click', () => {
    clearEntryFeedback();
    showEntryMode('join');
  });
  for (const input of [nameInput, codeInput]) {
    input.addEventListener('input', () => {
      if (input === invalidInput) clearEntryFeedback();
    });
  }
  openButton.addEventListener('click', () => openEntry());
  savedRoom.addEventListener('change', () => {
    resumeButton.textContent = 'กลับเข้าห้อง ' + savedRoom.value;
  });
  resumeButton.addEventListener('click', () => {
    const seat = seats.find(saved => saved.code === savedRoom.value);
    if (seat && !active) activate(seat);
  });
  document.addEventListener('visibilitychange', () => {
    if (document.hidden) schedulePoll();
    else schedulePoll(0);
  });
  window.addEventListener('focus', () => {
    if (!document.hidden) schedulePoll(0);
  });
  closeButton.addEventListener('click', () => dialog.close());
  dialog.addEventListener('cancel', event => { if (entering) event.preventDefault(); });
  leaveButton.addEventListener('click', leave);
  permanentLeaveButton.addEventListener('click', confirmLeave);
  cancelLeaveButton.addEventListener('click', () => leaveDialog.close());
  confirmLeaveButton.addEventListener('click', () => { void leavePermanently(); });
  leaveDialog.addEventListener('cancel', event => { if (sending === 'leave') event.preventDefault(); });
  copyButton.addEventListener('click', async () => {
    if (!active) return;
    try {
      await navigator.clipboard.writeText(inviteInput.value);
      message(status, 'คัดลอกลิงก์แล้ว');
    } catch {
      inviteInput.hidden = false;
      inviteInput.select();
      message(status, 'คัดลอกลิงก์ที่เลือกแล้วส่งให้เพื่อน');
    }
  });

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (entering || supported !== true) return;
    clearEntryFeedback();
    const code = normalizeCode(codeInput.value);
    const joining = entryMode === 'join';
    if (joining && !validCode(code)) {
      showEntryError(codeInput, 'ตรวจรหัสห้องหรือลิงก์เชิญแล้วลองอีกครั้ง');
      return;
    }
    const previous = joining ? seats.find(seat => seat.code === code) : undefined;
    if (previous) {
      activate(previous);
      return;
    }
    const rawName = nameInput.value;
    const name = normalizeName(rawName);
    if (!name || [...name].length > 24 || [...rawName].length > 80 || /\p{C}/u.test(name)) {
      showEntryError(nameInput, 'กรอกชื่อที่เพื่อนจะเห็น 1–24 ตัวอักษร โดยไม่ใช้อักขระควบคุม');
      return;
    }

    entering = true;
    setConnectionControls();
    message(dialogStatus, joining ? 'กำลังเข้าห้อง' : 'กำลังสร้างห้อง');
    try {
      const entry = joining
        ? await roomsRequest<EntryResponse>('/' + code + '/join', { name })
        : await roomsRequest<EntryResponse>('', { name, mode: modeInput.value });
      message(dialogStatus, '');
      activate({ code: entry.snapshot.code, token: entry.token, paused: false }, entry.snapshot);
    } catch (error) {
      const status = error instanceof RoomError ? error.status : 0;
      const feedback = status === 404 || status === 410 ? 'ไม่พบห้องนี้หรือห้องหมดอายุแล้ว'
        : status === 409 && joining ? 'ห้องนี้มีผู้เล่นครบแล้ว'
        : status === 422 ? 'กรอกชื่อและข้อมูลห้องให้ถูกต้อง'
        : status === 429 ? 'ส่งคำขอเร็วเกินไป กรุณารอสักครู่แล้วลองใหม่'
        : 'เชื่อมต่อห้องออนไลน์ไม่ได้ กรุณาลองใหม่';
      message(dialogStatus, feedback);
    } finally {
      entering = false;
      setConnectionControls();
    }
  });

  renderEntry();
  setConnectionControls();
  const invite = normalizeCode(new URL(location.href).searchParams.get('room') ?? '');
  const seat = invite ? seats.find(saved => saved.code === invite) : seats.find(saved => !saved.paused);
  if (seat) {
    activate(seat);
  } else if (validCode(invite)) {
    openEntry(invite);
  }

  return { submit, leave, confirmLeave };
}

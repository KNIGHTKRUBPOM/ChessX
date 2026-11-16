import './profile.css';

export interface LocalProfile {
  readonly id: string;
  readonly name: string;
}

interface ProfilePreferences {
  activeId: string | null;
  profiles: LocalProfile[];
}

export interface ProfileController {
  getActiveProfile(): LocalProfile | null;
  loadGame<T>(slot: string): T | null;
  saveGame<T>(slot: string, game: T): boolean;
  clearGame(slot: string): boolean;
}

const STORAGE_PREFIX = 'hidden-orders:v1:';
const PREFERENCES_KEY = STORAGE_PREFIX + 'profiles';
const MAX_NAME_LENGTH = 32;
const GUEST_NAME = 'ผู้เล่นรับเชิญ';
const STORAGE_ERROR = 'บันทึกโปรไฟล์ไม่ได้ กรุณาตรวจสอบการตั้งค่าพื้นที่จัดเก็บของเบราว์เซอร์';

function readStorage(key: string): unknown {
  try {
    const raw = window.localStorage.getItem(key);
    return raw === null ? null : JSON.parse(raw);
  } catch {
    return null;
  }
}

function writeStorage(key: string, value: unknown): boolean {
  try {
    const serialized = JSON.stringify(value);
    if (serialized === undefined) return false;
    window.localStorage.setItem(key, serialized);
    return true;
  } catch {
    return false;
  }
}

function normalizeName(name: string): string {
  return name.normalize('NFC').trim().replace(/\s+/gu, ' ');
}

function isValidName(name: string): boolean {
  return name.length > 0
    && [...name].length <= MAX_NAME_LENGTH
    && !/[\p{Cc}\u202A-\u202E\u2066-\u2069]/u.test(name);
}

function isLocalProfile(value: unknown): value is LocalProfile {
  return typeof value === 'object'
    && value !== null
    && 'id' in value
    && typeof value.id === 'string'
    && /^[a-f0-9]{32}$/u.test(value.id)
    && 'name' in value
    && typeof value.name === 'string'
    && isValidName(value.name);
}

function readPreferences(): ProfilePreferences {
  const saved = readStorage(PREFERENCES_KEY);
  if (typeof saved !== 'object' || saved === null || !('profiles' in saved) || !Array.isArray(saved.profiles)) {
    return { activeId: null, profiles: [] };
  }

  const profiles = saved.profiles.filter(isLocalProfile);
  const active = 'activeId' in saved ? profiles.find(profile => profile.id === saved.activeId) : undefined;
  return { activeId: active?.id ?? null, profiles };
}

function createProfileId(): string {
  const parts = crypto.getRandomValues(new Uint32Array(4));
  return Array.from(parts, part => part.toString(16).padStart(8, '0')).join('');
}

export function mountProfiles(
  host: HTMLElement,
  onProfileChange: (profile: LocalProfile | null) => void
): ProfileController {
  let preferences = readPreferences();
  host.innerHTML = `
    <button class="ghost profile-trigger" type="button" aria-haspopup="dialog"
      aria-controls="profile-dialog"></button>
    <dialog class="profile-dialog" id="profile-dialog" aria-labelledby="profile-title"
      aria-describedby="profile-description">
      <div class="profile-heading">
        <h2 id="profile-title">โปรไฟล์ผู้เล่น</h2>
        <button type="button" class="ghost profile-close">ปิด</button>
      </div>
      <p id="profile-description">โปรไฟล์และเกมที่บันทึกจะอยู่ในเบราว์เซอร์นี้ ผู้เล่นแต่ละคนมีเซฟแยกกัน</p>
      <ul class="profile-list" aria-label="เลือกผู้เล่น"></ul>
      <form class="profile-create">
        <label for="profile-name">ชื่อโปรไฟล์ใหม่</label>
        <div class="profile-fields">
          <input id="profile-name" name="profileName" autocomplete="off" required maxlength="64"
            aria-errormessage="profile-error">
          <button type="submit" class="primary">สร้างโปรไฟล์</button>
        </div>
      </form>
      <p class="profile-error" id="profile-error" role="alert" aria-atomic="true"></p>
    </dialog>
  `;

  const trigger = host.querySelector<HTMLButtonElement>('.profile-trigger')!;
  const dialog = host.querySelector<HTMLDialogElement>('.profile-dialog')!;
  const closeButton = host.querySelector<HTMLButtonElement>('.profile-close')!;
  const list = host.querySelector<HTMLUListElement>('.profile-list')!;
  const form = host.querySelector<HTMLFormElement>('.profile-create')!;
  const nameInput = host.querySelector<HTMLInputElement>('#profile-name')!;
  const error = host.querySelector<HTMLParagraphElement>('.profile-error')!;

  function getActiveProfile(): LocalProfile | null {
    return preferences.profiles.find(profile => profile.id === preferences.activeId) ?? null;
  }

  function renderTrigger(): void {
    const active = getActiveProfile();
    trigger.textContent = active?.name ?? 'โปรไฟล์ผู้เล่น';
    trigger.title = active ? `โปรไฟล์ผู้เล่น · ${active.name}` : 'โปรไฟล์ผู้เล่น';
    trigger.setAttribute('aria-label', trigger.title);
  }

  function setActive(next: ProfilePreferences): void {
    if (!writeStorage(PREFERENCES_KEY, next)) {
      error.textContent = STORAGE_ERROR;
      return;
    }

    const changed = next.activeId !== preferences.activeId;
    preferences = next;
    renderTrigger();
    dialog.close();
    if (changed) onProfileChange(getActiveProfile());
  }

  function renderProfiles(): void {
    const available = readPreferences();
    list.replaceChildren();

    for (const profile of [null, ...available.profiles]) {
      const id = profile?.id ?? null;
      const current = id === preferences.activeId;
      const row = document.createElement('li');
      const button = document.createElement('button');
      const name = document.createElement('span');
      button.type = 'button';
      button.className = 'ghost profile-choice';
      button.setAttribute('aria-pressed', String(current));
      name.textContent = profile?.name ?? GUEST_NAME;
      button.append(name);

      if (current) {
        const status = document.createElement('span');
        status.className = 'profile-current';
        status.textContent = 'ใช้งานอยู่';
        status.setAttribute('aria-hidden', 'true');
        button.append(status);
      }

      button.addEventListener('click', () => {
        if (current) {
          dialog.close();
          return;
        }

        const latest = readPreferences();
        if (id !== null && !latest.profiles.some(candidate => candidate.id === id)) {
          error.textContent = 'ไม่พบโปรไฟล์นี้ในเบราว์เซอร์';
          renderProfiles();
          return;
        }
        setActive({ ...latest, activeId: id });
      });
      row.append(button);
      list.append(row);
    }
  }

  trigger.addEventListener('click', () => {
    error.textContent = '';
    nameInput.removeAttribute('aria-invalid');
    form.reset();
    renderProfiles();
    dialog.showModal();
  });
  closeButton.addEventListener('click', () => dialog.close());
  nameInput.addEventListener('input', () => {
    nameInput.removeAttribute('aria-invalid');
    error.textContent = '';
  });
  form.addEventListener('submit', event => {
    event.preventDefault();
    error.textContent = '';
    const name = normalizeName(nameInput.value);
    const latest = readPreferences();
    let feedback = '';

    if (!isValidName(name)) {
      feedback = `กรอกชื่อผู้เล่น 1–${MAX_NAME_LENGTH} ตัวอักษร`;
    } else if ([GUEST_NAME, ...latest.profiles.map(profile => profile.name)].some(
      used => used.toLowerCase() === name.toLowerCase()
    )) {
      feedback = 'มีชื่อผู้เล่นนี้แล้ว กรุณาใช้ชื่ออื่นหรือเลือกจากรายการด้านบน';
    }

    if (feedback) {
      nameInput.setAttribute('aria-invalid', 'true');
      error.textContent = feedback;
      nameInput.focus();
      return;
    }

    const profile = { id: createProfileId(), name };
    setActive({ activeId: profile.id, profiles: [...latest.profiles, profile] });
  });

  function saveKey(slot: string): string {
    return `${STORAGE_PREFIX}save:${preferences.activeId ?? 'guest'}:${slot}`;
  }

  renderTrigger();

  return {
    getActiveProfile,
    loadGame<T>(slot: string): T | null {
      return readStorage(saveKey(slot)) as T | null;
    },
    saveGame<T>(slot: string, game: T): boolean {
      return writeStorage(saveKey(slot), game);
    },
    clearGame(slot: string): boolean {
      try {
        window.localStorage.removeItem(saveKey(slot));
        return true;
      } catch {
        return false;
      }
    }
  };
}

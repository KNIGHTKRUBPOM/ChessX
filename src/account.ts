import './account.css';

interface AccountUser {
  id: string;
  email: string;
  displayName: string | null;
}

interface AccountState {
  enabled: boolean;
  user: AccountUser | null;
}

type AccountMode = 'login' | 'register' | 'confirm';

const serviceUnavailable = 'เชื่อมต่อระบบบัญชีไม่ได้ กรุณาลองอีกครั้ง';
const feedbackByCode: Record<string, string> = {
  auth_not_configured: 'เซิร์ฟเวอร์นี้ยังไม่ได้เปิดระบบบัญชี',
  auth_unavailable: serviceUnavailable,
  invalid_code: 'รหัสยืนยันไม่ถูกต้องหรือหมดอายุ ตรวจอีเมลและรหัสแล้วลองอีกครั้ง',
  invalid_credentials: 'อีเมลหรือรหัสผ่านไม่ถูกต้อง',
  invalid_input: 'ตรวจข้อมูลที่กรอกแล้วลองอีกครั้ง',
  rate_limited: 'ลองหลายครั้งเกินไป กรุณารอสักครู่แล้วลองใหม่',
  request_origin: 'เปิดหน้านี้ใหม่แล้วลองอีกครั้ง',
};

class AccountError extends Error {
  constructor(readonly code: string) {
    super(code);
  }
}

async function accountRequest(method: AccountMode | 'logout' | '', payload?: Record<string, string>) {
  const endpoint = new URL('./api/account' + (method ? '/' + method : ''), location.href);
  const signal = AbortSignal.timeout(12_000);
  const send = async () => {
    const response = await fetch(endpoint, {
      method: method ? 'POST' : 'GET',
      headers: method ? { 'Content-Type': 'application/json' } : undefined,
      body: method ? JSON.stringify(payload ?? {}) : undefined,
      cache: 'no-store',
      credentials: 'same-origin',
      mode: 'same-origin',
      redirect: 'error',
      signal,
    });
    if (!response.ok) {
      const error = await response.json().catch(() => null);
      throw new AccountError(typeof error?.detail === 'string' ? error.detail : 'auth_unavailable');
    }
    return response;
  };
  // Serialize session changes when several tabs share the same cookies.
  if (!navigator.locks) return send();
  return await navigator.locks.request('chessmess-account-session', { signal }, send);
}

export function mountAccount(trigger: HTMLButtonElement, dialog: HTMLDialogElement) {
  function element<T extends HTMLElement = HTMLElement>(selector: string) {
    return dialog.querySelector<T>(selector)!;
  }

  const closeButton = element<HTMLButtonElement>('#account-close');
  const guest = element('#account-guest');
  const signedIn = element('#account-signed-in');
  const userName = element('#account-user-name');
  const userEmail = element('#account-user-email');
  const logoutButton = element<HTMLButtonElement>('#account-logout');
  const form = element<HTMLFormElement>('#account-form');
  const fields = element<HTMLFieldSetElement>('#account-fields');
  const nameField = element('#account-name-field');
  const name = element<HTMLInputElement>('#account-display-name');
  const email = element<HTMLInputElement>('#account-email');
  const passwordField = element('#account-password-field');
  const password = element<HTMLInputElement>('#account-password');
  const passwordNote = element('#account-password-note');
  const codeField = element('#account-code-field');
  const code = element<HTMLInputElement>('#account-code');
  const submit = element<HTMLButtonElement>('#account-submit');
  const status = element('#account-status');
  const modeButtons = {
    login: element<HTMLButtonElement>('#account-show-login'),
    register: element<HTMLButtonElement>('#account-show-register'),
    confirm: element<HTMLButtonElement>('#account-show-confirm'),
  };

  let mode: AccountMode = 'login';
  let state: AccountState = { enabled: false, user: null };
  let pendingStatus: Promise<string> | undefined;
  let busy = false;

  function setMessage(text: string, isError = false) {
    status.textContent = text;
    status.classList.toggle('account-error', isError);
  }

  function renderAccount() {
    guest.hidden = !state.enabled || Boolean(state.user);
    signedIn.hidden = !state.user;
    userName.textContent = state.user?.displayName ?? '';
    userEmail.textContent = state.user?.email ?? '';
    renderTrigger();
  }

  function renderTrigger() {
    const displayName = state.user?.displayName;
    trigger.textContent = state.user ? displayName || 'บัญชี' : 'เข้าสู่ระบบ';
    trigger.setAttribute('aria-label', displayName ? 'บัญชีผู้เล่น ' + displayName : trigger.textContent);
  }

  function markInvalid(input: HTMLInputElement, message: string) {
    input.setAttribute('aria-invalid', 'true');
    input.setAttribute('aria-errormessage', status.id);
    setMessage(message, true);
    input.focus();
  }

  function switchMode(nextMode: AccountMode) {
    mode = nextMode;
    const registering = mode === 'register';
    const confirming = mode === 'confirm';
    nameField.hidden = name.disabled = !registering;
    name.required = registering;
    passwordField.hidden = password.disabled = confirming;
    password.required = !confirming;
    password.autocomplete = registering ? 'new-password' : 'current-password';
    passwordNote.hidden = !registering;
    if (registering) password.setAttribute('aria-describedby', passwordNote.id);
    else password.removeAttribute('aria-describedby');
    codeField.hidden = code.disabled = !confirming;
    code.required = confirming;
    for (const input of [name, email, password, code]) {
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-errormessage');
    }
    password.value = '';
    code.value = '';
    for (const [key, button] of Object.entries(modeButtons)) button.setAttribute('aria-pressed', String(key === mode));
    submit.textContent = modeButtons[mode].textContent;
    setMessage('');
  }

  function firstField() {
    if (mode === 'register') return name;
    return mode === 'confirm' && email.value ? code : email;
  }

  function setBusy(next: boolean) {
    busy = next;
    closeButton.disabled = fields.disabled = logoutButton.disabled = next;
    for (const button of Object.values(modeButtons)) button.disabled = next;
  }

  function refreshAccount() {
    if (!pendingStatus) {
      pendingStatus = accountRequest('')
        .then(async response => {
          const next = await response.json() as AccountState;
          if (typeof next?.enabled !== 'boolean') throw new Error('Invalid account response');
          state = next;
          return next.enabled ? '' : feedbackByCode.auth_not_configured;
        })
        .catch(() => {
          state = { enabled: false, user: null };
          return serviceUnavailable;
        })
        .finally(() => {
          pendingStatus = undefined;
          renderTrigger();
        });
    }
    return pendingStatus;
  }

  trigger.addEventListener('click', () => {
    switchMode('login');
    guest.hidden = signedIn.hidden = true;
    setMessage('กำลังตรวจสอบบัญชี');
    dialog.showModal();
    void refreshAccount().then(message => {
      if (!dialog.open) return;
      renderAccount();
      setMessage(message, Boolean(message));
      if (state.enabled && document.activeElement === closeButton) {
        (state.user ? logoutButton : firstField()).focus();
      }
    });
  });

  dialog.addEventListener('cancel', event => {
    if (busy) event.preventDefault();
  });
  dialog.addEventListener('close', () => {
    password.value = '';
    code.value = '';
  });

  for (const modeName of ['login', 'register', 'confirm'] as const) {
    modeButtons[modeName].addEventListener('click', () => {
      switchMode(modeName);
      firstField().focus();
    });
  }
  for (const input of [name, email, password, code]) {
    input.addEventListener('input', () => {
      if (!input.hasAttribute('aria-invalid')) return;
      input.removeAttribute('aria-invalid');
      input.removeAttribute('aria-errormessage');
      setMessage('');
    });
  }

  form.addEventListener('submit', async event => {
    event.preventDefault();
    if (busy || !state.enabled) return;

    const displayName = name.value.normalize('NFKC')
      .split(/[\p{White_Space}\u001c-\u001f]+/u).filter(Boolean).join(' ');
    if (mode === 'register' && (!displayName || [...displayName].length > 24 || /\p{C}/u.test(displayName))) {
      markInvalid(name, 'กรอกชื่อที่แสดง 1–24 ตัวอักษร');
      return;
    }
    if (mode === 'register' && [...password.value].length < 8) {
      markInvalid(password, 'กรอกรหัสผ่านอย่างน้อย 8 ตัวอักษร');
      return;
    }
    if (mode !== 'confirm' && new TextEncoder().encode(password.value).length > 72) {
      markInvalid(password, 'รหัสผ่านยาวเกิน 72 ไบต์ กรุณากรอกให้สั้นลง');
      return;
    }
    const address = email.value.trim();
    const payload: Record<string, string> = mode === 'confirm' ? { email: address, code: code.value } :
      { email: address, password: password.value, ...(mode === 'register' ? { displayName } : {}) };
    const operation = mode;
    let focus: HTMLElement = submit;
    setBusy(true);
    setMessage(mode === 'login' ? 'กำลังเข้าสู่ระบบ' : mode === 'register' ? 'กำลังสมัครสมาชิก' : 'กำลังยืนยันอีเมล');
    try {
      const response = await accountRequest(operation, payload);
      if (operation === 'login') {
        state = await response.json() as AccountState;
        form.reset();
        renderAccount();
        setMessage('เข้าสู่ระบบแล้ว');
        focus = logoutButton;
      } else if (operation === 'register') {
        switchMode('confirm');
        setMessage('ตรวจอีเมลเพื่อดูรหัสยืนยัน');
        focus = firstField();
      } else {
        switchMode('login');
        setMessage('ยืนยันอีเมลแล้ว เข้าสู่ระบบได้เลย');
        focus = password;
      }
    } catch (error) {
      const key = error instanceof AccountError ? error.code : 'auth_unavailable';
      if (key === 'email_unconfirmed') {
        switchMode('confirm');
        setMessage('ยืนยันอีเมลด้วยรหัสที่ได้รับก่อนเข้าสู่ระบบ');
        focus = firstField();
      } else {
        setMessage(Object.hasOwn(feedbackByCode, key) ? feedbackByCode[key] : serviceUnavailable, true);
        if (key === 'invalid_credentials') {
          password.value = '';
          focus = password;
        } else if (key === 'invalid_code') {
          code.select();
          focus = code;
        }
      }
    } finally {
      setBusy(false);
      focus.focus();
    }
  });

  logoutButton.addEventListener('click', async () => {
    if (busy) return;
    setBusy(true);
    setMessage('กำลังออกจากระบบ');
    let focus: HTMLElement = logoutButton;
    try {
      await accountRequest('logout');
      state = { enabled: true, user: null };
      form.reset();
      switchMode('login');
      renderAccount();
      setMessage('ออกจากระบบแล้ว');
      focus = email;
    } catch {
      setMessage('ออกจากระบบไม่ได้ กรุณาลองอีกครั้ง', true);
    } finally {
      setBusy(false);
      focus.focus();
    }
  });

  void refreshAccount();
  return { getDisplayName: () => state.user?.displayName ?? '' };
}

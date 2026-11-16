
import { accountFeedback, accountRequest, openProvider, providerName, type AccountPayload, type Provider } from './lib/account-api';

type Factor = { id: string; name?: string; status: string };
type Identity = { id: string; provider: string };
type SecurityState = {
  aal: 'aal1' | 'aal2';
  mfaRequired: boolean;
  factors: Factor[];
  identities: Identity[];
};

type Field = { name: string; label: string; type?: string; autocomplete?: string; choices?: { value: string; label: string }[] };
type Task = { title: string; fields: Field[]; run(payload: AccountPayload): Promise<void> };

export function mountAccountSecurity(onAccountChanged: () => Promise<void>) {
  const dialog = document.createElement('dialog');
  dialog.className = 'account-dialog';
  dialog.setAttribute('aria-labelledby', 'security-title');
  dialog.innerHTML = '<div class="account-heading"><h2 id="security-title">ตั้งค่าบัญชี</h2>' +
    '<form method="dialog"><button class="ghost">ปิด</button></form></div>' +
    '<p id="security-level"></p><p id="security-player"></p><div class="account-security-actions" id="security-actions"></div>' +
    '<div id="security-enrollment" hidden></div>' +
    '<form class="account-fields" id="security-form" method="post" action="/api/account" hidden>' +
    '<h3 id="security-task-label"></h3><div class="account-fields" id="security-inputs"></div>' +
    '<button type="submit" class="primary">ยืนยัน</button></form>' +
    '<p class="account-status" id="security-status" role="status" aria-atomic="true"></p>';
  document.body.append(dialog);

  const actions = dialog.querySelector<HTMLElement>('#security-actions')!;
  const level = dialog.querySelector<HTMLElement>('#security-level')!;
  const playerStatus = dialog.querySelector<HTMLElement>('#security-player')!;
  const status = dialog.querySelector<HTMLElement>('#security-status')!;
  const enrollment = dialog.querySelector<HTMLElement>('#security-enrollment')!;
  const form = dialog.querySelector<HTMLFormElement>('#security-form')!;
  const heading = dialog.querySelector<HTMLElement>('#security-task-label')!;
  const inputs = dialog.querySelector<HTMLElement>('#security-inputs')!;
  const close = dialog.querySelector<HTMLButtonElement>('form[method="dialog"] button')!;

  let security: SecurityState;
  let providers: Provider[] = [];
  let recovery = false;
  let task: Task | undefined;
  let busy = false;
  let exportPage = 0;

  function tell(text: string, error = false) {
    status.textContent = text;
    status.classList.toggle('account-error', error);
  }

  function setBusy(next: boolean) {
    busy = next;
    for (const control of dialog.querySelectorAll<HTMLButtonElement>('button')) control.disabled = next;
    dialog.setAttribute('aria-busy', String(next));
  }

  async function perform(operation: () => Promise<void>) {
    if (busy) return;
    setBusy(true);
    tell('กำลังตรวจสอบ');
    try {
      await operation();
    } catch (error) {
      tell(accountFeedback(error), true);
    } finally {
      setBusy(false);
    }
  }

  function action(label: string, handle: () => void) {
    const button = document.createElement('button');
    button.type = 'button';
    button.className = 'ghost';
    button.textContent = label;
    button.disabled = busy;
    button.addEventListener('click', handle);
    actions.append(button);
    return button;
  }

  function reveal(next: Task) {
    task = next;
    heading.textContent = next.title;
    inputs.replaceChildren();
    for (const field of next.fields) {
      const label = document.createElement('label');
      label.className = 'account-field';
      const caption = document.createElement('span');
      caption.textContent = field.label;
      label.append(caption);
      if (field.choices) {
        const choice = document.createElement('select');
        choice.name = field.name;
        choice.required = true;
        for (const item of field.choices) choice.add(new Option(item.label, item.value));
        label.append(choice);
      } else {
        const input = document.createElement('input');
        input.name = field.name;
        input.type = field.type ?? 'text';
        if (field.autocomplete) input.setAttribute('autocomplete', field.autocomplete);
        input.required = !['nonce', 'currentPassword'].includes(field.name);
        if (field.name === 'code' || field.name === 'nonce') {
          input.inputMode = 'numeric';
          input.pattern = '[0-9]{6,10}';
          input.maxLength = 10;
        }
        label.append(input);
      }
      inputs.append(label);
    }
    form.hidden = false;
    inputs.querySelector<HTMLElement>('input, select')?.focus();
  }

  function ask(title: string, fields: Field[], path: string, success: string) {
    enrollment.hidden = true;
    enrollment.replaceChildren();
    reveal({ title, fields, run: async payload => {
      await accountRequest(path, payload);
      form.reset();
      form.hidden = true;
      tell(success);
    } });
  }

  const code: Field = { name: 'code', label: 'รหัสยืนยัน', autocomplete: 'one-time-code' };
  const email: Field = { name: 'email', label: 'อีเมลใหม่', type: 'email', autocomplete: 'email' };
  const password: Field = { name: 'password', label: 'รหัสผ่านใหม่', type: 'password', autocomplete: 'new-password' };

  function changePassword() {
    const fields = recovery ? [password] : [
      password, { name: 'currentPassword', label: 'รหัสผ่านปัจจุบัน (ถ้ามี)', type: 'password', autocomplete: 'current-password' },
      { name: 'nonce', label: 'รหัสยืนยันจากอีเมล (ถ้าได้รับ)', autocomplete: 'one-time-code' },
    ];
    reveal({ title: 'เปลี่ยนรหัสผ่าน', fields, run: async payload => {
      await accountRequest('password', { ...payload, ...(recovery ? { recovery: true } : {}) });
      form.reset();
      form.hidden = true;
      if (recovery) {
        await onAccountChanged();
        dialog.close();
      } else tell('บันทึกรหัสผ่านใหม่แล้ว');
    } });
  }

  function verifyFactor(factor?: string) {
    const choices = security.factors.filter(item => item.status === 'verified')
      .map((item, index) => ({ value: item.id, label: item.name || 'Authenticator ' + String(index + 1) }));
    const fields = factor ? [code] : [{ name: 'factorId', label: 'แอป Authenticator', choices }, code];
    reveal({ title: 'ยืนยันด้วยแอป Authenticator', fields, run: async payload => {
      await accountRequest('mfa/verify', { ...payload, ...(factor ? { factorId: factor } : {}), ...(recovery ? { recovery: true } : {}) });
      form.reset();
      form.hidden = true;
      enrollment.hidden = true;
      enrollment.replaceChildren();
      await refresh();
      tell('ยืนยันแอป Authenticator แล้ว');
    } });
  }

  async function enrollFactor() {
    const response = await accountRequest('mfa/enroll', { name: 'ChessMess' });
    const item = await response.json() as { factorId: string; qrCode: string; secret: string };
    const instruction = document.createElement('p');
    instruction.textContent = 'สแกน QR ด้วย Authenticator หรือป้อนคีย์ด้วยตนเอง แล้วกรอกรหัสจากแอป';
    const manual = document.createElement('code');
    manual.textContent = item.secret;
    enrollment.replaceChildren(instruction);
    if (item.qrCode.startsWith('data:image/svg+xml;base64,')) {
      const qr = document.createElement('img');
      qr.src = item.qrCode;
      qr.alt = 'QR สำหรับเพิ่ม ChessMess ในแอป Authenticator';
      qr.width = qr.height = 144;
      enrollment.append(qr);
    }
    enrollment.append(manual);
    enrollment.hidden = false;
    verifyFactor(item.factorId);
    tell('');
  }

  async function endSession(path: string, payload: AccountPayload = {}) {
    await accountRequest(path, payload);
    await onAccountChanged();
    dialog.close();
  }

  function drawActions() {
    actions.replaceChildren();
    level.textContent = security.aal === 'aal2' ? 'ยืนยันสองขั้นตอนแล้ว' :
      security.mfaRequired ? 'กรุณายืนยันด้วยแอป Authenticator' : 'ยืนยันตัวตนแล้ว';
    const verified = security.factors.filter(item => item.status === 'verified');
    if (verified.length) action('ยืนยันด้วย Authenticator', () => verifyFactor());
    if (security.mfaRequired && security.aal !== 'aal2') return;
    action('เปลี่ยนรหัสผ่าน', changePassword);
    if (recovery) return;
    action('แก้ไขโปรไฟล์', () => ask('แก้ไขโปรไฟล์', [
      { name: 'username', label: 'ชื่อผู้ใช้ 3–34 ตัว เลือก a–z, 0–9 หรือ _', autocomplete: 'username' },
      { name: 'displayName', label: 'ชื่อที่แสดง 1–24 ตัว', autocomplete: 'nickname' },
    ], 'profile', 'บันทึกโปรไฟล์แล้ว'));
    action('ส่งรหัสยืนยันตัวตน', () => { void perform(async () => {
      await accountRequest('reauthenticate', {});
      tell('หากระบบส่งรหัสให้ กรุณาตรวจอีเมล');
    }); });
    action('เปลี่ยนอีเมล', () => ask('เปลี่ยนอีเมล', [email], 'email', 'ตรวจกล่องอีเมลเพื่อยืนยันการเปลี่ยน'));
    action('ยืนยันอีเมลที่เปลี่ยน', () => ask('ยืนยันการเปลี่ยนอีเมล', [email, code], 'email/confirm', 'ตรวจอีเมลทั้งสองกล่องเพื่อทำรายการให้ครบ'));
    action('เพิ่ม Authenticator', () => { void perform(enrollFactor); });
    if (verified.length) action('ลบ Authenticator', () => ask('ลบ Authenticator', [{
      name: 'factorId', label: 'เลือกรายการที่จะลบ',
      choices: verified.map((item, index) => ({ value: item.id, label: item.name || 'Authenticator ' + (index + 1) })),
    }], 'mfa/remove', 'ลบ Authenticator แล้ว กรุณาเปิดการตั้งค่าใหม่เพื่อดูสถานะ'));
    for (const provider of providers) {
      if (security.identities.some(identity => identity.provider === provider)) continue;
      action('ผูกบัญชี ' + providerName(provider), () => { void perform(() => openProvider(provider, true)); });
    }
    const linked = security.identities.filter(identity => identity.provider !== 'email');
    if (security.identities.length > 1 && linked.length) action('ยกเลิกการผูกบัญชี', () => ask('เลือกบัญชีที่จะเลิกผูก', [{
      name: 'identityId', label: 'บัญชีที่ผูก',
      choices: linked.map(identity => ({ value: identity.id, label: providerName(identity.provider) })),
    }], 'identity/unlink', 'ยกเลิกการผูกแล้ว'));
    action('ออกจากระบบทุกอุปกรณ์', () => { void perform(() => endSession('logout-all')); });
    const download = action('ดาวน์โหลดข้อมูลของฉัน', () => { void perform(async () => {
      const response = await accountRequest('export?page=' + exportPage);
      const data = await response.json() as { nextPage: number | null };
      const url = URL.createObjectURL(new Blob([JSON.stringify(data, null, 2)], { type: 'application/json' }));
      const link = document.createElement('a');
      link.href = url;
      link.download = 'chessmess-account-' + (exportPage + 1) + '.json';
      link.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 5000);
      exportPage = data.nextPage ?? 0;
      download.textContent = data.nextPage === null ? 'ดาวน์โหลดข้อมูลของฉัน' : 'ดาวน์โหลดข้อมูลหน้าถัดไป';
      tell('เตรียมไฟล์ข้อมูลแล้ว');
    }); });
    action('ลบบัญชี', () => reveal({
      title: 'ลบบัญชีถาวร',
      fields: [{ name: 'confirmation', label: 'พิมพ์ DELETE เพื่อยืนยันการลบบัญชีและประวัติ' }],
      run: async payload => { await endSession('delete', payload); },
    }));
  }

  async function refresh() {
    const response = await accountRequest('security' + (recovery ? '?recovery=true' : ''));
    security = await response.json() as SecurityState;
    drawActions();
    if (recovery || (security.mfaRequired && security.aal !== 'aal2')) return;
    try {
      const profile = await accountRequest('profile');
      const player = await profile.json() as { profile: { username: string } | null; stats: { games_played: number; wins: number; losses: number; draws: number } | null };
      if (player.profile && player.stats) {
        const { games_played, wins, losses, draws } = player.stats;
        playerStatus.textContent = player.profile.username + ' · แข่ง ' + games_played + ' · ชนะ ' + wins + ' · แพ้ ' + losses + ' · เสมอ ' + draws;
      }
    } catch {
      playerStatus.textContent = '';
    }
  }

  form.addEventListener('submit', event => {
    event.preventDefault();
    const pending = task;
    if (!pending) return;
    const payload = Object.fromEntries([...new FormData(form)].filter(([, value]) => value !== '')) as AccountPayload;
    void perform(() => pending.run(payload));
  });
  dialog.addEventListener('cancel', event => { if (busy) event.preventDefault(); });
  dialog.addEventListener('close', () => {
    form.reset();
    form.hidden = true;
    task = undefined;
    enrollment.hidden = true;
    enrollment.replaceChildren();
  });

  return (enabledProviders: Provider[], recovering = false) => {
    if (dialog.open) return;
    providers = enabledProviders;
    recovery = recovering;
    actions.replaceChildren();
    level.textContent = '';
    playerStatus.textContent = '';
    exportPage = 0;
    dialog.showModal();
    close.focus();
    void perform(async () => {
      await refresh();
      tell('');
      if (security.mfaRequired && security.aal !== 'aal2') verifyFactor();
      else if (recovery) changePassword();
    });
  };
}

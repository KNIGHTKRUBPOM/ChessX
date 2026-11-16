
type Value = string | boolean;
export type AccountPayload = Record<string, Value>;
export type Provider = 'google' | 'facebook';
export interface AccountOptions {
  providers: Provider[];
  captcha: { provider: 'turnstile'; siteKey: string } | null;
}

const fallback = 'เชื่อมต่อระบบบัญชีไม่ได้ กรุณาลองอีกครั้ง';
const messages: Record<string, string> = {
  auth_not_configured: 'เซิร์ฟเวอร์นี้ยังไม่ได้เปิดระบบบัญชี',
  auth_unavailable: fallback,
  auth_required: 'กรุณาเข้าสู่ระบบก่อน',
  session_required: 'กรุณาเข้าสู่ระบบใหม่',
  mfa_required: 'ยืนยันด้วยแอป Authenticator ก่อนทำรายการ',
  aal2_required: 'ยืนยันด้วยแอป Authenticator ก่อนทำรายการ',
  reauthentication_required: 'ยืนยันตัวตนอีกครั้งก่อนเปลี่ยนการตั้งค่า',
  recent_login_required: 'กรุณาเข้าสู่ระบบใหม่ หรือยืนยัน Authenticator แล้วลองอีกครั้ง',
  profile_change_rejected: 'บันทึกโปรไฟล์ไม่ได้ กรุณาตรวจชื่อหรือเลือกชื่อผู้ใช้ใหม่',
  invalid_code: 'รหัสไม่ถูกต้องหรือหมดอายุ กรุณาตรวจรหัสอีกครั้ง',
  invalid_credentials: 'อีเมลหรือรหัสผ่านไม่ถูกต้อง',
  invalid_input: 'ตรวจข้อมูลที่กรอกแล้วลองอีกครั้ง',
  rate_limited: 'ลองหลายครั้งเกินไป กรุณารอสักครู่แล้วลองใหม่',
  captcha_required: 'กรุณาทำการตรวจสอบก่อนส่งข้อมูล',
  request_origin: 'เปิดเกมจากโดเมนที่ตั้งไว้แล้วลองอีกครั้ง',
};

export class AccountError extends Error {
  readonly code: string;
  constructor(code: string) {
    super(code);
    this.code = code;
  }
}

export function accountFeedback(error: unknown) {
  return error instanceof AccountError && Object.hasOwn(messages, error.code) ? messages[error.code] : fallback;
}

export async function accountRequest(path = '', payload?: AccountPayload) {
  const endpoint = new URL('/api/account' + (path ? '/' + path : ''), location.origin);
  const signal = AbortSignal.timeout(15_000);
  const send = async () => {
    const response = await fetch(endpoint, {
      method: payload === undefined ? 'GET' : 'POST',
      headers: payload === undefined ? undefined : { 'Content-Type': 'application/json' },
      body: payload === undefined ? undefined : JSON.stringify(payload),
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
  if (!navigator.locks) return send();
  return await navigator.locks.request('chessmess-account-session', { signal }, send);
}

export async function openProvider(provider: Provider, link = false) {
  const response = await accountRequest('oauth', { provider, link });
  const { url } = await response.json() as { url: string };
  location.assign(providerDestination(url, location.origin).href);
}

export function providerDestination(url: string, appOrigin: string) {
  const destination = new URL(url);
  const loopback = ['localhost', '127.0.0.1', '[::1]'];
  const local = destination.protocol === 'http:' && loopback.includes(destination.hostname) &&
    loopback.includes(new URL(appOrigin).hostname);
  if ((destination.protocol !== 'https:' && !local) || destination.username || destination.password) {
    throw new AccountError('auth_unavailable');
  }
  return destination;
}

export function providerName(provider: string) {
  if (provider === 'google') return 'Google';
  if (provider === 'facebook') return 'Facebook';
  if (provider === 'email') return 'อีเมล';
  return provider;
}

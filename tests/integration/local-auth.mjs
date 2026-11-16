import { createHmac, randomUUID } from 'node:crypto';
import { setTimeout as delay } from 'node:timers/promises';
import { createClient } from '@supabase/supabase-js';
import { localUrl } from '../../scripts/local.mjs';

const origin = localUrl(process.env.APP_ORIGIN);
const supabase = localUrl(process.env.SUPABASE_URL);
const mail = localUrl(process.env.CHESS_QA_LOCAL_MAIL_URL);
const publishable = process.env.SUPABASE_PUBLISHABLE_KEY;
const secret = process.env.SUPABASE_SECRET_KEY;
const aliases = {
  signup: 'รหัสยืนยันบัญชี ChessMess',
  recovery: 'รหัสตั้งรหัสผ่านใหม่ ChessMess',
};
const jar = new Map();

function verify(condition, description) {
  if (!condition) throw new Error(description);
}

function sdk(key) {
  verify(Boolean(key), 'Local Supabase key missing');
  return createClient(supabase, key, {
    auth: { flowType: 'pkce', persistSession: false, autoRefreshToken: false, detectSessionInUrl: false },
  });
}

async function account(label, path = '', { body, status = 200 } = {}) {
  const headers = new Headers({ Accept: 'application/json' });
  if (jar.size) headers.set('Cookie', Array.from(jar, ([name, value]) => name + '=' + value).join('; '));
  if (body !== undefined) {
    headers.set('Origin', origin);
    headers.set('Content-Type', 'application/json');
  }
  const response = await fetch(origin + '/api/account' + path, {
    method: body === undefined ? 'GET' : 'POST', headers, redirect: 'error',
    body: body === undefined ? undefined : JSON.stringify(body), signal: AbortSignal.timeout(15000),
  }).catch(() => { throw new Error(label + ': local request failed'); });
  verify(response.status === status, label + ': HTTP ' + response.status);
  for (const cookie of response.headers.getSetCookie()) {
    const [pair, ...extensions] = cookie.split(';');
    const equals = pair.indexOf('=');
    const name = pair.slice(0, equals);
    if (extensions.some(extension => extension.trim().toLowerCase() === 'max-age=0')) jar.delete(name);
    else jar.set(name, pair.slice(equals + 1));
  }
  if (status === 204) return null;
  return await response.json().catch(() => { throw new Error(label + ': invalid response format'); });
}

async function otp(email, subject) {
  const url = new URL('/view/latest.html', mail);
  url.searchParams.set('query', 'to:' + email + ' subject:"' + subject + '"');
  for (let attempt = 0; attempt < 25; ++attempt) {
    const response = await fetch(url, { redirect: 'error', signal: AbortSignal.timeout(2000) })
      .catch(() => { throw new Error('Mailpit connection failed'); });
    if (response.ok) {
      const html = await response.text();
      const match = /<strong>\s*([0-9]{6})\s*<\/strong>/u.exec(html);
      if (match) return match[1];
    } else if (response.status !== 404) {
      throw new Error('Mailpit returned HTTP ' + response.status);
    }
    await delay(400);
  }
  throw new Error('Expected OTP message did not arrive in Mailpit');
}

function totp(secretValue) {
  const alphabet = 'ABCDEFGHIJKLMNOPQRSTUVWXYZ234567';
  const bytes = [];
  let bits = 0;
  let value = 0;
  for (const digit of secretValue.replace(/=+$/u, '')) {
    const index = alphabet.indexOf(digit);
    verify(index >= 0, 'Unexpected TOTP secret encoding');
    value = (value << 5) | index;
    bits += 5;
    if (bits >= 8) {
      bits -= 8;
      bytes.push((value >> bits) & 255);
      value &= (1 << bits) - 1;
    }
  }
  const counter = Buffer.alloc(8);
  counter.writeBigUInt64BE(BigInt(Math.floor(Date.now() / 30000)));
  const digest = createHmac('sha1', Buffer.from(bytes)).update(counter).digest();
  const offset = digest.at(-1) & 15;
  return String((digest.readUInt32BE(offset) & 0x7fffffff) % 1_000_000).padStart(6, '0');
}

async function run() {
  const admin = sdk(secret);
  const browserSdk = sdk(publishable);
  const id = randomUUID();
  const email = 'chessx-qa-' + id + '@example.test';
  let password = 'Local-QA-' + id;
  let userId;
  try {
    await account('Signup', '/register', { body: { email, password, displayName: 'Local QA' }, status: 202 });
    await account('Confirm email', '/confirm', { body: { email, code: await otp(email, aliases.signup) }, status: 204 });
    const signedIn = await account('Password login', '/login', { body: { email, password } });
    userId = signedIn.user?.id;
    verify(typeof userId === 'string' && signedIn.user.email === email, 'Confirmed account did not sign in');
    verify(jar.has('chessmess_access') && jar.has('chessmess_refresh'), 'Session cookies not issued');
    const hidden = await browserSdk.from('profiles').select('id').eq('id', userId);
    verify(Boolean(hidden.error) || hidden.data?.length === 0, 'Anonymous profile read returned data');
    const user = await browserSdk.auth.signInWithPassword({ email, password });
    verify(!user.error && user.data.user?.id === userId, 'Official Supabase SDK did not sign in');
    const profile = await browserSdk.from('profiles').select('id,display_name').eq('id', userId).single();
    verify(!profile.error && profile.data?.display_name === 'Local QA', 'Profile trigger or own RLS read failed');
    await browserSdk.auth.signOut({ scope: 'local' });

    jar.delete('chessmess_access');
    const refreshed = await account('Session refresh');
    verify(refreshed.user?.id === userId && jar.has('chessmess_access'), 'Refresh did not restore session');
    await account('Session logout', '/logout', { body: {}, status: 204 });
    verify((await account('Anonymous status')).user === null, 'Logout left the current browser session signed in');

    await account('Request password recovery', '/recover', { body: { email }, status: 202 });
    const recovery = await account('Verify recovery OTP', '/recover/confirm', {
      body: { email, code: await otp(email, aliases.recovery) },
    });
    verify(recovery.recovery && !jar.has('chessmess_access'), 'Recovery emitted general account credentials');
    await account('Recovery cannot open profile', '/profile', { status: 401 });
    password = 'Changed-QA-' + randomUUID();
    await account('Set recovered password', '/password', { body: { password, recovery: true }, status: 204 });
    verify(!jar.has('chessmess_recovery_access'), 'Recovery session cookie was not cleared');
    verify((await account('New password login', '/login', { body: { email, password } })).user?.id === userId,
      'Recovery password did not authenticate');

    const enrollment = await account('TOTP enroll', '/mfa/enroll', { body: { name: 'Local QA TOTP' } });
    verify(Boolean(enrollment.factorId && enrollment.secret) &&
      enrollment.qrCode?.startsWith('data:image/svg+xml;base64,'), 'TOTP enrollment fields missing');
    const factor = { factorId: enrollment.factorId, code: totp(enrollment.secret) };
    verify((await account('TOTP verify', '/mfa/verify', { body: factor })).aal === 'aal2', 'AAL2 not established');
    const security = await account('Verified factors', '/security');
    verify(security.aal === 'aal2' && security.factors.some(item =>
      item.id === enrollment.factorId && item.status === 'verified'), 'Verified TOTP factor missing');

    const exported = await account('Export own data', '/export');
    verify(exported.account?.id === userId && exported.profiles.some(item => item.id === userId),
      'Export did not contain own profile');
    await account('Delete synthetic account', '/delete', { body: { confirmation: 'DELETE' }, status: 204 });
    const remaining = await admin.auth.admin.getUserById(userId);
    verify(remaining.error?.status === 404, 'Synthetic account remained after deletion');
    userId = undefined;
  } finally {
    if (userId) {
      await admin.auth.admin.deleteUser(userId).catch(() => undefined);
    }
  }
  console.log('PASS Local Supabase signup, OTP, SDK RLS, refresh/logout, recovery, TOTP, export/delete');
}

await run().catch(error => {
  console.error('FAIL: ' + error.message);
  process.exitCode = 1;
});

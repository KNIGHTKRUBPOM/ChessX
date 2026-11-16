import assert from 'node:assert/strict';
import test from 'node:test';

import { AccountError, accountFeedback, providerDestination } from '../../src/lib/account-api.ts';
import { localUrl } from '../../scripts/local.mjs';

test('test environment only accepts loopback origins', () => {
  assert.equal(localUrl('http://127.0.0.1:54321'), 'http://127.0.0.1:54321');
  assert.throws(() => localUrl('https://example.invalid'));
});

test('OAuth destination allows an HTTPS provider and restricts HTTP to loopback development', () => {
  assert.equal(providerDestination('https://accounts.google.com/o/oauth2/v2/auth', 'https://chessmess.vercel.app').hostname, 'accounts.google.com');
  assert.equal(providerDestination('http://127.0.0.1:54321/auth/v1/authorize', 'http://127.0.0.1:3210').port, '54321');
  assert.throws(() => providerDestination('http://127.0.0.1:54321/auth/v1/authorize', 'https://chessmess.vercel.app'));
});

test('unexpected provider errors use fixed UI feedback instead of internals', () => {
  assert.equal(accountFeedback(new AccountError('unexpected-provider-detail')), accountFeedback(new Error('request failed')));
  assert.match(accountFeedback(new AccountError('invalid_code')), /รหัส/);
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { resolveSessionExpiryUnixSeconds } from './session-expiry.ts';

const toBase64Url = (value: string): string =>
  Buffer.from(value, 'utf8')
    .toString('base64')
    .replace(/\+/g, '-')
    .replace(/\//g, '_')
    .replace(/=+$/g, '');

const buildJwtWithExp = (exp: number): string => {
  const header = toBase64Url(JSON.stringify({ alg: 'HS256', typ: 'JWT' }));
  const payload = toBase64Url(JSON.stringify({ sub: 'user-1', exp }));
  return `${header}.${payload}.signature`;
};

test('prefers expires_at when provided', () => {
  assert.equal(
    resolveSessionExpiryUnixSeconds(
      {
        expires_at: 1700001234,
        expires_in: 3600,
      },
      1700000000,
    ),
    1700001234,
  );
});

test('falls back to expires_in when expires_at is missing', () => {
  assert.equal(
    resolveSessionExpiryUnixSeconds(
      {
        expires_in: 1800,
      },
      1700000000,
    ),
    1700001800,
  );
});

test('falls back to JWT exp when expires fields are missing', () => {
  const exp = 1700002222;
  assert.equal(
    resolveSessionExpiryUnixSeconds(
      {
        access_token: buildJwtWithExp(exp),
      },
      1700000000,
    ),
    exp,
  );
});

test('returns undefined when no valid expiry metadata exists', () => {
  assert.equal(
    resolveSessionExpiryUnixSeconds(
      {
        access_token: 'invalid-token',
      },
      1700000000,
    ),
    undefined,
  );
});

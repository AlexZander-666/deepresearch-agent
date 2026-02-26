import assert from 'node:assert/strict';
import test from 'node:test';
import {
  getBackendUrl,
  getPublicEnv,
  getServerBackendUrl,
  normalizePublicEnvValue,
} from './env.ts';

test('normalizePublicEnvValue removes wrapping quotes', () => {
  assert.equal(
    normalizePublicEnvValue('"http://localhost:8000/api"'),
    'http://localhost:8000/api',
  );
  assert.equal(normalizePublicEnvValue('""'), '');
  assert.equal(normalizePublicEnvValue("'value'"), 'value');
});

test('normalizePublicEnvValue handles nullish and placeholder strings', () => {
  assert.equal(normalizePublicEnvValue(undefined), '');
  assert.equal(normalizePublicEnvValue(null), '');
  assert.equal(normalizePublicEnvValue('null'), '');
  assert.equal(normalizePublicEnvValue('undefined'), '');
});

test('getPublicEnv applies fallback after normalization', () => {
  const env = {
    NEXT_PUBLIC_BACKEND_URL: '"http://localhost:8000/api"',
    NEXT_PUBLIC_POSTHOG_KEY: '""',
  } as NodeJS.ProcessEnv;

  assert.equal(
    getPublicEnv('NEXT_PUBLIC_BACKEND_URL', '', env),
    'http://localhost:8000/api',
  );
  assert.equal(getPublicEnv('NEXT_PUBLIC_POSTHOG_KEY', 'fallback', env), 'fallback');
});

test('getBackendUrl falls back to local api when env is missing', () => {
  assert.equal(getBackendUrl({} as NodeJS.ProcessEnv), 'http://localhost:8000/api');
});

test('getBackendUrl normalizes explicit NEXT_PUBLIC_BACKEND_URL', () => {
  const env = {
    NEXT_PUBLIC_BACKEND_URL: "'https://example.com/api'",
  } as NodeJS.ProcessEnv;

  assert.equal(getBackendUrl(env), 'https://example.com/api');
});

test('getServerBackendUrl prefers BACKEND_URL when provided', () => {
  const env = {
    BACKEND_URL: 'http://backend.internal:8000/api',
    NEXT_PUBLIC_BACKEND_URL: 'http://localhost:8000/api',
  } as NodeJS.ProcessEnv;

  assert.equal(
    getServerBackendUrl(env, { isDocker: false }),
    'http://backend.internal:8000/api',
  );
});

test('getServerBackendUrl rewrites localhost in docker mode', () => {
  const env = {
    NEXT_PUBLIC_BACKEND_URL: 'http://localhost:8000/api',
  } as NodeJS.ProcessEnv;

  assert.equal(
    getServerBackendUrl(env, { isDocker: true }),
    'http://host.docker.internal:8000/api',
  );
});

test('getServerBackendUrl does not rewrite non-local hosts in docker mode', () => {
  const env = {
    NEXT_PUBLIC_BACKEND_URL: 'https://example.com/api',
  } as NodeJS.ProcessEnv;

  assert.equal(
    getServerBackendUrl(env, { isDocker: true }),
    'https://example.com/api',
  );
});

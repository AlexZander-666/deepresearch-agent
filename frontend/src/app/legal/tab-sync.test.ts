import assert from 'node:assert/strict';
import test from 'node:test';
import { getLegalTabFromParam, getNextLegalTabUrl } from './tab-sync.ts';

test('getLegalTabFromParam falls back to terms for invalid values', () => {
  assert.equal(getLegalTabFromParam('terms'), 'terms');
  assert.equal(getLegalTabFromParam('privacy'), 'privacy');
  assert.equal(getLegalTabFromParam(null), 'terms');
  assert.equal(getLegalTabFromParam('invalid'), 'terms');
});

test('getNextLegalTabUrl returns null when tab is already in sync', () => {
  const current = new URLSearchParams('tab=terms');
  assert.equal(getNextLegalTabUrl('/legal', current, 'terms'), null);
});

test('getNextLegalTabUrl updates only the tab query parameter', () => {
  const current = new URLSearchParams('foo=bar&tab=terms');
  assert.equal(
    getNextLegalTabUrl('/legal', current, 'privacy'),
    '/legal?foo=bar&tab=privacy',
  );
});

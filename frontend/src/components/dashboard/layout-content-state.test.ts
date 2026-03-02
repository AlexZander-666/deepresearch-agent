import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldShowDashboardLoading } from './layout-content-state.ts';

test('shows loading while auth is still loading', () => {
  assert.equal(
    shouldShowDashboardLoading({
      authLoading: true,
      healthLoading: false,
      healthStatus: undefined,
      healthError: null,
    }),
    true,
  );
});

test('shows loading during initial health check', () => {
  assert.equal(
    shouldShowDashboardLoading({
      authLoading: false,
      healthLoading: true,
      healthStatus: undefined,
      healthError: null,
    }),
    true,
  );
});

test('stops loading when health check already failed even if a retry is running', () => {
  assert.equal(
    shouldShowDashboardLoading({
      authLoading: false,
      healthLoading: true,
      healthStatus: undefined,
      healthError: new Error('network down'),
    }),
    false,
  );
});

test('does not show loading when a healthy value is already available', () => {
  assert.equal(
    shouldShowDashboardLoading({
      authLoading: false,
      healthLoading: true,
      healthStatus: 'ok',
      healthError: null,
    }),
    false,
  );
});

import assert from 'node:assert/strict';
import test from 'node:test';

import { shouldUseAlexManusComputerPrivacyView } from './alexmanus-privacy';

test('returns true for AlexManus computer tools', () => {
  assert.equal(
    shouldUseAlexManusComputerPrivacyView('AlexManus', 'browser_navigate_to'),
    true,
  );
  assert.equal(
    shouldUseAlexManusComputerPrivacyView('alexmanus-research', 'screenshot'),
    true,
  );
});

test('returns false for non-AlexManus agents or non-computer tools', () => {
  assert.equal(
    shouldUseAlexManusComputerPrivacyView('ResearchAgent', 'browser_navigate_to'),
    false,
  );
  assert.equal(
    shouldUseAlexManusComputerPrivacyView('AlexManus', 'create_tasks'),
    false,
  );
  assert.equal(shouldUseAlexManusComputerPrivacyView(undefined, 'screenshot'), false);
});

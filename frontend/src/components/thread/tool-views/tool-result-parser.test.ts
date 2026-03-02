import assert from 'node:assert/strict';
import test from 'node:test';

import { parseToolResult } from './tool-result-parser';

test('marks scrape_webpage textual failures as unsuccessful when success flag is missing', () => {
  const parsed = parseToolResult({
    tool_name: 'scrape_webpage',
    result:
      'Failed to scrape all 3 URLs. Errors: https://en.wikipedia.org/wiki/HTTP_401',
  });

  assert.ok(parsed);
  assert.equal(parsed?.toolName, 'scrape-webpage');
  assert.equal(parsed?.isSuccess, false);
});

test('keeps explicit success=true as successful', () => {
  const parsed = parseToolResult({
    tool_name: 'scrape_webpage',
    success: true,
    result: 'Scraped 3 pages successfully.',
  });

  assert.ok(parsed);
  assert.equal(parsed?.isSuccess, true);
});

test('treats streaming placeholder output as successful/in-progress', () => {
  const parsed = parseToolResult({
    tool_name: 'browser_navigate_to',
    result: 'STREAMING',
  });

  assert.ok(parsed);
  assert.equal(parsed?.isSuccess, true);
});

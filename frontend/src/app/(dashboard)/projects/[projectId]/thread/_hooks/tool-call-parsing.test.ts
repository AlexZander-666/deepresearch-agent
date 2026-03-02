import assert from 'node:assert/strict';
import test from 'node:test';

import {
  hasExplicitNullToolCalls,
  parseAssistantToolCallInfo,
} from './tool-call-parsing.ts';
import { mergeServerAndLocalMessages } from './message-merge.ts';

const buildMessage = (overrides: Record<string, unknown> = {}) => ({
  message_id: null,
  thread_id: 'thread-1',
  type: 'assistant',
  is_llm_message: true,
  content: '',
  metadata: '{}',
  created_at: new Date(0).toISOString(),
  updated_at: new Date(0).toISOString(),
  ...overrides,
});

test('hasExplicitNullToolCalls detects null tool_calls even when content JSON is malformed', () => {
  const malformed = '{"role":"assistant","content":"hello","tool_calls": null';
  assert.equal(hasExplicitNullToolCalls(malformed), true);
});

test('parseAssistantToolCallInfo returns null when tool_calls is explicitly null', () => {
  const content = JSON.stringify({
    role: 'assistant',
    content: 'plain text only',
    tool_calls: null,
  });

  assert.equal(parseAssistantToolCallInfo(content), null);
});

test('parseAssistantToolCallInfo extracts first tool name and id when tool_calls exists', () => {
  const content = JSON.stringify({
    role: 'assistant',
    content: '',
    tool_calls: [
      {
        id: 'call_abc123',
        type: 'function',
        function: {
          name: 'view_tasks',
          arguments: { section: 'planning' },
        },
      },
    ],
  });

  assert.deepEqual(parseAssistantToolCallInfo(content), {
    toolName: 'view-tasks',
    toolCallId: 'call_abc123',
  });
});

test('mergeServerAndLocalMessages keeps optimistic temp messages and removes stale local extras', () => {
  const now = Date.parse('2026-02-28T10:00:00.000Z');
  const server = [
    buildMessage({
      message_id: 'srv-1',
      type: 'assistant',
      content: 'server-content',
      created_at: '2026-02-28T09:59:00.000Z',
      updated_at: '2026-02-28T09:59:00.000Z',
    }),
  ];

  const local = [
    buildMessage({
      message_id: 'srv-1',
      type: 'assistant',
      content: 'stale-local-content',
      created_at: '2026-02-28T09:59:00.000Z',
      updated_at: '2026-02-28T09:59:00.000Z',
    }),
    buildMessage({
      message_id: 'temp-123',
      type: 'assistant',
      content: 'optimistic',
      created_at: '2026-02-28T09:59:30.000Z',
      updated_at: '2026-02-28T09:59:30.000Z',
    }),
    buildMessage({
      message_id: 'local-only-old',
      type: 'assistant',
      content: 'should-drop',
      created_at: '2026-02-28T09:40:00.000Z',
      updated_at: '2026-02-28T09:40:00.000Z',
    }),
  ];

  const merged = mergeServerAndLocalMessages(server as any, local as any, {
    now,
    localMessageGracePeriodMs: 60_000,
  });

  assert.equal(merged.length, 2);
  assert.equal(merged[0].message_id, 'srv-1');
  assert.equal(merged[0].content, 'server-content');
  assert.equal(merged[1].message_id, 'temp-123');
});

test('mergeServerAndLocalMessages keeps recent local extra messages within grace period', () => {
  const now = Date.parse('2026-02-28T10:00:00.000Z');
  const server = [
    buildMessage({
      message_id: 'srv-1',
      content: 'server-content',
      created_at: '2026-02-28T09:59:00.000Z',
      updated_at: '2026-02-28T09:59:00.000Z',
    }),
  ];

  const local = [
    buildMessage({
      message_id: 'local-only-recent',
      content: 'recent-local-message',
      created_at: '2026-02-28T09:59:45.000Z',
      updated_at: '2026-02-28T09:59:45.000Z',
    }),
  ];

  const merged = mergeServerAndLocalMessages(server as any, local as any, {
    now,
    localMessageGracePeriodMs: 60_000,
  });

  assert.equal(merged.length, 2);
  assert.equal(merged[1].message_id, 'local-only-recent');
});

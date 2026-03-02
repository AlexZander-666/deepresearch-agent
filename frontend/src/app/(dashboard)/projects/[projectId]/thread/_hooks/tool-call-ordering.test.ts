import assert from 'node:assert/strict';
import test from 'node:test';

import type { ToolCallInput } from '../../../../../../components/thread/tool-call-side-panel';
import {
  sortToolCallsByExecutionOrder,
  upsertStreamingToolCall,
} from './tool-call-ordering';

const buildToolCall = (
  overrides: Partial<ToolCallInput> = {},
  assistantOverrides: Partial<ToolCallInput['assistantCall']> = {},
  resultOverrides: Partial<NonNullable<ToolCallInput['toolResult']>> = {},
): ToolCallInput => ({
  assistantCall: {
    name: 'web-search',
    content: '{}',
    timestamp: '2026-03-01T00:00:00.000Z',
    ...assistantOverrides,
  },
  toolResult: {
    content: 'STREAMING',
    isSuccess: true,
    timestamp: '2026-03-01T00:00:00.000Z',
    ...resultOverrides,
  },
  ...overrides,
});

test('sortToolCallsByExecutionOrder keeps explicit tool_index order', () => {
  const input = [
    buildToolCall({}, { name: 'update-tasks', toolIndex: 2, toolCallId: 'call-2' }),
    buildToolCall({}, { name: 'create-tasks', toolIndex: 0, toolCallId: 'call-0' }),
    buildToolCall({}, { name: 'view-tasks', toolIndex: 1, toolCallId: 'call-1' }),
  ];

  const sorted = sortToolCallsByExecutionOrder(input);

  assert.deepEqual(
    sorted.map((item) => item.assistantCall.name),
    ['create-tasks', 'view-tasks', 'update-tasks'],
  );
});

test('upsertStreamingToolCall appends distinct task tool calls instead of replacing earlier task rows', () => {
  const previous = [
    buildToolCall({}, { name: 'create-tasks', toolCallId: 'task-1', toolIndex: 0 }),
  ];
  const incoming = buildToolCall(
    {},
    { name: 'view-tasks', toolCallId: 'task-2', toolIndex: 1 },
    { content: 'STREAMING' },
  );

  const next = upsertStreamingToolCall(previous, incoming);

  assert.equal(next.length, 2);
  assert.deepEqual(
    next.map((item) => item.assistantCall.toolCallId),
    ['task-1', 'task-2'],
  );
});

test('upsertStreamingToolCall updates same streaming row when tool_call_id matches', () => {
  const previous = [
    buildToolCall({}, { name: 'web-search', toolCallId: 'call-7', toolIndex: 7 }, { content: 'STREAMING' }),
  ];
  const incoming = buildToolCall(
    {},
    { name: 'web-search', toolCallId: 'call-7', toolIndex: 7, content: '{"q":"new"}' },
    { content: 'STREAMING' },
  );

  const next = upsertStreamingToolCall(previous, incoming);

  assert.equal(next.length, 1);
  assert.equal(next[0].assistantCall.content, '{"q":"new"}');
});

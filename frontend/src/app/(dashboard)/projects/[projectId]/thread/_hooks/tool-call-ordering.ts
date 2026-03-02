import type { ToolCallInput } from '@/components/thread/tool-call-side-panel';

const toEpoch = (value?: string): number => {
  if (!value) {
    return Number.POSITIVE_INFINITY;
  }
  const parsed = Date.parse(value);
  return Number.isNaN(parsed) ? Number.POSITIVE_INFINITY : parsed;
};

const hasToolIndex = (item: ToolCallInput): item is ToolCallInput & {
  assistantCall: ToolCallInput['assistantCall'] & { toolIndex: number };
} => typeof item.assistantCall.toolIndex === 'number';

export const sortToolCallsByExecutionOrder = (
  calls: ToolCallInput[],
): ToolCallInput[] => {
  return [...calls].sort((a, b) => {
    const aHasIndex = hasToolIndex(a);
    const bHasIndex = hasToolIndex(b);

    if (aHasIndex && bHasIndex && a.assistantCall.toolIndex !== b.assistantCall.toolIndex) {
      return a.assistantCall.toolIndex - b.assistantCall.toolIndex;
    }

    if (aHasIndex !== bHasIndex) {
      return aHasIndex ? -1 : 1;
    }

    const aTime = toEpoch(a.assistantCall.timestamp || a.toolResult?.timestamp);
    const bTime = toEpoch(b.assistantCall.timestamp || b.toolResult?.timestamp);
    if (aTime !== bTime) {
      return aTime - bTime;
    }

    return (a.assistantCall.toolCallId || '').localeCompare(
      b.assistantCall.toolCallId || '',
    );
  });
};

export const upsertStreamingToolCall = (
  previous: ToolCallInput[],
  incoming: ToolCallInput,
): ToolCallInput[] => {
  const existingStreamingIndex = previous.findIndex((item) => {
    if (item.toolResult?.content !== 'STREAMING') {
      return false;
    }

    if (incoming.assistantCall.toolCallId && item.assistantCall.toolCallId) {
      return item.assistantCall.toolCallId === incoming.assistantCall.toolCallId;
    }

    if (
      typeof incoming.assistantCall.toolIndex === 'number' &&
      typeof item.assistantCall.toolIndex === 'number'
    ) {
      return item.assistantCall.toolIndex === incoming.assistantCall.toolIndex;
    }

    return item.assistantCall.name === incoming.assistantCall.name;
  });

  if (existingStreamingIndex === -1) {
    return [...previous, incoming];
  }

  const next = [...previous];
  next[existingStreamingIndex] = incoming;
  return next;
};

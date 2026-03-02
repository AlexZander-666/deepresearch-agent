import { safeJsonParse } from '../../../../../../components/thread/utils';
import { extractToolName } from '../../../../../../components/thread/tool-views/xml-parser';

export interface AssistantToolCallInfo {
  toolName: string;
  toolCallId?: string;
}

const normalizeToolName = (name: string): string =>
  name.replace(/_/g, '-').toLowerCase();

const getFirstToolCall = (value: unknown) => {
  if (!value || typeof value !== 'object') {
    return null;
  }

  const maybeToolCalls = (value as any).tool_calls;
  if (!Array.isArray(maybeToolCalls) || maybeToolCalls.length === 0) {
    return null;
  }

  return maybeToolCalls[0] as {
    id?: string;
    function?: { name?: string };
    name?: string;
  };
};

const hasNullToolCallsInParsedObject = (value: unknown): boolean => {
  if (!value || typeof value !== 'object') {
    return false;
  }

  if ('tool_calls' in (value as any) && (value as any).tool_calls === null) {
    return true;
  }

  const nested = (value as any).content;
  if (typeof nested === 'string') {
    const nestedParsed = safeJsonParse<Record<string, any>>(nested, {});
    return hasNullToolCallsInParsedObject(nestedParsed);
  }

  if (nested && typeof nested === 'object') {
    return hasNullToolCallsInParsedObject(nested);
  }

  return false;
};

export const hasExplicitNullToolCalls = (content: string): boolean => {
  const parsed = safeJsonParse<Record<string, any>>(content, {});
  if (hasNullToolCallsInParsedObject(parsed)) {
    return true;
  }

  return (
    /"tool_calls"\s*:\s*null/i.test(content) ||
    /\\"tool_calls\\"\s*:\s*null/i.test(content)
  );
};

export const parseAssistantToolCallInfo = (
  content: string,
): AssistantToolCallInfo | null => {
  if (hasExplicitNullToolCalls(content)) {
    return null;
  }

  const assistantContentParsed = safeJsonParse<Record<string, any>>(content, {});
  const fromTopLevel = getFirstToolCall(assistantContentParsed);

  const nestedContentRaw = assistantContentParsed?.content;
  const nestedContentParsed =
    typeof nestedContentRaw === 'string'
      ? safeJsonParse<Record<string, any>>(nestedContentRaw, {})
      : nestedContentRaw;
  const fromNested = getFirstToolCall(nestedContentParsed);

  const firstToolCall = fromTopLevel || fromNested;
  if (firstToolCall) {
    const rawName = firstToolCall.function?.name || firstToolCall.name || 'unknown';
    return {
      toolName: normalizeToolName(rawName),
      toolCallId: firstToolCall.id,
    };
  }

  const candidates: string[] = [content];
  if (typeof nestedContentRaw === 'string') {
    candidates.push(nestedContentRaw);
  }

  for (const candidate of candidates) {
    const xmlToolName = extractToolName(candidate);
    if (xmlToolName) {
      return {
        toolName: normalizeToolName(xmlToolName),
      };
    }
  }

  return null;
};

import { UnifiedMessage } from '../_types';

interface MergeOptions {
  now?: number;
  localMessageGracePeriodMs?: number;
}

const DEFAULT_GRACE_PERIOD_MS = 60_000;

const parseTimestamp = (value: string | undefined): number => {
  if (!value) {
    return Number.NaN;
  }

  const parsed = Date.parse(value);
  return Number.isFinite(parsed) ? parsed : Number.NaN;
};

const isRecentMessage = (
  message: UnifiedMessage,
  now: number,
  gracePeriodMs: number,
): boolean => {
  const createdAt = parseTimestamp(message.created_at);
  if (!Number.isFinite(createdAt)) {
    return false;
  }

  return now - createdAt <= gracePeriodMs;
};

const shouldKeepLocalExtra = (
  message: UnifiedMessage,
  now: number,
  gracePeriodMs: number,
): boolean => {
  if (!message.message_id) {
    return true;
  }

  if (message.message_id.startsWith('temp-')) {
    return true;
  }

  return isRecentMessage(message, now, gracePeriodMs);
};

const shouldPreferLocalVersion = (
  serverMessage: UnifiedMessage,
  localMessage: UnifiedMessage,
  now: number,
  gracePeriodMs: number,
): boolean => {
  if (serverMessage.content === localMessage.content) {
    return false;
  }

  if (!isRecentMessage(localMessage, now, gracePeriodMs)) {
    return false;
  }

  const serverUpdatedAt = parseTimestamp(serverMessage.updated_at);
  const localUpdatedAt = parseTimestamp(localMessage.updated_at);

  if (!Number.isFinite(serverUpdatedAt) || !Number.isFinite(localUpdatedAt)) {
    return localMessage.content.length > serverMessage.content.length;
  }

  return localUpdatedAt > serverUpdatedAt;
};

const messageSortTime = (message: UnifiedMessage): number => {
  const createdAt = parseTimestamp(message.created_at);
  return Number.isFinite(createdAt) ? createdAt : 0;
};

export const mergeServerAndLocalMessages = (
  serverMessages: UnifiedMessage[],
  localMessages: UnifiedMessage[],
  options: MergeOptions = {},
): UnifiedMessage[] => {
  const now = options.now ?? Date.now();
  const gracePeriodMs =
    options.localMessageGracePeriodMs ?? DEFAULT_GRACE_PERIOD_MS;

  const mergedById = new Map<string, UnifiedMessage>();
  const localExtras: UnifiedMessage[] = [];

  for (const serverMessage of serverMessages) {
    if (serverMessage.message_id) {
      mergedById.set(serverMessage.message_id, serverMessage);
    } else {
      localExtras.push(serverMessage);
    }
  }

  for (const localMessage of localMessages) {
    const localId = localMessage.message_id;

    if (!localId) {
      localExtras.push(localMessage);
      continue;
    }

    const serverMessage = mergedById.get(localId);
    if (serverMessage) {
      if (shouldPreferLocalVersion(serverMessage, localMessage, now, gracePeriodMs)) {
        mergedById.set(localId, localMessage);
      }
      continue;
    }

    if (shouldKeepLocalExtra(localMessage, now, gracePeriodMs)) {
      localExtras.push(localMessage);
    }
  }

  const dedupedExtras = new Map<string, UnifiedMessage>();
  for (const extra of localExtras) {
    const key =
      extra.message_id ||
      `${extra.type}:${extra.created_at}:${extra.content}:${extra.metadata}`;
    if (!dedupedExtras.has(key)) {
      dedupedExtras.set(key, extra);
    }
  }

  return [...mergedById.values(), ...dedupedExtras.values()].sort(
    (a, b) => messageSortTime(a) - messageSortTime(b),
  );
};

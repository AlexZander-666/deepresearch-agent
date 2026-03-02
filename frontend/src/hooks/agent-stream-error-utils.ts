const getErrorMessage = (
  error: string | Error | null | undefined,
): string => {
  if (typeof error === 'string') {
    return error;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return '';
};

export const isAgentRunNotRunningError = (
  error: string | Error | null | undefined,
): boolean => {
  const message = getErrorMessage(error);

  if (!message) {
    return false;
  }

  const normalized = message.toLowerCase();
  return (
    normalized.includes('agent run') &&
    (normalized.includes('not running') ||
      normalized.includes('not in running state'))
  );
};

const RECOVERABLE_STREAM_ERROR_MARKERS = [
  'apiconnectionerror',
  'server disconnected',
  'connection reset',
  'connection aborted',
  'remote end closed connection',
  'temporarily unavailable',
  'connection timed out',
  'timeout reading from redis',
];

export const isRecoverableAgentStreamError = (
  error: string | Error | null | undefined,
): boolean => {
  const message = getErrorMessage(error);

  if (!message) {
    return false;
  }

  const normalized = message.toLowerCase();
  return RECOVERABLE_STREAM_ERROR_MARKERS.some((marker) =>
    normalized.includes(marker),
  );
};

const PROVIDER_ACCOUNT_ERROR_MARKERS = [
  'overdue-payment',
  'account is in good standing',
  'model-studio/error-code',
  'openaiexception - access denied',
];

export const isProviderAccountStreamError = (
  error: string | Error | null | undefined,
): boolean => {
  const message = getErrorMessage(error);
  if (!message) {
    return false;
  }

  const normalized = message.toLowerCase();
  return PROVIDER_ACCOUNT_ERROR_MARKERS.some((marker) =>
    normalized.includes(marker),
  );
};

export const toDisplayAgentStreamError = (
  error: string | Error | null | undefined,
): string => {
  const message = getErrorMessage(error);
  if (!message) {
    return 'Unknown stream error';
  }

  if (isProviderAccountStreamError(message)) {
    return 'Model provider rejected the request due to account status (for example overdue payment). Check DashScope/Qwen billing or switch provider credentials.';
  }

  return message;
};

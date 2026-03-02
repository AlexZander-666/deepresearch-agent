import { CLIENT_DEBUG_LOGS_ENABLED } from './env';

export const debugLog = (...args: unknown[]): void => {
  if (!CLIENT_DEBUG_LOGS_ENABLED) {
    return;
  }
  console.log(...args);
};

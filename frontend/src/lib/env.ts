const isWrappedWith = (value: string, wrapper: '"' | "'"): boolean =>
  value.startsWith(wrapper) && value.endsWith(wrapper) && value.length >= 2;

export const normalizePublicEnvValue = (
  value: string | null | undefined,
): string => {
  if (value == null) {
    return '';
  }

  let normalized = value.trim();

  while (isWrappedWith(normalized, '"') || isWrappedWith(normalized, "'")) {
    normalized = normalized.slice(1, -1).trim();
  }

  if (!normalized) {
    return '';
  }

  const lowered = normalized.toLowerCase();
  if (lowered === 'null' || lowered === 'undefined') {
    return '';
  }

  return normalized;
};

export const getPublicEnv = (
  key: keyof NodeJS.ProcessEnv,
  fallback = '',
  env: NodeJS.ProcessEnv = process.env,
): string => {
  const normalized = normalizePublicEnvValue(env[key]);
  return normalized || fallback;
};

export const DEFAULT_BACKEND_URL = 'http://localhost:8000/api';

export const isLocalEnvMode = (
  env: NodeJS.ProcessEnv = process.env,
): boolean => {
  const envMode = getPublicEnv('NEXT_PUBLIC_ENV_MODE', '', env).toLowerCase();
  return envMode === 'local' || envMode === 'development';
};

export const isClientDebugLoggingEnabled = (
  env: NodeJS.ProcessEnv = process.env,
): boolean => {
  return getPublicEnv('NEXT_PUBLIC_DEBUG_LOGS', '', env).toLowerCase() === 'true';
};

export const isTelemetryEnabled = (
  env: NodeJS.ProcessEnv = process.env,
): boolean => {
  const explicit = getPublicEnv('NEXT_PUBLIC_ENABLE_ANALYTICS', '', env).toLowerCase();
  if (explicit === 'true') {
    return true;
  }
  if (explicit === 'false') {
    return false;
  }
  return !isLocalEnvMode(env);
};

export const getBackendUrl = (
  env: NodeJS.ProcessEnv = process.env,
  fallback = DEFAULT_BACKEND_URL,
): string => {
  return getPublicEnv('NEXT_PUBLIC_BACKEND_URL', fallback, env);
};

type ServerBackendUrlOptions = {
  isDocker?: boolean;
  dockerHost?: string;
};

const LOOPBACK_HOST_SEGMENT = /:\/\/(localhost|127\.0\.0\.1)(?=[:/]|$)/i;

const rewriteLoopbackHost = (url: string, replacementHost: string): string => {
  if (!LOOPBACK_HOST_SEGMENT.test(url)) {
    return url;
  }

  return url.replace(LOOPBACK_HOST_SEGMENT, `://${replacementHost}`);
};

export const getServerBackendUrl = (
  env: NodeJS.ProcessEnv = process.env,
  options: ServerBackendUrlOptions = {},
  fallback = DEFAULT_BACKEND_URL,
): string => {
  const explicitServerBackendUrl = getPublicEnv('BACKEND_URL', '', env);
  const backendUrl = explicitServerBackendUrl || getBackendUrl(env, fallback);

  if (!options.isDocker) {
    return backendUrl;
  }

  const dockerHost = normalizePublicEnvValue(options.dockerHost) || 'host.docker.internal';
  return rewriteLoopbackHost(backendUrl, dockerHost);
};

export const BACKEND_URL = getBackendUrl();
export const POSTHOG_KEY = getPublicEnv('NEXT_PUBLIC_POSTHOG_KEY');
export const TOLT_REFERRAL_ID = getPublicEnv('NEXT_PUBLIC_TOLT_REFERRAL_ID');
export const CLIENT_DEBUG_LOGS_ENABLED = isClientDebugLoggingEnabled();

export type SessionExpiryInput = {
  expires_at?: number | string | null;
  expires_in?: number | string | null;
  access_token?: string | null;
};

const toFiniteNumber = (value: number | string | null | undefined): number | undefined => {
  if (value == null) {
    return undefined;
  }

  if (typeof value === 'number') {
    return Number.isFinite(value) ? value : undefined;
  }

  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : undefined;
};

const normalizeUnixSeconds = (value: number): number => {
  const rounded = Math.floor(value);
  if (rounded <= 0) {
    return 0;
  }

  // Defensive handling in case milliseconds accidentally get persisted.
  return rounded > 1_000_000_000_000 ? Math.floor(rounded / 1000) : rounded;
};

const decodeBase64Url = (value: string): string | undefined => {
  if (!value) {
    return undefined;
  }

  const normalized = value.replace(/-/g, '+').replace(/_/g, '/');
  const padLength = (4 - (normalized.length % 4)) % 4;
  const padded = normalized + '='.repeat(padLength);

  if (typeof atob === 'function') {
    return atob(padded);
  }

  if (typeof Buffer !== 'undefined') {
    return Buffer.from(padded, 'base64').toString('utf8');
  }

  return undefined;
};

export const decodeJwtExpUnixSeconds = (
  accessToken?: string | null,
): number | undefined => {
  if (!accessToken) {
    return undefined;
  }

  const tokenParts = accessToken.split('.');
  if (tokenParts.length < 2) {
    return undefined;
  }

  const payloadJson = decodeBase64Url(tokenParts[1]);
  if (!payloadJson) {
    return undefined;
  }

  try {
    const payload = JSON.parse(payloadJson) as { exp?: number | string };
    const exp = toFiniteNumber(payload.exp);
    if (!exp || exp <= 0) {
      return undefined;
    }
    return normalizeUnixSeconds(exp);
  } catch {
    return undefined;
  }
};

export const resolveSessionExpiryUnixSeconds = (
  input: SessionExpiryInput,
  nowUnixSeconds = Math.floor(Date.now() / 1000),
): number | undefined => {
  const expiresAt = toFiniteNumber(input.expires_at);
  if (expiresAt && expiresAt > 0) {
    return normalizeUnixSeconds(expiresAt);
  }

  const expiresIn = toFiniteNumber(input.expires_in);
  if (expiresIn && expiresIn > 0) {
    return normalizeUnixSeconds(nowUnixSeconds + expiresIn);
  }

  return decodeJwtExpUnixSeconds(input.access_token);
};

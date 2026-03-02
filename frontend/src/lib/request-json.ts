const PATH_KEYS = new Set([
  'path',
  'file_path',
  'filepath',
  'target_path',
  'targetpath',
  'directory_path',
  'directorypath',
  'cwd',
  'workdir',
]);

const TEXT_KEYS = new Set(['content', 'message', 'prompt', 'query', 'text']);

function normalizeSlashes(value: string): string {
  if (!value.includes('\\')) {
    return value;
  }

  let normalized = value.replace(/\\/g, '/');
  if (!normalized.startsWith('//')) {
    normalized = normalized.replace(/\/{2,}/g, '/');
  }
  return normalized;
}

function normalizeWindowsPathTokens(text: string): string {
  // Convert obvious Windows path segments (for example frontend\src\lib\api.ts) to POSIX separators.
  return text.replace(
    /([A-Za-z]:\\[^\s"'`<>]+|(?:[A-Za-z0-9._-]+\\){1,}[A-Za-z0-9._-]+)/g,
    (segment) => normalizeSlashes(segment),
  );
}

type Token = {
  value: string;
};

function tokenizeCommand(line: string): Token[] {
  const tokens: Token[] = [];
  let buffer = '';
  let quote: '"' | "'" | null = null;

  for (let i = 0; i < line.length; i += 1) {
    const char = line[i];

    if (quote) {
      if (char === quote) {
        quote = null;
      } else if (char === '\\' && i + 1 < line.length && line[i + 1] === quote) {
        buffer += quote;
        i += 1;
      } else {
        buffer += char;
      }
      continue;
    }

    if (char === '"' || char === "'") {
      quote = char;
      continue;
    }

    if (/\s/.test(char)) {
      if (buffer.length > 0) {
        tokens.push({ value: buffer });
        buffer = '';
      }
      continue;
    }

    buffer += char;
  }

  if (buffer.length > 0) {
    tokens.push({ value: buffer });
  }

  return tokens;
}

function quoteToken(value: string): string {
  if (!/[\s"'|&;()]/.test(value)) {
    return value;
  }
  return `"${value.replace(/\\/g, '\\\\').replace(/"/g, '\\"')}"`;
}

function isPathToken(token: string): boolean {
  if (!token) {
    return false;
  }
  return (
    token.includes('/') ||
    token.includes('\\') ||
    token === '.' ||
    token === '..' ||
    token.startsWith('./') ||
    token.startsWith('../')
  );
}

function canonicalPath(path: string): string {
  let normalized = normalizeSlashes(path);
  if (normalized.endsWith('/') && normalized.length > 1) {
    normalized = normalized.slice(0, -1);
  }
  return normalized;
}

function isSameOrParentPath(parent: string, child: string): boolean {
  if (parent === child) {
    return true;
  }
  return child.startsWith(`${parent}/`);
}

function dedupeRgSearchPaths(line: string): string {
  if (!line.trimStart().startsWith('rg ')) {
    return line;
  }

  const tokens = tokenizeCommand(line);
  if (tokens.length < 4 || tokens[0].value !== 'rg') {
    return line;
  }

  let patternIndex = 1;
  while (patternIndex < tokens.length && tokens[patternIndex].value.startsWith('-')) {
    patternIndex += 1;
  }

  if (patternIndex >= tokens.length - 2) {
    return line;
  }

  const trailingTokens = tokens.slice(patternIndex + 1);
  const pathEntries = trailingTokens
    .map((token, index) => ({
      index,
      original: token.value,
      normalized: canonicalPath(token.value),
      isPath: isPathToken(token.value),
    }))
    .filter((entry) => entry.isPath);

  if (pathEntries.length < 2) {
    return line;
  }

  const keepIndex = new Set<number>();
  for (const entry of pathEntries) {
    const redundant = pathEntries.some(
      (other) =>
        other.index !== entry.index &&
        isSameOrParentPath(other.normalized, entry.normalized),
    );
    if (!redundant) {
      keepIndex.add(entry.index);
    }
  }

  const rebuiltTrailing = trailingTokens
    .filter((token, index) => {
      if (!isPathToken(token.value)) {
        return true;
      }
      return keepIndex.has(index);
    })
    .map((token) => quoteToken(normalizeSlashes(token.value)));

  const rebuilt = [
    ...tokens.slice(0, patternIndex + 1).map((token) => quoteToken(token.value)),
    ...rebuiltTrailing,
  ].join(' ');

  return rebuilt;
}

export function normalizePathForRequest(path: string): string {
  return normalizeSlashes(path);
}

export function preprocessOutgoingText(text: string): string {
  return text
    .split('\n')
    .map((line) => normalizeWindowsPathTokens(dedupeRgSearchPaths(line)))
    .join('\n');
}

function sanitizeJsonValue(
  value: unknown,
  key: string | undefined,
  normalizeText: boolean,
): unknown {
  if (typeof value === 'string') {
    const keyName = key?.toLowerCase();
    if (keyName && PATH_KEYS.has(keyName)) {
      return normalizePathForRequest(value);
    }
    if (normalizeText && keyName && TEXT_KEYS.has(keyName)) {
      return preprocessOutgoingText(value);
    }
    return value;
  }

  if (Array.isArray(value)) {
    return value.map((item) => sanitizeJsonValue(item, undefined, normalizeText));
  }

  if (value && typeof value === 'object') {
    const result: Record<string, unknown> = {};
    for (const [entryKey, entryValue] of Object.entries(value)) {
      result[entryKey] = sanitizeJsonValue(entryValue, entryKey, normalizeText);
    }
    return result;
  }

  return value;
}

export function buildSafeJsonBody(
  payload: unknown,
  options?: { normalizeText?: boolean },
): string {
  return JSON.stringify(
    sanitizeJsonValue(payload, undefined, options?.normalizeText === true),
  );
}

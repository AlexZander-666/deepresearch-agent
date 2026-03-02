import assert from 'node:assert/strict';

import {
  buildSafeJsonBody,
  preprocessOutgoingText,
} from '../src/lib/request-json';

const serialized = buildSafeJsonBody({
  path: 'frontend/src\\lib\\api.ts',
  content:
    'rg -n -S "interface Model|type Model" frontend/src/lib/api.ts frontend/src',
}, { normalizeText: true });

const parsed = JSON.parse(serialized) as { path: string; content: string };

assert.equal(parsed.path, 'frontend/src/lib/api.ts');
assert.equal(
  parsed.content,
  'rg -n -S "interface Model|type Model" frontend/src',
);

const messageWithWindowsPath =
  'Found at frontend/src\\hooks\\react-query\\threads\\use-messages.ts';
assert.equal(
  preprocessOutgoingText(messageWithWindowsPath),
  'Found at frontend/src/hooks/react-query/threads/use-messages.ts',
);

const fileWriteBody = buildSafeJsonBody({
  path: 'workspace\\notes\\todo.txt',
  content: 'const regex = /\\w+\\\\.ts/;',
});
const parsedFileWriteBody = JSON.parse(fileWriteBody) as {
  path: string;
  content: string;
};
assert.equal(parsedFileWriteBody.path, 'workspace/notes/todo.txt');
assert.equal(parsedFileWriteBody.content, 'const regex = /\\w+\\\\.ts/;');

console.log('verify-json-request-safety: ok');

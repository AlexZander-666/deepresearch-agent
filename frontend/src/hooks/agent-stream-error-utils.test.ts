import assert from 'node:assert/strict';
import test from 'node:test';

import {
  isAgentRunNotRunningError,
  isProviderAccountStreamError,
  isRecoverableAgentStreamError,
  toDisplayAgentStreamError,
} from './agent-stream-error-utils';

test('matches not-running errors that include a run id', () => {
  assert.equal(
    isAgentRunNotRunningError(
      'Agent run 7d417baa-6b7b-45f5-ab9a-b82d1797fd6f is not running',
    ),
    true,
  );
});

test('matches not-running errors with terminal status details', () => {
  assert.equal(
    isAgentRunNotRunningError(
      'Agent run 7d417baa-6b7b-45f5-ab9a-b82d1797fd6f is not running (status: completed)',
    ),
    true,
  );
});

test('matches generic not-running phrasing', () => {
  assert.equal(
    isAgentRunNotRunningError(
      'Agent run 7d417baa-6b7b-45f5-ab9a-b82d1797fd6f is not in running state',
    ),
    true,
  );
});

test('does not match unrelated errors', () => {
  assert.equal(
    isAgentRunNotRunningError('Error getting agent status: Unauthorized (401)'),
    false,
  );
});

test('matches recoverable provider stream disconnect errors', () => {
  assert.equal(
    isRecoverableAgentStreamError(
      'litellm.APIConnectionError: Ollama_chatException - Server disconnected',
    ),
    true,
  );
});

test('does not match non-recoverable stream errors', () => {
  assert.equal(
    isRecoverableAgentStreamError('Function create_tasks is not found in the tools_dict.'),
    false,
  );
});

test('matches provider account stream errors from DashScope overdue payment', () => {
  assert.equal(
    isProviderAccountStreamError(
      'litellm.BadRequestError: OpenAIException - Access denied, please make sure your account is in good standing. For details, see: https://help.aliyun.com/zh/model-studio/error-code#overdue-payment',
    ),
    true,
  );
});

test('maps provider account stream errors to friendly guidance', () => {
  assert.equal(
    toDisplayAgentStreamError(
      'litellm.BadRequestError: OpenAIException - Access denied, please make sure your account is in good standing. For details, see: https://help.aliyun.com/zh/model-studio/error-code#overdue-payment',
    ),
    'Model provider rejected the request due to account status (for example overdue payment). Check DashScope/Qwen billing or switch provider credentials.',
  );
});

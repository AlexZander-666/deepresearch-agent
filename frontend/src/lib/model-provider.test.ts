import assert from 'node:assert/strict';
import test from 'node:test';

import {
  DEFAULT_MODEL_PROVIDER,
  DASHSCOPE_MODEL_ID,
  SILICONFLOW_SELECTOR_MODEL_ID,
  inferProviderFromModelId,
  normalizeModelIdForRequest,
  normalizeModelIdForSelection,
  normalizeModelProvider,
} from './model-provider';

test('normalizes all deepseek aliases to canonical selection model', () => {
  assert.equal(normalizeModelIdForSelection('deepseek-chat'), DASHSCOPE_MODEL_ID);
  assert.equal(
    normalizeModelIdForSelection('deepseek/deepseek-chat'),
    DASHSCOPE_MODEL_ID,
  );
  assert.equal(
    normalizeModelIdForSelection('deepseek-ai/DeepSeek-V3.2'),
    DASHSCOPE_MODEL_ID,
  );
  assert.equal(
    normalizeModelIdForSelection('openai/deepseek-ai/DeepSeek-V3.2'),
    DASHSCOPE_MODEL_ID,
  );
});

test('keeps canonical model name when explicit provider toggle is used', () => {
  assert.equal(
    normalizeModelIdForRequest(DASHSCOPE_MODEL_ID, 'siliconflow'),
    DASHSCOPE_MODEL_ID,
  );
});

test('preserves legacy siliconflow alias when provider toggle is absent', () => {
  assert.equal(
    normalizeModelIdForRequest(SILICONFLOW_SELECTOR_MODEL_ID),
    SILICONFLOW_SELECTOR_MODEL_ID,
  );
});

test('infers provider from legacy model ids for backward compatibility', () => {
  assert.equal(
    inferProviderFromModelId('deepseek-ai/DeepSeek-V3.2'),
    'siliconflow',
  );
  assert.equal(inferProviderFromModelId('deepseek-v3.2'), 'dashscope');
  assert.equal(inferProviderFromModelId('gpt-4o-mini'), null);
});

test('normalizes provider values safely', () => {
  assert.equal(normalizeModelProvider('DashScope'), 'dashscope');
  assert.equal(normalizeModelProvider('siliconflow'), 'siliconflow');
  assert.equal(normalizeModelProvider('unknown'), DEFAULT_MODEL_PROVIDER);
});

test('does not rewrite non-target deepseek models', () => {
  const customDeepSeekModel = 'openrouter/deepseek/deepseek-chat';
  assert.equal(
    normalizeModelIdForSelection(customDeepSeekModel),
    customDeepSeekModel,
  );
  assert.equal(
    normalizeModelIdForRequest(customDeepSeekModel, 'siliconflow'),
    customDeepSeekModel,
  );
});

export type ModelProvider = 'dashscope' | 'siliconflow';

export const DEFAULT_MODEL_PROVIDER: ModelProvider = 'dashscope';

export const DASHSCOPE_MODEL_ID = 'deepseek-v3.2';
export const SILICONFLOW_SELECTOR_MODEL_ID = 'deepseek-siliconflow';

const DASHSCOPE_MODEL_ALIASES = new Set([
  'deepseek-v3.2',
  'deepseek-chat',
  'deepseek/deepseek-chat',
  'openai/deepseek-v3.2',
]);

const SILICONFLOW_MODEL_ALIASES = new Set([
  'deepseek-siliconflow',
  'deepseek-v3.2-siliconflow',
  'deepseek-ai/DeepSeek-V3.2',
  'openai/deepseek-ai/DeepSeek-V3.2',
]);

const ALL_DEEPSEEK_ALIASES = new Set([
  ...DASHSCOPE_MODEL_ALIASES,
  ...SILICONFLOW_MODEL_ALIASES,
]);

const PROVIDER_TOGGLE_CANONICAL_TARGETS = new Set([
  'deepseek-v3.2',
  'deepseek-ai/deepseek-v3.2',
]);

const normalizeValue = (value: string): string => value.trim();

const appendProviderLabel = (baseLabel: string, provider: string): string => {
  if (baseLabel.includes('(DashScope)') || baseLabel.includes('(SiliconFlow)')) {
    return baseLabel;
  }
  return `${baseLabel} (${provider})`;
};

export const normalizeModelProvider = (
  modelProvider?: string | null,
): ModelProvider => {
  if (!modelProvider) {
    return DEFAULT_MODEL_PROVIDER;
  }

  const normalized = modelProvider.trim().toLowerCase();
  if (normalized === 'siliconflow') {
    return 'siliconflow';
  }
  if (normalized === 'dashscope') {
    return 'dashscope';
  }
  return DEFAULT_MODEL_PROVIDER;
};

export const inferProviderFromModelId = (
  modelId: string,
): ModelProvider | null => {
  const normalized = normalizeValue(modelId);
  if (SILICONFLOW_MODEL_ALIASES.has(normalized)) {
    return 'siliconflow';
  }
  if (DASHSCOPE_MODEL_ALIASES.has(normalized)) {
    return 'dashscope';
  }
  return null;
};

export const isDeepSeekModel = (modelId: string): boolean => {
  const normalized = normalizeValue(modelId);
  if (ALL_DEEPSEEK_ALIASES.has(normalized)) {
    return true;
  }
  const lower = normalized.toLowerCase();
  const modelWithoutProvider = lower.startsWith('openai/')
    ? lower.slice('openai/'.length)
    : lower;
  return PROVIDER_TOGGLE_CANONICAL_TARGETS.has(modelWithoutProvider);
};

export const normalizeModelIdForSelection = (modelId: string): string => {
  const normalized = normalizeValue(modelId);
  if (isDeepSeekModel(normalized)) {
    return DASHSCOPE_MODEL_ID;
  }
  return normalized;
};

export const normalizeModelIdForRequest = (
  modelId: string,
  modelProvider?: ModelProvider | string | null,
): string => {
  const normalized = normalizeValue(modelId);
  if (!normalized) {
    return normalized;
  }

  if (modelProvider && isDeepSeekModel(normalized)) {
    // With explicit provider toggle, keep canonical DeepSeek model id
    // and let backend route by `model_provider`.
    return DASHSCOPE_MODEL_ID;
  }

  if (SILICONFLOW_MODEL_ALIASES.has(normalized)) {
    return SILICONFLOW_SELECTOR_MODEL_ID;
  }
  if (DASHSCOPE_MODEL_ALIASES.has(normalized)) {
    return DASHSCOPE_MODEL_ID;
  }
  return normalized;
};

export const getProviderAwareModelLabel = (
  modelId: string,
  fallbackLabel?: string,
  modelProvider?: ModelProvider | string | null,
): string => {
  const normalizedModelId = normalizeValue(modelId);
  const baseLabel = fallbackLabel || 'DeepSeek V3.2';
  if (!isDeepSeekModel(normalizedModelId)) {
    return baseLabel;
  }

  const provider =
    modelProvider != null
      ? normalizeModelProvider(modelProvider)
      : inferProviderFromModelId(normalizedModelId) || DEFAULT_MODEL_PROVIDER;

  if (provider === 'siliconflow') {
    return appendProviderLabel(baseLabel, 'SiliconFlow');
  }
  return appendProviderLabel(baseLabel, 'DashScope');
};

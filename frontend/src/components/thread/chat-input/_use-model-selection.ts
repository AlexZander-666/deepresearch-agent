'use client';

import { useState, useEffect, useMemo } from 'react';
import { isLocalMode } from '@/lib/config';
import { useAvailableModels } from '@/hooks/react-query/subscriptions/use-model';
import {
  DEFAULT_MODEL_PROVIDER,
  DASHSCOPE_MODEL_ID,
  inferProviderFromModelId,
  isDeepSeekModel,
  normalizeModelIdForRequest,
  normalizeModelIdForSelection,
  normalizeModelProvider,
  type ModelProvider,
} from '@/lib/model-provider';

export const STORAGE_KEY_MODEL = 'suna-preferred-model-v3';
export const STORAGE_KEY_MODEL_PROVIDER = 'suna-model-provider-v1';
export const STORAGE_KEY_CUSTOM_MODELS = 'customModels';
// 统一默认模型为 deepseek-v3.2
export const DEFAULT_PREMIUM_MODEL_ID = DASHSCOPE_MODEL_ID;
export const DEFAULT_FREE_MODEL_ID = DASHSCOPE_MODEL_ID;

export type SubscriptionStatus = 'no_subscription' | 'active';

export interface ModelOption {
  id: string;
  label: string;
  requiresSubscription: boolean;
  description?: string;
  top?: boolean;
  isCustom?: boolean;
  priority?: number;
}

export interface CustomModel {
  id: string;
  label: string;
}

// SINGLE SOURCE OF TRUTH for all model data - aligned with backend constants
export const MODELS = {
  // 🎯 默认显示的三个主要模型
  // Local models (available in local mode only)
  'ollama': {
    tier: 'local',
    priority: 110,
    recommended: true,
    lowQuality: false,
    localOnly: true
  },
  // Premium OpenAI GPT-4o
  'gpt-4o': { 
    tier: 'premium', 
    priority: 105,
    recommended: true,
    lowQuality: false
  },
  // Free tier models (available to all users)
  [DASHSCOPE_MODEL_ID]: {
    tier: 'free',
    priority: 100, 
    recommended: true,
    lowQuality: false
  },

  // 🔽 其他模型暂时注释，不在默认列表中显示
  /*
  'claude-sonnet-4': { 
    tier: 'premium',
    priority: 99, 
    recommended: true,
    lowQuality: false
  },
  // OpenAI models
  'gpt-4o': {
    tier: 'premium',
    priority: 98,
    recommended: true,
    lowQuality: false
  },
  'gpt-4o-mini': {
    tier: 'free',
    priority: 95,
    recommended: false,
    lowQuality: false
  },
  'gpt-3.5-turbo': {
    tier: 'free',
    priority: 85,
    recommended: false,
    lowQuality: true
  },

  // 'gemini-flash-2.5': { 
  //   tier: 'free', 
  //   priority: 70,
  //   recommended: false,
  //   lowQuality: false
  // },
  // 'qwen3': { 
  //   tier: 'free', 
  //   priority: 60,
  //   recommended: false,
  //   lowQuality: false
  // },

  // Premium/Paid tier models (require subscription) - except specific free models
  'moonshotai/kimi-k2': { 
    tier: 'free', 
    priority: 96,
    recommended: false,
    lowQuality: false
  },
  'grok-4': { 
    tier: 'premium', 
    priority: 94,
    recommended: false,
    lowQuality: false
  },
  'sonnet-3.7': { 
    tier: 'premium', 
    priority: 93, 
    recommended: false,
    lowQuality: false
  },
  'google/gemini-2.5-pro': { 
    tier: 'premium', 
    priority: 96,
    recommended: false,
    lowQuality: false
  },
  'sonnet-3.5': { 
    tier: 'premium', 
    priority: 90,
    recommended: false,
    lowQuality: false
  },
  'gpt-5-mini': { 
    tier: 'premium', 
    priority: 98,
    recommended: false,
    lowQuality: false
  },
  'gemini-2.5-flash:thinking': { 
    tier: 'premium', 
    priority: 84,
    recommended: false,
    lowQuality: false
  },
  // 'deepseek/deepseek-chat-v3-0324': { 
  //   tier: 'free', 
  //   priority: 75,
  //   recommended: false,
  //   lowQuality: false
  // },
  */
};

// Helper to check if a user can access a model based on subscription status
export const canAccessModel = (
  subscriptionStatus: SubscriptionStatus,
  requiresSubscription: boolean,
): boolean => {
  return true;
};

// Helper to format a model name for display
export const formatModelName = (name: string): string => {
  return name
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
};

// Add openrouter/ prefix to custom models
export const getPrefixedModelId = (modelId: string, isCustom: boolean): string => {
  if (isCustom && !modelId.startsWith('openrouter/')) {
    return `openrouter/${modelId}`;
  }
  return modelId;
};

// Helper to get custom models from localStorage
export const getCustomModels = (): CustomModel[] => {
  if (!isLocalMode() || typeof window === 'undefined') return [];
  
  try {
    const storedModels = localStorage.getItem(STORAGE_KEY_CUSTOM_MODELS);
    if (!storedModels) return [];
    
    const parsedModels = JSON.parse(storedModels);
    if (!Array.isArray(parsedModels)) return [];
    
    return parsedModels
      .filter((model: any) => 
        model && typeof model === 'object' && 
        typeof model.id === 'string' && 
        typeof model.label === 'string');
  } catch (e) {
    console.error('Error parsing custom models:', e);
    return [];
  }
};

// Helper to save model preference to localStorage safely
const saveModelPreference = (modelId: string): void => {
  try {
    localStorage.setItem(STORAGE_KEY_MODEL, modelId);
  } catch (error) {
    console.warn('Failed to save model preference to localStorage:', error);
  }
};

const saveProviderPreference = (provider: ModelProvider): void => {
  try {
    localStorage.setItem(STORAGE_KEY_MODEL_PROVIDER, provider);
  } catch (error) {
    console.warn('Failed to save provider preference to localStorage:', error);
  }
};

export const useModelSelection = () => {
  const [selectedModel, setSelectedModel] = useState(DEFAULT_FREE_MODEL_ID);
  const [selectedProvider, setSelectedProvider] = useState<ModelProvider>(
    DEFAULT_MODEL_PROVIDER,
  );
  const [customModels, setCustomModels] = useState<CustomModel[]>([]);
  const [hasInitialized, setHasInitialized] = useState(false);

  const { data: modelsData, isLoading: isLoadingModels } = useAvailableModels({
    refetchOnMount: false,
  });

  const subscriptionStatus: SubscriptionStatus = 'active';

  // Function to refresh custom models from localStorage
  const refreshCustomModels = () => {
    if (isLocalMode() && typeof window !== 'undefined') {
      const freshCustomModels = getCustomModels();
      setCustomModels(freshCustomModels);
    }
  };

  // Load custom models from localStorage
  useEffect(() => {
    refreshCustomModels();
  }, []);

  // Generate model options list with consistent structure
  const MODEL_OPTIONS = useMemo(() => {
    let models = [];
    
    // 默认只显示 deepseek-v3.2，local 模式附加 ollama
    if (!modelsData?.models || isLoadingModels) {
      models = [
        // DeepSeek (免费)
        {
          id: DASHSCOPE_MODEL_ID,
          label: 'DeepSeek V3.2',
          requiresSubscription: false,
          priority: MODELS[DASHSCOPE_MODEL_ID]?.priority || 100,
          recommended: true
        },
      ];
      
      // Add ollama model in local mode
      if (isLocalMode()) {
        models.push({
          id: 'ollama',
          label: 'Ollama (Local)',
          requiresSubscription: false,
          priority: MODELS['ollama']?.priority || 110,
          localOnly: true,
          recommended: true
        });
      }
    } else {
      // 从API数据中筛选，只保留 deepseek 目标模型
      const targetModels = [
        DASHSCOPE_MODEL_ID,
        'deepseek-chat',
        'deepseek-ai/DeepSeek-V3.2',
        'openai/deepseek-ai/DeepSeek-V3.2',
      ]; // ollama将在本地模式下单独添加

      const modelMap = new Map<string, any>();
      modelsData.models
        .filter(model => {
          const shortName = model.short_name || model.id;
          return targetModels.includes(shortName);
        })
        .forEach(model => {
          const shortName = model.short_name || model.id;
          const normalizedShortName = normalizeModelIdForSelection(shortName);
          if (modelMap.has(normalizedShortName)) {
            return;
          }

          const displayName = model.display_name || shortName;
          let cleanLabel = displayName;
          if (cleanLabel.includes('/')) {
            cleanLabel = cleanLabel.split('/').pop() || cleanLabel;
          }

          cleanLabel = cleanLabel
            .replace(/-/g, ' ')
            .split(' ')
            .map(word => word.charAt(0).toUpperCase() + word.slice(1))
            .join(' ');

          if (isDeepSeekModel(normalizedShortName)) {
            cleanLabel = 'DeepSeek V3.2';
          }

          const modelData = MODELS[normalizedShortName] || {};
          const isPremium =
            model?.requires_subscription || modelData.tier === 'premium' || false;

          modelMap.set(normalizedShortName, {
            id: normalizedShortName,
            label: cleanLabel,
            requiresSubscription: isPremium,
            top: modelData.priority >= 90, // Mark high-priority models as "top"
            priority: modelData.priority || 0,
            lowQuality: modelData.lowQuality || false,
            recommended: modelData.recommended || false,
          });
        });

      models = Array.from(modelMap.values());
      
      // Always add ollama model in local mode (from API data scenario)
      if (isLocalMode()) {
        const ollamaExists = models.some(model => model.id === 'ollama');
        if (!ollamaExists) {
          models.push({
            id: 'ollama',
            label: 'Ollama (Local)',
            requiresSubscription: false,
            priority: MODELS['ollama']?.priority || 110,
            localOnly: true,
            recommended: true,
            top: true
          });
        }
      }
    }
    
    // Add custom models if in local mode
    if (isLocalMode() && customModels.length > 0) {
      const customModelOptions = customModels.map(model => ({
        id: model.id,
        label: model.label || formatModelName(model.id),
        requiresSubscription: false,
        top: false,
        isCustom: true,
        priority: 30, // Low priority by default
        lowQuality: false,
        recommended: false
      }));
      
      models = [...models, ...customModelOptions];
    }
    
    // Sort models consistently in one place:
    // 1. First by recommended (recommended first)
    // 2. Then by priority (higher first)
    // 3. Finally by name (alphabetical)
    const sortedModels = models.sort((a, b) => {
      // First by recommended status
      if (a.recommended !== b.recommended) {
        return a.recommended ? -1 : 1;
      }

      // Then by priority (higher first)
      if (a.priority !== b.priority) {
        return b.priority - a.priority;
      }
      
      // Finally by name
      return a.label.localeCompare(b.label);
    });
    return sortedModels;
  }, [modelsData, isLoadingModels, customModels]);

  // Get filtered list of models the user can access (no additional sorting)
  const availableModels = useMemo(() => {
    return isLocalMode() 
      ? MODEL_OPTIONS 
      : MODEL_OPTIONS.filter(model => 
          canAccessModel(subscriptionStatus, model.requiresSubscription)
        );
  }, [MODEL_OPTIONS, subscriptionStatus]);

  // Initialize selected model from localStorage ONLY ONCE
  useEffect(() => {
    if (typeof window === 'undefined' || hasInitialized) return;
    try {
      const savedModel = localStorage.getItem(STORAGE_KEY_MODEL);
      const savedProvider = localStorage.getItem(STORAGE_KEY_MODEL_PROVIDER);
      const storageProvider = savedProvider
        ? normalizeModelProvider(savedProvider)
        : null;
      const inferredProvider = savedModel
        ? inferProviderFromModelId(savedModel)
        : null;
      const initialProvider =
        inferredProvider || storageProvider || DEFAULT_MODEL_PROVIDER;

      setSelectedProvider(initialProvider);
      saveProviderPreference(initialProvider);

      // If we have a saved model, validate it's still available and accessible
      if (savedModel) {
        // Wait for models to load before validating
        if (isLoadingModels) {
          return;
        }

        const normalizedSavedModel = normalizeModelIdForSelection(savedModel);
        const modelOption = MODEL_OPTIONS.find(
          option => option.id === normalizedSavedModel,
        );
        const isCustomModel =
          isLocalMode() &&
          customModels.some(
            model =>
              model.id === normalizedSavedModel || model.id === savedModel,
          );
        
        // Check if saved model is still valid and accessible
        if (modelOption || isCustomModel) {
          const isAccessible = isLocalMode() || 
            canAccessModel(subscriptionStatus, modelOption?.requiresSubscription ?? false);
          
          if (isAccessible) {
            setSelectedModel(normalizedSavedModel);
            saveModelPreference(normalizedSavedModel);
            setHasInitialized(true);
            return;
          }
        }
      }
      
      // Fallback to default model
      // 🎯 在本地模式下优先选择ollama，否则根据订阅状态选择
      let defaultModel;
      if (isLocalMode()) {
        defaultModel = 'ollama';
      } else {
        defaultModel = subscriptionStatus === 'active' ? DEFAULT_PREMIUM_MODEL_ID : DEFAULT_FREE_MODEL_ID;
      }
      setSelectedModel(defaultModel);
      saveModelPreference(defaultModel);
      setHasInitialized(true);
      
    } catch (error) {
      console.warn('Failed to load preferences from localStorage:', error);
      // 🎯 在本地模式下优先选择ollama，否则根据订阅状态选择
      let defaultModel;
      if (isLocalMode()) {
        defaultModel = 'ollama';
      } else {
        defaultModel = subscriptionStatus === 'active' ? DEFAULT_PREMIUM_MODEL_ID : DEFAULT_FREE_MODEL_ID;
      }
      setSelectedModel(defaultModel);
      saveModelPreference(defaultModel);
      setSelectedProvider(DEFAULT_MODEL_PROVIDER);
      saveProviderPreference(DEFAULT_MODEL_PROVIDER);
      setHasInitialized(true);
    }
  }, [subscriptionStatus, MODEL_OPTIONS, isLoadingModels, customModels, hasInitialized]);

  // Handle model selection change
  const handleModelChange = (modelId: string) => {
    // Refresh custom models from localStorage to ensure we have the latest
    if (isLocalMode()) {
      refreshCustomModels();
    }
    
    // First check if it's a custom model in local mode
    const normalizedModelId = normalizeModelIdForSelection(modelId);
    const isCustomModel =
      isLocalMode() &&
      customModels.some(
        model => model.id === modelId || model.id === normalizedModelId,
      );
    
    // Then check if it's in standard MODEL_OPTIONS
    const modelOption = MODEL_OPTIONS.find(
      option => option.id === normalizedModelId,
    );
    
    // Check if model exists in either custom models or standard options
    if (!modelOption && !isCustomModel) {
      console.warn(
        'Model not found in options:',
        modelId,
        MODEL_OPTIONS,
        isCustomModel,
        customModels,
      );
      
      // Reset to default model when the selected model is not found
      const defaultModel = isLocalMode() ? DEFAULT_PREMIUM_MODEL_ID : DEFAULT_FREE_MODEL_ID;
      setSelectedModel(defaultModel);
      saveModelPreference(defaultModel);
      return;
    }

    // Check access permissions (except for custom models in local mode)
    if (!isCustomModel && !isLocalMode() && 
        !canAccessModel(subscriptionStatus, modelOption?.requiresSubscription ?? false)) {
      console.warn('Model not accessible:', modelId);
      return;
    }
    
    setSelectedModel(normalizedModelId);
    saveModelPreference(normalizedModelId);

    const inferredProvider = inferProviderFromModelId(modelId);
    if (inferredProvider) {
      setSelectedProvider(inferredProvider);
      saveProviderPreference(inferredProvider);
    }
  };

  const handleProviderChange = (provider: ModelProvider) => {
    const normalizedProvider = normalizeModelProvider(provider);
    setSelectedProvider(normalizedProvider);
    saveProviderPreference(normalizedProvider);
  };

  // Get the actual model ID to send to the backend
  const getActualModelId = (modelId: string): string => {
    // For ollama local model, always return "ollama" as the backend model name
    if (modelId === 'ollama') {
      return 'ollama';
    }
    
    return normalizeModelIdForRequest(modelId, selectedProvider);
  };

  return {
    selectedModel,
    setSelectedModel: (modelId: string) => {
      handleModelChange(modelId);
    },
    selectedProvider,
    setSelectedProvider: (provider: ModelProvider) => {
      handleProviderChange(provider);
    },
    subscriptionStatus: subscriptionStatus as SubscriptionStatus,
    availableModels,
    allModels: MODEL_OPTIONS,  // Already pre-sorted
    customModels,
    getActualModelId,
    refreshCustomModels,
    canAccessModel: (modelId: string) => {
      if (isLocalMode()) return true;
      const model = MODEL_OPTIONS.find(m => m.id === modelId);
      return model ? canAccessModel(subscriptionStatus, model.requiresSubscription) : false;
    },
    isSubscriptionRequired: (modelId: string) => {
      return MODEL_OPTIONS.find(m => m.id === modelId)?.requiresSubscription || false;
    }
  };
};

// Export the hook but not any sorting logic - sorting is handled internally

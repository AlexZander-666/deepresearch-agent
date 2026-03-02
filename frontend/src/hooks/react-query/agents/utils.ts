import { createClient } from "@/lib/supabase/client";
import { isFlagEnabled } from "@/lib/feature-flags";

const API_URL = process.env.NEXT_PUBLIC_BACKEND_URL || '';
const CUSTOM_AGENTS_DISABLED_ERROR = 'Custom agents is not enabled';

const emptyAgentsResponse = (params: AgentsParams): AgentsResponse => ({
  agents: [],
  pagination: {
    page: params.page ?? 1,
    limit: params.limit ?? 20,
    total: 0,
    pages: 0,
  },
});

const emptyAgentBuilderChatHistory = (): { messages: any[]; thread_id: string | null } => ({
  messages: [],
  thread_id: null,
});

const getErrorMessage = (value: unknown, depth = 0): string => {
  if (depth > 6 || value == null) return '';
  if (typeof value === 'string') return value;
  if (value instanceof Error) {
    const fromMessage = getErrorMessage(value.message, depth + 1);
    if (fromMessage) return fromMessage;
    const cause = (value as Error & { cause?: unknown }).cause;
    return getErrorMessage(cause, depth + 1);
  }
  if (Array.isArray(value)) {
    for (const item of value) {
      const nested = getErrorMessage(item, depth + 1);
      if (nested) return nested;
    }
    return '';
  }
  if (typeof value === 'object') {
    const record = value as Record<string, unknown>;
    const candidates = [
      record.message,
      record.detail,
      record.error,
      record.error_description,
      record.reason,
      record.msg,
    ];
    for (const candidate of candidates) {
      const nested = getErrorMessage(candidate, depth + 1);
      if (nested) return nested;
    }
  }
  return '';
};

const getHttpErrorMessage = (status: number, statusText: string, errorData: unknown): string =>
  getErrorMessage(errorData) || `HTTP ${status}: ${statusText}`;

const isCustomAgentsDisabledError = (value: unknown): boolean => {
  const message = getErrorMessage(value).toLowerCase();
  return message.includes('custom agents') && (message.includes('disabled') || message.includes('not enabled'));
};

export type Agent = {
  agent_id: string;
  account_id: string;
  name: string;
  description?: string;
  system_prompt: string;
  configured_mcps: Array<{
    name: string;
    config: Record<string, any>;
  }>;
  custom_mcps?: Array<{
    name: string;
    type: 'json' | 'sse';
    config: Record<string, any>;
    enabledTools: string[];
  }>;
  agentpress_tools: Record<string, any>;
  is_default: boolean;
  is_public?: boolean;
  marketplace_published_at?: string;
  download_count?: number;
  tags?: string[];
  created_at: string;
  updated_at: string;
  // New
  profile_image_url?: string;
  current_version_id?: string | null;
  version_count?: number;
  current_version?: AgentVersion | null;
  metadata?: {
    is_suna_default?: boolean;
    centrally_managed?: boolean;
    management_version?: string;
    restrictions?: {
      system_prompt_editable?: boolean;
      tools_editable?: boolean;
      name_editable?: boolean;
      description_editable?: boolean;
      mcps_editable?: boolean;
    };
    installation_date?: string;
    last_central_update?: string;
  };
};

export type PaginationInfo = {
  page: number;
  limit: number;
  total: number;
  pages: number;
};

export type AgentsResponse = {
  agents: Agent[];
  pagination: PaginationInfo;
};

export type AgentsParams = {
  page?: number;
  limit?: number;
  search?: string;
  sort_by?: string;
  sort_order?: string;
  has_default?: boolean;
  has_mcp_tools?: boolean;
  has_agentpress_tools?: boolean;
  tools?: string;
};

export type ThreadAgentResponse = {
  agent: Agent | null;
  source: 'thread' | 'default' | 'none' | 'missing';
  message: string;
};

export type AgentCreateRequest = {
  name: string;
  description?: string;
  system_prompt?: string;
  configured_mcps?: Array<{
    name: string;
    config: Record<string, any>;
  }>;
  custom_mcps?: Array<{
    name: string;
    type: 'json' | 'sse';
    config: Record<string, any>;
    enabledTools: string[];
  }>;
  agentpress_tools?: Record<string, any>;
  is_default?: boolean;
  // New
  profile_image_url?: string;
};

export type AgentVersionCreateRequest = {
  system_prompt: string;
  model?: string;  // Add model field
  configured_mcps?: Array<{
    name: string;
    config: Record<string, any>;
  }>;
  custom_mcps?: Array<{
    name: string;
    type: 'json' | 'sse';
    config: Record<string, any>;
    enabledTools: string[];
  }>;
  agentpress_tools?: Record<string, any>;
  version_name?: string;
  description?: string;
};

export type AgentVersion = {
  version_id: string;
  agent_id: string;
  version_number: number;
  version_name: string;
  system_prompt: string;
  model?: string;  // Add model field
  configured_mcps: Array<any>;
  custom_mcps: Array<any>;
  agentpress_tools: Record<string, any>;
  is_active: boolean;
  created_at: string;
  updated_at: string;
  created_by?: string;
  change_description?: string;
};

export type AgentUpdateRequest = {
  name?: string;
  description?: string;
  system_prompt?: string;
  configured_mcps?: Array<{
    name: string;
    config: Record<string, any>;
  }>;
  custom_mcps?: Array<{
    name: string;
    type: 'json' | 'sse';
    config: Record<string, any>;
    enabledTools: string[];
  }>;
  agentpress_tools?: Record<string, any>;
  is_default?: boolean;
  // New
  profile_image_url?: string;
};

export const getAgents = async (params: AgentsParams = {}): Promise<AgentsResponse> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      return emptyAgentsResponse(params);
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to get agents');
    }

    const queryParams = new URLSearchParams();
    if (params.page) queryParams.append('page', params.page.toString());
    if (params.limit) queryParams.append('limit', params.limit.toString());
    if (params.search) queryParams.append('search', params.search);
    if (params.sort_by) queryParams.append('sort_by', params.sort_by);
    if (params.sort_order) queryParams.append('sort_order', params.sort_order);
    if (params.has_default !== undefined) queryParams.append('has_default', params.has_default.toString());
    if (params.has_mcp_tools !== undefined) queryParams.append('has_mcp_tools', params.has_mcp_tools.toString());
    if (params.has_agentpress_tools !== undefined) queryParams.append('has_agentpress_tools', params.has_agentpress_tools.toString());
    if (params.tools) queryParams.append('tools', params.tools);

    const url = `${API_URL}/agents${queryParams.toString() ? `?${queryParams.toString()}` : ''}`;

    const response = await fetch(url, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      if (isCustomAgentsDisabledError(errorData)) {
        return emptyAgentsResponse(params);
      }
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const result = await response.json();
    return result;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      return emptyAgentsResponse(params);
    }
    console.error('Error fetching agents:', err);
    throw err;
  }
};

export const getAgent = async (agentId: string): Promise<Agent> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to get agent details');
    }

    const response = await fetch(`${API_URL}/agents/${agentId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const agent = await response.json();
    return agent;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error fetching agent:', err);
    throw err;
  }
};

export const createAgent = async (agentData: AgentCreateRequest): Promise<Agent> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to create an agent');
    }

    const response = await fetch(`${API_URL}/agents`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(agentData),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      const isAgentLimitError = (response.status === 402) && (
        errorData.error_code === 'AGENT_LIMIT_EXCEEDED' || 
        errorData.detail?.error_code === 'AGENT_LIMIT_EXCEEDED'
      );
      
      if (isAgentLimitError) {
        const { AgentCountLimitError } = await import('@/lib/api');
        const errorDetail = errorData.detail || errorData;
        throw new AgentCountLimitError(response.status, errorDetail);
      }
      
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const agent = await response.json();
    return agent;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error creating agent:', err);
    throw err;
  }
};

export const updateAgent = async (agentId: string, agentData: AgentUpdateRequest): Promise<Agent> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to update an agent');
    }

    const response = await fetch(`${API_URL}/agents/${agentId}`, {
      method: 'PUT',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(agentData),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const agent = await response.json();
    return agent;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error updating agent:', err);
    throw err;
  }
};

export const deleteAgent = async (agentId: string): Promise<void> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to delete an agent');
    }

    const response = await fetch(`${API_URL}/agents/${agentId}`, {
      method: 'DELETE',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error deleting agent:', err);
    throw err;
  }
};

export const getThreadAgent = async (threadId: string): Promise<ThreadAgentResponse> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      return {
        agent: null,
        source: 'none',
        message: CUSTOM_AGENTS_DISABLED_ERROR,
      };
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to get thread agent');
    }

    const response = await fetch(`${API_URL}/thread/${threadId}/agent`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      if (isCustomAgentsDisabledError(errorData)) {
        return {
          agent: null,
          source: 'none',
          message: CUSTOM_AGENTS_DISABLED_ERROR,
        };
      }
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const agent = await response.json();
    return agent;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      return {
        agent: null,
        source: 'none',
        message: CUSTOM_AGENTS_DISABLED_ERROR,
      };
    }
    console.error('Error fetching thread agent:', err);
    throw err;
  }
};

export const getAgentBuilderChatHistory = async (agentId: string): Promise<{messages: any[], thread_id: string | null}> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      return emptyAgentBuilderChatHistory();
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to get agent builder chat history');
    }

    const response = await fetch(`${API_URL}/agents/${agentId}/builder-chat-history`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      if (isCustomAgentsDisabledError(errorData)) {
        return emptyAgentBuilderChatHistory();
      }
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const data = await response.json();
    return data;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      return emptyAgentBuilderChatHistory();
    }
    console.error('Error fetching agent builder chat history:', err);
    throw err;
  }
};

// Agent Builder Chat Types
export type AgentBuilderMessage = {
  role: 'user' | 'assistant';
  content: string;
};

export type AgentBuilderConfig = {
  name?: string;
  description?: string;
  system_prompt?: string;
  agentpress_tools?: Record<string, { enabled: boolean; description: string }>;
  configured_mcps?: Array<{ name: string; qualifiedName: string; config: any; enabledTools?: string[] }>;
};

export type AgentBuilderChatRequest = {
  message: string;
  conversation_history: AgentBuilderMessage[];
  agent_id: string;
  partial_config?: AgentBuilderConfig;
};

export type AgentBuilderStreamData = {
  type: 'content' | 'config' | 'done' | 'error';
  content?: string;
  config?: AgentBuilderConfig;
  next_step?: string;
  error?: string;
};

export const startAgentBuilderChat = async (
  request: AgentBuilderChatRequest,
  onData: (data: AgentBuilderStreamData) => void,
  onComplete: () => void,
  signal?: AbortSignal
): Promise<void> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to use the agent builder');
    }

    const response = await fetch(`${API_URL}/agents/builder/chat/${request.agent_id}`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        message: request.message,
        conversation_history: request.conversation_history,
        partial_config: request.partial_config
      }),
      signal,
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const reader = response.body?.getReader();
    const decoder = new TextDecoder();

    if (!reader) {
      throw new Error('No response body');
    }

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      const chunk = decoder.decode(value);
      const lines = chunk.split('\n');

      for (const line of lines) {
        if (line.startsWith('data: ')) {
          try {
            const data = JSON.parse(line.slice(6));
            onData(data);
            
            if (data.type === 'done') {
              onComplete();
              return;
            }
          } catch (e) {
            console.error('Error parsing SSE data:', e);
          }
        }
      }
    }
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error in agent builder chat:', err);
    throw err;
  }
};

export const getAgentVersions = async (agentId: string): Promise<AgentVersion[]> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      return [];
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to get agent versions');
    }

    const response = await fetch(`${API_URL}/agents/${agentId}/versions`, {
      headers: {
        'Authorization': `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      if (isCustomAgentsDisabledError(errorData)) {
        return [];
      }
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const versions = await response.json();
    return versions;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      return [];
    }
    console.error('Error fetching agent versions:', err);
    throw err;
  }
};

export const createAgentVersion = async (
  agentId: string,
  data: AgentVersionCreateRequest
): Promise<AgentVersion> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to create agent version');
    }

    const response = await fetch(`${API_URL}/agents/${agentId}/versions`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        'Authorization': `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(data),
    });

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const version = await response.json();
    return version;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error creating agent version:', err);
    throw err;
  }
};

export const activateAgentVersion = async (
  agentId: string,
  versionId: string
): Promise<void> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to activate agent version');
    }

    const response = await fetch(
      `${API_URL}/agents/${agentId}/versions/${versionId}/activate`,
      {
        method: 'PUT',
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
        },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error activating agent version:', err);
    throw err;
  }
};

export const getAgentVersion = async (
  agentId: string,
  versionId: string
): Promise<AgentVersion> => {
  try {
    const agentPlaygroundEnabled = await isFlagEnabled('custom_agents');
    if (!agentPlaygroundEnabled) {
      throw new Error('Custom agents is not enabled');
    }
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session) {
      throw new Error('You must be logged in to get agent version');
    }

    const response = await fetch(
      `${API_URL}/agents/${agentId}/versions/${versionId}`,
      {
        headers: {
          'Authorization': `Bearer ${session.access_token}`,
        },
      }
    );

    if (!response.ok) {
      const errorData = await response.json().catch(() => ({ message: 'Unknown error' }));
      throw new Error(getHttpErrorMessage(response.status, response.statusText, errorData));
    }

    const version = await response.json();
    return version;
  } catch (err) {
    if (isCustomAgentsDisabledError(err)) {
      throw new Error(CUSTOM_AGENTS_DISABLED_ERROR);
    }
    console.error('Error fetching agent version:', err);
    throw err;
  }
};
  

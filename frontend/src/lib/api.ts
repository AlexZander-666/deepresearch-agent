import { createClient } from '@/lib/supabase/client';
import { handleApiError } from './error-handler';
import posthog from 'posthog-js';
import { BACKEND_URL } from './env';

// Get backend URL from environment variables
const API_URL = BACKEND_URL;

// Set to keep track of agent runs that are known to be non-running
const nonRunningAgentRuns = new Set<string>();
// Map to keep track of active EventSource streams
const activeStreams = new Map<string, EventSource>();

// Custom error for billing issues
export class BillingError extends Error {
  status: number;
  detail: { message: string; [key: string]: any }; // Allow other properties in detail

  constructor(
    status: number,
    detail: { message: string; [key: string]: any },
    message?: string,
  ) {
    super(message || detail.message || `Billing Error: ${status}`);
    this.name = 'BillingError';
    this.status = status;
    this.detail = detail;

    // Set the prototype explicitly.
    Object.setPrototypeOf(this, BillingError.prototype);
  }
}

// Custom error for agent run limit exceeded
export class AgentRunLimitError extends Error {
  status: number;
  detail: { 
    message: string;
    running_thread_ids: string[];
    running_count: number;
  };

  constructor(
    status: number,
    detail: { 
      message: string;
      running_thread_ids: string[];
      running_count: number;
      [key: string]: any;
    },
    message?: string,
  ) {
    super(message || detail.message || `Agent Run Limit Exceeded: ${status}`);
    this.name = 'AgentRunLimitError';
    this.status = status;
    this.detail = detail;

    // Set the prototype explicitly.
    Object.setPrototypeOf(this, AgentRunLimitError.prototype);
  }
}

export class AgentCountLimitError extends Error {
  status: number;
  detail: { 
    message: string;
    current_count: number;
    limit: number;
    tier_name: string;
    error_code: string;
  };

  constructor(
    status: number,
    detail: { 
      message: string;
      current_count: number;
      limit: number;
      tier_name: string;
      error_code: string;
      [key: string]: any;
    },
    message?: string,
  ) {
    super(message || detail.message || `Agent Count Limit Exceeded: ${status}`);
    this.name = 'AgentCountLimitError';
    this.status = status;
    this.detail = detail;
    Object.setPrototypeOf(this, AgentCountLimitError.prototype);
  }
}

export class NoAccessTokenAvailableError extends Error {
  constructor(message?: string, options?: { cause?: Error }) {
    super(message || 'No access token available', options);
  }
  name = 'NoAccessTokenAvailableError';
}

// Type Definitions (moved from potential separate file for clarity)
export type Project = {
  id: string;
  name: string;
  description: string;
  account_id: string;
  created_at: string;
  updated_at?: string;
  sandbox: {
    vnc_preview?: string;
    sandbox_url?: string;
    id?: string;
    pass?: string;
  };
  is_public?: boolean; // Flag to indicate if the project is public
  [key: string]: any; // Allow additional properties to handle database fields
};

export type Thread = {
  thread_id?: string; // 原有格式
  id?: string; // 新后端格式
  account_id: string | null;
  project_id?: string | null;
  name?: string | null; // 后端返回的name字段
  status?: string; // 后端返回的status字段
  metadata?: any; // 元数据
  is_public?: boolean;
  created_at: string;
  updated_at: string;
  [key: string]: any; // Allow additional properties to handle database fields
};

export type Message = {
  role: string;
  content: string;
  type: string;
  agent_id?: string;
  agents?: {
    name: string;
    avatar?: string;
    avatar_color?: string;
    profile_image_url?: string;
  };
};

export type AgentRun = {
  id: string;
  thread_id: string;
  status: 'running' | 'completed' | 'stopped' | 'error';
  started_at: string;
  completed_at: string | null;
  responses: Message[];
  error: string | null;
};

export type ToolCall = {
  name: string;
  arguments: Record<string, unknown>;
};

export interface InitiateAgentResponse {
  thread_id: string;
  agent_run_id: string;
}

export interface HealthCheckResponse {
  status: string;
  timestamp: string;
  instance_id: string;
}

export interface FileInfo {
  name: string;
  path: string;
  is_dir: boolean;
  size: number;
  mod_time: string;
  permissions?: string;
}

export type WorkflowExecution = {
  id: string;
  workflow_id: string;
  workflow_name: string;
  status: 'pending' | 'running' | 'completed' | 'failed' | 'cancelled';
  started_at: string | null;
  completed_at: string | null;
  result: any;
  error: string | null;
};

export type WorkflowExecutionLog = {
  id: string;
  execution_id: string;
  node_id: string;
  node_name: string;
  node_type: string;
  started_at: string;
  completed_at: string | null;
  status: 'running' | 'completed' | 'failed';
  input_data: any;
  output_data: any;
  error: string | null;
};

// Workflow Types
export type Workflow = {
  id: string;
  name: string;
  description: string;
  status: 'draft' | 'active' | 'paused' | 'disabled' | 'archived';
  project_id: string;
  account_id: string;
  definition: {
    name: string;
    description: string;
    nodes: any[];
    edges: any[];
    variables?: Record<string, any>;
  };
  created_at: string;
  updated_at: string;
};

export type WorkflowNode = {
  id: string;
  type: string;
  position: { x: number; y: number };
  data: any;
};

export type WorkflowEdge = {
  id: string;
  source: string;
  target: string;
  sourceHandle?: string;
  targetHandle?: string;
};

// Project APIs
export const getProjects = async (): Promise<Project[]> => {
  try {
    const supabase = createClient();

    // Get the current user's ID to filter projects
    const { data: userData, error: userError } = await supabase.auth.getUser();
    if (userError) {
      console.error('Error getting current user:', userError);
      return [];
    }

    // If no user is logged in, return an empty array
    if (!userData.user) {
      return [];
    }

    // Query only projects where account_id matches the current user's ID
    const { data, error } = await supabase
      .from('projects')
      .select('*')
      .eq('account_id', userData.user.id);

    if (error) {
      // Handle permission errors specifically
      if (
        error.code === '42501' &&
        error.message.includes('has_role_on_account')
      ) {
        console.error(
          'Permission error: User does not have proper account access',
        );
        return []; // Return empty array instead of throwing
      }
      throw error;
    }

    // Map database fields to our Project type
    const mappedProjects: Project[] = (data || []).map((project) => ({
      id: project.project_id,
      name: project.name || '',
      description: project.description || '',
      account_id: project.account_id,
      created_at: project.created_at,
      updated_at: project.updated_at,
      sandbox: (() => {
        // Handle sandbox as JSON string from API
        if (typeof project.sandbox === 'string') {
          try {
            return JSON.parse(project.sandbox);
          } catch (e) {
            console.warn('Failed to parse sandbox JSON string:', project.sandbox);
            return {
              id: '',
              pass: '',
              vnc_preview: '',
              sandbox_url: '',
            };
          }
        }
        // Handle sandbox as object (fallback)
        return project.sandbox || {
          id: '',
          pass: '',
          vnc_preview: '',
          sandbox_url: '',
        };
      })(),
    }));

    return mappedProjects;
  } catch (err) {
    console.error('Error fetching projects:', err);
    handleApiError(err, { operation: 'load projects', resource: 'projects' });
    // Return empty array for permission errors to avoid crashing the UI
    return [];
  }
};

// 专门用于侧边栏的项目获取函数
export const getSidebarProjects = async (): Promise<Project[]> => {
  try {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    const response = await fetch(`${API_URL}/sidebar/projects`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Failed to fetch sidebar projects:', response.status, errorText);
      return []; // Return empty array for errors to avoid crashing the UI
    }

    const data = await response.json();
    // 确保返回的是数组格式
    if (Array.isArray(data)) {
      return data;
    } else {
      console.warn('Backend returned non-array data for sidebar projects:', data);
      return [];
    }
  } catch (err) {
    console.error('Error fetching sidebar projects:', err);
    if (err instanceof NoAccessTokenAvailableError) {
      return [];
    }
    handleApiError(err, { operation: 'load sidebar projects', resource: 'sidebar projects' });
    // Return empty array for permission errors to avoid crashing the UI
    return [];
  }
};

export const getProject = async (projectId: string): Promise<Project> => {
  const supabase = createClient();

  try {
    const { data, error } = await supabase
      .from('projects')
      .select('*')
      .eq('project_id', projectId)
      .single();

    if (error) {
      // Handle the specific "no rows returned" error from Supabase
      if (error.code === 'PGRST116') {
        throw new Error(`Project not found or not accessible: ${projectId}`);
      }
      throw error;
    }

    // If project has a sandbox, ensure it's started
    if (data.sandbox?.id) {
      // Fire off sandbox activation without blocking
      const ensureSandboxActive = async () => {
        try {
          const {
            data: { session },
          } = await supabase.auth.getSession();

          // For public projects, we don't need authentication
          const headers: Record<string, string> = {
            'Content-Type': 'application/json',
          };

          if (session?.access_token) {
            headers['Authorization'] = `Bearer ${session.access_token}`;
          }

          const response = await fetch(
            `${API_URL}/project/${projectId}/sandbox/ensure-active`,
            {
              method: 'POST',
              headers,
            },
          );

          if (!response.ok) {
            const errorText = await response
              .text()
              .catch(() => 'No error details available');
            console.warn(
              `Failed to ensure sandbox is active: ${response.status} ${response.statusText}`,
              errorText,
            );
          }
        } catch (sandboxError) {
          console.warn('Failed to ensure sandbox is active:', sandboxError);
        }
      };

      // Start the sandbox activation without awaiting
      ensureSandboxActive();
    }

    // Map database fields to our Project type
    const mappedProject: Project = {
      id: data.project_id,
      name: data.name || '',
      description: data.description || '',
      account_id: data.account_id,
      is_public: data.is_public || false,
      created_at: data.created_at,
      sandbox: (() => {
        // Handle sandbox as JSON string from API
        if (typeof data.sandbox === 'string') {
          try {
            return JSON.parse(data.sandbox);
          } catch (e) {
            console.warn('Failed to parse sandbox JSON string:', data.sandbox);
            return {
              id: '',
              pass: '',
              vnc_preview: '',
              sandbox_url: '',
            };
          }
        }
        // Handle sandbox as object (fallback)
        return data.sandbox || {
          id: '',
          pass: '',
          vnc_preview: '',
          sandbox_url: '',
        };
      })(),
    };

    return mappedProject;
  } catch (error) {
    console.error(`Error fetching project ${projectId}:`, error);
    handleApiError(error, { operation: 'load project', resource: `project ${projectId}` });
    throw error;
  }
};

export const createProject = async (
  projectData: { name: string; description: string },
  accountId?: string,
): Promise<Project> => {
  const supabase = createClient();

  // If accountId is not provided, we'll need to get the user's ID
  if (!accountId) {
    const { data: userData, error: userError } = await supabase.auth.getUser();

    if (userError) throw userError;
    if (!userData.user)
      throw new Error('You must be logged in to create a project');

    // In Basejump, the personal account ID is the same as the user ID
    accountId = userData.user.id;
  }

  const { data, error } = await supabase
    .from('projects')
    .insert({
      name: projectData.name,
      description: projectData.description || null,
      account_id: accountId,
    })
    .select()
    .single();

  if (error) {
    handleApiError(error, { operation: 'create project', resource: 'project' });
    throw error;
  }

  const project = {
    id: data.project_id,
    name: data.name,
    description: data.description || '',
    account_id: data.account_id,
    created_at: data.created_at,
    sandbox: { id: '', pass: '', vnc_preview: '' },
  };
  return project;
};

export const updateProject = async (
  projectId: string,
  data: Partial<Project>,
): Promise<Project> => {
  const supabase = createClient();

  // Sanity check to avoid update errors
  if (!projectId || projectId === '') {
    console.error('Attempted to update project with invalid ID:', projectId);
    throw new Error('Cannot update project: Invalid project ID');
  }

  const { data: updatedData, error } = await supabase
    .from('projects')
    .update(data)
    .eq('project_id', projectId)
    .select()
    .single();

  if (error) {
    console.error('Error updating project:', error);
    handleApiError(error, { operation: 'update project', resource: `project ${projectId}` });
    throw error;
  }

  if (!updatedData) {
    const noDataError = new Error('No data returned from update');
    handleApiError(noDataError, { operation: 'update project', resource: `project ${projectId}` });
    throw noDataError;
  }

  // Dispatch a custom event to notify components about the project change
  if (typeof window !== 'undefined') {
    window.dispatchEvent(
      new CustomEvent('project-updated', {
        detail: {
          projectId,
          updatedData: {
            id: updatedData.project_id,
            name: updatedData.name,
            description: updatedData.description,
          },
        },
      }),
    );
  }

  // Return formatted project data - use same mapping as getProject
  const project = {
    id: updatedData.project_id,
    name: updatedData.name,
    description: updatedData.description || '',
    account_id: updatedData.account_id,
    created_at: updatedData.created_at,
    sandbox: updatedData.sandbox || {
      id: '',
      pass: '',
      vnc_preview: '',
      sandbox_url: '',
    },
  };
  return project;
};

export const deleteProject = async (projectId: string): Promise<void> => {
  const supabase = createClient();
  const { error } = await supabase
    .from('projects')
    .delete()
    .eq('project_id', projectId);

  if (error) {
    handleApiError(error, { operation: 'delete project', resource: `project ${projectId}` });
    throw error;
  }
};

// Thread APIs
export const getThreads = async (projectId?: string): Promise<Thread[]> => {
  const supabase = createClient();

  // Get the current user's ID to filter threads
  const { data: userData, error: userError } = await supabase.auth.getUser();
  if (userError) {
    console.error('Error getting current user:', userError);
    return [];
  }

  // If no user is logged in, return an empty array
  if (!userData.user) {
    return [];
  }

  let query = supabase.from('threads').select('*');

  // Always filter by the current user's account ID
  query = query.eq('account_id', userData.user.id);

  if (projectId) {
    query = query.eq('project_id', projectId);
  }

  const { data, error } = await query;

  if (error) {
    handleApiError(error, { operation: 'load threads', resource: projectId ? `threads for project ${projectId}` : 'threads' });
    throw error;
  }

  const mappedThreads: Thread[] = (data || [])
    .filter((thread) => {
      const metadata = thread.metadata || {};
      return !metadata.is_agent_builder;
    })
    .map((thread) => ({
      thread_id: thread.thread_id,
      account_id: thread.account_id,
      project_id: thread.project_id,
      created_at: thread.created_at,
      updated_at: thread.updated_at,
      metadata: thread.metadata,
    }));
  return mappedThreads;
};

// 专门用于侧边栏的线程获取函数
export const getSidebarThreads = async (projectId?: string): Promise<Thread[]> => {
  try {
    const supabase = createClient();
    const { data: { session } } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    const url = new URL(`${API_URL}/sidebar/threads`);
    if (projectId) {
      url.searchParams.append('project_id', projectId);
    }

    const response = await fetch(url.toString(), {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response.text();
      console.error('Failed to fetch sidebar threads:', response.status, errorText);
      return [];
    }

    const data = await response.json();
    // 确保返回的是数组格式
    if (Array.isArray(data)) {
      return data;
    } else {
      console.warn('Backend returned non-array data for sidebar threads:', data);
      return [];
    }
  } catch (error) {
    console.error('Error getting sidebar threads:', error);
    if (error instanceof NoAccessTokenAvailableError) {
      return [];
    }
    handleApiError(error, { operation: 'load sidebar threads', resource: projectId ? `sidebar threads for project ${projectId}` : 'sidebar threads' });
    return [];
  }
};

export const getThread = async (threadId: string): Promise<Thread> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    const response = await fetch(`${API_URL}/threads/${threadId}`, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(
        `Error getting thread: ${response.statusText} (${response.status})`,
      );
    }

    const data = await response.json();
    return data;
  } catch (error) {
    handleApiError(error, { operation: 'load thread', resource: `thread ${threadId}` });
    throw error;
  }
};

export const createThread = async (projectId: string): Promise<Thread> => {
  const supabase = createClient();

  // If user is not logged in, redirect to login
  const {
    data: { user },
  } = await supabase.auth.getUser();
  if (!user) {
    throw new Error('You must be logged in to create a thread');
  }

  const { data, error } = await supabase
    .from('threads')
    .insert({
      project_id: projectId,
      account_id: user.id, // Use the current user's ID as the account ID
    })
    .select()
    .single();

  if (error) {
    handleApiError(error, { operation: 'create thread', resource: 'thread' });
    throw error;
  }
  return data;
};

export const addUserMessage = async (
  threadId: string,
  content: string,
): Promise<void> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    // Call backend API to add user message
    const response = await fetch(`${API_URL}/threads/${threadId}/messages`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify({
        content: content,
        type: 'user'
      }),
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(
        `Error adding user message: ${response.statusText} (${response.status})`,
      );
    }

    console.log('✅ [addUserMessage] User message sent to backend successfully');
  } catch (error: any) {
    console.error('❌ [addUserMessage] Error adding user message:', error);
    handleApiError(error, { operation: 'add message', resource: 'message' });
    throw error;
  }
};

export const getMessages = async (threadId: string): Promise<Message[]> => {
  try {
    console.log('🚀 [getMessages] API调用开始:', {
      threadId,
      API_URL,
      timestamp: new Date().toISOString()
    });
    
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    const apiUrl = `${API_URL}/threads/${threadId}/messages`;
    console.log('🌐 [getMessages] 调用API URL:', apiUrl);

    const response = await fetch(apiUrl, {
      method: 'GET',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(
        `Error getting messages: ${response.statusText} (${response.status})`,
      );
    }

    const data = await response.json();
    console.log('📡 [getMessages] API响应数据:', {
      status: response.status,
      statusText: response.statusText,
      responseType: typeof data,
      isArray: Array.isArray(data),
      dataKeys: data ? Object.keys(data) : null,
      data: JSON.stringify(data, null, 2)
    });
    
    let messages: any[] = [];
    
    // 提取消息数组
    if (Array.isArray(data)) {
      messages = data;
      console.log('📨 [getMessages] 使用直接数组格式');
    } else if (data && Array.isArray(data.messages)) {
      messages = data.messages;
      console.log('📨 [getMessages] 使用data.messages格式');
    } else if (data && Array.isArray(data.data)) {
      messages = data.data;
      console.log('📨 [getMessages] 使用data.data格式');
    } else {
      console.warn('Messages API returned unexpected format:', data);
      return [];
    }
    
    console.log('📊 [getMessages] 提取的消息统计:', {
      totalCount: messages.length,
      messageTypes: messages.reduce((acc: any, msg: any) => {
        acc[msg.type] = (acc[msg.type] || 0) + 1;
        return acc;
      }, {}),
      toolMessages: messages.filter((msg: any) => msg.type === 'tool').length
    });
    
    // 映射后端数据格式到前端期望的格式
    const mappedMessages = messages.map((msg: any) => ({
      message_id: msg.message_id || msg.id,
      thread_id: msg.thread_id,
      type: msg.type, // 'user' | 'assistant' 等
      role: msg.type, // 添加role字段
      is_llm_message: msg.is_llm_message || false,
      content: typeof msg.content === 'string' ? msg.content : JSON.stringify(msg.content),
      metadata: msg.metadata ? (typeof msg.metadata === 'string' ? msg.metadata : JSON.stringify(msg.metadata)) : '{}',
      created_at: msg.created_at,
      updated_at: msg.updated_at || msg.created_at, // 如果没有updated_at，使用created_at
      agent_id: msg.agent_id,
      agent_version_id: msg.agent_version_id,
      agents: msg.agents,
      author: msg.author, // 保留原有字段
      event_id: msg.event_id, // 保留原有字段
    }));
    
    console.log('🔍 [getMessages] 原始数据:', messages);
    console.log('🔍 [getMessages] 映射后数据:', mappedMessages);
    
    return mappedMessages;
  } catch (error) {
    handleApiError(error, { operation: 'load messages', resource: `messages for thread ${threadId}` });
    throw error;
  }
};

export const getSharedThread = async (threadId: string): Promise<Thread> => {
  const supabase = createClient();

  const { data, error } = await supabase
    .from('threads')
    .select('*')
    .eq('thread_id', threadId)
    .eq('is_public', true)
    .single();

  if (error || !data) {
    if (error?.code === 'PGRST116') {
      throw new Error('Shared conversation not found or is private');
    }
    throw new Error(error?.message || 'Failed to load shared conversation');
  }

  return {
    ...data,
    id: data.thread_id,
    thread_id: data.thread_id,
  };
};

export const getSharedMessages = async (threadId: string): Promise<Message[]> => {
  const supabase = createClient();

  const { data, error } = await supabase
    .from('messages')
    .select('*')
    .eq('thread_id', threadId)
    .order('created_at', { ascending: true });

  if (error) {
    throw new Error(`Failed to load shared messages: ${error.message}`);
  }

  const messages = Array.isArray(data) ? data : [];

  return messages.map((msg: any) => ({
    message_id: msg.message_id || msg.id,
    thread_id: msg.thread_id,
    type: msg.type,
    role: msg.type,
    is_llm_message: msg.is_llm_message || false,
    content:
      typeof msg.content === 'string'
        ? msg.content
        : JSON.stringify(msg.content),
    metadata: msg.metadata
      ? typeof msg.metadata === 'string'
        ? msg.metadata
        : JSON.stringify(msg.metadata)
      : '{}',
    created_at: msg.created_at,
    updated_at: msg.updated_at || msg.created_at,
    agent_id: msg.agent_id,
    agent_version_id: msg.agent_version_id,
    agents: msg.agents,
    author: msg.author,
    event_id: msg.event_id,
  }));
};

// Agent APIs
export const startAgent = async (
  threadId: string,
  options?: {
    model_name?: string;
    enable_thinking?: boolean;
    reasoning_effort?: string;
    stream?: boolean;
    agent_id?: string; // Optional again
  },
): Promise<{ agent_run_id: string }> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    // Check if backend URL is configured
    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    const defaultOptions = {
      model_name: 'claude-3-7-sonnet-latest',
      enable_thinking: false,
      reasoning_effort: 'low',
      stream: true,
    };

    const finalOptions = { ...defaultOptions, ...options };

    const body: any = {
      model_name: finalOptions.model_name,
      enable_thinking: finalOptions.enable_thinking,
      reasoning_effort: finalOptions.reasoning_effort,
      stream: finalOptions.stream,
    };
    
    // Only include agent_id if it's provided
    if (finalOptions.agent_id) {
      body.agent_id = finalOptions.agent_id;
    }

    const response = await fetch(`${API_URL}/thread/${threadId}/agent/start`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(body),
    });

    if (!response.ok) {
      if (response.status === 402) {
        try {
          const errorData = await response.json();
          const detail = errorData?.detail || { message: 'Payment Required' };
          if (typeof detail.message !== 'string') {
            detail.message = 'Payment Required';
          }
          throw new BillingError(response.status, detail);
        } catch (parseError) {
          throw new BillingError(
            response.status,
            { message: 'Payment Required' },
            `Error starting agent: ${response.statusText} (402)`,
          );
        }
      }

      if (response.status === 429) {
          const errorData = await response.json();
          const detail = errorData?.detail || { 
            message: 'Too many agent runs running',
            running_thread_ids: [],
            running_count: 0,
          };
          if (typeof detail.message !== 'string') {
            detail.message = 'Too many agent runs running';
          }
          if (!Array.isArray(detail.running_thread_ids)) {
            detail.running_thread_ids = [];
          }
          if (typeof detail.running_count !== 'number') {
            detail.running_count = 0;
          }
          throw new AgentRunLimitError(response.status, detail);
      }

      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `[API] Error starting agent: ${response.status} ${response.statusText}`,
      );
      throw new Error(
        `Error starting agent: ${response.statusText} (${response.status})`,
      );
    }

    const result = await response.json();
    return result;
  } catch (error) {
    if (error instanceof BillingError || error instanceof AgentRunLimitError) {
      throw error;
    }

    if (error instanceof NoAccessTokenAvailableError) {
      throw error;
    }

    console.error('[API] Failed to start agent:', error);
    
    if (
      error instanceof TypeError &&
      error.message.includes('Failed to fetch')
    ) {
      const networkError = new Error(
        `Cannot connect to backend server. Please check your internet connection and make sure the backend is running.`,
      );
      handleApiError(networkError, { operation: 'start agent', resource: 'AI assistant' });
      throw networkError;
    }

    handleApiError(error, { operation: 'start agent', resource: 'AI assistant' });
    throw error;
  }
};

export const stopAgent = async (agentRunId: string): Promise<void> => {
  nonRunningAgentRuns.add(agentRunId);

  const existingStream = activeStreams.get(agentRunId);
  if (existingStream) {
    existingStream.close();
    activeStreams.delete(agentRunId);
  }

  const supabase = createClient();
  const {
    data: { session },
  } = await supabase.auth.getSession();

  if (!session?.access_token) {
    const authError = new NoAccessTokenAvailableError();
    handleApiError(authError, { operation: 'stop agent', resource: 'AI assistant' });
    throw authError;
  }

  const response = await fetch(`${API_URL}/agent-run/${agentRunId}/stop`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      Authorization: `Bearer ${session.access_token}`,
    },
    cache: 'no-store',
  });

  posthog.capture('task_abandoned', { agentRunId });

  if (!response.ok) {
    const stopError = new Error(`Error stopping agent: ${response.statusText}`);
    handleApiError(stopError, { operation: 'stop agent', resource: 'AI assistant' });
    throw stopError;
  }
};

export const getAgentStatus = async (agentRunId: string): Promise<AgentRun> => {
  if (nonRunningAgentRuns.has(agentRunId)) {
    throw new Error(`Agent run ${agentRunId} is not running`);
  }

  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      console.error('[API] No access token available for getAgentStatus');
      throw new NoAccessTokenAvailableError();
    }

    const url = `${API_URL}/agent-run/${agentRunId}`;
    const response = await fetch(url, {
      headers: {
        Authorization: `Bearer ${session.access_token}`,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `[API] Error getting agent status: ${response.status} ${response.statusText}`,
        errorText,
      );
      if (response.status === 404) {
        nonRunningAgentRuns.add(agentRunId);
      }

      throw new Error(
        `Error getting agent status: ${response.statusText} (${response.status})`,
      );
    }

    const data = await response.json();
    if (data.status !== 'running') {
      nonRunningAgentRuns.add(agentRunId);
    }

    return data;
  } catch (error) {
    console.error('[API] Failed to get agent status:', error);
    handleApiError(error, { operation: 'get agent status', resource: 'AI assistant status', silent: true });
    throw error;
  }
};

export const getAgentRuns = async (threadId: string): Promise<AgentRun[]> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    const response = await fetch(`${API_URL}/thread/${threadId}/agent-runs`, {
      headers: {
        Authorization: `Bearer ${session.access_token}`,
      },
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(`Error getting agent runs: ${response.statusText}`);
    }

    const data = await response.json();
    
    // 确保返回的是数组格式
    if (Array.isArray(data)) {
      return data;
    } else if (data && Array.isArray(data.agent_runs)) {
      return data.agent_runs;
    } else if (data && Array.isArray(data.data)) {
      return data.data;
    } else {
      console.warn('Agent runs API returned unexpected format:', data);
      return [];
    }
  } catch (error) {
    if (error instanceof NoAccessTokenAvailableError) {
      throw error;
    }

    console.error('Failed to get agent runs:', error);
    handleApiError(error, { operation: 'load agent runs', resource: 'conversation history' });
    throw error;
  }
};

export const streamAgent = (
  agentRunId: string,
  callbacks: {
    onMessage: (content: string) => void;
    onError: (error: Error | string) => void;
    onClose: () => void;
  },
): (() => void) => {
  if (nonRunningAgentRuns.has(agentRunId)) {
    setTimeout(() => {
      callbacks.onError(`Agent run ${agentRunId} is not running`);
      callbacks.onClose();
    }, 0);

    return () => {};
  }

  const existingStream = activeStreams.get(agentRunId);
  if (existingStream) {
    existingStream.close();
    activeStreams.delete(agentRunId);
  }

  try {
    const setupStream = async () => {
      try {
        const status = await getAgentStatus(agentRunId);
        if (status.status !== 'running') {
          nonRunningAgentRuns.add(agentRunId);
          callbacks.onError(
            `Agent run ${agentRunId} is not running (status: ${status.status})`,
          );
          callbacks.onClose();
          return;
        }
      } catch (err) {
        const errorMessage = err instanceof Error ? err.message : String(err);
        const isNotFoundError =
          errorMessage.includes('not found') ||
          errorMessage.includes('404') ||
          errorMessage.includes('does not exist');

        if (isNotFoundError) {
          nonRunningAgentRuns.add(agentRunId);
        }

        callbacks.onError(errorMessage);
        callbacks.onClose();
        return;
      }

      const supabase = createClient();
      const {
        data: { session },
      } = await supabase.auth.getSession();

      if (!session?.access_token) {
        const authError = new NoAccessTokenAvailableError();
        callbacks.onError(authError);
        callbacks.onClose();
        return;
      }

      const url = new URL(`${API_URL}/agent-run/${agentRunId}/stream`);
      url.searchParams.append('token', session.access_token);

      const eventSource = new EventSource(url.toString());

      activeStreams.set(agentRunId, eventSource);

      eventSource.onopen = () => {
      };

      eventSource.onmessage = (event) => {
        try {
          const rawData = event.data;
          if (rawData.includes('"type": "ping"')) return;

          // Skip empty messages
          if (!rawData || rawData.trim() === '') {
            return;
          }

          // Check for error status messages
          try {
            const jsonData = JSON.parse(rawData);
            if (jsonData.status === 'error') {
              console.error(`[STREAM] Error status received for ${agentRunId}:`, jsonData);
              
              // Pass the error message to the callback
              callbacks.onError(jsonData.message || 'Unknown error occurred');
              
              // Don't close the stream for error status messages as they may continue
              return;
            }
          } catch (jsonError) {
            // Not JSON or invalid JSON, continue with normal processing
          }

          // Check for "Agent run not found" error
          if (
            rawData.includes('Agent run') &&
            rawData.includes('not found in active runs')
          ) {
            // Add to non-running set to prevent future reconnection attempts
            nonRunningAgentRuns.add(agentRunId);

            // Notify about the error
            callbacks.onError('Agent run not found in active runs');

            // Clean up
            eventSource.close();
            activeStreams.delete(agentRunId);
            callbacks.onClose();

            return;
          }

          // Check for completion messages
          if (
            rawData.includes('"type": "status"') &&
            rawData.includes('"status": "completed"')
          ) {
            // Check for specific completion messages that indicate we should stop checking
            if (rawData.includes('Agent run completed successfully')) {
              // Add to non-running set to prevent future reconnection attempts
              nonRunningAgentRuns.add(agentRunId);
            }

            // Notify about the message
            callbacks.onMessage(rawData);

            // Clean up
            eventSource.close();
            activeStreams.delete(agentRunId);
            callbacks.onClose();

            return;
          }

          // Check for thread run end message
          if (
            rawData.includes('"type": "status"') &&
            rawData.includes('thread_run_end')
          ) {
            // Notify about the message
            callbacks.onMessage(rawData);
            return;
          }

          // For all other messages, just pass them through
          callbacks.onMessage(rawData);
        } catch (error) {
          console.error(`[STREAM] Error handling message:`, error);
          callbacks.onError(error instanceof Error ? error : String(error));
        }
      };

      eventSource.onerror = (event) => {
        // Check if the agent is still running
        getAgentStatus(agentRunId)
          .then((status) => {
            if (status.status !== 'running') {
              nonRunningAgentRuns.add(agentRunId);
              eventSource.close();
              activeStreams.delete(agentRunId);
              callbacks.onClose();
            } else {
              // Let the browser handle reconnection for non-fatal errors
            }
          })
          .catch((err) => {
            console.error(
              `[STREAM] Error checking agent status after stream error:`,
              err,
            );

            // Check if this is a "not found" error
            const errMsg = err instanceof Error ? err.message : String(err);
            const isNotFoundErr =
              errMsg.includes('not found') ||
              errMsg.includes('404') ||
              errMsg.includes('does not exist');

            if (isNotFoundErr) {
              nonRunningAgentRuns.add(agentRunId);
              eventSource.close();
              activeStreams.delete(agentRunId);
              callbacks.onClose();
            }

            // For other errors, notify but don't close the stream
            callbacks.onError(errMsg);
          });
      };
    };

    // Start the stream setup
    setupStream();

    // Return a cleanup function
    return () => {
      const stream = activeStreams.get(agentRunId);
      if (stream) {
        stream.close();
        activeStreams.delete(agentRunId);
      }
    };
  } catch (error) {
    console.error(`[STREAM] Error setting up stream for ${agentRunId}:`, error);
    callbacks.onError(error instanceof Error ? error : String(error));
    callbacks.onClose();
    return () => {};
  }
};

// Sandbox API Functions
export const createSandboxFile = async (
  sandboxId: string,
  filePath: string,
  content: string,
): Promise<void> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    // Use FormData to handle both text and binary content more reliably
    const formData = new FormData();
    formData.append('path', filePath);

    // Create a Blob from the content string and append as a file
    const blob = new Blob([content], { type: 'application/octet-stream' });
    formData.append('file', blob, filePath.split('/').pop() || 'file');

    const headers: Record<string, string> = {};
    if (session?.access_token) {
      headers['Authorization'] = `Bearer ${session.access_token}`;
    }

    const response = await fetch(`${API_URL}/sandboxes/${sandboxId}/files`, {
      method: 'POST',
      headers,
      body: formData,
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error creating sandbox file: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error creating sandbox file: ${response.statusText} (${response.status})`,
      );
    }

    const result = await response.json();
    return result;
  } catch (error) {
    console.error('Failed to create sandbox file:', error);
    handleApiError(error, { operation: 'create file', resource: `file ${filePath}` });
    throw error;
  }
};

// Fallback method for legacy support using JSON
export const createSandboxFileJson = async (
  sandboxId: string,
  filePath: string,
  content: string,
): Promise<void> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    const headers: Record<string, string> = {
      'Content-Type': 'application/json',
    };

    if (session?.access_token) {
      headers['Authorization'] = `Bearer ${session.access_token}`;
    }

    const response = await fetch(
      `${API_URL}/sandboxes/${sandboxId}/files/json`,
      {
        method: 'POST',
        headers,
        body: JSON.stringify({
          path: filePath,
          content: content,
        }),
      },
    );

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error creating sandbox file (JSON): ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error creating sandbox file: ${response.statusText} (${response.status})`,
      );
    }

    const result = await response.json();
    return result;
  } catch (error) {
    console.error('Failed to create sandbox file with JSON:', error);
    handleApiError(error, { operation: 'create file', resource: `file ${filePath}` });
    throw error;
  }
};

// Helper function to normalize file paths with Unicode characters
function normalizePathWithUnicode(path: string): string {
  try {
    // Replace escaped Unicode sequences with actual characters
    return path.replace(/\\u([0-9a-fA-F]{4})/g, (_, hexCode) => {
      return String.fromCharCode(parseInt(hexCode, 16));
    });
  } catch (e) {
    console.error('Error processing Unicode escapes in path:', e);
    return path;
  }
}

export const listSandboxFiles = async (
  sandboxId: string,
  path: string,
): Promise<FileInfo[]> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    const url = new URL(`${API_URL}/sandboxes/${sandboxId}/files`);
    
    // Normalize the path to handle Unicode escape sequences
    const normalizedPath = normalizePathWithUnicode(path);
    
    // Properly encode the path parameter for UTF-8 support
    url.searchParams.append('path', normalizedPath);

    const headers: Record<string, string> = {};
    if (session?.access_token) {
      headers['Authorization'] = `Bearer ${session.access_token}`;
    }

    const response = await fetch(url.toString(), {
      headers,
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error listing sandbox files: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error listing sandbox files: ${response.statusText} (${response.status})`,
      );
    }

    const data = await response.json();
    return data.files || [];
  } catch (error) {
    console.error('Failed to list sandbox files:', error);
    // handleApiError(error, { operation: 'list files', resource: `directory ${path}` });
    throw error;
  }
};

export const getSandboxFileContent = async (
  sandboxId: string,
  path: string,
): Promise<string | Blob> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    const url = new URL(`${API_URL}/sandboxes/${sandboxId}/files/content`);
    
    // Normalize the path to handle Unicode escape sequences
    const normalizedPath = normalizePathWithUnicode(path);
    
    // Properly encode the path parameter for UTF-8 support
    url.searchParams.append('path', normalizedPath);

    const headers: Record<string, string> = {};
    if (session?.access_token) {
      headers['Authorization'] = `Bearer ${session.access_token}`;
    }

    const response = await fetch(url.toString(), {
      headers,
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error getting sandbox file content: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error getting sandbox file content: ${response.statusText} (${response.status})`,
      );
    }

    // Check if it's a text file or binary file based on content-type
    const contentType = response.headers.get('content-type');
    if (
      (contentType && contentType.includes('text')) ||
      contentType?.includes('application/json')
    ) {
      return await response.text();
    } else {
      return await response.blob();
    }
  } catch (error) {
    console.error('Failed to get sandbox file content:', error);
    handleApiError(error, { operation: 'load file content', resource: `file ${path}` });
    throw error;
  }
};

// Function to get public projects
export const getPublicProjects = async (): Promise<Project[]> => {
  try {
    const supabase = createClient();

    // Query for threads that are marked as public
    const { data: publicThreads, error: threadsError } = await supabase
      .from('threads')
      .select('project_id')
      .eq('is_public', true);

    if (threadsError) {
      console.error('Error fetching public threads:', threadsError);
      return [];
    }

    // If no public threads found, return empty array
    if (!publicThreads?.length) {
      return [];
    }

    // Extract unique project IDs from public threads
    const publicProjectIds = [
      ...new Set(publicThreads.map((thread) => thread.project_id)),
    ].filter(Boolean);

    // If no valid project IDs, return empty array
    if (!publicProjectIds.length) {
      return [];
    }

    // Get the projects that have public threads
    const { data: projects, error: projectsError } = await supabase
      .from('projects')
      .select('*')
      .in('project_id', publicProjectIds);

    if (projectsError) {
      console.error('Error fetching public projects:', projectsError);
      return [];
    }

    // Map database fields to our Project type
    const mappedProjects: Project[] = (projects || []).map((project) => ({
      id: project.project_id,
      name: project.name || '',
      description: project.description || '',
      account_id: project.account_id,
      created_at: project.created_at,
      updated_at: project.updated_at,
      sandbox: project.sandbox || {
        id: '',
        pass: '',
        vnc_preview: '',
        sandbox_url: '',
      },
      is_public: true, // Mark these as public projects
    }));

    return mappedProjects;
  } catch (err) {
    console.error('Error fetching public projects:', err);
    handleApiError(err, { operation: 'load public projects', resource: 'public projects' });
    return [];
  }
};


export const initiateAgent = async (
  formData: FormData,
): Promise<InitiateAgentResponse> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    if (!API_URL) {
      throw new Error(
        'Backend URL is not configured. Set NEXT_PUBLIC_BACKEND_URL in your environment.',
      );
    }

    const response = await fetch(`${API_URL}/agent/initiate`, {
      method: 'POST',
      headers: {
        Authorization: `Bearer ${session.access_token}`,
      },
      body: formData,
      cache: 'no-store',
    });

    if (!response.ok) {
      // Check for 402 Payment Required first
      if (response.status === 402) {
        try {
          const errorData = await response.json();
          // Ensure detail exists and has a message property
          const detail = errorData?.detail || { message: 'Payment Required' };
          if (typeof detail.message !== 'string') {
            detail.message = 'Payment Required'; // Default message if missing
          }
          throw new BillingError(response.status, detail);
        } catch (parseError) {
          // Handle cases where parsing fails or the structure isn't as expected
          throw new BillingError(
            response.status,
            { message: 'Payment Required' },
            `Error initiating agent: ${response.statusText} (402)`,
          );
        }
      }

      // Check for 429 Too Many Requests (Agent Run Limit)
      if (response.status === 429) {
          const errorData = await response.json();
          // Ensure detail exists and has required properties
          const detail = errorData?.detail || { 
            message: 'Too many agent runs running',
            running_thread_ids: [],
            running_count: 0,
          };
          if (typeof detail.message !== 'string') {
            detail.message = 'Too many agent runs running';
          }
          if (!Array.isArray(detail.running_thread_ids)) {
            detail.running_thread_ids = [];
          }
          if (typeof detail.running_count !== 'number') {
            detail.running_count = 0;
          }
          throw new AgentRunLimitError(response.status, detail);
      }

      // Handle other errors
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      
      console.error(
        `[API] Error initiating agent: ${response.status} ${response.statusText}`,
        errorText,
      );
    
      if (response.status === 401) {
        throw new Error('Authentication error: Please sign in again');
      } else if (response.status >= 500) {
        throw new Error('Server error: Please try again later');
      }
    
      throw new Error(
        `Error initiating agent: ${response.statusText} (${response.status})`,
      );
    }

    const result = await response.json();
    return result;
  } catch (error) {
    // Rethrow BillingError and AgentRunLimitError instances directly
    if (error instanceof BillingError || error instanceof AgentRunLimitError) {
      throw error;
    }

    console.error('[API] Failed to initiate agent:', error);

    if (
      error instanceof TypeError &&
      error.message.includes('Failed to fetch')
    ) {
      const networkError = new Error(
        `Cannot connect to backend server. Please check your internet connection and make sure the backend is running.`,
      );
      handleApiError(networkError, { operation: 'initiate agent', resource: 'AI assistant' });
      throw networkError;
    }
    handleApiError(error, { operation: 'initiate agent' });
    throw error;
  }
};

export const checkApiHealth = async (): Promise<HealthCheckResponse> => {
  try {
    const response = await fetch(`${API_URL}/health`, {
      cache: 'no-store',
    });

    if (!response.ok) {
      throw new Error(`API health check failed: ${response.statusText}`);
    }

    return response.json();
  } catch (error) {
    throw error;
  }
};

// Billing API Types
export interface CreateCheckoutSessionRequest {
  price_id: string;
  success_url: string;
  cancel_url: string;
  referral_id?: string;
  commitment_type?: 'monthly' | 'yearly' | 'yearly_commitment';
}

export interface CreatePortalSessionRequest {
  return_url: string;
}

export interface SubscriptionStatus {
  status: string; // Includes 'active', 'trialing', 'past_due', 'scheduled_downgrade', 'no_subscription'
  plan_name?: string;
  price_id?: string;
  current_period_end?: string; // ISO datetime string
  cancel_at_period_end?: boolean;
  trial_end?: string; // ISO datetime string
  minutes_limit?: number;
  cost_limit?: number;
  current_usage?: number;
  // Fields for scheduled changes
  has_schedule?: boolean;
  scheduled_plan_name?: string;
  scheduled_price_id?: string;
  scheduled_change_date?: string; // ISO datetime string
  // Subscription data for frontend components
  subscription_id?: string;
  subscription?: {
    id: string;
    status: string;
    cancel_at_period_end: boolean;
    current_period_end: number; // timestamp
  };
}

export interface CommitmentInfo {
  has_commitment: boolean;
  commitment_type?: string;
  months_remaining?: number;
  can_cancel: boolean;
  commitment_end_date?: string;
}

// Interface for user subscription details from Stripe
export interface UserSubscriptionResponse {
  subscription?: {
    id: string;
    status: string;
    current_period_end: number;
    current_period_start: number;
    cancel_at_period_end: boolean;
    cancel_at?: number;
    items: {
      data: Array<{
        id: string;
        price: {
          id: string;
          unit_amount: number;
          currency: string;
          recurring: {
            interval: string;
            interval_count: number;
          };
        };
        quantity: number;
      }>;
    };
    metadata: {
      [key: string]: string;
    };
  };
  price_id?: string;
  plan_name?: string;
  status?: string;
  has_schedule?: boolean;
  scheduled_price_id?: string;
  current_period_end?: number;
  current_period_start?: number;
  cancel_at_period_end?: boolean;
  cancel_at?: number;
  customer_email?: string;
  usage?: {
    total_usage: number;
    limit: number;
  };
}

// Usage log entry interface
export interface UsageLogEntry {
  message_id: string;
  thread_id: string;
  created_at: string;
  content: {
    usage: {
      prompt_tokens: number;
      completion_tokens: number;
    };
    model: string;
  };
  total_tokens: number;
  estimated_cost: number;
  project_id: string;
}

// Usage logs response interface
export interface UsageLogsResponse {
  logs: UsageLogEntry[];
  has_more: boolean;
  message?: string;
}

export interface BillingStatusResponse {
  can_run: boolean;
  message: string;
  subscription: {
    price_id: string;
    plan_name: string;
    minutes_limit?: number;
  };
}

export interface Model {
  id: string;
  display_name: string;
  short_name?: string;
  requires_subscription?: boolean;
  is_available?: boolean;
  input_cost_per_million_tokens?: number | null;
  output_cost_per_million_tokens?: number | null;
  max_tokens?: number | null;
}

export interface AvailableModelsResponse {
  models: Model[];
  subscription_tier: string;
  total_models: number;
}

export interface CreateCheckoutSessionResponse {
  status:
    | 'upgraded'
    | 'downgrade_scheduled'
    | 'checkout_created'
    | 'no_change'
    | 'new'
    | 'updated'
    | 'scheduled'
    | 'commitment_created'
    | 'commitment_blocks_downgrade';
  subscription_id?: string;
  schedule_id?: string;
  session_id?: string;
  url?: string;
  effective_date?: string;
  message?: string;
  details?: {
    is_upgrade?: boolean;
    effective_date?: string;
    current_price?: number;
    new_price?: number;
    commitment_end_date?: string;
    months_remaining?: number;
    invoice?: {
      id: string;
      status: string;
      amount_due: number;
      amount_paid: number;
    };
  };
}

export interface CancelSubscriptionResponse {
  success: boolean;
  status: 'cancelled_at_period_end' | 'commitment_prevents_cancellation';
  message: string;
  details?: {
    subscription_id?: string;
    cancellation_effective_date?: string;
    current_period_end?: number;
    access_until?: string;
    months_remaining?: number;
    commitment_end_date?: string;
    can_cancel_after?: string;
  };
}

export interface ReactivateSubscriptionResponse {
  success: boolean;
  status: 'reactivated' | 'not_cancelled';
  message: string;
  details?: {
    subscription_id?: string;
    next_billing_date?: string;
  };
}

// Billing API Functions
export const createCheckoutSession = async (
  request: CreateCheckoutSessionRequest,
): Promise<CreateCheckoutSessionResponse> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }
    
    
    const requestBody = { ...request, tolt_referral: window.tolt_referral };
    
    const response = await fetch(`${API_URL}/billing/create-checkout-session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(requestBody),
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error creating checkout session: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error creating checkout session: ${response.statusText} (${response.status})`,
      );
    }

    const data = await response.json();
    switch (data.status) {
      case 'upgraded':
      case 'updated':
      case 'downgrade_scheduled':
      case 'scheduled':
      case 'no_change':
        return data;
      case 'new':
      case 'checkout_created':
        if (!data.url) {
          throw new Error('No checkout URL provided');
        }
        return data;
      default:
        console.warn(
          'Unexpected status from createCheckoutSession:',
          data.status,
        );
        return data;
    }
  } catch (error) {
    console.error('Failed to create checkout session:', error);
    handleApiError(error, { operation: 'create checkout session', resource: 'billing' });
    throw error;
  }
};


export const createPortalSession = async (
  request: CreatePortalSessionRequest,
): Promise<{ url: string }> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    const response = await fetch(`${API_URL}/billing/create-portal-session`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
      body: JSON.stringify(request),
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error creating portal session: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error creating portal session: ${response.statusText} (${response.status})`,
      );
    }

    return response.json();
  } catch (error) {
    console.error('Failed to create portal session:', error);
    handleApiError(error, { operation: 'create portal session', resource: 'billing portal' });
    throw error;
  }
};


export const getSubscription = async (): Promise<SubscriptionStatus> => {
  // 暂时不调用后端API，直接返回默认的无订阅状态
  console.log('Billing API temporarily disabled - returning default subscription status');
  return {
    status: 'no_subscription',
    plan_name: undefined,
    price_id: undefined,
    current_period_end: undefined,
    cancel_at_period_end: undefined,
    trial_end: undefined,
    minutes_limit: undefined,
    cost_limit: undefined,
    current_usage: 0
  };
};

export const getSubscriptionCommitment = async (subscriptionId: string): Promise<CommitmentInfo> => {
  // 暂时不调用后端API，直接返回默认的承诺信息
  console.log('Billing commitment API temporarily disabled - returning default commitment info');
  return {
    has_commitment: false,
    commitment_type: undefined,
    months_remaining: undefined,
    can_cancel: true,
    commitment_end_date: undefined
  };
};

export const getAvailableModels = async (): Promise<AvailableModelsResponse> => {
  // 暂时不调用后端API，直接返回默认的模型列表
  console.log('Available models API temporarily disabled - returning default models');
  return {
    models: [
      {
        id: 'deepseek-chat',
        short_name: 'deepseek-chat',
        display_name: 'DeepSeek Chat',
        created_by: 'DeepSeek',
        model_id: 'deepseek-chat',
        requires_subscription: false,
        vision_enabled: false,
        input_cost_per_million_tokens: 0.000000150,
        output_cost_per_million_tokens: 0.000000600,
        supports_thinking: false,
        max_thinking_tokens: 0,
        is_available: true
      },
      {
        id: 'claude-sonnet-4',
        short_name: 'claude-sonnet-4',
        display_name: 'Claude Sonnet 4',
        created_by: 'Anthropic',
        model_id: 'claude-sonnet-4',
        requires_subscription: true,
        vision_enabled: true,
        input_cost_per_million_tokens: 0.000003000,
        output_cost_per_million_tokens: 0.000015000,
        supports_thinking: true,
        max_thinking_tokens: 4000,
        is_available: true
      },
      {
        id: 'gpt-4o',
        short_name: 'gpt-4o',
        display_name: 'GPT-4o',
        created_by: 'OpenAI',
        model_id: 'gpt-4o',
        requires_subscription: true,
        vision_enabled: true,
        input_cost_per_million_tokens: 0.000002500,
        output_cost_per_million_tokens: 0.000010000,
        supports_thinking: false,
        max_thinking_tokens: 0,
        is_available: true
      },
      {
        id: 'gpt-4o-mini',
        short_name: 'gpt-4o-mini',
        display_name: 'GPT-4o Mini',
        created_by: 'OpenAI',
        model_id: 'gpt-4o-mini',
        requires_subscription: false,
        vision_enabled: true,
        input_cost_per_million_tokens: 0.000000150,
        output_cost_per_million_tokens: 0.000000600,
        supports_thinking: false,
        max_thinking_tokens: 0,
        is_available: true
      },
      {
        id: 'gpt-3.5-turbo',
        short_name: 'gpt-3.5-turbo',
        display_name: 'GPT-3.5 Turbo',
        created_by: 'OpenAI',
        model_id: 'gpt-3.5-turbo',
        requires_subscription: false,
        vision_enabled: false,
        input_cost_per_million_tokens: 0.000000500,
        output_cost_per_million_tokens: 0.000001500,
        supports_thinking: false,
        max_thinking_tokens: 0,
        is_available: true
      }
    ],
    subscription_tier: 'free',
    total_models: 5
  };
};


export const checkBillingStatus = async (): Promise<BillingStatusResponse> => {
  // 暂时不调用后端API，直接返回默认的计费状态
  console.log('Billing status API temporarily disabled - returning default status');
  return {
    status: 'healthy',
    message: 'Billing system is temporarily disabled',
    limits: {
      daily_cost_limit: 1000,
      monthly_cost_limit: 10000,
      daily_usage: 0,
      monthly_usage: 0
    },
    subscription: {
      status: 'no_subscription',
      plan_name: 'Free',
      current_period_end: null
    }
  };
};

export const cancelSubscription = async (): Promise<CancelSubscriptionResponse> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    const response = await fetch(`${API_URL}/billing/cancel-subscription`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error cancelling subscription: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error cancelling subscription: ${response.statusText} (${response.status})`,
      );
    }

    return response.json();
  } catch (error) {
    console.error('Failed to cancel subscription:', error);
    handleApiError(error, { operation: 'cancel subscription', resource: 'subscription' });
    throw error;
  }
};

// 🔧 添加缺失的 reactivateSubscription 函数
export const reactivateSubscription = async (): Promise<ReactivateSubscriptionResponse> => {
  try {
    const supabase = createClient();
    const {
      data: { session },
    } = await supabase.auth.getSession();

    if (!session?.access_token) {
      throw new NoAccessTokenAvailableError();
    }

    const response = await fetch(`${API_URL}/billing/reactivate-subscription`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Authorization: `Bearer ${session.access_token}`,
      },
    });

    if (!response.ok) {
      const errorText = await response
        .text()
        .catch(() => 'No error details available');
      console.error(
        `Error reactivating subscription: ${response.status} ${response.statusText}`,
        errorText,
      );
      throw new Error(
        `Error reactivating subscription: ${response.statusText} (${response.status})`,
      );
    }

    return response.json();
  } catch (error) {
    console.error('Failed to reactivate subscription:', error);
    handleApiError(error, { operation: 'reactivate subscription', resource: 'subscription' });
    throw error;
  }
};

// Transcription API Types
export interface TranscriptionResponse {
  text: string;
}

// Transcription API Functions
export const transcribeAudio = async (audioFile: File): Promise<TranscriptionResponse> => {
  // 暂时不调用后端API，直接返回模拟的转录结果
  console.log('Transcription API temporarily disabled - returning mock transcription');
  return {
    text: "This is a mock transcription result. Please implement the actual transcription API."
  };
};

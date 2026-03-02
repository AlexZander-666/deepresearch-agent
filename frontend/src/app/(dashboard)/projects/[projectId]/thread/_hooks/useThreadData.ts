import { useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { Project } from '@/lib/api';
import { useThreadQuery } from '@/hooks/react-query/threads/use-threads';
import { useMessagesQuery } from '@/hooks/react-query/threads/use-messages';
import { useProjectQuery } from '@/hooks/react-query/threads/use-project';
import { useAgentRunsQuery } from '@/hooks/react-query/threads/use-agent-run';
import { ApiMessageType, UnifiedMessage, AgentStatus } from '../_types';
import { mergeServerAndLocalMessages } from './message-merge';
import { debugLog } from '@/lib/client-logger';

interface UseThreadDataReturn {
  messages: UnifiedMessage[];
  setMessages: React.Dispatch<React.SetStateAction<UnifiedMessage[]>>;
  project: Project | null;
  sandboxId: string | null;
  projectName: string;
  agentRunId: string | null;
  setAgentRunId: React.Dispatch<React.SetStateAction<string | null>>;
  agentStatus: AgentStatus;
  setAgentStatus: React.Dispatch<React.SetStateAction<AgentStatus>>;
  isLoading: boolean;
  error: string | null;
  initialLoadCompleted: boolean;
  threadQuery: ReturnType<typeof useThreadQuery>;
  messagesQuery: ReturnType<typeof useMessagesQuery>;
  projectQuery: ReturnType<typeof useProjectQuery>;
  agentRunsQuery: ReturnType<typeof useAgentRunsQuery>;
}

const mapApiMessageToUnified = (
  msg: ApiMessageType,
  threadId: string,
): UnifiedMessage => ({
  message_id: msg.message_id || null,
  thread_id: msg.thread_id || threadId,
  type: (msg.type || 'system') as UnifiedMessage['type'],
  is_llm_message: Boolean(msg.is_llm_message),
  content: msg.content || '',
  metadata: msg.metadata || '{}',
  created_at: msg.created_at || new Date().toISOString(),
  updated_at: msg.updated_at || new Date().toISOString(),
  agent_id: (msg as any).agent_id,
  agents: (msg as any).agents,
});

export function useThreadData(threadId: string, projectId: string): UseThreadDataReturn {
  const [messages, setMessages] = useState<UnifiedMessage[]>([]);
  const [project, setProject] = useState<Project | null>(null);
  const [sandboxId, setSandboxId] = useState<string | null>(null);
  const [projectName, setProjectName] = useState<string>('');
  const [agentRunId, setAgentRunId] = useState<string | null>(null);
  const [agentStatus, setAgentStatus] = useState<AgentStatus>('idle');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  
  // 🎯 添加流式保护标志
  const isStreamingOrRecentlyStreamedRef = useRef(false);
  
  const initialLoadCompleted = useRef<boolean>(false);
  const messagesLoadedRef = useRef(false);
  const agentRunsCheckedRef = useRef(false);
  const hasInitiallyScrolled = useRef<boolean>(false);
  

  const threadQuery = useThreadQuery(threadId);
  const messagesQuery = useMessagesQuery(threadId);

  // 调试React Query状态
  debugLog('🔎 [useThreadData] messagesQuery完整状态:', {
    data: messagesQuery.data,
    status: messagesQuery.status,
    isLoading: messagesQuery.isLoading,
    isFetching: messagesQuery.isFetching,
    isError: messagesQuery.isError,
    error: messagesQuery.error,
    enabled: !!threadId,
    threadId
  });
  const projectQuery = useProjectQuery(projectId);
  const agentRunsQuery = useAgentRunsQuery(threadId);
  
  // 🎯 监听agentStatus变化，在工具开始执行时立即刷新项目数据
  const prevAgentStatusForProjectRef = useRef<AgentStatus>('idle');
  useEffect(() => {
    const currentStatus = agentStatus;
    const prevStatus = prevAgentStatusForProjectRef.current;
    
    // 🔍 调试：始终显示状态变化
    if (prevStatus !== currentStatus) {
      debugLog(`🔄 [useThreadData] AgentStatus变化: ${prevStatus} → ${currentStatus}`);
    }
    
    // 🚀 关键修复：当开始运行时立即刷新项目数据（获取最新沙盒配置用于实时预览）
    if (
      (prevStatus === 'idle' || prevStatus === 'error') && 
      (currentStatus === 'running' || currentStatus === 'connecting')
    ) {
      debugLog('🚀 [useThreadData] Agent开始运行，立即刷新项目数据获取VNC配置');
      projectQuery.refetch();
    }
    
    prevAgentStatusForProjectRef.current = currentStatus;
  }, [agentStatus, projectQuery]);
  
  // 🎯 管理流式保护标志
  useEffect(() => {
    if (agentStatus === 'running' || agentStatus === 'connecting') {
      debugLog('🛡️ [useThreadData] 启用流式保护 - agentStatus:', agentStatus);
      isStreamingOrRecentlyStreamedRef.current = true;
    } else if (agentStatus === 'idle') {
      // 延迟清除保护标志，给消息状态稳定一些时间
      debugLog('⏰ [useThreadData] 5秒后清除流式保护');
      setTimeout(() => {
        debugLog('🔓 [useThreadData] 清除流式保护');
        isStreamingOrRecentlyStreamedRef.current = false;
      }, 5000); // 增加到5秒
    }
  }, [agentStatus]);
  
  // (debug logs removed)

  useEffect(() => {
    let isMounted = true;
    
    // Reset refs when thread changes
    agentRunsCheckedRef.current = false;
    messagesLoadedRef.current = false;
    initialLoadCompleted.current = false;
    
    // Clear messages on thread change; fresh data will set messages
    setMessages([]);

    async function initializeData() {
      if (!initialLoadCompleted.current) setIsLoading(true);
      setError(null);
      try {
        if (!threadId) throw new Error('Thread ID is required');

        if (threadQuery.isError) {
          throw new Error('Failed to load thread data: ' + threadQuery.error);
        }
        if (!isMounted) return;

        if (projectQuery.data) {
          setProject(projectQuery.data);
          if (typeof projectQuery.data.sandbox === 'string') {
            setSandboxId(projectQuery.data.sandbox);
          } else if (projectQuery.data.sandbox?.id) {
            setSandboxId(projectQuery.data.sandbox.id);
          }

          setProjectName(projectQuery.data.name || '');
        }

        if (messagesQuery.data && !messagesLoadedRef.current) {
          debugLog('🔍 [useThreadData] 接收到消息数据:', messagesQuery.data);
          debugLog('🔍 [useThreadData] 消息数据详细分析:', {
            isArray: Array.isArray(messagesQuery.data),
            length: messagesQuery.data?.length,
            types: messagesQuery.data?.map((m: any) => m.type),
            messageIds: messagesQuery.data?.map((m: any) => m.message_id || m.id),
            rawData: JSON.stringify(messagesQuery.data, null, 2)
          });

          const unifiedMessages = (messagesQuery.data || []).map((msg: ApiMessageType) =>
            mapApiMessageToUnified(msg, threadId),
          );
            
          debugLog('🔍 [useThreadData] 过滤后的消息:', unifiedMessages);
          setMessages((prev) => {
            const mergedMessages = mergeServerAndLocalMessages(unifiedMessages, prev, {
              localMessageGracePeriodMs: 60_000,
            });
            debugLog('🔍 [useThreadData] 合并后的消息:', mergedMessages);
            return mergedMessages;
          });
          debugLog('🔍 [useThreadData] 消息已设置到state');
          // Messages set only from server merge; no cross-thread cache
          messagesLoadedRef.current = true;

          if (!hasInitiallyScrolled.current) {
            hasInitiallyScrolled.current = true;
          }
        }

        if (agentRunsQuery.data && !agentRunsCheckedRef.current && isMounted) {
          debugLog('🔍 [useThreadData] Processing agent runs:', {
            total: agentRunsQuery.data.length,
            statuses: agentRunsQuery.data.map(r => ({ id: r.id, status: r.status }))
          });
          
          agentRunsCheckedRef.current = true;
          
          // Check for any running agents - only connect to RUNNING agents!
          const runningRuns = agentRunsQuery.data.filter(r => r.status === 'running');
          debugLog('🏃 [useThreadData] Running agent runs:', runningRuns.length);
          
          if (runningRuns.length > 0) {
            const latestRunning = runningRuns[0]; // Use first running agent
            debugLog('✅ [useThreadData] Found running agent:', latestRunning.id);
            setAgentRunId(latestRunning.id);
            setAgentStatus((current) => {
              if (current !== 'running') {
                debugLog('✅ [useThreadData] Changed agentStatus to RUNNING');
                return 'running';
              }
              return current;
            });
          } else {
            // For historical conversations, don't set any agentRunId
            debugLog('💤 [useThreadData] No running agents found - this is likely a historical conversation');
            setAgentStatus((current) => {
              if (current !== 'idle') {
                debugLog('✅ [useThreadData] Changed agentStatus to IDLE');
                return 'idle';
              }
              return current;
            });
            // Explicitly clear any previous agentRunId to prevent streaming attempts
            setAgentRunId(null);
          }
        }

        if (threadQuery.data && messagesQuery.data && agentRunsQuery.data) {
          initialLoadCompleted.current = true;
          setIsLoading(false);
          // Removed time-based final check to avoid incorrectly forcing idle while a stream is active
        }

      } catch (err) {
        console.error('Error loading thread data:', err);
        if (isMounted) {
          const errorMessage =
            err instanceof Error ? err.message : 'Failed to load thread';
          setError(errorMessage);
          toast.error(errorMessage);
          setIsLoading(false);
        }
      }
    }

    if (threadId) {
      initializeData();
    }

    return () => {
      isMounted = false;
    };
  }, [
    threadId,
    threadQuery.data,
    threadQuery.isError,
    threadQuery.error,
    projectQuery.data,
    messagesQuery.data,
    agentRunsQuery.data
  ]);

  // Force message reload when thread changes or new data arrives
  useEffect(() => {
    debugLog('📡 [useThreadData] useEffect triggered:', {
      messagesQueryDataLength: messagesQuery.data?.length || 0,
      messagesQueryStatus: messagesQuery.status,
      isLoading,
      threadId,
      timestamp: Date.now()
    });
    
    debugLog('📡 [useThreadData] 详细检查条件:', {
      hasMessagesQueryData: !!messagesQuery.data,
      messagesQueryData: messagesQuery.data,
      statusIsSuccess: messagesQuery.status === 'success',
      notLoading: !isLoading,
      willEnterIf: messagesQuery.data && messagesQuery.status === 'success' && !isLoading
    });
    
    if (messagesQuery.data && messagesQuery.status === 'success' && !isLoading) {
      const unifiedMessages = (messagesQuery.data || []).map((msg: ApiMessageType) =>
        mapApiMessageToUnified(msg, threadId),
      );

      setMessages((prev) => {
        const merged = mergeServerAndLocalMessages(unifiedMessages, prev, {
          localMessageGracePeriodMs: 60_000,
        });

        if (prev && prev.length === merged.length) {
          const hasChanges = prev.some((prevMsg, index) => {
            const mergedMsg = merged[index];
            return !mergedMsg ||
                   prevMsg.message_id !== mergedMsg.message_id ||
                   prevMsg.content !== mergedMsg.content ||
                   prevMsg.type !== mergedMsg.type ||
                   prevMsg.metadata !== mergedMsg.metadata;
          });

          if (!hasChanges) {
            debugLog('✅ [useThreadData] Messages unchanged, reusing prev reference');
            return prev;
          }
        }

        debugLog('🔄 [useThreadData] setMessages called:', {
          prevLength: prev?.length || 0,
          unifiedMessagesLength: unifiedMessages.length,
          mergedLength: merged.length,
          timestamp: Date.now()
        });

        return merged;
      });
    }
  }, [messagesQuery.data, messagesQuery.status, isLoading, threadId]); // [MESSAGE RELOAD LOOP] - 移除 messages.length 避免循环依赖

  return {
    messages,
    setMessages,
    project,
    sandboxId,
    projectName,
    agentRunId,
    setAgentRunId,
    agentStatus,
    setAgentStatus,
    isLoading,
    error,
    initialLoadCompleted: initialLoadCompleted.current,
    threadQuery,
    messagesQuery,
    projectQuery,
    agentRunsQuery,
  };
} 


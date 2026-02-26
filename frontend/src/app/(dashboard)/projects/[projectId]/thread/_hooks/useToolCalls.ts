import React, { useCallback, useEffect, useRef, useState } from 'react';
import { toast } from 'sonner';
import { ToolCallInput } from '@/components/thread/tool-call-side-panel';
import { UnifiedMessage, ParsedMetadata, StreamingToolCall, AgentStatus } from '../_types';
import { safeJsonParse } from '@/components/thread/utils';
import { ParsedContent } from '@/components/thread/types';
import { extractToolName } from '@/components/thread/tool-views/xml-parser';
import { useIsMobile } from '@/hooks/use-mobile';

interface UseToolCallsReturn {
  toolCalls: ToolCallInput[];
  setToolCalls: React.Dispatch<React.SetStateAction<ToolCallInput[]>>;
  currentToolIndex: number;
  setCurrentToolIndex: React.Dispatch<React.SetStateAction<number>>;
  isSidePanelOpen: boolean;
  setIsSidePanelOpen: React.Dispatch<React.SetStateAction<boolean>>;
  autoOpenedPanel: boolean;
  setAutoOpenedPanel: React.Dispatch<React.SetStateAction<boolean>>;
  externalNavIndex: number | undefined;
  setExternalNavIndex: React.Dispatch<React.SetStateAction<number | undefined>>;
  handleToolClick: (clickedAssistantMessageId: string | null, clickedToolName: string) => void;
  handleStreamingToolCall: (toolCall: StreamingToolCall | null) => void;
  toggleSidePanel: () => void;
  handleSidePanelNavigate: (newIndex: number) => void;
  userClosedPanelRef: React.MutableRefObject<boolean>;
}

// Helper function to parse tool content from the new format
function parseToolContent(content: any): {
  toolName: string;
  parameters: any;
  result: any;
} | null {
  try {
    // First try to parse as JSON if it's a string
    const parsed = typeof content === 'string' ? safeJsonParse(content, content) : content;
    
    // Check if it's the new structured format
    if (parsed && typeof parsed === 'object') {
      // New format: { tool_name, xml_tag_name, parameters, result }
      if ('tool_name' in parsed || 'xml_tag_name' in parsed) {
        return {
          toolName: parsed.tool_name || parsed.xml_tag_name || 'unknown',
          parameters: parsed.parameters || {},
          result: parsed.result || null
        };
      }
      
      // Check if it has a content field that might contain the structured data
      if ('content' in parsed && typeof parsed.content === 'object') {
        const innerContent = parsed.content;
        if ('tool_name' in innerContent || 'xml_tag_name' in innerContent) {
          return {
            toolName: innerContent.tool_name || innerContent.xml_tag_name || 'unknown',
            parameters: innerContent.parameters || {},
            result: innerContent.result || null
          };
        }
      }
    }
  } catch (e) {
    // Continue with old format parsing
  }
  
  return null;
}

export function useToolCalls(
  messages: UnifiedMessage[],
  setLeftSidebarOpen: (open: boolean) => void,
  agentStatus?: AgentStatus
): UseToolCallsReturn {
  // 🔍 实例调试：检查是否有多个实例
  const instanceId = React.useRef(Math.random().toString(36).substring(7));
  console.log(`🏗️ [useToolCalls-${instanceId.current}] Hook instance created/called`);
  
  const [toolCalls, setToolCalls] = useState<ToolCallInput[]>([]);
  const [currentToolIndex, setCurrentToolIndex] = useState<number>(0);
  const [isSidePanelOpen, setIsSidePanelOpen] = useState(false);
  const [autoOpenedPanel, setAutoOpenedPanel] = useState(false);
  const [externalNavIndex, setExternalNavIndex] = useState<number | undefined>(undefined);
  const userClosedPanelRef = useRef(false);
  const userNavigatedRef = useRef(false); // Track if user manually navigated
  const isMobile = useIsMobile();

  const toggleSidePanel = useCallback(() => {
    setIsSidePanelOpen((prevIsOpen) => {
      const newState = !prevIsOpen;
      if (!newState) {
        userClosedPanelRef.current = true;
      }
      if (newState) {
        setLeftSidebarOpen(false);
      }
      return newState;
    });
  }, [setLeftSidebarOpen]);

  const handleSidePanelNavigate = useCallback((newIndex: number) => {
    setCurrentToolIndex(newIndex);
    userNavigatedRef.current = true; // Mark that user manually navigated
  }, []);

  // Create a map of assistant message IDs to their tool call indices for faster lookup
  const assistantMessageToToolIndex = useRef<Map<string, number>>(new Map());

  useEffect(() => {
    console.log(`🚀 [useToolCalls-${instanceId.current}] useEffect TRIGGERED:`, {
      messagesLength: messages.length,
      messagesReference: messages,
      agentStatus,
      isMobile,
      timestamp: Date.now()
    });
    
    // 🔍 统计消息类型
    const messageTypes = messages.reduce((acc, msg) => {
      acc[msg.type] = (acc[msg.type] || 0) + 1;
      return acc;
    }, {} as Record<string, number>);
    console.log('📊 [useToolCalls] Message types breakdown:', messageTypes);
    
    const historicalToolPairs: ToolCallInput[] = [];
    const messageIdToIndex = new Map<string, number>();
    const assistantMessages = messages.filter(m => m.type === 'assistant' && m.message_id);

    // 🎯 详细分析assistant消息
    console.log('🎯 [useToolCalls] Assistant messages analysis:', {
      totalCount: assistantMessages.length,
      messageIds: assistantMessages.map(msg => msg.message_id),
      uniqueIds: [...new Set(assistantMessages.map(msg => msg.message_id))].length,
      hasDuplicates: assistantMessages.length !== [...new Set(assistantMessages.map(msg => msg.message_id))].length
    });

    assistantMessages.forEach(assistantMsg => {
      console.log('🔧 [useToolCalls] Processing assistant message:', {
        messageId: assistantMsg.message_id,
        content: assistantMsg.content,
        hasToolCalls: assistantMsg.content.includes('tool_calls')
      });

      // 查找所有tool类型的消息进行调试
      const allToolMessages = messages.filter(msg => msg.type === 'tool');
      console.log('🔍 [useToolCalls] All tool messages:', allToolMessages.map(msg => ({
        messageId: msg.message_id,
        metadata: msg.metadata,
        type: msg.type
      })));

      const resultMessage = messages.find(toolMsg => {
        if (toolMsg.type !== 'tool' || !toolMsg.metadata || !assistantMsg.message_id) {
          console.log('🔍 [useToolCalls] Skipping message:', {
            type: toolMsg.type,
            hasMetadata: !!toolMsg.metadata,
            hasAssistantId: !!assistantMsg.message_id
          });
          return false;
        }
        try {
          const metadata = safeJsonParse<ParsedMetadata>(toolMsg.metadata, {});
          const matches = metadata.assistant_message_id === assistantMsg.message_id;
          
          console.log('🔍 [useToolCalls] Checking tool message match:', {
            toolMsgId: toolMsg.message_id,
            assistantMsgId: assistantMsg.message_id,
            metadataAssistantId: metadata.assistant_message_id,
            matches: matches
          });

          return matches;
        } catch (e) {
          console.error('🔍 [useToolCalls] Metadata parsing error:', e);
          return false;
        }
      });

      if (resultMessage) {
        console.log('✅ [useToolCalls] Found matching tool result for assistant message:', {
          assistantMsgId: assistantMsg.message_id,
          toolMsgId: resultMessage.message_id,
          assistantContent: assistantMsg.content?.substring(0, 100),
          toolContent: resultMessage.content?.substring(0, 100)
        });
        
        let toolName = 'unknown';
        let isSuccess = true;
        

        
        // First try to parse the new format from the tool message
        const toolContentParsed = parseToolContent(resultMessage.content);
        
        if (toolContentParsed) {
          // New format detected
          toolName = toolContentParsed.toolName.replace(/_/g, '-').toLowerCase();
          
          // Extract success status from the result
          if (toolContentParsed.result && typeof toolContentParsed.result === 'object') {
            isSuccess = toolContentParsed.result.success !== false;
          }
        } else {
          console.log('🔧 [useToolCalls] Tool content parsing failed, trying fallback methods');
          // Fall back to old format parsing
          try {
            const assistantContent = (() => {
              try {
                const parsed = safeJsonParse<ParsedContent>(assistantMsg.content, {});
                return parsed.content || assistantMsg.content;
              } catch {
                return assistantMsg.content;
              }
            })();
            
            const extractedToolName = extractToolName(assistantContent);
            if (extractedToolName) {
              toolName = extractedToolName;
            } else {
              const assistantContentParsed = safeJsonParse<{
                tool_calls?: Array<{ function?: { name?: string }; name?: string }>;
              }>(assistantMsg.content, {});
              if (
                assistantContentParsed.tool_calls &&
                assistantContentParsed.tool_calls.length > 0
              ) {
                const firstToolCall = assistantContentParsed.tool_calls[0];
                const rawName = firstToolCall.function?.name || firstToolCall.name || 'unknown';
                toolName = rawName.replace(/_/g, '-').toLowerCase();
                console.log('🔧 [useToolCalls] Extracted tool name from assistant content:', toolName);
              }
            }
          } catch (err) {
            console.error('🔧 [useToolCalls] Error extracting tool name:', err);
          }

          // Parse success status from old format
          try {
            const toolResultContent = (() => {
              try {
                const parsed = safeJsonParse<ParsedContent>(resultMessage.content, {});
                return parsed.content || resultMessage.content;
              } catch {
                return resultMessage.content;
              }
            })();
            
            if (toolResultContent && typeof toolResultContent === 'string') {
              const toolResultMatch = toolResultContent.match(/ToolResult\s*\(\s*success\s*=\s*(True|False|true|false)/i);
              if (toolResultMatch) {
                isSuccess = toolResultMatch[1].toLowerCase() === 'true';
              } else {
                const toolContent = toolResultContent.toLowerCase();
                isSuccess = !(toolContent.includes('failed') ||
                  toolContent.includes('error') ||
                  toolContent.includes('failure'));
              }
            }
          } catch (err) {
            console.error('🔧 [useToolCalls] Error parsing success status:', err);
          }
        }

        const toolIndex = historicalToolPairs.length;
        const toolCallInput = {
          assistantCall: {
            name: toolName,
            content: assistantMsg.content,
            timestamp: assistantMsg.created_at,
          },
          toolResult: {
            content: resultMessage.content,
            isSuccess: isSuccess,
            timestamp: resultMessage.created_at,
          },
        };

        console.log('🔧 [useToolCalls] Created tool call pair:', {
          index: toolIndex,
          toolName,
          isSuccess,
          assistantMsgId: assistantMsg.message_id,
          toolMsgId: resultMessage?.message_id,
          pairCount: historicalToolPairs.length + 1,
          assistantTimestamp: assistantMsg.created_at,
          toolTimestamp: resultMessage.created_at
        });

        historicalToolPairs.push(toolCallInput);

        // Map the assistant message ID to its tool index
        if (assistantMsg.message_id) {
          messageIdToIndex.set(assistantMsg.message_id, toolIndex);
        }
      } else {
        console.log('❌ [useToolCalls] No tool result found for assistant message:', {
          assistantMsgId: assistantMsg.message_id,
          assistantContent: assistantMsg.content.substring(0, 200) + '...',
          availableToolMessages: allToolMessages.length
        });
      }
    });

    console.log('🔧 [useToolCalls] Final historical tool pairs:', {
      count: historicalToolPairs.length,
      pairs: historicalToolPairs
    });

    // ✅ 不再合并任务工具，让每个工具调用都独立显示
    const finalToolPairs = historicalToolPairs;

    assistantMessageToToolIndex.current = messageIdToIndex;
    
    console.log('🎯 [useToolCalls] About to setToolCalls:', {
      historicalToolPairsCount: historicalToolPairs.length,
      finalToolPairsCount: finalToolPairs.length,
      toolNames: finalToolPairs.map(tc => tc.assistantCall.name),
      firstFew: finalToolPairs.slice(0, 3).map(tc => tc.assistantCall.name),
      lastFew: finalToolPairs.slice(-3).map(tc => tc.assistantCall.name),
      timestamp: Date.now()
    });
    
    // 保留正在 STREAMING 的项，避免 N/N+1 抖动
    setToolCalls((prev) => {
      console.log('🔄 [useToolCalls] setToolCalls called:', {
        prevCount: prev.length,
        newFinalCount: finalToolPairs.length,
        prevStreaming: prev.filter(tc => tc.toolResult?.content === 'STREAMING').length,
        prevStreamingDetails: prev.filter(tc => tc.toolResult?.content === 'STREAMING').map(tc => ({
          name: tc.assistantCall.name,
          timestamp: tc.assistantCall.timestamp
        })),
        finalDetails: finalToolPairs.map(tc => ({
          name: tc.assistantCall.name,
          timestamp: tc.assistantCall.timestamp
        })),
        timestamp: Date.now()
      });
      
      // 🚨 修复：正确合并历史完成项和当前streaming项
      const streamingItems = prev.filter(tc => tc.toolResult?.content === 'STREAMING');
      
      console.log('🔍 [useToolCalls] Detailed streaming items:', streamingItems.map(item => ({
        name: item.assistantCall.name,
        content: item.assistantCall.content?.substring(0, 100),
        timestamp: item.assistantCall.timestamp
      })));
      
      console.log('🔍 [useToolCalls] Detailed final items:', finalToolPairs.map(item => ({
        name: item.assistantCall.name,
        content: item.assistantCall.content?.substring(0, 100),
        timestamp: item.assistantCall.timestamp
      })));
      
      // 🔧 修复：更可靠的匹配逻辑 - 使用时间窗口和工具名称匹配
      const remainingStreamingItems = streamingItems.filter(streamingItem => {
        // 策略1: 先尝试完全匹配（同名+同内容）
        let matchingFinalItem = finalToolPairs.find(
          finalItem => 
            finalItem.assistantCall.name === streamingItem.assistantCall.name &&
            finalItem.assistantCall.content === streamingItem.assistantCall.content
        );
        
        // 策略2: 如果完全匹配失败，使用时间窗口匹配（更可靠）
        if (!matchingFinalItem) {
          const streamingTime = new Date(streamingItem.assistantCall.timestamp).getTime();
          
          matchingFinalItem = finalToolPairs.find(finalItem => {
            const finalTime = new Date(finalItem.assistantCall.timestamp).getTime();
            const timeDiff = Math.abs(finalTime - streamingTime);
            const isSameTool = finalItem.assistantCall.name === streamingItem.assistantCall.name;
            const isWithinTimeWindow = timeDiff < 30000; // 30秒时间窗口
            
            return isSameTool && isWithinTimeWindow;
          });
        }
        
        console.log(`🔍 [useToolCalls] Checking streaming item "${streamingItem.assistantCall.name}":`, {
          hasExactMatch: !!matchingFinalItem,
          streamingContent: streamingItem.assistantCall.content?.substring(0, 50),
          foundFinalContent: matchingFinalItem?.assistantCall.content?.substring(0, 50),
          streamingTimestamp: streamingItem.assistantCall.timestamp,
          matchingTimestamp: matchingFinalItem?.assistantCall.timestamp
        });
        
        if (matchingFinalItem) {
          console.log(`🔄 [useToolCalls] Found match for streaming tool "${streamingItem.assistantCall.name}", removing streaming item`);
          return false; // 移除streaming项
        }
        
        // 没有找到匹配的项，保留streaming项
        console.log(`✅ [useToolCalls] No match for streaming tool "${streamingItem.assistantCall.name}", keeping as streaming`);
        return true;
      });
      
      console.log('🔧 [useToolCalls] Merging results:', {
        finalCount: finalToolPairs.length,
        totalStreamingCount: streamingItems.length,
        remainingStreamingCount: remainingStreamingItems.length,
        removedStreamingCount: streamingItems.length - remainingStreamingItems.length
      });
      
      // 合并：完成项 + 剩余streaming项
      const finalResult = [...finalToolPairs, ...remainingStreamingItems];
      
      // 优化：避免不必要的更新
      if (prev.length === finalResult.length) {
        const hasContentChange = prev.some((prevItem, index) => {
          const newItem = finalResult[index];
          return !newItem || 
                 prevItem.assistantCall.name !== newItem.assistantCall.name ||
                 prevItem.assistantCall.content !== newItem.assistantCall.content ||
                 prevItem.toolResult?.content !== newItem.toolResult?.content;
        });
        
        if (!hasContentChange) {
          console.log('⏭️ [useToolCalls] SKIPPED - toolCalls content unchanged');
          return prev;
        }
      }
      
      console.log('✅ [useToolCalls] Final merged result:', {
        totalCount: finalResult.length,
        toolNames: finalResult.map(tc => tc.assistantCall.name),
        streamingTools: finalResult.filter(tc => tc.toolResult?.content === 'STREAMING').map(tc => tc.assistantCall.name),
        completedTools: finalResult.filter(tc => tc.toolResult?.content !== 'STREAMING').map(tc => tc.assistantCall.name)
      });
      
      // 🚨 强制检查：如果历史工具数量大于0且streaming项数量也大于0，说明可能有问题
      const streamingCount = finalResult.filter(tc => tc.toolResult?.content === 'STREAMING').length;
      const historicalCount = historicalToolPairs.length;
      
      if (historicalCount > 0 && streamingCount > 0) {
        console.warn('⚠️ [useToolCalls] Warning: Both historical and streaming tools exist:', {
          historicalCount,
          streamingCount,
          historicalNames: historicalToolPairs.map(tc => tc.assistantCall.name),
          streamingNames: finalResult.filter(tc => tc.toolResult?.content === 'STREAMING').map(tc => tc.assistantCall.name)
        });
      }
      
      return finalResult;
    });

    if (historicalToolPairs.length > 0) {
      if (agentStatus === 'running' && !userNavigatedRef.current) {
        setCurrentToolIndex(historicalToolPairs.length - 1);
      } else if (isSidePanelOpen && !userClosedPanelRef.current && !userNavigatedRef.current) {
        setCurrentToolIndex(historicalToolPairs.length - 1);
      } else if (!isSidePanelOpen && !autoOpenedPanel && !userClosedPanelRef.current && !isMobile) {
        setCurrentToolIndex(historicalToolPairs.length - 1);
        setIsSidePanelOpen(true);
        setAutoOpenedPanel(true);
      }
    }
  }, [messages, agentStatus, isMobile]); // 移除 isSidePanelOpen 和 autoOpenedPanel 依赖，避免循环

  // Reset user navigation flag when agent stops
  useEffect(() => {
    if (agentStatus === 'idle') {
      userNavigatedRef.current = false;
    }
  }, [agentStatus]);

  useEffect(() => {
    if (!isSidePanelOpen) {
      setAutoOpenedPanel(false);
    }
  }, [isSidePanelOpen]);



  const handleToolClick = useCallback((clickedAssistantMessageId: string | null, clickedToolName: string) => {
    if (!clickedAssistantMessageId) {
      console.warn("Clicked assistant message ID is null. Cannot open side panel.");
      toast.warning("Cannot view details: Assistant message ID is missing.");
      return;
    }

    userClosedPanelRef.current = false;
    userNavigatedRef.current = true; // Mark that user manually navigated

    // Use the pre-computed mapping for faster lookup
    const toolIndex = assistantMessageToToolIndex.current.get(clickedAssistantMessageId);

    if (toolIndex !== undefined) {
      setExternalNavIndex(toolIndex);
      setCurrentToolIndex(toolIndex);
      setIsSidePanelOpen(true);

      setTimeout(() => setExternalNavIndex(undefined), 100);
    } else {
      console.warn(
        `[PAGE] Could not find matching tool call in toolCalls array for assistant message ID: ${clickedAssistantMessageId}`,
      );
      
      // Fallback: Try to find by matching the tool name and approximate position
      const assistantMessage = messages.find(
        m => m.message_id === clickedAssistantMessageId && m.type === 'assistant'
      );
      
      if (assistantMessage) {
        // Find the index of this assistant message among all assistant messages
        const assistantMessages = messages.filter(m => m.type === 'assistant' && m.message_id);
        const messageIndex = assistantMessages.findIndex(m => m.message_id === clickedAssistantMessageId);
        
        // Check if we have a tool call at this index
        if (messageIndex !== -1 && messageIndex < toolCalls.length) {
          setExternalNavIndex(messageIndex);
          setCurrentToolIndex(messageIndex);
          setIsSidePanelOpen(true);
          setTimeout(() => setExternalNavIndex(undefined), 100);
          return;
        }
      }
      
      toast.info('Could not find details for this tool call.');
    }
  }, [messages, toolCalls]);

  const handleStreamingToolCall = useCallback(
    (toolCall: StreamingToolCall | null) => {
      console.log(`🔥 [handleStreamingToolCall-${instanceId.current}] Called with:`, {
        toolCall,
        hasUserClosed: userClosedPanelRef.current,
        timestamp: Date.now()
      });
      
      if (!toolCall) {
        console.log(`⏭️ [handleStreamingToolCall-${instanceId.current}] Early return - no toolCall`);
        return;
      }

      // Get the raw tool name and ensure it uses hyphens
      const rawToolName = toolCall.name || toolCall.xml_tag_name || 'Unknown Tool';
      const toolName = rawToolName.replace(/_/g, '-').toLowerCase();

      if (userClosedPanelRef.current) return;

      const toolArguments = toolCall.arguments || '';
      let formattedContent = toolArguments;
      if (
        toolName.includes('command') &&
        !toolArguments.includes('<execute-command>')
      ) {
        formattedContent = `<execute-command>${toolArguments}</execute-command>`;
      } else if (
        toolName.includes('file') ||
        toolName === 'create-file' ||
        toolName === 'delete-file' ||
        toolName === 'full-file-rewrite' ||
        toolName === 'edit-file'
      ) {
        const fileOpTags = ['create-file', 'delete-file', 'full-file-rewrite', 'edit-file'];
        const matchingTag = fileOpTags.find((tag) => toolName === tag);
        if (matchingTag) {
          if (!toolArguments.includes(`<${matchingTag}>`) && !toolArguments.includes('file_path=') && !toolArguments.includes('target_file=')) {
            const filePath = toolArguments.trim();
            if (filePath && !filePath.startsWith('<')) {
              if (matchingTag === 'edit-file') {
                formattedContent = `<${matchingTag} target_file="${filePath}">`;
              } else {
              formattedContent = `<${matchingTag} file_path="${filePath}">`;
              }
            } else {
              formattedContent = `<${matchingTag}>${toolArguments}</${matchingTag}>`;
            }
          } else {
            formattedContent = toolArguments;
          }
        }
      }

      const newToolCall: ToolCallInput = {
        assistantCall: {
          name: toolName, 
          content: formattedContent,
          timestamp: new Date().toISOString(),
        },
        toolResult: {
          content: 'STREAMING',
          isSuccess: true,
          timestamp: new Date().toISOString(),
        },
      };

      console.log(`🎯 [handleStreamingToolCall-${instanceId.current}] About to setToolCalls with:`, {
        toolName,
        formattedContent,
        currentToolCallsLength: toolCalls.length
      });

            setToolCalls((prev) => {
        console.log(`🔄 [handleStreamingToolCall-${instanceId.current}] setToolCalls called:`, {
          prevLength: prev.length,
          toolName,
          timestamp: Date.now()
        });

        // 🎯 特殊处理：任务管理工具（create-tasks, update-tasks）
        const isTaskTool = ['create-tasks', 'create_tasks', 'update-tasks', 'update_tasks', 'view-tasks', 'view_tasks'].includes(toolName);
        
        if (isTaskTool) {
          console.log(`📋 [handleStreamingToolCall-${instanceId.current}] Task management tool detected: ${toolName}`);
          
          // 查找已存在的任务管理工具调用（无论是否streaming）
          const existingTaskToolIndex = prev.findIndex(
            tc => ['create-tasks', 'create_tasks', 'update-tasks', 'update_tasks', 'view-tasks', 'view_tasks'].includes(tc.assistantCall.name)
          );
          
          if (existingTaskToolIndex !== -1) {
            // 更新现有的任务管理工具调用
            console.log(`♻️ [handleStreamingToolCall-${instanceId.current}] Updating existing task tool at index ${existingTaskToolIndex}`);
            const updated = [...prev];
            updated[existingTaskToolIndex] = {
              ...updated[existingTaskToolIndex],
              assistantCall: {
                ...updated[existingTaskToolIndex].assistantCall,
                name: toolName, // 更新为最新的工具名
                content: formattedContent,
              },
              toolResult: {
                content: 'STREAMING',
                isSuccess: true,
                timestamp: new Date().toISOString(),
              }
            };
            return updated;
          }
        }

        // 🚨 修复：检查是否已存在正在streaming的相同工具调用
        const existingStreamingIndex = prev.findIndex(
          tc => tc.assistantCall.name === toolName && tc.toolResult?.content === 'STREAMING'
        );
        
        console.log(`🔍 [handleStreamingToolCall-${instanceId.current}] Existing STREAMING tool index for "${toolName}":`, existingStreamingIndex);
        
        if (existingStreamingIndex !== -1) {
          // 只更新正在streaming的同名工具调用
          console.log(`♻️ [handleStreamingToolCall-${instanceId.current}] Updating existing STREAMING tool: ${toolName}`);
          const updated = [...prev];
          updated[existingStreamingIndex] = {
            ...updated[existingStreamingIndex],
            assistantCall: {
              ...updated[existingStreamingIndex].assistantCall,
              content: formattedContent,
            },
            toolResult: {
              content: 'STREAMING',
              isSuccess: true,
              timestamp: new Date().toISOString(),
            }
          };
          return updated;
        } else {
          // 添加新工具调用（即使存在同名但非streaming的工具调用）
          console.log(`➕ [handleStreamingToolCall-${instanceId.current}] Adding new streaming tool: ${toolName}`);
          return [...prev, newToolCall];
        }
      });

      // If agent is running and user hasn't manually navigated, show the latest tool
      if (!userNavigatedRef.current) {
        // 🚨 修复：使用setTimeout确保在setToolCalls完成后再设置index到最新的streaming项
        setTimeout(() => {
          setToolCalls(currentToolCalls => {
            if (currentToolCalls.length > 0) {
              const latestIndex = currentToolCalls.length - 1;
              const latestTool = currentToolCalls[latestIndex];
              
              console.log(`🎯 [handleStreamingToolCall] Setting index to latest streaming tool:`, {
                index: latestIndex,
                toolName: latestTool?.assistantCall?.name,
                isStreaming: latestTool?.toolResult?.content === 'STREAMING',
                totalTools: currentToolCalls.length
              });
              
              setCurrentToolIndex(latestIndex);
            }
            return currentToolCalls;
        });
        }, 0);
      }
      
      setIsSidePanelOpen(true);
    },
    [toolCalls.length],
  );

  return {
    toolCalls,
    setToolCalls,
    currentToolIndex,
    setCurrentToolIndex,
    isSidePanelOpen,
    setIsSidePanelOpen,
    autoOpenedPanel,
    setAutoOpenedPanel,
    externalNavIndex,
    setExternalNavIndex,
    handleToolClick,
    handleStreamingToolCall,
    toggleSidePanel,
    handleSidePanelNavigate,
    userClosedPanelRef,
  };
}



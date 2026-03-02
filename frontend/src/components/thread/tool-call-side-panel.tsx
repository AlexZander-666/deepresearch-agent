'use client';

import { Project } from '@/lib/api';
import { getUserFriendlyToolName } from '@/components/thread/utils';
import React from 'react';
import { Slider } from '@/components/ui/slider';
import { Skeleton } from '@/components/ui/skeleton';
import { ApiMessageType } from '@/components/thread/types';
import {
  CircleDashed,
  X,
  ChevronLeft,
  ChevronRight,
  Computer,
  Minimize2,
} from 'lucide-react';
import { useIsMobile } from '@/hooks/use-mobile';
import { Button } from '@/components/ui/button';
import { ToolView } from './tool-views/wrapper';
import { motion, AnimatePresence } from 'framer-motion';
import {
  Drawer,
  DrawerContent,
  DrawerDescription,
  DrawerHeader,
  DrawerTitle,
} from '@/components/ui/drawer';

export interface ToolCallInput {
  assistantCall: {
    content?: string;
    name?: string;
    timestamp?: string;
    toolCallId?: string;
    toolIndex?: number;
    statusType?: string;
  };
  toolResult?: {
    content?: string;
    isSuccess?: boolean;
    timestamp?: string;
  };
  messages?: ApiMessageType[];
}

interface ToolCallSidePanelProps {
  isOpen: boolean;
  onClose: () => void;
  toolCalls: ToolCallInput[];
  currentIndex: number;
  onNavigate: (newIndex: number) => void;
  externalNavigateToIndex?: number;
  messages?: ApiMessageType[];
  agentStatus: string;
  project?: Project;
  renderAssistantMessage?: (
    assistantContent?: string,
    toolContent?: string,
  ) => React.ReactNode;
  renderToolResult?: (
    toolContent?: string,
    isSuccess?: boolean,
  ) => React.ReactNode;
  isLoading?: boolean;
  agentName?: string;
  onFileClick?: (filePath: string) => void;
  disableInitialAnimation?: boolean;
}

interface ToolCallSnapshot {
  id: string;
  toolCall: ToolCallInput;
  index: number;
  timestamp: number;
}

const FLOATING_LAYOUT_ID = 'tool-panel-float';
const CONTENT_LAYOUT_ID = 'tool-panel-content';

// Helper function to generate the computer title
const getComputerTitle = (agentName?: string): string => {
  return agentName ? `${agentName}'s Computer` : "AlexManus's Computer";
};

// Reusable header component for the tool panel
interface PanelHeaderProps {
  agentName?: string;
  onClose: () => void;
  isStreaming?: boolean;
  variant?: 'drawer' | 'desktop' | 'motion';
  showMinimize?: boolean;
  hasToolResult?: boolean;
  layoutId?: string;
}

const PanelHeader: React.FC<PanelHeaderProps> = ({
  agentName,
  onClose,
  isStreaming = false,
  variant = 'desktop',
  showMinimize = false,
  hasToolResult = false,
  layoutId,
}) => {
  const title = getComputerTitle(agentName);
  
  if (variant === 'drawer') {
    return (
      <DrawerHeader className="pb-2">
        <div className="flex items-center justify-between">
          <DrawerTitle className="text-lg font-medium">
            {title}
          </DrawerTitle>
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8"
            title="Minimize to floating preview"
          >
            <Minimize2 className="h-4 w-4" />
          </Button>
        </div>
      </DrawerHeader>
    );
  }

  if (variant === 'motion') {
    return (
      <motion.div
        layoutId={layoutId}
        className="p-3"
      >
        <div className="flex items-center justify-between">
          <motion.div layoutId="tool-icon" className="ml-2 flex items-center gap-2">
            <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
              {title}
            </h2>
          </motion.div>

          {hasToolResult && !isStreaming && (
            <div className="flex items-center gap-2">
              <Button
                variant="ghost"
                size="icon"
                onClick={onClose}
                className="h-8 w-8 ml-1"
                title="Minimize to floating preview"
              >
                <Minimize2 className="h-4 w-4" />
              </Button>
            </div>
          )}

          {isStreaming && (
            <div className="flex items-center gap-2">
              <div className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400 flex items-center gap-1.5">
                <CircleDashed className="h-3 w-3 animate-spin" />
                <span>Running</span>
              </div>
              <Button
                variant="ghost"
                size="icon"
                onClick={onClose}
                className="h-8 w-8 ml-1"
                title="Minimize to floating preview"
              >
                <Minimize2 className="h-4 w-4" />
              </Button>
            </div>
          )}

          {!hasToolResult && !isStreaming && (
            <Button
              variant="ghost"
              size="icon"
              onClick={onClose}
              className="h-8 w-8"
              title="Minimize to floating preview"
            >
              <Minimize2 className="h-4 w-4" />
            </Button>
          )}
        </div>
      </motion.div>
    );
  }

  return (
    <div className="pt-4 pl-4 pr-4">
      <div className="flex items-center justify-between">
        <div className="ml-2 flex items-center gap-2">
          <h2 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
            {title}
          </h2>
        </div>
        <div className="flex items-center gap-2">
          {isStreaming && (
            <div className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400 flex items-center gap-1.5">
              <CircleDashed className="h-3 w-3 animate-spin" />
              <span>Running</span>
            </div>
          )}
          <Button
            variant="ghost"
            size="icon"
            onClick={onClose}
            className="h-8 w-8"
            title={showMinimize ? "Minimize to floating preview" : "Close"}
          >
            {showMinimize ? <Minimize2 className="h-4 w-4" /> : <X className="h-4 w-4" />}
          </Button>
        </div>
      </div>
    </div>
  );
};

export function ToolCallSidePanel({
  isOpen,
  onClose,
  toolCalls,
  currentIndex,
  onNavigate,
  messages,
  agentStatus,
  project,
  isLoading = false,
  externalNavigateToIndex,
  agentName,
  onFileClick,
  disableInitialAnimation,
}: ToolCallSidePanelProps) {
  const [internalIndex, setInternalIndex] = React.useState(0);
  const [navigationMode, setNavigationMode] = React.useState<'live' | 'manual'>('live');
  const [toolCallSnapshots, setToolCallSnapshots] = React.useState<ToolCallSnapshot[]>([]);
  const [isInitialized, setIsInitialized] = React.useState(false);

  const isMobile = useIsMobile();

  const assistantWithoutToolsCount = React.useMemo(() => {
    if (!messages || messages.length === 0) {
      return 0;
    }
    return messages.filter((message) => {
      if (message.type !== 'assistant' || !message.content) {
        return false;
      }
      try {
        const parsed = JSON.parse(message.content);
        if (parsed && typeof parsed === 'object' && 'tool_calls' in parsed) {
          return parsed.tool_calls === null;
        }
        if (
          parsed &&
          typeof parsed === 'object' &&
          typeof parsed.content === 'string'
        ) {
          const nested = JSON.parse(parsed.content);
          if (nested && typeof nested === 'object' && 'tool_calls' in nested) {
            return nested.tool_calls === null;
          }
        }
      } catch {
        // ignore parse errors
      }
      return false;
    }).length;
  }, [messages]);

  const handleClose = React.useCallback(() => {
    onClose();
  }, [onClose]);

  // 大幅简化逻辑，只在必要时更新
  React.useEffect(() => {
    const filteredToolCalls = toolCalls
      .map((toolCall) => {
        const rawName = (toolCall.assistantCall?.name || '').trim();
        if (rawName) {
          return toolCall;
        }
        return {
          ...toolCall,
          assistantCall: {
            ...toolCall.assistantCall,
            name: 'unknown-tool',
          },
        };
      })
      .filter((toolCall) => !!toolCall.assistantCall.name);

    // 只在 toolCalls 长度变化时重新生成快照
    const newSnapshots = filteredToolCalls.map((toolCall, index) => ({
      id: `${index}-${toolCall.assistantCall.timestamp || 'no-timestamp'}`,
      toolCall,
      index,
      timestamp: parseInt(toolCall.assistantCall.timestamp || toolCall.toolResult?.timestamp || '0') || index,
    }));

    setToolCallSnapshots(newSnapshots);

    // 仅在初始化时设置索引
    if (!isInitialized && newSnapshots.length > 0) {
      setInternalIndex(newSnapshots.length - 1);
      setIsInitialized(true);
    }
  }, [toolCalls, isInitialized]); // 依赖完整数组，确保过滤条件变化可生效

  // 简化的索引同步，完全避免 toolCallSnapshots 依赖
  React.useEffect(() => {
    setInternalIndex(currentIndex);
  }, [currentIndex]);

  const safeInternalIndex = Math.min(internalIndex, Math.max(0, toolCallSnapshots.length - 1));
  const currentSnapshot = toolCallSnapshots[safeInternalIndex];
  const currentToolCall = currentSnapshot?.toolCall;
  const totalCalls = toolCallSnapshots.length;

  const completedToolCalls = toolCallSnapshots.filter(snapshot =>
    snapshot.toolCall.toolResult?.content &&
    snapshot.toolCall.toolResult.content !== 'STREAMING'
  );
  const totalCompletedCalls = completedToolCalls.length;

  const displayToolCall = currentToolCall;
  let displayIndex = safeInternalIndex;
  let displayTotalCalls = totalCalls;

  const isCurrentToolStreaming = currentToolCall?.toolResult?.content === 'STREAMING';

  // 🚨 修复：如果当前工具正在streaming，应该显示streaming状态而不是切换到已完成项
  if (isCurrentToolStreaming) {
    // 保持显示当前streaming的工具，这样TaskView可以正确显示loading状态
    // displayToolCall 保持为 currentToolCall（默认值）
  } else if (!isCurrentToolStreaming) {
    const completedIndex = completedToolCalls.findIndex(snapshot => snapshot.id === currentSnapshot?.id);
    if (completedIndex >= 0) {
      displayIndex = completedIndex;
      displayTotalCalls = totalCompletedCalls;
    }
  }

  const isStreaming = displayToolCall?.toolResult?.content === 'STREAMING';

  // Extract actual success value from tool content with fallbacks
  const getActualSuccess = (toolCall: any): boolean => {
    const content = toolCall?.toolResult?.content;
    if (!content) return toolCall?.toolResult?.isSuccess ?? true;

    const safeParse = (data: any) => {
      try { return typeof data === 'string' ? JSON.parse(data) : data; }
      catch { return null; }
    };

    const parsed = safeParse(content);
    if (!parsed) return toolCall?.toolResult?.isSuccess ?? true;

    if (parsed.content) {
      const inner = safeParse(parsed.content);
      if (inner?.tool_execution?.result?.success !== undefined) {
        return inner.tool_execution.result.success;
      }
    }
    const success = parsed.tool_execution?.result?.success ??
      parsed.result?.success ??
      parsed.success;

    return success !== undefined ? success : (toolCall?.toolResult?.isSuccess ?? true);
  };

  const isSuccess = isStreaming ? true : getActualSuccess(displayToolCall);

  const internalNavigate = React.useCallback((newIndex: number, source: string = 'internal') => {
    if (newIndex < 0 || newIndex >= totalCalls) return;

    const isNavigatingToLatest = newIndex === totalCalls - 1;
    setInternalIndex(newIndex);

    if (isNavigatingToLatest) {
      setNavigationMode('live');
    } else {
      setNavigationMode('manual');
    }

    if (source === 'user_explicit') {
      onNavigate(newIndex);
    }
  }, [totalCalls, onNavigate]);

  const isLiveMode = navigationMode === 'live';
  const showJumpToLive = navigationMode === 'manual' && agentStatus === 'running';
  const showJumpToLatest = navigationMode === 'manual' && agentStatus !== 'running';

  const navigateToPrevious = React.useCallback(() => {
    // 🔧 修复：在streaming状态下也允许导航到之前的任务
    if (displayIndex > 0) {
      // 如果当前正在streaming，直接使用toolCallSnapshots而不是completedToolCalls
      const targetSnapshots = isCurrentToolStreaming ? toolCallSnapshots : completedToolCalls;
      const targetIndex = displayIndex - 1;
      const targetSnapshot = targetSnapshots[targetIndex];
      
      if (targetSnapshot) {
        const actualIndex = toolCallSnapshots.findIndex(s => s.id === targetSnapshot.id);
        if (actualIndex >= 0) {
          setNavigationMode('manual');
          internalNavigate(actualIndex, 'user_explicit');
        }
      }
    }
  }, [displayIndex, isCurrentToolStreaming, completedToolCalls, toolCallSnapshots, internalNavigate]);

  const navigateToNext = React.useCallback(() => {
    // 🔧 修复：在streaming状态下也允许导航到后面的任务
    if (displayIndex < displayTotalCalls - 1) {
      // 如果当前正在streaming，直接使用toolCallSnapshots而不是completedToolCalls
      const targetSnapshots = isCurrentToolStreaming ? toolCallSnapshots : completedToolCalls;
      const targetIndex = displayIndex + 1;
      const targetSnapshot = targetSnapshots[targetIndex];
      
      if (targetSnapshot) {
        const actualIndex = toolCallSnapshots.findIndex(s => s.id === targetSnapshot.id);
        if (actualIndex >= 0) {
          // 如果导航到最后一个，进入live模式
          const isLastTool = targetIndex === targetSnapshots.length - 1;
          if (isLastTool) {
            setNavigationMode('live');
          } else {
            setNavigationMode('manual');
          }
          internalNavigate(actualIndex, 'user_explicit');
        }
      }
    }
  }, [displayIndex, displayTotalCalls, isCurrentToolStreaming, completedToolCalls, toolCallSnapshots, internalNavigate]);

  const jumpToLive = React.useCallback(() => {
    setNavigationMode('live');
    internalNavigate(totalCalls - 1, 'user_explicit');
  }, [totalCalls, internalNavigate]);

  const jumpToLatest = React.useCallback(() => {
    setNavigationMode('manual');
    internalNavigate(totalCalls - 1, 'user_explicit');
  }, [totalCalls, internalNavigate]);

  const renderStatusButton = React.useCallback(() => {
    const baseClasses = "flex items-center justify-center gap-1.5 px-2 py-0.5 rounded-full w-[116px]";
    const dotClasses = "w-1.5 h-1.5 rounded-full";
    const textClasses = "text-xs font-medium";

    if (isLiveMode) {
      if (agentStatus === 'running') {
        return (
          <div className={`${baseClasses} bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800`}>
            <div className={`${dotClasses} bg-green-500 animate-pulse`} />
            <span className={`${textClasses} text-green-700 dark:text-green-400`}>Live Updates</span>
          </div>
        );
      } else {
        return (
          <div className={`${baseClasses} bg-neutral-50 dark:bg-neutral-900/20 border border-neutral-200 dark:border-neutral-800`}>
            <div className={`${dotClasses} bg-neutral-500`} />
            <span className={`${textClasses} text-neutral-700 dark:text-neutral-400`}>Latest Tool</span>
          </div>
        );
      }
    } else {
      if (agentStatus === 'running') {
        return (
          <div
            className={`${baseClasses} bg-green-50 dark:bg-green-900/20 border border-green-200 dark:border-green-800 hover:bg-green-100 dark:hover:bg-green-900/30 transition-colors cursor-pointer`}
            onClick={jumpToLive}
          >
            <div className={`${dotClasses} bg-green-500 animate-pulse`} />
            <span className={`${textClasses} text-green-700 dark:text-green-400`}>Jump to Live</span>
          </div>
        );
      } else {
        return (
          <div
            className={`${baseClasses} bg-blue-50 dark:bg-blue-900/20 border border-blue-200 dark:border-blue-800 hover:bg-blue-100 dark:hover:bg-blue-900/30 transition-colors cursor-pointer`}
            onClick={jumpToLatest}
          >
            <div className={`${dotClasses} bg-blue-500`} />
            <span className={`${textClasses} text-blue-700 dark:text-blue-400`}>Jump to Latest</span>
          </div>
        );
      }
    }
  }, [isLiveMode, agentStatus, jumpToLive, jumpToLatest]);

  const handleSliderChange = React.useCallback(([newValue]: [number]) => {
    // 🔧 修复：在streaming状态下也允许通过滑动条导航
    const targetSnapshots = isCurrentToolStreaming ? toolCallSnapshots : completedToolCalls;
    const targetSnapshot = targetSnapshots[newValue];
    
    if (targetSnapshot) {
      const actualIndex = toolCallSnapshots.findIndex(s => s.id === targetSnapshot.id);
      if (actualIndex >= 0) {
        const isLastTool = newValue === targetSnapshots.length - 1;
        if (isLastTool) {
          setNavigationMode('live');
        } else {
          setNavigationMode('manual');
        }

        internalNavigate(actualIndex, 'user_explicit');
      }
    }
  }, [isCurrentToolStreaming, completedToolCalls, toolCallSnapshots, internalNavigate]);

  React.useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (event: KeyboardEvent) => {
      // Close panel with Cmd/Ctrl+I
      if ((event.metaKey || event.ctrlKey) && event.key === 'i') {
        event.preventDefault();
        handleClose();
        return;
      }

      // 🎯 新增：使用左右箭头键导航任务
      if (event.key === 'ArrowLeft') {
        event.preventDefault();
        navigateToPrevious();
      } else if (event.key === 'ArrowRight') {
        event.preventDefault();
        navigateToNext();
      }
    };

    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [isOpen, handleClose, navigateToPrevious, navigateToNext]);

  React.useEffect(() => {
    if (!isOpen) return;
    const handleSidebarToggle = (event: CustomEvent) => {
      if (event.detail.expanded) {
        handleClose();
      }
    };

    window.addEventListener(
      'sidebar-left-toggled',
      handleSidebarToggle as EventListener,
    );
    return () =>
      window.removeEventListener(
        'sidebar-left-toggled',
        handleSidebarToggle as EventListener,
      );
  }, [isOpen, handleClose]);

  React.useEffect(() => {
    if (externalNavigateToIndex !== undefined && externalNavigateToIndex >= 0 && externalNavigateToIndex < totalCalls) {
      internalNavigate(externalNavigateToIndex, 'external_click');
    }
  }, [externalNavigateToIndex, totalCalls, internalNavigate]);

  React.useEffect(() => {
    if (!isMobile || !isOpen) {
      return;
    }

    const active = document.activeElement;
    if (active instanceof HTMLElement) {
      active.blur();
    }
  }, [isMobile, isOpen]);

  if (!isOpen) {
    return null;
  }

  if (isLoading) {
    if (isMobile) {
      return (
        <Drawer open={isOpen} onOpenChange={(open) => !open && onClose()}>
          <DrawerContent className="h-[85vh]">
            <DrawerDescription className="sr-only">
              Tool activity details panel
            </DrawerDescription>
            <PanelHeader 
              agentName={agentName}
              onClose={handleClose}
              variant="drawer"
            />
            
            <div className="flex-1 p-4 overflow-auto">
              <div className="space-y-4">
                <Skeleton className="h-8 w-32" />
                <Skeleton className="h-20 w-full rounded-md" />
                <Skeleton className="h-40 w-full rounded-md" />
                <Skeleton className="h-20 w-full rounded-md" />
              </div>
            </div>
          </DrawerContent>
        </Drawer>
      );
    }

    return (
      <div className="fixed inset-0 z-30 pointer-events-none">
        <div className="p-4 h-full flex items-stretch justify-end pointer-events-auto">
          <div className="border rounded-2xl flex flex-col shadow-2xl bg-background w-[90%] sm:w-[450px] md:w-[500px] lg:w-[550px] xl:w-[650px]">
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="flex flex-col h-full">
                <PanelHeader 
                  agentName={agentName}
                  onClose={handleClose}
                  showMinimize={true}
                />
                <div className="flex-1 p-4 overflow-auto">
                  <div className="space-y-4">
                    <Skeleton className="h-8 w-32" />
                    <Skeleton className="h-20 w-full rounded-md" />
                    <Skeleton className="h-40 w-full rounded-md" />
                    <Skeleton className="h-20 w-full rounded-md" />
                  </div>
                </div>
              </div>
            </div>
          </div>
        </div>
      </div>
    );
  }

  const renderContent = () => {
    if (!displayToolCall && toolCallSnapshots.length === 0) {
      const isAgentBusy =
        agentStatus === 'running' || agentStatus === 'connecting';

      if (isAgentBusy) {
        return (
          <div className="flex flex-col h-full">
            {!isMobile && (
              <PanelHeader
                agentName={agentName}
                onClose={handleClose}
                isStreaming={true}
              />
            )}
            <div className="flex flex-col items-center justify-center flex-1 p-8">
              <div className="flex flex-col items-center space-y-4 max-w-sm text-center">
                <div className="relative">
                  <div className="w-16 h-16 bg-blue-50 dark:bg-blue-900/20 rounded-full flex items-center justify-center">
                    <CircleDashed className="h-8 w-8 text-blue-500 dark:text-blue-400 animate-spin" />
                  </div>
                </div>
                <div className="space-y-2">
                  <h3 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
                    Preparing tool activity
                  </h3>
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                    Deep search is running. Tool calls will appear here as soon as they are emitted.
                  </p>
                </div>
              </div>
            </div>
          </div>
        );
      }

      if (assistantWithoutToolsCount > 0) {
        return (
          <div className="flex flex-col h-full">
            {!isMobile && (
              <PanelHeader
                agentName={agentName}
                onClose={handleClose}
              />
            )}
            <div className="flex flex-col items-center justify-center flex-1 p-8">
              <div className="flex flex-col items-center space-y-4 max-w-sm text-center">
                <div className="relative">
                  <div className="w-16 h-16 bg-amber-50 dark:bg-amber-900/20 rounded-full flex items-center justify-center">
                    <Computer className="h-8 w-8 text-amber-500 dark:text-amber-400" />
                  </div>
                </div>
                <div className="space-y-2">
                  <h3 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
                    No executable tool calls
                  </h3>
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                    This run returned assistant text only (`tool_calls: null`), so there is no tool activity timeline to display.
                  </p>
                </div>
              </div>
            </div>
          </div>
        );
      }

      return (
        <div className="flex flex-col h-full">
          {!isMobile && (
            <PanelHeader 
              agentName={agentName}
              onClose={handleClose}
            />
          )}
          <div className="flex flex-col items-center justify-center flex-1 p-8">
            <div className="flex flex-col items-center space-y-4 max-w-sm text-center">
              <div className="relative">
                <div className="w-16 h-16 bg-zinc-100 dark:bg-zinc-800 rounded-full flex items-center justify-center">
                  <Computer className="h-8 w-8 text-zinc-400 dark:text-zinc-500" />
                </div>
                <div className="absolute -bottom-1 -right-1 w-6 h-6 bg-zinc-200 dark:bg-zinc-700 rounded-full flex items-center justify-center">
                  <div className="w-2 h-2 bg-zinc-400 dark:text-zinc-500 rounded-full"></div>
                </div>
              </div>
              <div className="space-y-2">
                <h3 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
                  No tool activity
                </h3>
                <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                  Tool calls and computer interactions will appear here when they're being executed.
                </p>
              </div>
            </div>
          </div>
        </div>
      );
    }

    if (!displayToolCall && toolCallSnapshots.length > 0) {
      const firstStreamingTool = toolCallSnapshots.find(s => s.toolCall.toolResult?.content === 'STREAMING');
      if (firstStreamingTool && totalCompletedCalls === 0) {
        return (
          <div className="flex flex-col h-full">
            {!isMobile && (
              <PanelHeader 
                agentName={agentName}
                onClose={handleClose}
                isStreaming={true}
              />
            )}
            {isMobile && (
              <div className="px-4 pb-2">
                <div className="flex items-center justify-center">
                  <div className="px-2.5 py-0.5 rounded-full text-xs font-medium bg-blue-50 text-blue-700 dark:bg-blue-900/20 dark:text-blue-400 flex items-center gap-1.5">
                    <CircleDashed className="h-3 w-3 animate-spin" />
                    <span>Running</span>
                  </div>
                </div>
              </div>
            )}
            <div className="flex flex-col items-center justify-center flex-1 p-8">
              <div className="flex flex-col items-center space-y-4 max-w-sm text-center">
                <div className="relative">
                  <div className="w-16 h-16 bg-blue-50 dark:bg-blue-900/20 rounded-full flex items-center justify-center">
                    <CircleDashed className="h-8 w-8 text-blue-500 dark:text-blue-400 animate-spin" />
                  </div>
                </div>
                <div className="space-y-2">
                  <h3 className="text-lg font-medium text-zinc-900 dark:text-zinc-100">
                    Tool is running
                  </h3>
                  <p className="text-sm text-zinc-500 dark:text-zinc-400 leading-relaxed">
                    {getUserFriendlyToolName(firstStreamingTool.toolCall.assistantCall.name || 'Tool')} is currently executing. Results will appear here when complete.
                  </p>
                </div>
              </div>
            </div>
          </div>
        );
      }

      return (
        <div className="flex flex-col h-full">
          {!isMobile && (
            <PanelHeader 
              agentName={agentName}
              onClose={handleClose}
            />
          )}
          <div className="flex-1 p-4 overflow-auto">
            <div className="space-y-4">
              <Skeleton className="h-8 w-32" />
              <Skeleton className="h-20 w-full rounded-md" />
            </div>
          </div>
        </div>
      );
    }

    const toolView = (
      <ToolView
        name={displayToolCall.assistantCall.name}
        assistantContent={displayToolCall.assistantCall.content}
        toolContent={displayToolCall.toolResult?.content}
        assistantTimestamp={displayToolCall.assistantCall.timestamp}
        toolTimestamp={displayToolCall.toolResult?.timestamp}
        isSuccess={isSuccess}
        isStreaming={isStreaming}
        project={project}
        messages={messages}
        agentStatus={agentStatus}
        agentName={agentName}
        currentIndex={displayIndex}
        totalCalls={displayTotalCalls}
        onFileClick={onFileClick}
      />
    );

    return (
      <div className="flex flex-col h-full">
        {!isMobile && (
          <PanelHeader 
            agentName={agentName}
            onClose={handleClose}
            isStreaming={isStreaming}
            variant="motion"
            hasToolResult={!!displayToolCall.toolResult?.content}
            layoutId={CONTENT_LAYOUT_ID}
          />
        )}

        <div className="flex-1 overflow-auto scrollbar-thin scrollbar-thumb-zinc-300 dark:scrollbar-thumb-zinc-700 scrollbar-track-transparent">
          {toolView}
        </div>
      </div>
    );
  };

  // Mobile version - use drawer
  if (isMobile) {
    return (
      <Drawer open={isOpen} onOpenChange={(open) => !open && onClose()}>
        <DrawerContent className="h-[85vh]">
          <DrawerDescription className="sr-only">
            Tool activity details panel
          </DrawerDescription>
          <PanelHeader 
            agentName={agentName}
            onClose={handleClose}
            variant="drawer"
          />
          
          <div className="flex-1 flex flex-col overflow-hidden">
            {renderContent()}
          </div>
          
          {(displayTotalCalls > 1 || (isCurrentToolStreaming && totalCompletedCalls > 0)) && (
            <div className="border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 p-3">
              <div className="flex items-center justify-between">
                <Button
                  variant="outline"
                  size="sm"
                  onClick={navigateToPrevious}
                  disabled={displayIndex <= 0}
                  className="h-8 px-2.5 text-xs"
                >
                  <ChevronLeft className="h-3.5 w-3.5 mr-1" />
                  <span>Prev</span>
                </Button>

                <div className="flex items-center gap-1.5">
                  <span className="text-xs text-zinc-600 dark:text-zinc-400 font-medium tabular-nums min-w-[44px]">
                    {displayIndex + 1}/{displayTotalCalls}
                  </span>
                  {renderStatusButton()}
                </div>

                <Button
                  variant="outline"
                  size="sm"
                  onClick={navigateToNext}
                  disabled={displayIndex >= displayTotalCalls - 1}
                  className="h-8 px-2.5 text-xs"
                >
                  <span>Next</span>
                  <ChevronRight className="h-3.5 w-3.5 ml-1" />
                </Button>
              </div>
            </div>
          )}
        </DrawerContent>
      </Drawer>
    );
  }

  // Desktop version - use fixed panel
  return (
    <AnimatePresence mode="wait">
      {isOpen && (
        <motion.div
          key="sidepanel"
          layoutId={FLOATING_LAYOUT_ID}
          initial={disableInitialAnimation ? { opacity: 1 } : { opacity: 0 }}
          animate={{ opacity: 1 }}
          exit={{ opacity: 0 }}
          transition={{
            opacity: { duration: disableInitialAnimation ? 0 : 0.15 },
            layout: {
              type: "spring",
              stiffness: 400,
              damping: 35
            }
          }}
          className="fixed top-2 right-2 bottom-4 border rounded-3xl flex flex-col z-30 w-[40vw] sm:w-[450px] md:w-[500px] lg:w-[550px] xl:w-[645px]"
          style={{
            overflow: 'hidden',
          }}
        >
          <div className="flex-1 flex flex-col overflow-hidden bg-card">
            {renderContent()}
          </div>
          {(displayTotalCalls > 1 || (isCurrentToolStreaming && totalCompletedCalls > 0)) && (
            <div className="border-t border-zinc-200 dark:border-zinc-800 bg-zinc-50 dark:bg-zinc-900 px-4 py-2.5">
              <div className="flex items-center gap-3">
                <div className="flex items-center gap-1">
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={navigateToPrevious}
                    disabled={displayIndex <= 0}
                    className="h-7 w-7 text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
                  >
                    <ChevronLeft className="h-4 w-4" />
                  </Button>
                  <span className="text-xs text-zinc-600 dark:text-zinc-400 font-medium tabular-nums px-1 min-w-[44px] text-center">
                    {displayIndex + 1}/{displayTotalCalls}
                  </span>
                  <Button
                    variant="ghost"
                    size="icon"
                    onClick={navigateToNext}
                    disabled={displayIndex >= displayTotalCalls - 1}
                    className="h-7 w-7 text-zinc-500 hover:text-zinc-700 dark:text-zinc-400 dark:hover:text-zinc-200"
                  >
                    <ChevronRight className="h-4 w-4" />
                  </Button>
                </div>

                <div className="flex-1 relative">
                  <Slider
                    min={0}
                    max={displayTotalCalls - 1}
                    step={1}
                    value={[displayIndex]}
                    onValueChange={handleSliderChange}
                    className="w-full [&>span:first-child]:h-1.5 [&>span:first-child]:bg-zinc-200 dark:[&>span:first-child]:bg-zinc-800 [&>span:first-child>span]:bg-zinc-500 dark:[&>span:first-child>span]:bg-zinc-400 [&>span:first-child>span]:h-1.5"
                  />
                </div>

                <div className="flex items-center gap-1.5">
                  {renderStatusButton()}
                </div>
              </div>
            </div>
          )}
        </motion.div>
      )}
    </AnimatePresence>
  );
}


import React, { useMemo } from 'react';
import { ToolViewProps } from '../types';
import { GenericToolView } from '../GenericToolView';
import { BrowserToolView } from '../BrowserToolView';
import { CommandToolView } from '../command-tool/CommandToolView';
import { CheckCommandOutputToolView } from '../command-tool/CheckCommandOutputToolView';
import { ExposePortToolView } from '../expose-port-tool/ExposePortToolView';
import { FileOperationToolView } from '../file-operation/FileOperationToolView';
import { FileEditToolView } from '../file-operation/FileEditToolView';
import { StrReplaceToolView } from '../str-replace/StrReplaceToolView';
import { WebCrawlToolView } from '../WebCrawlToolView';
import { WebScrapeToolView } from '../web-scrape-tool/WebScrapeToolView';
import { WebSearchToolView } from '../web-search-tool/WebSearchToolView';
import { SeeImageToolView } from '../see-image-tool/SeeImageToolView';
import { TerminateCommandToolView } from '../command-tool/TerminateCommandToolView';
import { AskToolView } from '../ask-tool/AskToolView';
import { CompleteToolView } from '../CompleteToolView';
import { ExecuteDataProviderCallToolView } from '../data-provider-tool/ExecuteDataProviderCallToolView';
import { DataProviderEndpointsToolView } from '../data-provider-tool/DataProviderEndpointsToolView';
import { DeployToolView } from '../DeployToolView';
import { SearchMcpServersToolView } from '../search-mcp-servers/search-mcp-servers';
import { GetAppDetailsToolView } from '../get-app-details/get-app-details';
import { CreateCredentialProfileToolView } from '../create-credential-profile/create-credential-profile';
import { ConnectCredentialProfileToolView } from '../connect-credential-profile/connect-credential-profile';
import { CheckProfileConnectionToolView } from '../check-profile-connection/check-profile-connection';
import { ConfigureProfileForAgentToolView } from '../configure-profile-for-agent/configure-profile-for-agent';
import { GetCredentialProfilesToolView } from '../get-credential-profiles/get-credential-profiles';
import { GetCurrentAgentConfigToolView } from '../get-current-agent-config/get-current-agent-config';
import { TaskListToolView } from '../task-list/TaskListToolView';
import { PresentationOutlineToolView } from '../PresentationOutlineToolView';
import { PresentationToolView } from '../PresentationToolView';
import { PresentationToolV2View } from '../PresentationToolV2View';
import { ListPresentationTemplatesToolView } from '../ListPresentationTemplatesToolView';
import { SheetsToolView } from '../sheets-tools/sheets-tool-view';
import { GetProjectStructureView } from '../web-dev/GetProjectStructureView';
import { ImageEditGenerateToolView } from '../image-edit-generate-tool/ImageEditGenerateToolView';


export type ToolViewComponent = React.ComponentType<ToolViewProps>;

type ToolViewRegistryType = Record<string, ToolViewComponent>;

const defaultRegistry: ToolViewRegistryType = {
  // 🌐 Browser-Use工具映射 - 你的后端browser-use工具完整映射
  'browser_navigate_to': BrowserToolView,    // 导航到指定URL (下划线格式)
  'browser-navigate-to': BrowserToolView,    // 导航到指定URL (连字符格式)
  'browser_go_back': BrowserToolView,        // 浏览器后退
  'browser-go-back': BrowserToolView,        // 浏览器后退 (连字符格式)
  'browser_wait': BrowserToolView,           // 等待指定秒数
  'browser-wait': BrowserToolView,           // 等待指定秒数 (连字符格式)
  'browser_click_element': BrowserToolView,  // 点击页面元素
  'browser-click-element': BrowserToolView,  // 点击页面元素 (连字符格式)
  'browser_input_text': BrowserToolView,     // 在元素中输入文本
  'browser-input-text': BrowserToolView,     // 在元素中输入文本 (连字符格式)
  'browser_send_keys': BrowserToolView,      // 发送键盘按键
  'browser-send-keys': BrowserToolView,      // 发送键盘按键 (连字符格式)
  'browser_scroll_down': BrowserToolView,    // 页面向下滚动
  'browser-scroll-down': BrowserToolView,    // 页面向下滚动 (连字符格式)
  'browser_scroll_up': BrowserToolView,      // 页面向上滚动
  'browser-scroll-up': BrowserToolView,      // 页面向上滚动 (连字符格式)
  
  // 🌐 兼容其他Browser工具命名
  'browser-act': BrowserToolView,
  'browser-extract-content': BrowserToolView,
  'browser-screenshot': BrowserToolView,

  // 🚀 ComputerUse工具映射 - 后端所有10个工具方法 (支持多种命名格式)
  'move_to': BrowserToolView,        // 移动鼠标到指定坐标 (下划线格式)
  'move-to': BrowserToolView,        // 移动鼠标到指定坐标 (连字符格式) 
  'click': BrowserToolView,          // 点击指定坐标
  'scroll': BrowserToolView,         // 滚轮滚动
  'typing': BrowserToolView,         // 输入文字
  'press': BrowserToolView,          // 按键操作
  'wait': BrowserToolView,           // 等待指定时间
  'mouse_down': BrowserToolView,     // 鼠标按下 (下划线格式)
  'mouse-down': BrowserToolView,     // 鼠标按下 (连字符格式)
  'mouse_up': BrowserToolView,       // 鼠标松开 (下划线格式)
  'mouse-up': BrowserToolView,       // 鼠标松开 (连字符格式)
  'drag_to': BrowserToolView,        // 拖拽到指定位置 (下划线格式)
  'drag-to': BrowserToolView,        // 拖拽到指定位置 (连字符格式)
  'screenshot': BrowserToolView,     // 截图
  'hotkey': BrowserToolView,         // 热键组合
  'key': BrowserToolView,            // 按键 (可能的替代名称)
  'type': BrowserToolView,           // 输入 (可能的替代名称)

  'execute-command': CommandToolView,
  'check-command-output': CheckCommandOutputToolView,
  'terminate-command': TerminateCommandToolView,
  'list-commands': GenericToolView,

  'create-file': FileOperationToolView,
  'delete-file': FileOperationToolView,
  'full-file-rewrite': FileOperationToolView,
  'read-file': FileOperationToolView,
  'edit-file': FileEditToolView,

  'str-replace': StrReplaceToolView,

  'web-search': WebSearchToolView,
  'crawl-webpage': WebCrawlToolView,
  'scrape-webpage': WebScrapeToolView,

  'execute-data-provider-call': ExecuteDataProviderCallToolView,
  'get-data-provider-endpoints': DataProviderEndpointsToolView,

  'search-mcp-servers': SearchMcpServersToolView,
  'get-app-details': GetAppDetailsToolView,
  'create-credential-profile': CreateCredentialProfileToolView,
  'connect-credential-profile': ConnectCredentialProfileToolView,
  'check-profile-connection': CheckProfileConnectionToolView,
  'configure-profile-for-agent': ConfigureProfileForAgentToolView,
  'get-credential-profiles': GetCredentialProfilesToolView,
  'get-current-agent-config': GetCurrentAgentConfigToolView,
  // Task management tools - support both underscore and hyphen formats
  'create-tasks': TaskListToolView,
  'create_tasks': TaskListToolView, // Backend format
  'view-tasks': TaskListToolView,
  'view_tasks': TaskListToolView, // Backend format
  'update-tasks': TaskListToolView,
  'update_tasks': TaskListToolView, // Backend format
  'delete-tasks': TaskListToolView,
  'delete_tasks': TaskListToolView, // Backend format
  'clear-all': TaskListToolView,


  'expose-port': ExposePortToolView,

  'see-image': SeeImageToolView,
  'image-edit-or-generate': ImageEditGenerateToolView,

  'ask': AskToolView,
  'complete': CompleteToolView,

  'deploy': DeployToolView,

  'create-presentation-outline': PresentationOutlineToolView,
  'create-presentation': PresentationToolV2View,
  'export-presentation': PresentationToolV2View,
  'list-presentation-templates': ListPresentationTemplatesToolView,
  
  'create-sheet': SheetsToolView,
  'update-sheet': SheetsToolView,
  'view-sheet': SheetsToolView,
  'analyze-sheet': SheetsToolView,
  'visualize-sheet': SheetsToolView,
  'format-sheet': SheetsToolView,

  'get-project-structure': GetProjectStructureView,
  'list-web-projects': GenericToolView,

  'default': GenericToolView,
};

class ToolViewRegistry {
  private registry: ToolViewRegistryType;

  constructor(initialRegistry: Partial<ToolViewRegistryType> = {}) {
    this.registry = { ...defaultRegistry };

    Object.entries(initialRegistry).forEach(([key, value]) => {
      if (value !== undefined) {
        this.registry[key] = value;
      }
    });
  }

  register(toolName: string, component: ToolViewComponent): void {
    this.registry[toolName] = component;
  }

  registerMany(components: Partial<ToolViewRegistryType>): void {
    Object.assign(this.registry, components);
  }

  get(toolName: string): ToolViewComponent {
    return this.registry[toolName] || this.registry['default'];
  }

  has(toolName: string): boolean {
    return toolName in this.registry;
  }

  getToolNames(): string[] {
    return Object.keys(this.registry).filter(key => key !== 'default');
  }

  clear(): void {
    this.registry = { default: this.registry['default'] };
  }
}

export const toolViewRegistry = new ToolViewRegistry();

export function useToolView(toolName: string): ToolViewComponent {
  return useMemo(() => toolViewRegistry.get(toolName), [toolName]);
}

export const ToolView = React.memo(function ToolView({ name = 'default', ...props }: ToolViewProps) {
  const ToolViewComponent = useToolView(name);
  return <ToolViewComponent name={name} {...props} />;
});
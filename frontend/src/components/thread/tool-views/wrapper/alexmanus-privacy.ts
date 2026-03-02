const ALEXMANUS_COMPUTER_TOOL_NAMES = new Set([
  'browser_navigate_to',
  'browser-navigate-to',
  'browser_go_back',
  'browser-go-back',
  'browser_wait',
  'browser-wait',
  'browser_click_element',
  'browser-click-element',
  'browser_input_text',
  'browser-input-text',
  'browser_send_keys',
  'browser-send-keys',
  'browser_scroll_down',
  'browser-scroll-down',
  'browser_scroll_up',
  'browser-scroll-up',
  'browser-act',
  'browser-extract-content',
  'browser-screenshot',
  'move_to',
  'move-to',
  'click',
  'scroll',
  'typing',
  'press',
  'wait',
  'mouse_down',
  'mouse-down',
  'mouse_up',
  'mouse-up',
  'drag_to',
  'drag-to',
  'screenshot',
  'hotkey',
  'key',
  'type',
]);

export function shouldUseAlexManusComputerPrivacyView(
  agentName?: string,
  toolName?: string,
): boolean {
  const normalizedAgentName = (agentName || '').trim().toLowerCase();
  if (!normalizedAgentName.includes('alexmanus')) {
    return false;
  }
  return ALEXMANUS_COMPUTER_TOOL_NAMES.has(toolName || '');
}

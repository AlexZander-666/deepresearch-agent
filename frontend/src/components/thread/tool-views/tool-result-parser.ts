/**
 * Tool Result Parser for handling both old and new tool result formats
 * 
 * Supports:
 * - New structured format with tool_execution
 * - Legacy XML-wrapped format
 * - Legacy direct format
 */

export interface ParsedToolResult {
  toolName: string;
  functionName: string;
  xmlTagName?: string;
  toolOutput: string;
  isSuccess: boolean;
  arguments?: Record<string, any>;
  timestamp?: string;
  toolCallId?: string;
  summary?: string;
}

function isLikelyFailureText(text: string): boolean {
  const normalized = text.trim().toLowerCase();
  if (!normalized) return false;
  if (normalized === 'streaming') return false;

  return (
    normalized.startsWith('failed') ||
    normalized.includes('failed to') ||
    normalized.includes('error:') ||
    normalized.includes('errors:') ||
    normalized.includes('exception') ||
    normalized.includes('traceback') ||
    normalized.includes('timed out') ||
    normalized.includes('timeout') ||
    normalized.includes('could not') ||
    normalized.includes('unable to') ||
    normalized.includes('permission denied')
  );
}

function inferSuccess(
  explicitSuccess: boolean | undefined,
  output: unknown,
): boolean {
  if (typeof explicitSuccess === 'boolean') {
    return explicitSuccess;
  }

  if (typeof output === 'string') {
    return !isLikelyFailureText(output);
  }

  return true;
}

/**
 * Parse tool result content from various formats
 */
export function parseToolResult(content: any): ParsedToolResult | null {
  try {
    // Handle string content
    if (typeof content === 'string') {
      return parseStringToolResult(content);
    }

    // Handle object content
    if (typeof content === 'object' && content !== null) {
      return parseObjectToolResult(content);
    }

    return null;
  } catch (error) {
    console.error('Error parsing tool result:', error);
    return null;
  }
}

/**
 * Parse string-based tool result (legacy format)
 */
function parseStringToolResult(content: string): ParsedToolResult | null {
  // Try to parse as JSON first
  try {
    const parsed = JSON.parse(content);
    if (typeof parsed === 'object') {
      return parseObjectToolResult(parsed);
    }
  } catch {
    // Not JSON, continue with string parsing
  }

  // Extract tool name from XML tags
  const toolMatch = content.match(/<\/?([\w-]+)>/);
  const toolName = toolMatch ? toolMatch[1] : 'unknown';

  // Check for success in ToolResult format
  let isSuccess = true;
  if (content.includes('ToolResult')) {
    const successMatch = content.match(/success\s*=\s*(True|False|true|false)/i);
    if (successMatch) {
      isSuccess = successMatch[1].toLowerCase() === 'true';
    }
  } else {
    isSuccess = inferSuccess(undefined, content);
  }

  return {
    toolName: toolName.replace(/_/g, '-'),
    functionName: toolName.replace(/-/g, '_'),
    toolOutput: content,
    isSuccess,
  };
}

/**
 * Parse object-based tool result (new and legacy formats)
 */
function parseObjectToolResult(content: any): ParsedToolResult | null {
  // New structured format with tool_execution
  if ('tool_execution' in content && typeof content.tool_execution === 'object') {
    const toolExecution = content.tool_execution;
    const functionName = toolExecution.function_name || 'unknown';
    const xmlTagName = toolExecution.xml_tag_name || '';
    const toolName = (xmlTagName || functionName).replace(/_/g, '-');
    const output = toolExecution.result?.output || '';
    const explicitSuccess =
      typeof toolExecution.result?.success === 'boolean'
        ? toolExecution.result.success
        : undefined;

    return {
      toolName,
      functionName,
      xmlTagName: xmlTagName || undefined,
      toolOutput: output,
      isSuccess: inferSuccess(explicitSuccess, output),
      arguments: toolExecution.arguments,
      timestamp: toolExecution.execution_details?.timestamp,
      toolCallId: toolExecution.tool_call_id,
      summary: content.summary,
    };
  }

  // Handle nested format with role and content
  if ('role' in content && 'content' in content && typeof content.content === 'object') {
    const nestedContent = content.content;
    
    // Check for new structured format nested in content
    if ('tool_execution' in nestedContent && typeof nestedContent.tool_execution === 'object') {
      return parseObjectToolResult(nestedContent);
    }

    // Legacy format with tool_name/xml_tag_name
    if ('tool_name' in nestedContent || 'xml_tag_name' in nestedContent) {
      const toolName = (nestedContent.tool_name || nestedContent.xml_tag_name || 'unknown').replace(/_/g, '-');
      
      // Handle both object and string result formats
      let toolOutput = '';
      let isSuccess = true;
      
      if (typeof nestedContent.result === 'string') {
        // Result is a string
        toolOutput = nestedContent.result;
        isSuccess = inferSuccess(
          typeof nestedContent.success === 'boolean' ? nestedContent.success : undefined,
          toolOutput,
        );
      } else if (typeof nestedContent.result === 'object' && nestedContent.result) {
        // Result is an object
        toolOutput = nestedContent.result.output || '';
        isSuccess = inferSuccess(
          typeof nestedContent.result.success === 'boolean'
            ? nestedContent.result.success
            : (typeof nestedContent.success === 'boolean' ? nestedContent.success : undefined),
          toolOutput,
        );
      } else {
        // Fallback
        toolOutput = nestedContent.result || '';
        isSuccess = inferSuccess(
          typeof nestedContent.success === 'boolean' ? nestedContent.success : undefined,
          toolOutput,
        );
      }
      
      return {
        toolName,
        functionName: toolName.replace(/-/g, '_'),
        toolOutput,
        isSuccess,
      };
    }
  }

  // Handle nested format with role and string content
  if ('role' in content && 'content' in content && typeof content.content === 'string') {
    return parseStringToolResult(content.content);
  }

  // Legacy direct format
  if ('tool_name' in content || 'xml_tag_name' in content) {
    const toolName = (content.tool_name || content.xml_tag_name || 'unknown').replace(/_/g, '-');

    // Handle both object and string result formats
    let toolOutput = '';
    let isSuccess = true;
    
    if (typeof content.result === 'string') {
      // Result is a string (your format)
      toolOutput = content.result;
      isSuccess = inferSuccess(
        typeof content.success === 'boolean' ? content.success : undefined,
        toolOutput,
      );
    } else if (typeof content.result === 'object' && content.result) {
      // Result is an object (legacy format)
      toolOutput = content.result.output || '';
      isSuccess = inferSuccess(
        typeof content.result.success === 'boolean'
          ? content.result.success
          : (typeof content.success === 'boolean' ? content.success : undefined),
        toolOutput,
      );
    } else {
      // Fallback: use result directly
      toolOutput = content.result || '';
      isSuccess = inferSuccess(
        typeof content.success === 'boolean' ? content.success : undefined,
        toolOutput,
      );
    }
    
    const result = {
      toolName,
      functionName: toolName.replace(/-/g, '_'),
      toolOutput,
      isSuccess,
    };
    
    return result;
  }

  return null;
}

/**
 * Check if content contains a tool result
 */
export function isToolResult(content: any): boolean {
  if (typeof content === 'string') {
    return content.includes('<tool_result>') || content.includes('ToolResult');
  }

  if (typeof content === 'object' && content !== null) {
    return (
      'tool_execution' in content ||
      ('role' in content && 'content' in content) ||
      'tool_name' in content ||
      'xml_tag_name' in content
    );
  }

  return false;
}

/**
 * Format tool name for display (convert kebab-case to Title Case)
 */
export function formatToolNameForDisplay(toolName: string): string {
  return toolName
    .split('-')
    .map(word => word.charAt(0).toUpperCase() + word.slice(1))
    .join(' ');
} 

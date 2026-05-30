'use strict';

const path = require('path');
const { ToolCallSchema } = require('./schemas');
const {
  SAFE_WORKSPACE_ROOT,
  FORBIDDEN_COMMAND_PATTERNS,
  BLOCKED_PATH_SNIPPETS,
} = require('./constants');

function isBlockedPath(candidatePath) {
  const normalized = candidatePath.replace(/\\/g, '/');
  return BLOCKED_PATH_SNIPPETS.some((snippet) => normalized.includes(snippet));
}

function sanitizeText(input) {
  if (typeof input !== 'string') return input;
  return input.replace(/[\u0000-\u001f\u007f]/g, '').trim();
}

function assertSafeWorkspacePath(userPath) {
  if (typeof userPath !== 'string' || userPath.length === 0) {
    throw new Error('Invalid path');
  }

  const cleaned = sanitizeText(userPath);
  if (path.isAbsolute(cleaned)) {
    throw new Error('Absolute paths are not allowed');
  }
  if (isBlockedPath(cleaned)) {
    throw new Error('Path is blocked by security policy');
  }

  // Resolve strictly as relative path inside /safe_workspace
  const normalizedRelative = cleaned
    .replace(/^(\.\.(\/|\\|$))+/, '')
    .replace(/^\/+/, '');
  const resolved = path.resolve(SAFE_WORKSPACE_ROOT, normalizedRelative);
  const workspaceWithSep = `${SAFE_WORKSPACE_ROOT}${path.sep}`;

  if (resolved !== SAFE_WORKSPACE_ROOT && !resolved.startsWith(workspaceWithSep)) {
    throw new Error('Path escapes safe workspace');
  }

  return resolved;
}

function rejectDestructiveInput(payload) {
  const text = JSON.stringify(payload);
  for (const pattern of FORBIDDEN_COMMAND_PATTERNS) {
    if (pattern.test(text)) {
      throw new Error('Destructive operation blocked by policy');
    }
  }
}

function validateToolCall(body) {
  const parsed = ToolCallSchema.safeParse(body);
  if (!parsed.success) {
    const msg = parsed.error.issues.map((i) => i.message).join('; ');
    throw new Error(`Validation failed: ${msg}`);
  }

  const toolCall = {
    tool: parsed.data.tool,
    args: parsed.data.args,
  };

  rejectDestructiveInput(toolCall);

  // Tool-specific guardrails
  if (toolCall.tool.startsWith('fs.')) {
    const p = toolCall.args.path;
    toolCall.args.path = assertSafeWorkspacePath(String(p || ''));
  }

  // limit content size for writes/updates
  if (toolCall.args.content && typeof toolCall.args.content === 'string') {
    toolCall.args.content = sanitizeText(toolCall.args.content).slice(0, 5000);
  }

  if (toolCall.args.title && typeof toolCall.args.title === 'string') {
    toolCall.args.title = sanitizeText(toolCall.args.title).slice(0, 120);
  }

  return toolCall;
}

function sanitizeOutput(output) {
  // Never leak tokens/secrets if upstream accidentally includes them.
  const asText = JSON.stringify(output);
  const redacted = asText
    .replace(/(secret|token|api[_-]?key|authorization)\s*[:=]\s*["'][^"']+["']/gi, '$1:"[REDACTED]"')
    .replace(/YOUR_NOTION_TOKEN_HERE/g, '[REDACTED_PLACEHOLDER]');

  return JSON.parse(redacted);
}

module.exports = {
  validateToolCall,
  sanitizeOutput,
  assertSafeWorkspacePath,
};

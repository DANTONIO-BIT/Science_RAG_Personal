'use strict';

/**
 * Shared security constants.
 * Keep policy in one place to avoid accidental drift.
 */

const path = require('path');

// Configurable sandbox root. Defaults to /safe_workspace, override with .env if needed.
const SAFE_WORKSPACE_ROOT = path.resolve(process.env.SAFE_WORKSPACE_ROOT || '/safe_workspace');

const FORBIDDEN_COMMAND_PATTERNS = [
  /\brm\s+-rf\b/i,
  /\bdelete\b/i,
  /\bpurge\b/i,
  /\btruncate\b/i,
  /\bmkfs\b/i,
  /\bdd\b/i,
];

const BLOCKED_PATH_SNIPPETS = [
  '.env',
  '/tmp',
  '/etc',
  '/var',
  '/private',
  '/proc',
  '/sys',
  '/dev',
  '/Users', // block direct traversal into user home/system locations
];

module.exports = {
  SAFE_WORKSPACE_ROOT,
  FORBIDDEN_COMMAND_PATTERNS,
  BLOCKED_PATH_SNIPPETS,
};

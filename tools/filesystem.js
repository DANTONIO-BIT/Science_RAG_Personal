'use strict';

const fs = require('fs/promises');
const pathLib = require('path');

/**
 * Filesystem tool with strict policy:
 *  - read/write ONLY on gateway-validated path in /safe_workspace
 *  - no delete APIs exposed
 *  - no shell execution
 */

async function readFileSafe({ path }) {
  const content = await fs.readFile(path, 'utf8');
  return {
    path,
    content: content.slice(0, 20000), // output limit
  };
}

async function writeFileSafe({ path, content }) {
  await fs.mkdir(pathLib.dirname(path), { recursive: true, mode: 0o700 });
  await fs.writeFile(path, String(content || ''), { encoding: 'utf8', flag: 'w', mode: 0o600 });
  return {
    ok: true,
    path,
  };
}

module.exports = {
  readFileSafe,
  writeFileSafe,
};

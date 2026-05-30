'use strict';

const { validateToolCall, sanitizeOutput } = require('./validators');

/**
 * Central gateway:
 *  - validate + normalize tool call
 *  - execute only via provided handlers (no arbitrary code)
 *  - sanitize returned data
 */
async function runThroughGateway(body, handlers) {
  const toolCall = validateToolCall(body);

  const handler = handlers[toolCall.tool];
  if (!handler) {
    throw new Error('Tool is not available');
  }

  const result = await handler(toolCall.args);
  return sanitizeOutput(result);
}

module.exports = {
  runThroughGateway,
};

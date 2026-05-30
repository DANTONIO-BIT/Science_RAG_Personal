'use strict';

const { z } = require('zod');

/**
 * Tool allowlist schema.
 * Agent can only call known operations.
 */
const ToolCallSchema = z.object({
  tool: z.enum([
    'notion.readPages',
    'notion.createNote',
    'notion.updateLimitedContent',
    'fs.readFile',
    'fs.writeFile',
  ]),
  args: z.record(z.any()).default({}),
});

module.exports = {
  ToolCallSchema,
};

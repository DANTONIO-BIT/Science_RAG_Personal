'use strict';

const { Client } = require('@notionhq/client');

/**
 * Write operations are intentionally limited:
 *  - create note with constrained title/content length
 *  - append content block only (no delete operations)
 */

function getNotionClient() {
  const token = process.env.NOTION_TOKEN;
  if (!token) {
    throw new Error('NOTION_TOKEN is not configured');
  }
  return new Client({ auth: token });
}

function toSafeRichText(text, maxLen) {
  const safe = String(text || '').replace(/[\u0000-\u001f\u007f]/g, '').trim().slice(0, maxLen);
  return [{ type: 'text', text: { content: safe } }];
}

async function createNote({ title, content }) {
  const databaseId = process.env.NOTION_DATABASE_ID;
  if (!databaseId) {
    throw new Error('NOTION_DATABASE_ID is not configured');
  }

  const notion = getNotionClient();

  const response = await notion.pages.create({
    parent: { database_id: databaseId },
    properties: {
      Name: {
        title: toSafeRichText(title || 'Untitled note', 120),
      },
    },
    children: [
      {
        object: 'block',
        type: 'paragraph',
        paragraph: {
          rich_text: toSafeRichText(content || '', 2000),
        },
      },
    ],
  });

  return {
    ok: true,
    page: {
      id: response.id,
      url: response.url,
      created_time: response.created_time,
    },
  };
}

async function updateLimitedContent({ pageId, content }) {
  const notion = getNotionClient();
  const safePageId = String(pageId || '').trim();
  if (!safePageId) {
    throw new Error('pageId is required');
  }

  const response = await notion.blocks.children.append({
    block_id: safePageId,
    children: [
      {
        object: 'block',
        type: 'paragraph',
        paragraph: {
          rich_text: toSafeRichText(content || '', 2000),
        },
      },
    ],
  });

  return {
    ok: true,
    updated_block_count: response.results.length,
    page_id: safePageId,
  };
}

module.exports = {
  createNote,
  updateLimitedContent,
};

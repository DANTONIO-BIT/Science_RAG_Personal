'use strict';

const { Client } = require('@notionhq/client');

/**
 * Read-only Notion operations.
 * Security:
 *  - token comes only from process.env
 *  - output is mapped to minimal safe fields
 *  - no raw response object is returned
 */

function getNotionClient() {
  const token = process.env.NOTION_TOKEN;
  if (!token) {
    throw new Error('NOTION_TOKEN is not configured');
  }
  return new Client({ auth: token });
}

function mapPage(page) {
  return {
    id: page.id,
    created_time: page.created_time,
    last_edited_time: page.last_edited_time,
    url: page.url,
  };
}

async function readPages({ pageSize = 10 }) {
  const databaseId = process.env.NOTION_DATABASE_ID;
  if (!databaseId) {
    throw new Error('NOTION_DATABASE_ID is not configured');
  }

  const notion = getNotionClient();

  const response = await notion.databases.query({
    database_id: databaseId,
    page_size: Math.min(Math.max(Number(pageSize) || 10, 1), 25),
  });

  return {
    count: response.results.length,
    pages: response.results.map(mapPage),
  };
}

module.exports = {
  readPages,
};

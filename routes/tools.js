'use strict';

const express = require('express');
const { runThroughGateway } = require('../gateway');

const { readPages } = require('../tools/notionRead');
const { createNote, updateLimitedContent } = require('../tools/notionWrite');
const { readFileSafe, writeFileSafe } = require('../tools/filesystem');

const router = express.Router();

const handlers = {
  'notion.readPages': readPages,
  'notion.createNote': createNote,
  'notion.updateLimitedContent': updateLimitedContent,
  'fs.readFile': readFileSafe,
  'fs.writeFile': writeFileSafe,
};

/**
 * Single execution endpoint:
 * Agent sends { tool, args }, gateway validates and dispatches.
 */
router.post('/execute', async (req, res, next) => {
  try {
    const data = await runThroughGateway(req.body, handlers);
    return res.json({ ok: true, data });
  } catch (error) {
    return next(error);
  }
});

module.exports = router;

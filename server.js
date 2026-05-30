/**
 * server.js — Secure AI Agent Backend
 *
 * SECURITY DESIGN:
 *  - Secrets are loaded from process.env ONLY (never passed to the model)
 *  - No raw API responses are forwarded to the agent
 *  - All tool calls go through the gateway validation layer first
 *  - Rate limiting prevents agent abuse
 */

'use strict';

require('dotenv').config(); // Loads .env into process.env at runtime only

const express  = require('express');
const helmet   = require('helmet');
const rateLimit = require('express-rate-limit');

const toolsRouter      = require('./routes/tools');
const requestLogger    = require('./middleware/requestLogger');
const errorHandler     = require('./middleware/errorHandler');

const app  = express();
const PORT = process.env.PORT || 3000;

// ── Security headers ────────────────────────────────────────────────────────
// helmet sets X-Content-Type-Options, X-Frame-Options, HSTS, etc.
app.use(helmet());

// ── Body parsing (hard size limit to prevent payload flooding) ──────────────
app.use(express.json({ limit: '64kb' }));

// ── Rate limiting — prevents model flooding the server ──────────────────────
const limiter = rateLimit({
  windowMs: 60 * 1000, // 1 minute window
  max: 60,             // max 60 requests per minute
  standardHeaders: true,
  legacyHeaders: false,
  message: { error: 'Too many requests — slow down.' },
});
app.use(limiter);

// ── Request logger (NEVER logs secret values) ───────────────────────────────
app.use(requestLogger);

// ── Routes ──────────────────────────────────────────────────────────────────
// All AI tool calls arrive here; the gateway layer validates before execution
app.use('/tools', toolsRouter);

// Health check (no sensitive info exposed)
app.get('/health', (_req, res) => res.json({ status: 'ok' }));

// ── Catch-all 404 ───────────────────────────────────────────────────────────
app.use((_req, res) => res.status(404).json({ error: 'Not found' }));

// ── Global error handler ────────────────────────────────────────────────────
app.use(errorHandler);

app.listen(PORT, '127.0.0.1', () => {
  // Bind to loopback ONLY — never expose to the network
  console.log(`[server] Listening on http://127.0.0.1:${PORT}`);
  console.log('[server] Secrets status: loaded from env, not exposed to model');
});

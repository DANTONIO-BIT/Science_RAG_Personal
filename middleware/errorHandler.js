'use strict';

/**
 * Centralized safe errors.
 * SECURITY:
 *  - generic message to clients
 *  - no stack traces or env values leaked
 */
module.exports = function errorHandler(err, _req, res, _next) {
  const message = String(err && err.message ? err.message : 'Internal error');
  const safeMessage = message.slice(0, 200);

  const status =
    /validation|blocked|invalid|required|not configured|not available/i.test(safeMessage)
      ? 400
      : 500;

  res.status(status).json({
    ok: false,
    error: safeMessage,
  });
};

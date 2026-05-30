'use strict';

/**
 * Logs metadata only (method/path/status/time).
 * SECURITY: avoids logging full body to prevent accidental secret leakage.
 */
module.exports = function requestLogger(req, res, next) {
  const start = Date.now();

  res.on('finish', () => {
    const ms = Date.now() - start;
    console.log(`${req.method} ${req.path} -> ${res.statusCode} (${ms}ms)`);
  });

  next();
};

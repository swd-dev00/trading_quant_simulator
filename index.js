const http = require('http');

const port = Number.parseInt(process.env.PORT, 10) || 8080;
const host = '0.0.0.0';
const SHUTDOWN_TIMEOUT_MS = 10000;

const server = http.createServer((req, res) => {
  const { method, url } = req;
  res.on('finish', () => {
    console.log(`[request] ${method} ${url} -> ${res.statusCode}`);
  });

  if (method === 'GET' && url === '/') {
    res.writeHead(200, { 'Content-Type': 'text/html; charset=utf-8' });
    res.end('<!doctype html><html><body><h1>tradingq up ✅</h1></body></html>');
    return;
  }

  if (method === 'GET' && url === '/healthz') {
    res.writeHead(200, { 'Content-Type': 'application/json; charset=utf-8' });
    res.end(JSON.stringify({ ok: true }));
    return;
  }

  res.writeHead(404, { 'Content-Type': 'text/plain; charset=utf-8' });
  res.end('Not Found');
});

server.listen(port, host, () => {
  console.log(`[startup] server listening on http://${host}:${port}`);
});

// Graceful shutdown handlers for containerized environments
function gracefulShutdown(signal) {
  console.log(`[shutdown] received ${signal}, closing server gracefully`);
  
  // Set a timeout to force exit if graceful shutdown takes too long
  const shutdownTimeout = setTimeout(() => {
    console.error('[shutdown] forced exit after timeout');
    process.exit(1);
  }, SHUTDOWN_TIMEOUT_MS);
  
  // Allow process to exit naturally if server closes before timeout
  shutdownTimeout.unref();
  
  server.close((err) => {
    clearTimeout(shutdownTimeout);
    if (err) {
      console.error('[shutdown] error closing server:', err.message);
      process.exit(1);
    }
    console.log('[shutdown] server closed, exiting process');
    process.exit(0);
  });
}

process.on('SIGTERM', () => gracefulShutdown('SIGTERM'));
process.on('SIGINT', () => gracefulShutdown('SIGINT'));

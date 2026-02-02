const http = require('http');

const port = Number.parseInt(process.env.PORT, 10) || 8080;
const host = '0.0.0.0';

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

server.on('error', (err) => {
  console.error('[error]', err);
  process.exit(1);
});

// Graceful shutdown handlers
const shutdown = (signal) => {
  console.log(`[shutdown] received ${signal}, closing server gracefully`);
  
  // Force shutdown after timeout if graceful shutdown doesn't complete
  const forceShutdownTimeout = setTimeout(() => {
    console.error('[shutdown] graceful shutdown timed out, forcing exit');
    process.exit(1);
  }, 30000); // 30 second timeout
  
  server.close(() => {
    clearTimeout(forceShutdownTimeout);
    console.log('[shutdown] server closed, exiting process');
    process.exit(0);
  });
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

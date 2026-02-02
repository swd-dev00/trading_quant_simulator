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
const shutdown = () => {
  console.log('[shutdown] received termination signal, closing server...');
  
  // Set a timeout to force exit if graceful shutdown takes too long
  const forceExitTimeout = setTimeout(() => {
    console.error('[shutdown] forced exit after timeout');
    process.exit(1);
  }, 10000); // 10 second grace period
  
  server.close(() => {
    clearTimeout(forceExitTimeout);
    console.log('[shutdown] server closed, exiting');
    process.exit(0);
  });
};

process.on('SIGTERM', shutdown);
process.on('SIGINT', shutdown);

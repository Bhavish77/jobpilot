/**
 * Notify — Node.js WebSocket push service.
 *
 * Phase 0: health check + the skeleton wiring (HTTP server, WebSocket
 * server, a Redis subscriber) so the container boots and the shape is
 * right. Phase 5 fills in: per-user connection tracking, the actual
 * pub/sub channel(s) agent-core/job-worker publish to, and logging each
 * event to MongoDB.
 *
 * Multi-instance note (see the roadmap's Scale section): every Notify
 * instance subscribes to the same Redis channel and just filters to the
 * users *it* holds a socket for — no distributed presence registry needed
 * at this scale.
 */

const express = require('express');
const http = require('http');
const { WebSocketServer } = require('ws');
const Redis = require('ioredis');

const PORT = process.env.NOTIFY_PORT || 4000;
const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379/0';

const app = express();
const server = http.createServer(app);
const wss = new WebSocketServer({ server });

// userId -> Set of open WebSocket connections (a user can have multiple tabs).
const connectionsByUser = new Map();

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.get('/ready', async (_req, res) => {
  try {
    const pong = await redisClient.ping();
    res.json({ status: pong === 'PONG' ? 'ready' : 'degraded' });
  } catch (err) {
    res.status(503).json({ status: 'degraded', error: String(err) });
  }
});

wss.on('connection', (ws, req) => {
  // Phase 5: derive the real userId from a session/JWT on the upgrade
  // request instead of a query param.
  const url = new URL(req.url, `http://${req.headers.host}`);
  const userId = url.searchParams.get('userId') || 'anonymous';

  if (!connectionsByUser.has(userId)) connectionsByUser.set(userId, new Set());
  connectionsByUser.get(userId).add(ws);

  ws.on('close', () => {
    connectionsByUser.get(userId)?.delete(ws);
  });
});

function pushToUser(userId, event) {
  const sockets = connectionsByUser.get(userId);
  if (!sockets) return;
  const payload = JSON.stringify(event);
  for (const ws of sockets) {
    if (ws.readyState === ws.OPEN) ws.send(payload);
  }
}

// Shared subscriber connection (ioredis needs a dedicated connection once
// SUBSCRIBE is called — it can no longer run other commands on it).
const redisClient = new Redis(REDIS_URL);
const subscriber = new Redis(REDIS_URL);

const EVENTS_CHANNEL = 'jobpilot:events';

subscriber.subscribe(EVENTS_CHANNEL, (err) => {
  if (err) {
    console.error('Failed to subscribe to', EVENTS_CHANNEL, err);
  } else {
    console.log(`Subscribed to ${EVENTS_CHANNEL}`);
  }
});

subscriber.on('message', (_channel, message) => {
  // Expected shape (Phase 4/5 finalizes this): { userId, type, payload }
  try {
    const event = JSON.parse(message);
    if (event.userId) pushToUser(event.userId, event);
  } catch (err) {
    console.error('Bad event on', EVENTS_CHANNEL, err);
  }
});

server.listen(PORT, () => {
  console.log(`Notify listening on :${PORT}`);
});

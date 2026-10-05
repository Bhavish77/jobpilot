/**
 * Notify — Node.js WebSocket push service.
 *
 * Phase 0: health check + the skeleton wiring (HTTP server, WebSocket
 * server, a Redis subscriber) so the container boots and the shape is
 * right. Phase 5 fills in: real per-connection auth, the actual pub/sub
 * channel agent-core/job-worker publish to, and logging each event to
 * MongoDB (see docs/PHASE_5_PLAN.md).
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
const jwt = require('jsonwebtoken');
const cookie = require('cookie');
const { MongoClient } = require('mongodb');

const PORT = process.env.NOTIFY_PORT || 4000;
const REDIS_URL = process.env.REDIS_URL || 'redis://localhost:6379/0';
const MONGO_URL = process.env.MONGO_URL || 'mongodb://localhost:27017';
const MONGO_DB = process.env.MONGO_DB || 'jobpilot';
const JWT_SECRET = process.env.JWT_SECRET || 'changeme-dev-only';
const JWT_ALGORITHM = process.env.JWT_ALGORITHM || 'HS256';
const SESSION_COOKIE_NAME = 'jobpilot_session';

// Same database shared/jobpilot_shared/mongo.py writes to (its own
// docstring already names "notification log" as one of Mongo's jobs here)
// — this is the Python side's counterpart, just connected from Node since
// Notify is the only service that ever reads jobpilot:events.
const mongoClient = new MongoClient(MONGO_URL);
let notifyEventsCollection;

async function connectMongo() {
  await mongoClient.connect();
  notifyEventsCollection = mongoClient.db(MONGO_DB).collection('notify_events');
  console.log('Connected to MongoDB');
}

const app = express();
const server = http.createServer(app);

// userId -> Set of open WebSocket connections (a user can have multiple tabs).
const connectionsByUser = new Map();

app.get('/health', (_req, res) => {
  res.json({ status: 'ok' });
});

app.get('/ready', async (_req, res) => {
  const checks = {};
  try {
    checks.redis = (await redisClient.ping()) === 'PONG';
  } catch (err) {
    checks.redis = `error: ${err}`;
  }
  try {
    await mongoClient.db(MONGO_DB).command({ ping: 1 });
    checks.mongo = true;
  } catch (err) {
    checks.mongo = `error: ${err}`;
  }

  const ok = Object.values(checks).every((v) => v === true);
  res.status(ok ? 200 : 503).json({ status: ok ? 'ready' : 'degraded', checks });
});

/**
 * Same session JWT agent-core's get_current_user() verifies
 * (shared/jobpilot_shared/auth.py) — same JWT_SECRET/algorithm via .env,
 * just re-implemented here since this service is Node, not Python. The
 * cookie's domain-scoped, not port-scoped, and SameSite=Lax doesn't block
 * this (confirmed against how auth.py actually sets it), so the browser
 * sends the same cookie whether it's talking to agent-core on :8000 or
 * Notify on :4000.
 */
function getUserIdFromRequest(req) {
  const cookies = cookie.parse(req.headers.cookie || '');
  const token = cookies[SESSION_COOKIE_NAME];
  if (!token) return null;
  try {
    const payload = jwt.verify(token, JWT_SECRET, { algorithms: [JWT_ALGORITHM] });
    return payload.sub || null;
  } catch (err) {
    return null;
  }
}

// verifyClient runs before the WebSocket handshake completes, so a missing
// or invalid session is rejected with a real HTTP 401 instead of accepting
// the upgrade and only then discovering there's no real user behind it.
const wss = new WebSocketServer({
  server,
  verifyClient: (info, callback) => {
    const userId = getUserIdFromRequest(info.req);
    if (!userId) {
      callback(false, 401, 'Unauthorized');
      return;
    }
    info.req.userId = userId;
    callback(true);
  },
});

wss.on('connection', (ws, req) => {
  const userId = req.userId;

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

subscriber.on('message', async (_channel, message) => {
  // Shape published by jobpilot_shared.redis_client.publish_event:
  // { userId, type, payload }
  let event;
  try {
    event = JSON.parse(message);
  } catch (err) {
    console.error('Bad event on', EVENTS_CHANNEL, err);
    return;
  }

  // Logged first, so there's a durable record even if nobody's connected
  // right now to receive the live push below (PUBLISH itself guarantees
  // nothing — see publish_event's docstring).
  try {
    await notifyEventsCollection.insertOne({ ...event, receivedAt: new Date() });
  } catch (err) {
    console.error('Failed to log event to MongoDB', err);
  }

  if (event.userId) pushToUser(event.userId, event);
});

connectMongo()
  .then(() => {
    server.listen(PORT, () => {
      console.log(`Notify listening on :${PORT}`);
    });
  })
  .catch((err) => {
    console.error('Failed to connect to MongoDB, exiting', err);
    process.exit(1);
  });

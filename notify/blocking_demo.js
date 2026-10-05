/**
 * Phase 5, chunk 4 — "deliberately profile one blocking sync call freezing
 * every other connection, then fix it" (docs/PHASE_5_PLAN.md).
 *
 * Standalone on purpose: this never touches index.js's real message
 * handler. Node has one thread running JS; anything synchronous and slow
 * in a WebSocket/Redis callback blocks every other connection this same
 * process holds, not just the one that triggered it. That's the actual
 * lesson, and the safest way to *prove* it without ever risking a
 * deliberately-broken branch being reachable through the real
 * jobpilot:events pub/sub path is to reproduce the whole thing in a
 * throwaway server that mirrors Notify's shape but isn't it.
 *
 * Run: node blocking_demo.js
 */

const http = require('http');
const { WebSocketServer, WebSocket } = require('ws');
const { Worker, isMainThread, parentPort, workerData } = require('worker_threads');
const crypto = require('crypto');

const PORT = 4099;

function hashForMs(ms) {
  // Deliberately synchronous CPU-bound work — standing in for "someone
  // wrote a heavy loop/JSON.parse/crypto call directly in a handler."
  const deadline = Date.now() + ms;
  let hash = Buffer.from('seed');
  while (Date.now() < deadline) {
    hash = crypto.createHash('sha256').update(hash).digest();
  }
  return hash.toString('hex');
}

let server;

if (!isMainThread) {
  // The fixed version's worker body — runs on its own OS thread, so it
  // never occupies the main thread's single event loop.
  const result = hashForMs(workerData.ms);
  parentPort.postMessage(result);
} else {
  runMain();
}

function runMain() {
server = http.createServer();
const wss = new WebSocketServer({ server });

wss.on('connection', (ws) => {
  ws.on('message', (raw) => {
    const msg = JSON.parse(raw.toString());

    if (msg.type === 'ping') {
      ws.send(JSON.stringify({ type: 'pong', sentAt: msg.sentAt }));
      return;
    }

    if (msg.type === 'block-broken') {
      // BROKEN: synchronous, on the main thread. Every other connection
      // this process holds — including totally unrelated users — stops
      // being served for the entire duration.
      hashForMs(msg.ms);
      ws.send(JSON.stringify({ type: 'block-done', variant: 'broken' }));
      return;
    }

    if (msg.type === 'block-fixed') {
      // FIXED: same CPU-bound work, moved to a worker_threads Worker.
      // The main thread's event loop is free to keep handling every
      // other connection's messages while this runs.
      const worker = new Worker(__filename, { workerData: { ms: msg.ms } });
      worker.on('message', () => {
        ws.send(JSON.stringify({ type: 'block-done', variant: 'fixed' }));
        worker.terminate();
      });
      return;
    }
  });
});

server.listen(PORT, () => runDemo());
}

function connectClient() {
  return new Promise((resolve) => {
    const ws = new WebSocket(`ws://localhost:${PORT}`);
    ws.on('open', () => resolve(ws));
  });
}

// Client B pings continuously; recording each round-trip time is the
// actual measurement instrument — a healthy server keeps these in the
// low single-digit milliseconds the whole time.
function measurePingLatencies(ws, durationMs) {
  const latencies = [];
  return new Promise((resolve) => {
    const start = Date.now();
    function sendPing() {
      if (Date.now() - start >= durationMs) {
        resolve(latencies);
        return;
      }
      const sentAt = Date.now();
      ws.send(JSON.stringify({ type: 'ping', sentAt }));
      const onPong = (raw) => {
        const msg = JSON.parse(raw.toString());
        if (msg.type === 'pong' && msg.sentAt === sentAt) {
          ws.off('message', onPong);
          latencies.push(Date.now() - sentAt);
          setTimeout(sendPing, 20);
        }
      };
      ws.on('message', onPong);
    }
    sendPing();
  });
}

async function runVariant(variant, blockMs) {
  const clientA = await connectClient(); // triggers the blocking call
  const clientB = await connectClient(); // innocent bystander, just pinging

  const measurement = measurePingLatencies(clientB, blockMs + 1000);
  clientA.send(JSON.stringify({ type: variant, ms: blockMs }));
  const latencies = await measurement;

  clientA.close();
  clientB.close();

  const max = Math.max(...latencies);
  const avg = latencies.reduce((a, b) => a + b, 0) / latencies.length;
  console.log(
    `${variant}: client B's ${latencies.length} pings during a ${blockMs}ms block -> ` +
      `max latency ${max}ms, avg ${avg.toFixed(1)}ms`
  );
  return { max, avg };
}

async function runDemo() {
  console.log('--- Phase 5, chunk 4: blocking-call demo ---\n');

  const broken = await runVariant('block-broken', 2000);
  const fixed = await runVariant('block-fixed', 2000);

  console.log();
  console.log('Conclusion:');
  console.log(
    `  broken: an innocent second connection's pings spiked to ~${broken.max}ms ` +
      `(frozen for the entire blocking call)`
  );
  console.log(
    `  fixed:  the same second connection's pings stayed ~${fixed.max}ms max ` +
      `(worker_threads kept the main event loop free)`
  );

  server.close();
  process.exit(0);
}

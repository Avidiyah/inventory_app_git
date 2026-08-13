// Foundation: browser real-time transport.
//
// Owns one same-origin WebSocket, reconnect scheduling, and event routing.
// It deliberately has no DOM access and imports no views. REST remains the
// source of truth: socket frames are invalidations, and subscribers decide
// whether their current surface is safe to refresh.

const RECONNECT_BASE_DELAY_MS = 1000;
const RECONNECT_MAX_DELAY_MS = 30000;

const subscriptions = new Map();

let activePageGetter = () => null;
let socket = null;
let reconnectTimer = null;
let reconnectAttempt = 0;
let connectionGeneration = 0;
let connectionWanted = false;
let recoveryRefreshNeeded = false;

function websocketUrl() {
  const url = new URL("/ws", globalThis.location.href);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  return url.href;
}

// Equal jitter gives every retry a non-zero floor while still spreading a
// deploy-wide reconnect wave. With this curve, even the earliest possible
// attempts stay below the server's 10-handshakes-per-minute budget.
function reconnectDelay(attempt) {
  const exponent = Math.min(attempt, 10);
  const ceiling = Math.min(
    RECONNECT_MAX_DELAY_MS,
    RECONNECT_BASE_DELAY_MS * (2 ** exponent)
  );
  return (ceiling / 2) + (Math.random() * ceiling / 2);
}

function currentActivePage() {
  try {
    return activePageGetter() ?? null;
  } catch {
    return null;
  }
}

function callSubscriber(handler, notification) {
  try {
    const result = handler(notification);
    if (result && typeof result.catch === "function") {
      result.catch((error) => console.error("Real-time subscriber failed.", error));
    }
  } catch (error) {
    console.error("Real-time subscriber failed.", error);
  }
}

function notifyEvent(envelope) {
  const handlers = subscriptions.get(envelope.type);
  if (!handlers || handlers.size === 0) return;

  const notification = {
    reason: "event",
    envelope,
    activePage: currentActivePage(),
  };
  for (const handler of [...handlers]) callSubscriber(handler, notification);
}

function notifyReconnect() {
  const handlers = new Set();
  for (const eventHandlers of subscriptions.values()) {
    for (const handler of eventHandlers) handlers.add(handler);
  }

  const notification = {
    reason: "reconnect",
    envelope: null,
    activePage: currentActivePage(),
  };
  for (const handler of handlers) callSubscriber(handler, notification);
}

function parseEnvelope(data) {
  if (typeof data !== "string") return null;

  let envelope;
  try {
    envelope = JSON.parse(data);
  } catch {
    return null;
  }

  if (!envelope || typeof envelope !== "object" || Array.isArray(envelope)) {
    return null;
  }
  const keys = Object.keys(envelope).sort();
  if (keys.length !== 3 || keys[0] !== "id" || keys[1] !== "req" || keys[2] !== "type") {
    return null;
  }
  if (typeof envelope.type !== "string" || !envelope.type) return null;
  if (envelope.id !== null && typeof envelope.id !== "string") return null;
  if (envelope.req !== null && typeof envelope.req !== "string") return null;
  return envelope;
}

function scheduleReconnect(generation) {
  if (
    !connectionWanted ||
    generation !== connectionGeneration ||
    reconnectTimer !== null ||
    socket !== null
  ) {
    return;
  }

  const delay = reconnectDelay(reconnectAttempt);
  reconnectAttempt += 1;
  reconnectTimer = globalThis.setTimeout(() => {
    reconnectTimer = null;
    if (!connectionWanted || generation !== connectionGeneration) return;
    openSocket(generation);
  }, delay);
}

function openSocket(generation) {
  if (!connectionWanted || generation !== connectionGeneration || socket !== null) return;

  let candidate;
  try {
    candidate = new WebSocket(websocketUrl());
  } catch {
    recoveryRefreshNeeded = true;
    scheduleReconnect(generation);
    return;
  }
  socket = candidate;

  candidate.addEventListener("open", () => {
    if (
      !connectionWanted ||
      generation !== connectionGeneration ||
      socket !== candidate
    ) {
      try {
        candidate.close(1000, "connection no longer needed");
      } catch {
        // The stale generation is already detached from current state.
      }
      return;
    }

    reconnectAttempt = 0;
    if (recoveryRefreshNeeded) {
      recoveryRefreshNeeded = false;
      notifyReconnect();
    }
  });

  candidate.addEventListener("message", (event) => {
    if (generation !== connectionGeneration || socket !== candidate) return;
    const envelope = parseEnvelope(event.data);
    if (!envelope || !subscriptions.has(envelope.type)) return;
    notifyEvent(envelope);
  });

  candidate.addEventListener("error", () => {
    if (generation !== connectionGeneration || socket !== candidate) return;
    // Browsers normally follow `error` with `close`; closing explicitly keeps
    // that lifecycle deterministic without surfacing a user-visible failure.
    try {
      candidate.close();
    } catch {
      // The close event, if one follows, remains the single retry trigger.
    }
  });

  candidate.addEventListener("close", () => {
    if (generation !== connectionGeneration || socket !== candidate) return;
    socket = null;
    if (!connectionWanted) return;
    recoveryRefreshNeeded = true;
    scheduleReconnect(generation);
  });
}

export function setActivePageGetter(getter) {
  if (typeof getter !== "function") {
    throw new TypeError("Active page getter must be a function.");
  }
  activePageGetter = getter;
}

export function subscribe(eventType, handler) {
  if (typeof eventType !== "string" || !eventType) {
    throw new TypeError("Event type must be a non-empty string.");
  }
  if (typeof handler !== "function") {
    throw new TypeError("Subscriber must be a function.");
  }

  let handlers = subscriptions.get(eventType);
  if (!handlers) {
    handlers = new Set();
    subscriptions.set(eventType, handlers);
  }
  handlers.add(handler);

  return () => {
    const current = subscriptions.get(eventType);
    if (!current) return;
    current.delete(handler);
    if (current.size === 0) subscriptions.delete(eventType);
  };
}

export function connectRealtime() {
  if (connectionWanted) return;
  connectionWanted = true;
  connectionGeneration += 1;
  reconnectAttempt = 0;
  recoveryRefreshNeeded = false;
  openSocket(connectionGeneration);
}

export function disconnectRealtime() {
  connectionWanted = false;
  connectionGeneration += 1;
  reconnectAttempt = 0;
  recoveryRefreshNeeded = false;

  if (reconnectTimer !== null) {
    globalThis.clearTimeout(reconnectTimer);
    reconnectTimer = null;
  }

  const current = socket;
  socket = null;
  if (!current) return;
  try {
    current.close(1000, "signed out");
  } catch {
    // Local state is already disconnected; transport cleanup is best-effort.
  }
}

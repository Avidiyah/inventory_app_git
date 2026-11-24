// Live messaging store: the signed-in user's conversation list and unread
// count, kept fresh by `message.changed` invalidations.
//
// Layer: shared state, no DOM. The socket carries only the conversation id;
// every refresh is a REST fetch (message text never rides the socket). Fetches
// coalesce like the other live views: one in flight, one rerun queued.
//
// `stopMessages()` (sign-out) drops every conversation from memory and bumps a
// generation counter so a response that lands afterwards is ignored.

import { apiListConversations } from "./api.js";
import { subscribe } from "./realtime.js";

const MESSAGE_CHANGED_EVENT = "message.changed";

const empty = () => ({ conversations: [], unreadPeople: 0 });

const listeners = new Set();
let state = empty();
let unsubscribe = null;
let generation = 0;
let inFlight = null;
let rerun = false;
let pendingIds = new Set();

export function getState() {
  return state;
}

export function onChange(listener) {
  listeners.add(listener);
  return () => listeners.delete(listener);
}

function notify(conversationId) {
  for (const listener of [...listeners]) {
    try {
      listener({ conversationId });
    } catch (error) {
      console.error("Messages listener failed.", error);
    }
  }
}

// Each id seen while a fetch was pending is announced once after it, so a
// burst for chats A and B never hides A from the chat that has A open.
function notifyAll(ids) {
  if (ids.size === 0) notify(null);
  for (const id of ids) notify(id);
}

async function runLoop(gen) {
  do {
    rerun = false;
    const ids = pendingIds;
    pendingIds = new Set();
    try {
      const data = await apiListConversations();
      if (gen !== generation) return;
      state = { conversations: data.conversations, unreadPeople: data.unread_people };
    } catch {
      // Best-effort: keep the last list over a dropped connection.
      if (gen !== generation) return;
    }
    notifyAll(ids);
  } while (rerun && gen === generation);
}

function load(conversationId = null) {
  if (!unsubscribe) return Promise.resolve();
  if (conversationId) pendingIds.add(conversationId);
  if (inFlight) {
    rerun = true;
    return inFlight;
  }
  const run = runLoop(generation).finally(() => {
    if (inFlight === run) inFlight = null;
  });
  inFlight = run;
  return run;
}

export function refresh() {
  return load();
}

export function startMessages() {
  if (!unsubscribe) {
    unsubscribe = subscribe(MESSAGE_CHANGED_EVENT, ({ envelope }) => load(envelope?.id ?? null));
  }
  return load();
}

export function stopMessages() {
  if (unsubscribe) unsubscribe();
  unsubscribe = null;
  generation += 1;
  inFlight = null;
  rerun = false;
  pendingIds = new Set();
  state = empty();
  notify(null);
}

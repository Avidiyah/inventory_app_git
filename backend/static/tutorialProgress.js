// Client-side record of which tutorials this person has seen / finished.
//
// Layer: shared module; imports api.js only, no view. The server is the
// record (first-write-wins); this cache lets page buttons and the Hub read it
// without a request each time. Cleared on sign-out and on a 401 so a shared
// crew phone never shows the last person's dots.

import { apiGetTutorialProgress, apiSetTutorialProgress } from "./api.js";

// key -> true when completed, false when only seen.
const cache = new Map();
const listeners = new Set();
let loaded = null;
let generation = 0;

function notify() {
  for (const fn of [...listeners]) fn();
}

// Subscribe to any cache change; returns the unsubscribe.
export function onChange(fn) {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

// GET `me` once per sign-in. A failed GET is logged and leaves the cache
// empty (no dot shown) rather than blocking sign-in.
export function loadProgress() {
  if (loaded) return loaded;
  const mine = generation;
  loaded = apiGetTutorialProgress()
    .then((rows) => {
      if (mine !== generation) return; // cleared while in flight
      for (const row of rows || []) {
        // A mark made before the GET landed wins over the server's older view.
        if (!cache.get(row.key)) cache.set(row.key, Boolean(row.completed_at));
      }
      notify();
    })
    .catch((err) => console.error("tutorial progress load failed", err));
  return loaded;
}

export const hasSeen = (key) => cache.has(key);
export const isDone = (key) => cache.get(key) === true;

// Update the cache at once, PUT in the background. `completed` implies seen.
// A failed PUT is logged, not retried; the cache keeps the optimistic value.
export function mark(key, event) {
  if (event === "completed" ? isDone(key) : hasSeen(key)) return;
  cache.set(key, event === "completed");
  notify();
  apiSetTutorialProgress(key, event).catch((err) =>
    console.error("tutorial progress save failed", err));
}

export function clearProgress() {
  generation += 1;
  loaded = null;
  cache.clear();
  notify();
}

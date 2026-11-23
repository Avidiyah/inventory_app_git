// Shared by Admin Review and SMR Admin Review: keep the open receipt or block
// matching the server when a live event names the selected order.
//
// Layer: views helper. No DOM here; each page passes what "shown", "in the
// queue" and "repaint" mean for it.

// Refetches the selected order and reports what happened. Never throws.
// Returns "same" | "changed" | "gone" | "skipped" (no selection, a newer
// selection won, or a network/401 failure). A 404 is "gone".
export async function refreshSelected({
  getSelected,   // () => detail | null
  fetchDetail,   // (id) => Promise<detail>
  isStale,       // () => boolean  true when the user selected something else meanwhile
  inQueue,       // (detail) => boolean
  signature,     // (detail) => string  everything the panel shows
  repaint,       // (detail) => void    text, status line, buttons; no focus, select or picker
  markGone,      // (detail | null) => void
}) {
  const shown = getSelected();
  if (!shown) return "skipped";
  let fresh = null;
  try {
    fresh = await fetchDetail(shown.id);
  } catch (err) {
    if (err?.status !== 404) return "skipped";
  }
  if (isStale()) return "skipped";
  if (!fresh || !inQueue(fresh)) {
    markGone(fresh);
    return "gone";
  }
  if (signature(fresh) === signature(shown)) return "same";
  repaint(fresh);
  return "changed";
}

// One run at a time with one rerun queued behind it, so a burst of events
// costs two fetches and the last paint is never older than the last event.
export function coalesce(run) {
  let pending = null;
  let again = false;
  return () => {
    if (pending) {
      again = true;
      return pending;
    }
    pending = (async () => {
      do {
        again = false;
        await run();
      } while (again);
    })().finally(() => { pending = null; });
    return pending;
  };
}

// The id rule both pages share: a recovered connection or an event with no
// id means anything may have changed; otherwise only the selected order.
export function concerns({ reason, envelope }, selected) {
  return reason === "reconnect" || !envelope?.id || envelope.id === selected?.id;
}

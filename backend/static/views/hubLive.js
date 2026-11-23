// View helper: the User Hub's live feeds -- what refetches when (W7).
//
// Layer: views. userHub.js builds one feed per payload and hands them to
// `connectHubLive`; this module owns the socket subscriptions and the
// 60-second safety timer that run them. Events carry no data (P2), so every
// trigger means "refetch"; each feed coalesces a burst into at most two
// fetches (spec rule 6), which keeps `GET /hub/admin` off a per-event path.

import { subscribe } from "../realtime.js";

const HUB_PAGE = "user-hub";
const SAFETY_REFRESH_MS = 60000;

// Which feeds each event invalidates (spec rules 4, 7). A reconnect (missed
// events) and the timer run every feed; each feed's own `when` decides
// whether it is visible to this viewer right now.
const ROUTES = {
  "attendance.changed": ["personal", "attendance", "leaderboards", "report"],
  "labor.session.changed": ["personal", "crew", "admin"],
  "work_order.status.changed": ["personal", "crew", "admin", "graphs", "leaderboards", "report"],
  "user_request.changed": ["personal"],
};

let feeds = {};
let timer = null;

// One fetch in flight; a `run` during it queues exactly one rerun, which is
// foreground if any queued caller was. `reset` drops whatever is in flight.
export function createFeed(fetcher, onData, { when = () => true, onError = null } = {}) {
  let cycle = null;
  let again = null;
  let generation = 0;

  async function loop(opts, gen) {
    let current = opts;
    while (current) {
      again = null;
      try {
        const payload = await fetcher();
        if (gen !== generation) return;
        onData(payload);
      } catch (err) {
        if (gen !== generation) return;
        onError?.(err, current);
      }
      current = again;
    }
  }

  function run({ background = false } = {}) {
    if (!when()) return Promise.resolve();
    if (cycle) {
      again = { background: (again ? again.background : true) && Boolean(background) };
      return cycle;
    }
    const gen = generation;
    cycle = loop({ background: Boolean(background) }, gen).finally(() => {
      if (gen === generation) cycle = null;
    });
    return cycle;
  }

  return {
    run,
    reset() {
      generation += 1;
      cycle = null;
      again = null;
    },
  };
}

function runFeeds(names) {
  for (const name of names) void feeds[name]?.run({ background: true });
}

export function connectHubLive(nextFeeds) {
  feeds = nextFeeds;
}

export function stopHubLive() {
  if (timer !== null) {
    clearInterval(timer);
    timer = null;
  }
}

export function startHubLive() {
  stopHubLive();
  timer = setInterval(() => {
    if (document.hidden) return;
    runFeeds(Object.keys(feeds));
  }, SAFETY_REFRESH_MS);
}

for (const [type, names] of Object.entries(ROUTES)) {
  subscribe(type, ({ activePage, reason }) => {
    if (activePage !== HUB_PAGE) return;
    runFeeds(reason === "reconnect" ? Object.keys(feeds) : names);
  });
}

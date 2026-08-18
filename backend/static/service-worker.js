// Push service worker.
//
// Layer: worker. Runs outside the page, in its own global scope, and is
// the only code that executes when a push arrives with the app closed.
// It has no DOM, no access to the page's modules, and no session state --
// everything it needs must arrive in the push payload.
//
// Served from `/service-worker.js` by `app/main.py::service_worker`, NOT
// from the `/static` mount. A worker's scope defaults to the directory it
// was served from, so a copy under `/static/` would control `/static/`
// and would never receive a push for the app.
//
// Deliberately does no caching. This is a notification transport, not an
// offline shell; an offline cache would introduce stale-asset behavior
// the app has taken care to avoid elsewhere (see `NoCacheStaticFiles`).

// Take over as soon as a new version installs rather than waiting for
// every tab to close. Without these two, a worker update can sit unused
// indefinitely -- painful when the installed PWA is rarely fully quit.
self.addEventListener("install", () => self.skipWaiting());
self.addEventListener("activate", (event) => event.waitUntil(self.clients.claim()));

// Shown when a push arrives that carries no usable payload. iOS treats a
// push that displays nothing as a fault, so there is always a fallback
// rather than an early return.
const FALLBACK = {
  title: "Inventory",
  body: "You have a new notification.",
};

function readPayload(event) {
  if (!event.data) return FALLBACK;
  try {
    const parsed = event.data.json();
    return {
      title: parsed.title || FALLBACK.title,
      body: parsed.body || FALLBACK.body,
    };
  } catch (err) {
    // Malformed or non-JSON payload. Still show something -- see below.
    return FALLBACK;
  }
}

self.addEventListener("push", (event) => {
  const { title, body } = readPayload(event);

  // `showNotification` is not optional on iOS. A push that resolves
  // without displaying anything is treated as a misbehaving app: Safari
  // substitutes a generic notification, and repeated offences can get the
  // site's push permission revoked with no way to re-prompt in-app. So
  // every path through this handler ends in a visible notification.
  event.waitUntil(
    self.registration.showNotification(title, {
      body,
      icon: "/static/icon-180.png",
      badge: "/static/icon-180.png",
      // Collapses repeats into one entry instead of stacking a queue of
      // identical alerts on the lock screen.
      tag: "inventory-notification",
    })
  );
});

self.addEventListener("notificationclick", (event) => {
  event.notification.close();

  // Prefer an already-open window over launching a second one.
  // `includeUncontrolled` matters on the first launch after install,
  // when a window may exist that this worker has not claimed yet.
  event.waitUntil(
    self.clients
      .matchAll({ type: "window", includeUncontrolled: true })
      .then((clientList) => {
        for (const client of clientList) {
          if ("focus" in client) return client.focus();
        }
        if (self.clients.openWindow) return self.clients.openWindow("/");
        return undefined;
      })
  );
});

// The realtime transport, brought up on a chosen page over the fake socket.
//
// Four P7 views subscribe to an invalidation event and gate on `activePage`;
// this is the wiring `helpers/hub.js::connectHub` and
// `views/workOrders/realtime.test.js` each carry inline, lifted once (P7
// deviation 9). Nothing here mocks realtime.js: the real module connects,
// parses the envelope and routes to the real subscriber.
//
// The relative import below and the file:// URL `mountView` imports with
// resolve to the same module id under Vitest, so `subscribe` calls made by the
// view at import land in the instance this helper connects (see session.js).

import { installFakeWebSocket } from "./fakeSocket.js";

export async function connectFakeRealtime(activePage) {
  let page = activePage;
  const ws = installFakeWebSocket();
  const realtime = await import("../../../backend/static/realtime.js");
  realtime.setActivePageGetter(() => page);
  realtime.connectRealtime();
  ws.last().emitOpen();
  return {
    ws,
    // A server invalidation. `extra` overrides the envelope's `id` / `req`.
    emit: (type, extra = {}) =>
      ws.last().emitMessage(JSON.stringify({ type, id: null, req: null, ...extra })),
    // Drop the socket and let the transport's reconnect deliver
    // `reason: "reconnect"` to every subscriber. Fake timers are needed to
    // advance past the backoff; the caller owns them.
    reconnect: () => { ws.last().emitClose(); },
    setActivePage: (name) => { page = name; },
    disconnect: () => { realtime.disconnectRealtime(); ws.restore(); },
  };
}

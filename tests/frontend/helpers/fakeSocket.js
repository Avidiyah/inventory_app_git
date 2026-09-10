// A scriptable WebSocket stand-in. realtime.js calls `new WebSocket(url)` at
// connect time, so replacing the global is enough -- no module mocking.
import { vi } from "vitest";

class FakeSocket extends EventTarget {
  constructor(url) {
    super();
    this.url = url;
    this.readyState = 0;
    this.closed = null;
  }

  close(code, reason) {
    this.readyState = 3;
    this.closed = { code, reason };
  }

  emitOpen() {
    this.readyState = 1;
    this.dispatchEvent(new Event("open"));
  }

  emitMessage(data) {
    // `data` is whatever the server would send: a JSON string, or a
    // deliberately malformed value for the validation tests.
    const event = new Event("message");
    event.data = data;
    this.dispatchEvent(event);
  }

  emitError() {
    this.dispatchEvent(new Event("error"));
  }

  emitClose() {
    this.readyState = 3;
    this.dispatchEvent(new Event("close"));
  }
}

// jsdom defines `WebSocket` as a read-only property -- a plain assignment
// throws "Cannot assign to read only property 'WebSocket'". vi.stubGlobal
// goes through defineProperty, which works, and unstubAllGlobals restores it.
export function installFakeWebSocket({ throwOnConstruct = false } = {}) {
  const sockets = [];
  vi.stubGlobal("WebSocket", function (url) {
    if (throwOnConstruct) throw new Error("blocked");
    const socket = new FakeSocket(url);
    sockets.push(socket);
    return socket;
  });
  return {
    sockets,
    last: () => sockets.at(-1),
    restore() { vi.unstubAllGlobals(); },
  };
}

// views/messageBubble.js: the floating chat-head bubble, its trashcan, the
// put-away flag, tutorial hiding and sign-out teardown. The store and the
// panel are other units, so both are stubbed here.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { importView, mountShell } from "../helpers/shell.js";

const m = vi.hoisted(() => ({
  state: { conversations: [], unreadPeople: 0 },
  listeners: new Set(),
  startMessages: vi.fn(async () => {}),
  stopMessages: vi.fn(),
  panel: { openChat: vi.fn(), destroy: vi.fn() },
  mountMessagePanel: vi.fn(),
}));

vi.mock("../../../backend/static/messagesStore.js", () => ({
  startMessages: m.startMessages,
  stopMessages: m.stopMessages,
  getState: () => m.state,
  onChange: (fn) => { m.listeners.add(fn); return () => m.listeners.delete(fn); },
}));
vi.mock("../../../backend/static/views/messagePanel.js", () => ({
  mountMessagePanel: m.mountMessagePanel,
}));

const el = (id) => document.getElementById(id);
const bubble = () => el("msg-bubble");
const badge = () => el("msg-bubble-badge");
const trash = () => el("msg-trash");
const float = () => el("msg-float");

function pointer(target, type, x, y) {
  target.dispatchEvent(new MouseEvent(type, { clientX: x, clientY: y, bubbles: true }));
}

function setViewport(w, h) {
  window.innerWidth = w;
  window.innerHeight = h;
}

let view;
beforeEach(async () => {
  setViewport(1024, 768);
  m.state = { conversations: [], unreadPeople: 0 };
  m.listeners.clear();
  m.startMessages.mockClear();
  m.stopMessages.mockClear();
  m.panel.openChat.mockClear();
  m.panel.destroy.mockClear();
  m.mountMessagePanel.mockReset();
  m.mountMessagePanel.mockReturnValue(m.panel);
  mountShell();
  view = await importView("views/messageBubble.js");
});

afterEach(() => {
  view.unmountMessages();
});

describe("pure helpers", () => {
  it("snapSide picks the nearer edge", () => {
    expect(view.snapSide(100, 390)).toBe("left");
    expect(view.snapSide(300, 390)).toBe("right");
  });

  it("badgeText hides zero and caps at 9+", () => {
    expect(view.badgeText(0)).toBe("");
    expect(view.badgeText(3)).toBe("3");
    expect(view.badgeText(12)).toBe("9+");
  });
});

describe("the bubble", () => {
  it("ships hidden and shows once mounted, starting the store", () => {
    expect(bubble().hidden).toBe(true);
    expect(bubble().tagName).toBe("BUTTON");
    expect(bubble().closest("button")).toBe(bubble());
    expect(badge().closest("button")).toBe(bubble());
    view.mountMessages();
    expect(bubble().hidden).toBe(false);
    expect(m.startMessages).toHaveBeenCalledTimes(1);
  });

  it("carries the side class and positions through style.transform", () => {
    localStorage.setItem("techfm.msgBubble.pos", JSON.stringify({ side: "left", y: 120 }));
    view.mountMessages();
    expect(bubble().classList.contains("on-left")).toBe(true);
    expect(bubble().classList.contains("on-right")).toBe(false);
    expect(bubble().style.transform).toBe("translate(8px, 120px)");
    expect(bubble().hasAttribute("style")).toBe(true); // CSSOM, set by script
  });

  it("defaults to the right edge", () => {
    view.mountMessages();
    expect(bubble().classList.contains("on-right")).toBe(true);
    expect(bubble().style.transform).toMatch(/^translate\(960px, /);
  });

  it("shows the unread count in the badge, the class and the aria-label", () => {
    view.mountMessages();
    expect(bubble().classList.contains("unread")).toBe(false);
    expect(badge().hidden).toBe(true);
    m.state = { conversations: [], unreadPeople: 2 };
    m.listeners.forEach((fn) => fn({ conversationId: null }));
    expect(badge().textContent).toBe("2");
    expect(badge().hidden).toBe(false);
    expect(bubble().classList.contains("unread")).toBe(true);
    expect(bubble().getAttribute("aria-label")).toMatch(/2 people/);
    m.state = { conversations: [], unreadPeople: 1 };
    m.listeners.forEach((fn) => fn({ conversationId: null }));
    expect(bubble().getAttribute("aria-label")).toMatch(/1 person/);
  });

  it("opens the keyboard way too", () => {
    view.mountMessages();
    bubble().click(); // detail 0, like Enter / Space
    expect(float().hidden).toBe(false);
  });
});

describe("drag", () => {
  beforeEach(() => {
    localStorage.setItem("techfm.msgBubble.pos", JSON.stringify({ side: "right", y: 100 }));
    view.mountMessages();
  });

  it("under 6 px of movement is a tap and opens the panel", () => {
    pointer(bubble(), "pointerdown", 988, 128);
    pointer(bubble(), "pointermove", 991, 130);
    expect(trash().hidden).toBe(true);
    pointer(bubble(), "pointerup", 991, 130);
    expect(m.mountMessagePanel).toHaveBeenCalledTimes(1);
    expect(float().hidden).toBe(false);
  });

  it("more than 6 px is a drag: trashcan shows, no panel, snaps to the nearer edge", () => {
    pointer(bubble(), "pointerdown", 988, 128);
    pointer(bubble(), "pointermove", 700, 300);
    expect(trash().hidden).toBe(false);
    expect(trash().classList.contains("over")).toBe(false);
    pointer(bubble(), "pointermove", 100, 300);
    pointer(bubble(), "pointerup", 100, 300);
    expect(m.mountMessagePanel).not.toHaveBeenCalled();
    expect(trash().hidden).toBe(true);
    expect(bubble().classList.contains("on-left")).toBe(true);
    expect(bubble().style.transform).toBe("translate(8px, 272px)");
    expect(JSON.parse(localStorage.getItem("techfm.msgBubble.pos"))).toEqual({ side: "left", y: 272 });
  });

  it("dropping on the trashcan hides the bubble and sets the flag", () => {
    pointer(bubble(), "pointerdown", 988, 128);
    pointer(bubble(), "pointermove", 512, 712);
    expect(trash().classList.contains("over")).toBe(true);
    pointer(bubble(), "pointerup", 512, 712);
    expect(bubble().hidden).toBe(true);
    expect(trash().hidden).toBe(true);
    expect(localStorage.getItem("techfm.msgBubble.away")).toBe("1");
  });
});

describe("put away", () => {
  beforeEach(() => localStorage.setItem("techfm.msgBubble.away", "1"));

  it("a real sign-in clears the flag", () => {
    view.mountMessages();
    expect(localStorage.getItem("techfm.msgBubble.away")).toBeNull();
    expect(bubble().hidden).toBe(false);
  });

  it("a reload (resume) leaves it", () => {
    view.mountMessages({ resume: true });
    expect(localStorage.getItem("techfm.msgBubble.away")).toBe("1");
    expect(bubble().hidden).toBe(true);
  });

  it("openMessages goes to the Hub opener while away", () => {
    const opener = vi.fn();
    view.setHubOpener(opener);
    view.mountMessages({ resume: true });
    view.openMessages("c1");
    expect(opener).toHaveBeenCalledWith("c1");
    expect(m.mountMessagePanel).not.toHaveBeenCalled();
  });

  it("falls back to the floating panel with no Hub opener", () => {
    view.mountMessages({ resume: true });
    view.openMessages("c1");
    expect(m.mountMessagePanel).toHaveBeenCalledTimes(1);
    expect(m.panel.openChat).toHaveBeenCalledWith("c1");
    expect(float().hidden).toBe(false);
  });
});

describe("deep links and the service worker", () => {
  it("opens ?chat=<id> and strips it from the URL", () => {
    window.history.replaceState({}, "", "/?chat=c7&x=1");
    view.mountMessages();
    expect(m.panel.openChat).toHaveBeenCalledWith("c7");
    expect(window.location.search).toBe("?x=1");
    window.history.replaceState({}, "", "/");
  });

  it("opens the chat named by a service-worker open-chat message", () => {
    const listeners = [];
    const sw = {
      addEventListener: (t, fn) => listeners.push(fn),
      removeEventListener: (t, fn) => listeners.splice(listeners.indexOf(fn), 1),
    };
    Object.defineProperty(navigator, "serviceWorker", { value: sw, configurable: true });
    try {
      view.mountMessages();
      expect(listeners).toHaveLength(1);
      listeners[0]({ data: { type: "open-chat", chat: "c9" } });
      expect(m.panel.openChat).toHaveBeenCalledWith("c9");
      view.unmountMessages();
      expect(listeners).toHaveLength(0);
    } finally {
      delete navigator.serviceWorker;
    }
  });
});

describe("tutorial", () => {
  it("hides the bubble and the panel while one plays, and restores after", () => {
    view.mountMessages();
    view.openMessages();
    expect(float().hidden).toBe(false);
    document.dispatchEvent(new CustomEvent("tutorial:start"));
    expect(bubble().hidden).toBe(true);
    expect(float().hidden).toBe(true);
    document.dispatchEvent(new CustomEvent("tutorial:end"));
    expect(bubble().hidden).toBe(false);
    expect(float().hidden).toBe(false);
  });
});

describe("narrow screens and resize", () => {
  it("under 600 px the open panel is a sheet and the bubble steps aside", () => {
    setViewport(390, 800);
    view.mountMessages();
    view.openMessages();
    expect(float().classList.contains("sheet")).toBe(true);
    expect(bubble().hidden).toBe(true);
  });

  it("wide screens keep the bubble beside the panel", () => {
    view.mountMessages();
    view.openMessages();
    expect(float().classList.contains("sheet")).toBe(false);
    expect(bubble().hidden).toBe(false);
  });

  it("resize re-clamps the remembered position on screen", () => {
    localStorage.setItem("techfm.msgBubble.pos", JSON.stringify({ side: "right", y: 600 }));
    view.mountMessages();
    expect(bubble().style.transform).toBe("translate(960px, 600px)");
    setViewport(500, 300);
    window.dispatchEvent(new Event("resize"));
    expect(bubble().style.transform).toBe("translate(436px, 236px)");
    setViewport(1024, 768);
    window.dispatchEvent(new Event("resize"));
    expect(bubble().style.transform).toBe("translate(960px, 600px)");
  });
});

describe("unmountMessages (sign-out on a shared phone)", () => {
  it("destroys the panel, stops the store and leaves nothing visible", () => {
    m.state = { conversations: [], unreadPeople: 4 };
    view.mountMessages();
    view.openMessages("c1");
    view.unmountMessages();
    expect(m.panel.destroy).toHaveBeenCalled();
    expect(m.stopMessages).toHaveBeenCalled();
    expect(bubble().hidden).toBe(true);
    expect(trash().hidden).toBe(true);
    expect(float().hidden).toBe(true);
    expect(float().childElementCount).toBe(0);
    expect(badge().textContent).toBe("");
    expect(bubble().classList.contains("unread")).toBe(false);
  });

  it("removes every listener it added", () => {
    view.mountMessages();
    view.unmountMessages();
    expect(m.listeners.size).toBe(0);
    pointer(bubble(), "pointerdown", 988, 128);
    pointer(bubble(), "pointerup", 988, 128);
    document.dispatchEvent(new CustomEvent("tutorial:start"));
    window.dispatchEvent(new Event("resize"));
    expect(m.mountMessagePanel).not.toHaveBeenCalled();
    expect(bubble().hidden).toBe(true);
    expect(float().hidden).toBe(true);
  });

  it("openMessages is a no-op once signed out", () => {
    view.mountMessages();
    view.unmountMessages();
    view.openMessages("c1");
    expect(m.mountMessagePanel).not.toHaveBeenCalled();
  });
});

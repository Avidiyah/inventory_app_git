// The User Hub Messages tab: the panel mounts without a close button while the
// tab shows, is destroyed on leaving, and the bubble's Hub opener lands on the
// tab and opens a chat. The panel and the bubble are other units, so both are
// stubbed; the hub itself is the real one.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";

const m = vi.hoisted(() => ({
  panel: { openChat: vi.fn(), destroy: vi.fn() },
  mountMessagePanel: vi.fn(),
  setHubOpener: vi.fn(),
}));

vi.mock("../../../backend/static/views/messagePanel.js", () => ({
  mountMessagePanel: m.mountMessagePanel,
}));
vi.mock("../../../backend/static/views/messageBubble.js", () => ({
  setHubOpener: m.setHubOpener,
}));

beforeEach(() => {
  m.panel.openChat.mockClear();
  m.panel.destroy.mockClear();
  m.setHubOpener.mockClear();
  m.mountMessagePanel.mockReset();
  m.mountMessagePanel.mockImplementation((host) => {
    host.appendChild(document.createElement("div")).className = "stub-panel";
    return m.panel;
  });
});

afterEach(() => {
  stopClock();
  restoreHub();
});

const show = async (tab) => {
  el.tab(tab).click();
  await vi.advanceTimersByTimeAsync(10);
};

describe("Hub Messages tab", () => {
  it.each(["technician", "supervisor", "admin"])("is visible to a %s and the picker reads Messages", async (role) => {
    await openHub({ role });
    expect(el.tab("messages").hidden).toBe(false);
    expect(el.tab("messages").textContent).toBe("Messages");
    expect(el.tabs().contains(el.tab("messages"))).toBe(true);
    await show("messages");
    expect(el.panel("messages").hidden).toBe(false);
    expect(document.getElementById("hub-picker-label").textContent).toBe("Messages");
  });

  it("mounts the panel without a close button, once, and leaving destroys it", async () => {
    await openHub();
    expect(m.mountMessagePanel).not.toHaveBeenCalled();
    await show("messages");
    await show("messages");
    expect(m.mountMessagePanel).toHaveBeenCalledTimes(1);
    const [host, options] = m.mountMessagePanel.mock.calls[0];
    expect(host).toBe(el.panel("messages"));
    expect(options?.onClose ?? null).toBeNull();
    expect(host.querySelector(".stub-panel")).not.toBeNull();

    await show("home");
    expect(m.panel.destroy).toHaveBeenCalledTimes(1);
    expect(el.panel("messages").children).toHaveLength(0);
    expect(el.panel("messages").hidden).toBe(true);
  });

  it("leaving the hub page destroys the panel", async () => {
    await openHub();
    el.page().classList.add("active");
    await show("messages");
    el.page().classList.remove("active");
    await vi.advanceTimersByTimeAsync(10);
    expect(m.panel.destroy).toHaveBeenCalledTimes(1);
  });

  it("sign-out (messages:stop) destroys the panel", async () => {
    await openHub();
    el.page().classList.add("active");
    await show("messages");
    document.dispatchEvent(new Event("messages:stop"));
    expect(m.panel.destroy).toHaveBeenCalledTimes(1);
  });

  it("registers the Hub opener, which selects the tab and opens that chat", async () => {
    await openHub();
    expect(m.setHubOpener).toHaveBeenCalledTimes(1);
    const open = m.setHubOpener.mock.calls[0][0];
    el.page().classList.add("active");

    open("chat-7");
    await vi.advanceTimersByTimeAsync(10);
    expect(el.panel("messages").hidden).toBe(false);
    expect(el.tab("messages").getAttribute("aria-selected")).toBe("true");
    expect(m.panel.openChat).toHaveBeenCalledTimes(1);
    expect(m.panel.openChat).toHaveBeenCalledWith("chat-7");

    // Already showing: the same panel is reused, not remounted.
    open("chat-9");
    expect(m.mountMessagePanel).toHaveBeenCalledTimes(1);
    expect(m.panel.openChat).toHaveBeenLastCalledWith("chat-9");
  });

  it("the opener from another page shows the hub page first", async () => {
    await openHub();
    expect(el.page().classList.contains("active")).toBe(false);
    m.setHubOpener.mock.calls[0][0]("chat-3");
    await vi.advanceTimersByTimeAsync(50);
    expect(el.page().classList.contains("active")).toBe(true);
    expect(el.tab("messages").getAttribute("aria-selected")).toBe("true");
    expect(m.panel.openChat).toHaveBeenCalledWith("chat-3");
  });
});

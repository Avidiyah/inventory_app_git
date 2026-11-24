// The message panel shell: list, search, person picker, group form. The store,
// the API wrappers and the chat module are mocked; each has its own tests.

import { beforeEach, describe, expect, it, vi } from "vitest";
import { userEvent } from "@testing-library/user-event";
import { importView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";

const m = vi.hoisted(() => ({
  state: { conversations: [], unreadPeople: 0 },
  listeners: new Set(),
  refresh: vi.fn(),
  search: vi.fn(),
  people: vi.fn(),
  openDirect: vi.fn(),
  createGroup: vi.fn(),
  mountChat: vi.fn(),
}));
vi.mock("../../../backend/static/messagesStore.js", () => ({
  getState: () => m.state,
  onChange: (listener) => { m.listeners.add(listener); return () => m.listeners.delete(listener); },
  refresh: (...a) => m.refresh(...a),
}));
vi.mock("../../../backend/static/api.js", () => ({
  apiSearchMessages: (...a) => m.search(...a),
  apiListMessagePeople: (...a) => m.people(...a),
  apiOpenDirect: (...a) => m.openDirect(...a),
  apiCreateGroup: (...a) => m.createGroup(...a),
}));
vi.mock("../../../backend/static/views/messagePanelChat.js", () => ({
  mountChat: (...a) => m.mountChat(...a),
}));

const PEOPLE = [
  { id: "p1", name: "Dana Ortiz", role_label: "Technician" },
  { id: "p2", name: "Luis Romero", role_label: "Technician" },
  { id: "p3", name: "Tom Keller", role_label: "Technician" },
];
const msg = (id, body, at, extra = {}) => ({
  id, body, created_at: at, sender_id: "p1", sender_name: "Dana Ortiz", ...extra,
});
const conv = (id, name, last, extra = {}) => ({
  id, kind: "direct", name, starter_id: null, member_count: 2, last_message: last,
  unread_count: 0, unread_sender_ids: [], ...extra,
});

let host;
let destroy;

async function mount({ role = "technician", onClose } = {}) {
  await setTestUser({ role, id: "me" });
  const { mountMessagePanel } = await importView("views/messagePanel.js");
  host = document.createElement("div");
  document.body.append(host);
  const panel = mountMessagePanel(host, onClose === undefined ? {} : { onClose });
  destroy = panel.destroy;
  return panel;
}

const rowNames = () => [...host.querySelectorAll(".msg-conv .msg-name > span")].map((n) => n.textContent);
const button = (text) => [...host.querySelectorAll("button")].find((b) => b.textContent === text);
const searchBox = () => host.querySelector('input[type="search"]');

beforeEach(() => {
  m.state = { conversations: [], unreadPeople: 0 };
  m.listeners.clear();
  Object.values(m).forEach((v) => v?.mockReset?.());
  m.refresh.mockResolvedValue();
  m.people.mockResolvedValue({ people: PEOPLE });
  m.search.mockResolvedValue({ people: [], conversations: [], messages: [] });
  m.mountChat.mockReturnValue({ destroy: vi.fn() });
  document.body.replaceChildren();
});

describe("the conversation list", () => {
  it("shows rows newest first with unread counts, and follows the store", async () => {
    m.state.conversations = [
      conv("a", "Old chat", msg(1, "hi", "2026-11-20T10:00:00Z")),
      conv("b", "Fresh chat", msg(2, "hello", "2026-11-24T10:00:00Z"), { unread_count: 3 }),
    ];
    await mount();
    expect(rowNames()).toEqual(["Fresh chat", "Old chat"]);
    expect(host.querySelector(".msg-dot").textContent).toBe("3");
    expect(host.querySelector(".msg-conv.unread .msg-name > span").textContent).toBe("Fresh chat");

    m.state = { conversations: [conv("c", "Newest", msg(3, "x", "2026-11-24T11:00:00Z")), ...m.state.conversations], unreadPeople: 0 };
    m.listeners.forEach((l) => l({ conversationId: "c" }));
    expect(rowNames()[0]).toBe("Newest");
  });

  it("renders message text as text, never as HTML", async () => {
    m.state.conversations = [conv("a", "Dana", msg(1, "<b>bold</b>", "2026-11-24T10:00:00Z"))];
    await mount();
    expect(host.querySelector(".msg-snip").textContent).toBe("<b>bold</b>");
    expect(host.querySelector(".msg-snip b")).toBeNull();
  });

  it("tapping a row opens that chat", async () => {
    m.state.conversations = [conv("a", "Dana", msg(1, "hi", "2026-11-24T10:00:00Z"))];
    await mount();
    host.querySelector(".msg-conv").click();
    expect(m.mountChat).toHaveBeenCalledWith(host, expect.objectContaining({ conversationId: "a" }));
  });
});

describe("search", () => {
  it("debounces to one request per pause, keeps focus, and shows both sections", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    m.search.mockResolvedValue({
      people: [PEOPLE[2]],
      conversations: [conv("a", "Dana Ortiz", msg(1, "hi", "2026-11-24T10:00:00Z"))],
      messages: [{ conversation_id: "a", conversation_name: "Dana Ortiz", message: msg(5, "the gasket is in", "2026-11-24T09:00:00Z") }],
    });
    await mount();
    const box = searchBox();
    await user.click(box);
    await user.type(box, "gasket");
    expect(m.search).not.toHaveBeenCalled();
    await vi.advanceTimersByTimeAsync(300);
    expect(m.search).toHaveBeenCalledTimes(1);
    expect(m.search).toHaveBeenCalledWith("gasket");
    expect(document.activeElement).toBe(box);
    expect(searchBox()).toBe(box);
    expect([...host.querySelectorAll(".msg-sec")].map((s) => s.textContent)).toEqual(["People and groups", "Messages"]);
    expect(host.querySelector("mark").textContent).toBe("gasket");
  });

  it("stays on the list under two characters", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    m.state.conversations = [conv("a", "Dana", msg(1, "hi", "2026-11-24T10:00:00Z"))];
    await mount();
    await user.type(searchBox(), "g");
    await vi.advanceTimersByTimeAsync(400);
    expect(m.search).not.toHaveBeenCalled();
    expect(rowNames()).toEqual(["Dana"]);
  });

  it("says when nothing matches", async () => {
    vi.useFakeTimers();
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    await mount();
    await user.type(searchBox(), "zzz");
    await vi.advanceTimersByTimeAsync(300);
    expect(host.querySelector(".msg-empty").textContent).toBe('Nothing found for "zzz".');
  });
});

describe("New chat and New group", () => {
  it("hides New group from a technician and shows it to a Team Lead", async () => {
    await mount({ role: "technician" });
    expect(button("New chat")).toBeTruthy();
    expect(button("New group")).toBeUndefined();
    destroy();
    vi.resetModules();
    await mount({ role: "supervisor" });
    expect(button("New group")).toBeTruthy();
  });

  it("tapping a person opens the direct chat", async () => {
    m.openDirect.mockResolvedValue({ id: "d9" });
    await mount();
    button("New chat").click();
    await vi.waitFor(() => expect(host.querySelectorAll(".msg-conv")).toHaveLength(3));
    host.querySelectorAll(".msg-conv")[1].click();
    await vi.waitFor(() => expect(m.mountChat).toHaveBeenCalled());
    expect(m.openDirect).toHaveBeenCalledWith("p2");
    expect(m.mountChat.mock.calls[0][1].conversationId).toBe("d9");
  });

  it("Start group stays disabled until a name and two people are given, then creates", async () => {
    m.createGroup.mockResolvedValue({ id: "g1" });
    const user = userEvent.setup();
    await mount({ role: "supervisor" });
    button("New group").click();
    await vi.waitFor(() => expect(host.querySelectorAll('input[type="checkbox"]')).toHaveLength(3));
    const start = button("Start group");
    const boxes = host.querySelectorAll('input[type="checkbox"]');
    expect(start.disabled).toBe(true);
    await user.type(host.querySelector('input[aria-label="Group name"]'), "Bldg 4 flood");
    await user.click(boxes[0]);
    expect(start.disabled).toBe(true);
    await user.click(boxes[1]);
    expect(start.disabled).toBe(false);
    await user.click(start);
    expect(m.createGroup).toHaveBeenCalledWith("Bldg 4 flood", ["p1", "p2"]);
    await vi.waitFor(() => expect(m.mountChat.mock.calls[0][1].conversationId).toBe("g1"));
  });
});

describe("chat hand-off, Escape and the close button", () => {
  it("returns to the list with the note when the chat ends", async () => {
    m.state.conversations = [conv("a", "Dana", msg(1, "hi", "2026-11-24T10:00:00Z"))];
    const panel = await mount();
    panel.openChat("g7");
    const { onEnded } = m.mountChat.mock.calls[0][1];
    const chat = m.mountChat.mock.results[0].value;
    onEnded('"Bldg 4" was ended.');
    expect(chat.destroy).toHaveBeenCalled();
    expect(host.querySelector(".msg-note").textContent).toBe('"Bldg 4" was ended.');
    expect(rowNames()).toEqual(["Dana"]);
  });

  it("Escape and the X call onClose", async () => {
    const onClose = vi.fn();
    await mount({ onClose });
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(onClose).toHaveBeenCalledTimes(1);
    host.querySelector('button[aria-label="Close messages"]').click();
    expect(onClose).toHaveBeenCalledTimes(2);
  });

  it("has no X when onClose is null", async () => {
    await mount({ onClose: null });
    expect(host.querySelector('button[aria-label="Close messages"]')).toBeNull();
  });

  it("destroy drops listeners and the mounted chat", async () => {
    const onClose = vi.fn();
    const panel = await mount({ onClose });
    panel.openChat("a");
    const chat = m.mountChat.mock.results[0].value;
    panel.destroy();
    expect(chat.destroy).toHaveBeenCalled();
    expect(m.listeners.size).toBe(0);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(onClose).not.toHaveBeenCalled();
    expect(host.children).toHaveLength(0);
  });
});

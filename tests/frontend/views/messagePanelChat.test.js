// views/messagePanelChat.js: one open chat in the message panel.
//
// Real api.js through MSW. Only messagesStore.js is replaced, by a stub whose
// `emit` stands in for a `message.changed` envelope reaching the open chat.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import { importView, mountShell } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { answerConfirm } from "../helpers/dialogs.js";
import { conversationDetail, message, person } from "../helpers/messages.js";

const ME = "me-id";
const CHAT = "chat-1";
const people = [
  person({ id: ME, name: "Me Myself", role_label: "Technician" }),
  person({ id: "dana", name: "Dana Ortiz", role_label: "Team Lead" }),
  person({ id: "luis", name: "Luis Romero", role_label: "Technician" }),
];
const msg = (id, from, body = `body ${id}`) => message({
  id, sender_id: from, sender_name: people.find((p) => p.id === from)?.name ?? from, body,
  created_at: "2026-11-24T14:00:00Z",
});
const detail = (over = {}) => conversationDetail({
  id: CHAT, kind: "direct", name: "Dana Ortiz", starter_id: null, starter_name: null,
  members: people.slice(0, 2), messages: [msg(1, "dana"), msg(2, ME), msg(3, "dana")],
  has_more: false, seen_message_id: null, my_read_message_id: 0, ...over,
});

let visibility = "visible";
Object.defineProperty(document, "visibilityState", { configurable: true, get: () => visibility });
afterEach(() => { visibility = "visible"; });

const settle = () => new Promise((r) => setTimeout(r, 15));
const q = (sel) => document.querySelector(sel);
const bodies = () => [...document.querySelectorAll(".msg-msg")].map((n) => n.textContent);
const input = () => q(".msg-composer input");
const sendBtn = () => [...document.querySelectorAll(".msg-composer button")].find((b) => b.textContent === "Send");
const buttonNamed = (t) => [...document.querySelectorAll("button")].find((b) => b.textContent === t);

async function open({ chat = detail(), older = null } = {}) {
  await mountShell();
  await setTestUser({ id: ME });
  const listeners = new Set();
  vi.doMock("../../../backend/static/messagesStore.js", () => ({
    onChange: (fn) => { listeners.add(fn); return () => listeners.delete(fn); },
  }));
  const srv = { chat, older, reads: [], posts: [], gets: [] };
  server.use(
    http.get("/messages/conversations/:id", ({ request }) => {
      const before = new URL(request.url).searchParams.get("before");
      srv.gets.push(before);
      if (srv.getStatus) return HttpResponse.json({ detail: "gone" }, { status: srv.getStatus });
      return HttpResponse.json(before ? srv.older : srv.chat);
    }),
    http.post("/messages/conversations/:id/read", async ({ request }) => {
      const { up_to } = await request.json();
      srv.reads.push(up_to);
      return HttpResponse.json({ my_read_message_id: up_to });
    }),
    http.post("/messages/conversations/:id/messages", async ({ request }) => {
      const { body } = await request.json();
      srv.posts.push(body);
      if (srv.gate) await srv.gate;
      if (srv.postStatus) return HttpResponse.json({ detail: "gone" }, { status: srv.postStatus });
      return HttpResponse.json(msg(100 + srv.posts.length, ME, body));
    }),
    http.delete("/messages/groups/:id", () => { srv.ended = true; return new HttpResponse(null, { status: 204 }); }),
  );
  const { mountChat } = await importView("views/messagePanelChat.js");
  const host = document.createElement("div");
  document.body.append(host);
  const onBack = vi.fn();
  const onEnded = vi.fn();
  const view = mountChat(host, { conversationId: CHAT, onBack, onEnded });
  await vi.waitFor(() => expect(bodies().length).toBeGreaterThan(0));
  const emit = async (conversationId = CHAT) => { listeners.forEach((fn) => fn({ conversationId })); await settle(); };
  return { srv, host, view, onBack, onEnded, emit, listeners };
}

describe("reading", () => {
  it("opening marks the newest message read", async () => {
    const { srv } = await open();
    await vi.waitFor(() => expect(srv.reads).toEqual([3]));
  });

  it("a refetch with nothing newer posts no second read", async () => {
    const { srv, emit } = await open();
    await vi.waitFor(() => expect(srv.reads).toEqual([3]));
    await emit();
    await emit();
    expect(srv.reads).toEqual([3]);
  });

  it("never posts for an id the server already marked", async () => {
    const { srv } = await open({ chat: detail({ my_read_message_id: 3 }) });
    await settle();
    expect(srv.reads).toEqual([]);
  });

  it("a hidden page posts no read for a new message; becoming visible posts one", async () => {
    const { srv, emit } = await open();
    await vi.waitFor(() => expect(srv.reads).toEqual([3]));
    visibility = "hidden";
    srv.chat = detail({ messages: [...srv.chat.messages, msg(4, "dana")] });
    await emit();
    expect(bodies()).toHaveLength(4);
    expect(srv.reads).toEqual([3]);
    visibility = "visible";
    document.dispatchEvent(new Event("visibilitychange"));
    await vi.waitFor(() => expect(srv.reads).toEqual([3, 4]));
  });

  it("a chat inside a hidden ancestor posts no read", async () => {
    const { srv, host, emit } = await open();
    await vi.waitFor(() => expect(srv.reads).toEqual([3]));
    host.hidden = true;
    srv.chat = detail({ messages: [...srv.chat.messages, msg(4, "dana")] });
    await emit();
    expect(srv.reads).toEqual([3]);
  });
});

describe("live updates", () => {
  it("a message.changed for this chat appends the message and keeps typed text", async () => {
    const { srv, emit } = await open();
    await userEvent.setup().type(input(), "half a thought");
    srv.chat = detail({ messages: [...srv.chat.messages, msg(4, "dana", "new one")] });
    await emit();
    expect(bodies()).toContain("new one");
    expect(input().value).toBe("half a thought");
  });

  it("ignores another chat's envelope", async () => {
    const { srv, emit } = await open();
    await settle();
    const before = srv.gets.length;
    await emit("someone-else");
    expect(srv.gets.length).toBe(before);
  });

  it("destroy drops the store subscription", async () => {
    const { view, listeners } = await open();
    expect(listeners.size).toBe(1);
    view.destroy();
    expect(listeners.size).toBe(0);
  });
});

describe("earlier messages", () => {
  it("shows no button without has_more", async () => {
    await open();
    expect(buttonNamed("Load earlier messages")).toBeUndefined();
  });

  it("prepends the older page by the oldest loaded id and keeps typed text", async () => {
    const older = detail({ messages: [msg(-1, "dana", "ancient"), msg(0, ME, "old")], has_more: false });
    const { srv } = await open({ chat: detail({ has_more: true }), older });
    await userEvent.setup().type(input(), "still typing");
    buttonNamed("Load earlier messages").click();
    await vi.waitFor(() => expect(bodies()[0]).toBe("ancient"));
    expect(srv.gets).toContain("1");
    expect(bodies()).toHaveLength(5);
    expect(input().value).toBe("still typing");
    expect(buttonNamed("Load earlier messages")).toBeUndefined();
  });
});

describe("Sent and Seen", () => {
  it("says Seen when the other person's mark reaches my last message", async () => {
    await open({ chat: detail({ seen_message_id: 2, messages: [msg(1, "dana"), msg(2, ME)] }) });
    expect(q(".msg-meta").textContent).toMatch(/Seen$/);
  });

  it("says Sent while their mark is behind", async () => {
    await open({ chat: detail({ seen_message_id: 1, messages: [msg(1, "dana"), msg(2, ME)] }) });
    expect(q(".msg-meta").textContent).toMatch(/Sent$/);
  });

  it("never says Seen in a group", async () => {
    await open({ chat: detail({ kind: "group", seen_message_id: 2, starter_id: "dana", starter_name: "Dana Ortiz",
      members: people, messages: [msg(1, "dana"), msg(2, ME)] }) });
    expect(q(".msg-meta").textContent).toMatch(/Sent$/);
  });
});

describe("groups", () => {
  const group = (starter) => detail({ kind: "group", name: "Bldg 4 flood", starter_id: starter,
    starter_name: people.find((p) => p.id === starter).name, members: people });

  it("labels the group and names who started it", async () => {
    await open({ chat: group("dana") });
    expect(q(".msg-p-head").textContent).toContain("Temporary group · 3 people");
    expect(q(".msg-note").textContent).toContain("Started by Dana Ortiz");
  });

  it("offers End group to the starter only", async () => {
    await open({ chat: group("dana") });
    expect(buttonNamed("End group").hidden).toBe(true);
  });

  it("End group confirms, ends the group and goes back", async () => {
    const { srv, onBack } = await open({ chat: group(ME) });
    expect(buttonNamed("End group").hidden).toBe(false);
    buttonNamed("End group").click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(onBack).toHaveBeenCalled());
    expect(srv.ended).toBe(true);
  });

  it("declining the confirm ends nothing", async () => {
    const { srv, onBack } = await open({ chat: group(ME) });
    buttonNamed("End group").click();
    await answerConfirm(false);
    await settle();
    expect(srv.ended).toBeUndefined();
    expect(onBack).not.toHaveBeenCalled();
  });
});

describe("sending", () => {
  it("Enter sends and clears the field", async () => {
    const { srv } = await open();
    await userEvent.setup().type(input(), "hello{Enter}");
    await vi.waitFor(() => expect(bodies()).toContain("hello"));
    expect(srv.posts).toEqual(["hello"]);
    expect(input().value).toBe("");
  });

  it("two fast taps while in flight post once, and Send is disabled meanwhile", async () => {
    const { srv } = await open();
    let release;
    srv.gate = new Promise((r) => { release = r; });
    input().value = "once";
    sendBtn().click();
    await vi.waitFor(() => expect(sendBtn().disabled).toBe(true));
    sendBtn().click();
    input().dispatchEvent(new KeyboardEvent("keydown", { key: "Enter" }));
    release();
    await vi.waitFor(() => expect(sendBtn().disabled).toBe(false));
    expect(srv.posts).toEqual(["once"]);
    expect(bodies().filter((b) => b === "once")).toHaveLength(1);
  });

  it("a failed send keeps the text and says so", async () => {
    const { srv } = await open();
    srv.postStatus = 500;
    input().value = "keep me";
    sendBtn().click();
    await vi.waitFor(() => expect(q(".msg-error").hidden).toBe(false));
    expect(input().value).toBe("keep me");
  });
});

describe("a chat that ended", () => {
  it("a 404 on the first fetch calls onEnded", async () => {
    await mountShell();
    await setTestUser({ id: ME });
    vi.doMock("../../../backend/static/messagesStore.js", () => ({ onChange: () => () => {} }));
    server.use(http.get("/messages/conversations/:id", () => HttpResponse.json({ detail: "x" }, { status: 404 })));
    const { mountChat } = await importView("views/messagePanelChat.js");
    const onEnded = vi.fn();
    mountChat(document.body.appendChild(document.createElement("div")), { conversationId: CHAT, onBack() {}, onEnded });
    await vi.waitFor(() => expect(onEnded).toHaveBeenCalledWith("This chat has ended."));
  });

  it("a 404 on a refetch calls onEnded", async () => {
    const { srv, emit, onEnded } = await open();
    srv.getStatus = 404;
    await emit();
    expect(onEnded).toHaveBeenCalledWith("This chat has ended.");
  });

  it("a 404 on send calls onEnded", async () => {
    const { srv, onEnded } = await open();
    srv.postStatus = 404;
    input().value = "hi";
    sendBtn().click();
    await vi.waitFor(() => expect(onEnded).toHaveBeenCalledWith("This chat has ended."));
  });
});

describe("rendering bodies", () => {
  it("shows HTML as literal text with no element made from it", async () => {
    await open({ chat: detail({ messages: [msg(1, "dana", "<b>x</b>")] }) });
    expect(bodies()).toEqual(["<b>x</b>"]);
    expect(q(".msg-thread b")).toBeNull();
  });

  it("keeps emoji and a very long unbroken word as text", async () => {
    const long = "w".repeat(500);
    await open({ chat: detail({ messages: [msg(1, "dana", `${long} 👍`)] }) });
    expect(bodies()).toEqual([`${long} 👍`]);
  });
});

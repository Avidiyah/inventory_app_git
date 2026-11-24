// Live Messaging: one open chat inside the message panel.
//
// Layer: view. `mountChat(host, { conversationId, onBack, onEnded })` fills
// `host` with the chat header, thread and composer and returns `{ destroy }`
// (plus `markRead`, for a host that re-shows a hidden panel).
//
// The skeleton (header, composer) is built once. A refetch re-renders the
// thread only, so typed text and focus survive an incoming message. Bodies go
// in as text nodes, never HTML. A 404 on fetch, send or end means the chat
// ended under the reader: `onEnded("This chat has ended.")`, no error screen.

import {
  apiEndGroup, apiGetConversation, apiMarkConversationRead, apiSendMessage,
} from "../api.js";
import { confirmDialog } from "../dom.js";
import { getCurrentUser } from "../state.js";
import { onChange } from "../messagesStore.js";

const ENDED = "This chat has ended.";
const NEAR_BOTTOM_PX = 80;

function h(tag, attrs = {}, ...kids) {
  const e = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.className = v;
    else if (k.startsWith("on")) e.addEventListener(k.slice(2), v);
    else if (v === true) e.setAttribute(k, "");
    else if (v !== false && v != null) e.setAttribute(k, v);
  }
  kids.flat().forEach((c) => c != null && c !== false && e.append(c));
  return e;
}

const initials = (n) => String(n || "").split(" ").filter(Boolean).map((w) => w[0]).join("").slice(0, 2).toUpperCase();
const fmtTime = (iso) => new Date(iso).toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });

export function mountChat(host, { conversationId, onBack, onEnded }) {
  let detail = null;          // newest ConversationDetail, older pages merged in
  let posted = 0;             // highest id this client has posted as read
  let loading = false;
  let again = false;
  let sending = false;
  let loadingEarlier = false;
  let destroyed = false;

  // ---- skeleton, built once ------------------------------------------------
  const avatar = h("span", { class: "msg-av" });
  const title = document.createTextNode("");
  const sub = h("small", {});
  const endBtn = h("button", { class: "msg-btn small", type: "button", hidden: true, onclick: endGroup }, "End group");
  const note = h("div", { class: "msg-note", hidden: true });
  const thread = h("div", { class: "msg-thread" });
  const scroll = h("div", { class: "msg-p-scroll" }, thread);
  const errorLine = h("p", { class: "msg-error", role: "alert", hidden: true });
  const input = h("input", {
    class: "msg-field", placeholder: "Message", "aria-label": "Message", maxlength: 2000,
    onkeydown: (e) => { if (e.key === "Enter") send(); },
    oninput: () => { errorLine.hidden = true; },
  });
  const sendBtn = h("button", { class: "msg-btn primary", type: "button", onclick: send }, "Send");
  const root = h("div", { class: "msg-chat" },
    h("div", { class: "msg-p-head" },
      h("button", { class: "msg-icon-btn", type: "button", "aria-label": "Back to messages", onclick: () => onBack?.() }, "‹"),
      avatar, h("h2", {}, title, sub), endBtn),
    note, scroll, errorLine,
    h("div", { class: "msg-composer" }, input, sendBtn));
  host.replaceChildren(root);

  // ---- helpers ---------------------------------------------------------------
  const meId = () => String(getCurrentUser()?.id ?? "");
  const lastId = () => detail?.messages.at(-1)?.id ?? 0;
  const onScreen = () => host.isConnected && !host.closest("[hidden]");
  const nearBottom = () => scroll.scrollHeight - scroll.scrollTop - scroll.clientHeight <= NEAR_BOTTOM_PX;

  function ended() {
    if (destroyed) return;
    destroy();
    onEnded?.(ENDED);
  }

  function showError(text) {
    errorLine.textContent = text;
    errorLine.hidden = false;
  }

  // ---- reading ---------------------------------------------------------------
  // Never posts for an id already posted or already <= the server's mark, so
  // two people with the chat open settle after one round.
  function markRead() {
    if (destroyed || !detail || document.visibilityState !== "visible" || !onScreen()) return;
    const newest = lastId();
    if (!newest || newest <= Math.max(detail.my_read_message_id ?? 0, posted)) return;
    const previous = posted;
    posted = newest;
    apiMarkConversationRead(conversationId, newest).then((res) => {
      if (detail && res && res.my_read_message_id > (detail.my_read_message_id ?? 0)) {
        detail.my_read_message_id = res.my_read_message_id;
      }
    }).catch((err) => {
      if (err?.status === 404) ended();
      else if (posted === newest) posted = previous;   // retry on the next occasion
    });
  }

  // ---- rendering -------------------------------------------------------------
  function renderHead() {
    const group = detail.kind === "group";
    const me = meId();
    const other = detail.members.find((p) => String(p.id) !== me);
    title.data = detail.name;
    sub.textContent = group ? `Temporary group · ${detail.members.length} people` : (other?.role_label ?? "");
    avatar.className = "msg-av" + (group ? " group" : "");
    avatar.textContent = group ? "👥" : initials(detail.name);
    endBtn.hidden = !(group && String(detail.starter_id) === me);
    note.hidden = !group;
    if (group) {
      const mine = String(detail.starter_id) === me;
      const first = String(detail.starter_name || "").split(" ")[0];
      note.textContent = `Started by ${mine ? "you" : detail.starter_name}. Ends when ${mine ? "you end" : first + " ends"} it, or after 7 quiet days.`;
    }
  }

  function renderThread({ keep = null } = {}) {
    const stick = keep ? false : nearBottom();
    const group = detail.kind === "group";
    const me = meId();
    const kids = [];
    if (detail.has_more) {
      kids.push(h("button", {
        class: "msg-load-earlier", type: "button", disabled: loadingEarlier, onclick: loadEarlier,
      }, "Load earlier messages"));
    }
    if (!detail.messages.length) kids.push(h("p", { class: "msg-empty" }, "No messages yet. Say hello."));
    for (const m of detail.messages) {
      const mine = String(m.sender_id) === me;
      kids.push(h("div", { class: "msg-msg " + (mine ? "mine" : "them") },
        group && !mine ? h("span", { class: "msg-who" }, m.sender_name) : null,
        document.createTextNode(m.body)));
    }
    const last = detail.messages.at(-1);
    if (last && String(last.sender_id) === me) {
      const seen = detail.kind === "direct" && detail.seen_message_id != null && detail.seen_message_id >= last.id;
      kids.push(h("span", { class: "msg-meta" }, `${fmtTime(last.created_at)} · ${seen ? "Seen" : "Sent"}`));
    }
    thread.replaceChildren(...kids);
    if (keep) scroll.scrollTop = keep();
    else if (stick) scroll.scrollTop = scroll.scrollHeight;
  }

  function render(opts) {
    renderHead();
    renderThread(opts);
    markRead();
  }

  // ---- loading ---------------------------------------------------------------
  async function fetchLatest() {
    const fresh = await apiGetConversation(conversationId);
    if (destroyed) return;
    const first = fresh.messages[0]?.id ?? Infinity;
    const kept = detail ? detail.messages.filter((m) => m.id < first) : [];
    const hasMore = kept.length ? detail.has_more : fresh.has_more;
    const wasEmpty = !detail;
    detail = { ...fresh, messages: [...kept, ...fresh.messages], has_more: hasMore };
    render();
    if (wasEmpty) scroll.scrollTop = scroll.scrollHeight;
  }

  // One fetch in flight plus one rerun, however many envelopes arrive.
  async function load() {
    if (loading) { again = true; return; }
    loading = true;
    try {
      do {
        again = false;
        await fetchLatest();
      } while (again && !destroyed);
    } catch (err) {
      if (err?.status === 404) ended();
      else if (!detail) showLoadFailure();
    } finally {
      loading = false;
    }
  }

  function showLoadFailure() {
    thread.replaceChildren(
      h("p", { class: "msg-empty" }, "Could not load this chat."),
      h("button", { class: "msg-btn small", type: "button", onclick: () => { thread.replaceChildren(); load(); } }, "Try again"));
  }

  async function loadEarlier() {
    if (loadingEarlier || !detail?.messages.length) return;
    loadingEarlier = true;
    const before = detail.messages[0].id;
    const fromBottom = scroll.scrollHeight - scroll.scrollTop;
    renderThread({ keep: () => scroll.scrollTop });
    try {
      const page = await apiGetConversation(conversationId, { before });
      if (destroyed) return;
      const have = new Set(detail.messages.map((m) => m.id));
      detail.messages = [...page.messages.filter((m) => !have.has(m.id)), ...detail.messages];
      detail.has_more = page.has_more;
      loadingEarlier = false;
      renderThread({ keep: () => scroll.scrollHeight - fromBottom });
    } catch (err) {
      loadingEarlier = false;
      if (err?.status === 404) return ended();
      showError("Could not load earlier messages. Try again.");
      if (detail) renderThread({ keep: () => scroll.scrollTop });
    }
  }

  // ---- sending / ending ------------------------------------------------------
  async function send() {
    const text = input.value.trim();
    if (sending || !text || !detail) return;
    sending = true;
    sendBtn.disabled = true;
    errorLine.hidden = true;
    try {
      const msg = await apiSendMessage(conversationId, text);
      if (destroyed) return;
      if (input.value.trim() === text) input.value = "";
      if (!detail.messages.some((m) => m.id === msg.id)) detail.messages = [...detail.messages, msg];
      posted = Math.max(posted, msg.id);   // the server moved the sender's mark with the send
      detail.my_read_message_id = Math.max(detail.my_read_message_id ?? 0, msg.id);
      renderThread();
      scroll.scrollTop = scroll.scrollHeight;
    } catch (err) {
      if (err?.status === 404) return ended();
      showError("Could not send. Your message is still here; try again.");
    } finally {
      sending = false;
      sendBtn.disabled = false;
      focusInput();
    }
  }

  async function endGroup() {
    if (!detail) return;
    const ok = await confirmDialog(
      `End "${detail.name}" for everyone? Its messages are deleted and this cannot be undone.`,
      { confirmText: "End group" });
    if (!ok || destroyed) return;
    try {
      await apiEndGroup(conversationId);
    } catch (err) {
      if (err?.status === 404) return ended();
      return showError("Could not end the group. Try again.");
    }
    if (!destroyed) onBack?.();
  }

  function focusInput() {
    // A phone keyboard popping up unasked would cover the thread.
    if (!destroyed && window.matchMedia?.("(pointer: fine)").matches) input.focus();
  }

  // ---- wiring ----------------------------------------------------------------
  // `null` = a refresh not tied to an envelope (reconnect), which may carry
  // messages this chat missed.
  const unsubscribe = onChange((ev) => {
    const id = ev?.conversationId ?? null;
    if (id === null || String(id) === String(conversationId)) load();
  });
  document.addEventListener("visibilitychange", markRead);
  host.addEventListener("focusin", markRead);
  host.addEventListener("pointerdown", markRead);

  function destroy() {
    if (destroyed) return;
    destroyed = true;
    unsubscribe?.();
    document.removeEventListener("visibilitychange", markRead);
    host.removeEventListener("focusin", markRead);
    host.removeEventListener("pointerdown", markRead);
  }

  load().then(focusInput);
  return { destroy, markRead };
}

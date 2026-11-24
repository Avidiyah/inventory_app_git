// View: the message panel shell -- conversation list, search, person picker
// and group form. A chat itself is mounted by messagePanelChat.js.
//
// Layer: views. Mounted into a host element by the floating bubble
// (messageBubble.js, with a close button) and by the User Hub tab
// (hubMessages.js, no close button). The list reads from messagesStore and
// never fetches itself. Every user-provided string is set with textContent
// or appended as a text node, never as HTML. The search input is built once
// per list render; typing only swaps the results beneath it, so focus stays.

import {
  apiBroadcastMessage, apiCreateGroup, apiListMessagePeople, apiOpenDirect, apiSearchMessages,
} from "../api.js";
import { friendlyError } from "../format.js";
import { onChange, getState, refresh } from "../messagesStore.js";
import { roleAtLeast } from "../roles.js";
import { getCurrentUser, getRole } from "../state.js";
import { mountChat } from "./messagePanelChat.js";
import { button, filterField, h, marked, nameMatches, pickList } from "./messagePanelPicker.js";

const SEARCH_MIN_CHARS = 2;
const SEARCH_DELAY_MS = 250;
const MAX_GROUP_NAME = 60;
const MAX_GROUP_MEMBERS = 30;
const MAX_BODY = 2000;

const initials = (name) => String(name || "?").split(/\s+/).filter(Boolean)
  .map((w) => w[0]).join("").slice(0, 2).toUpperCase();

function timeLabel(iso) {
  if (!iso) return "";
  const then = new Date(iso);
  if (Number.isNaN(then.getTime())) return "";
  const now = new Date();
  if (then.toDateString() === now.toDateString()) {
    return then.toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
  }
  const yesterday = new Date(now);
  yesterday.setDate(now.getDate() - 1);
  if (then.toDateString() === yesterday.toDateString()) return "Yesterday";
  return then.toLocaleDateString([], { month: "short", day: "numeric" });
}

// `broadcast` (the Hub tab passes it) offers Admin+ "Message many".
export function mountMessagePanel(host, { onClose = null, broadcast = false } = {}) {
  let chat = null;
  let destroyed = false;
  let searchTimer = null;
  let searchSeq = 0;
  let fillList = null; // set while the list view is on screen
  let query = "";

  const meId = () => getCurrentUser()?.id ?? null;
  const canGroup = () => roleAtLeast(getRole(), "supervisor");

  function leaveChat() {
    chat?.destroy();
    chat = null;
  }

  function stopSearch() {
    clearTimeout(searchTimer);
    searchTimer = null;
    searchSeq += 1; // drops any response still in flight
  }

  // ---------- shared pieces ----------
  function header(title, back) {
    const head = h("div", "msg-p-head");
    if (back) head.append(button("msg-icon-btn", "‹", () => showList(), "Back to messages"));
    head.append(h("h2", "", title));
    if (!back && onClose) head.append(button("msg-icon-btn", "✕", onClose, "Close messages"));
    return head;
  }

  function show(...nodes) {
    stopSearch();
    leaveChat();
    fillList = null;
    host.replaceChildren(...nodes);
  }

  function personRow(person, q) {
    const label = h("span", "");
    label.append(...marked(person.name, q));
    const name = h("span", "msg-name");
    name.append(label);
    const mid = h("span", "msg-mid");
    mid.append(name, h("span", "msg-snip", person.role_label || ""));
    const row = button("msg-conv", "", () => openDirect(person.id));
    row.append(h("span", "msg-av", initials(person.name)), mid);
    return row;
  }

  function snippetOf(row) {
    const last = row.last_message;
    if (!last) return "No messages yet";
    return senderPrefix(last, row.kind) + last.body;
  }

  function senderPrefix(message, kind) {
    if (message.sender_id === meId()) return "You: ";
    return kind === "group" ? `${String(message.sender_name || "").split(" ")[0]}: ` : "";
  }

  // One list row. `snippet` is a string or an array of nodes; `time` an ISO string.
  function convRow({ id, kind, name, unread = 0, time, snippet, q }) {
    const row = button("msg-conv" + (unread ? " unread" : ""), "", () => openChat(id));
    const title = h("span", "msg-name");
    const label = h("span", "");
    label.append(...marked(name || "", q));
    title.append(label);
    if (kind === "group") title.append(h("span", "msg-tag", "Group"));
    title.append(h("time", "", timeLabel(time)));
    const snip = h("span", "msg-snip");
    snip.append(...(Array.isArray(snippet) ? snippet : [snippet]));
    const mid = h("span", "msg-mid");
    mid.append(title, snip);
    row.append(h("span", "msg-av" + (kind === "group" ? " group" : ""),
      kind === "group" ? "\u{1F465}" : initials(name)), mid);
    if (unread) {
      const dot = h("span", "msg-dot", String(unread));
      dot.setAttribute("aria-label", `${unread} unread`);
      row.append(dot);
    }
    return row;
  }

  function listRow(c) {
    return convRow({
      id: c.id, kind: c.kind, name: c.name, unread: c.unread_count,
      time: c.last_message?.created_at, snippet: snippetOf(c),
    });
  }

  // ---------- list view ----------
  function showList(note = "") {
    const results = h("div", "msg-p-scroll");
    const search = h("input", "msg-field");
    search.type = "search";
    search.placeholder = "Search people and messages";
    search.setAttribute("aria-label", "Search people and messages");
    search.value = query;
    const tools = h("div", "msg-p-tools");
    const buttons = h("div", "msg-row-btns");
    buttons.append(button("msg-btn primary", "New chat", showPeople));
    if (canGroup()) buttons.append(button("msg-btn", "New group", showGroupForm));
    if (broadcast && roleAtLeast(getRole(), "admin")) buttons.append(button("msg-btn", "Message many", showBroadcast));
    tools.append(search, buttons);

    const nodes = [header("Messages", false)];
    if (note) {
      const strip = h("div", "msg-note", note);
      strip.setAttribute("role", "status");
      nodes.push(strip);
    }
    nodes.push(tools, results);
    show(...nodes);

    const empty = (text) => results.replaceChildren(h("p", "msg-empty", text));

    function fillRows() {
      const rows = [...getState().conversations].sort((a, b) =>
        (b.last_message?.created_at ?? "").localeCompare(a.last_message?.created_at ?? ""));
      if (!rows.length) return empty("No messages yet. Tap New chat to start one.");
      results.replaceChildren(...rows.map(listRow));
    }

    function fillResults(found, q) {
      const directNames = new Set(found.conversations.filter((c) => c.kind === "direct").map((c) => c.name));
      const people = found.people.filter((p) => !directNames.has(p.name));
      const nodes = [];
      if (found.conversations.length || people.length) {
        nodes.push(h("div", "msg-sec", "People and groups"),
          ...found.conversations.map((c) => convRow({
            id: c.id, kind: c.kind, name: c.name, unread: c.unread_count,
            time: c.last_message?.created_at, snippet: snippetOf(c), q,
          })),
          ...people.map((p) => personRow(p, q)));
      }
      if (found.messages.length) {
        nodes.push(h("div", "msg-sec", "Messages"),
          ...found.messages.map(({ conversation_id: id, conversation_name: name, message: m }) => {
            const kind = found.conversations.find((c) => c.id === id)?.kind
              ?? getState().conversations.find((c) => c.id === id)?.kind;
            return convRow({
              id, kind, name, time: m.created_at,
              snippet: [senderPrefix(m, kind), ...marked(m.body, q)],
            });
          }));
      }
      if (nodes.length) results.replaceChildren(...nodes);
      else empty(`Nothing found for "${q}".`);
    }

    async function runSearch(q) {
      const seq = ++searchSeq;
      let found;
      try {
        found = await apiSearchMessages(q);
      } catch (err) {
        if (seq === searchSeq && !destroyed) empty(friendlyError(err, "Search failed. Try again."));
        return;
      }
      if (seq === searchSeq && !destroyed) fillResults(found, q);
    }

    function fill() {
      const q = query.trim();
      stopSearch();
      if (q.length < SEARCH_MIN_CHARS) return fillRows();
      searchTimer = setTimeout(() => runSearch(q), SEARCH_DELAY_MS);
    }

    search.addEventListener("input", () => { query = search.value; fill(); });
    fillList = fillRows;
    if (query.trim().length >= SEARCH_MIN_CHARS) fill(); else fillRows();
  }

  // ---------- person picker ----------
  async function loadPeople() {
    try {
      return (await apiListMessagePeople()).people;
    } catch (err) {
      return friendlyError(err, "Could not load people. Try again.");
    }
  }

  async function showPeople() {
    const filter = filterField();
    const tools = h("div", "msg-p-tools");
    tools.append(filter);
    const scroll = h("div", "msg-p-scroll");
    scroll.append(h("p", "msg-empty", "Loading..."));
    show(header("New chat", true), tools, scroll);
    // A phone keyboard popping up unasked would cover the list (same rule as the chat).
    if (window.matchMedia?.("(pointer: fine)").matches) filter.focus();
    const people = await loadPeople();
    if (destroyed || host.lastChild !== scroll) return;
    if (typeof people === "string") return scroll.replaceChildren(h("p", "msg-empty", people));
    if (!people.length) return scroll.replaceChildren(h("p", "msg-empty", "No one else to message."));
    const render = () => {
      const q = filter.value.trim();
      const shown = people.filter((p) => nameMatches(p.name, q));
      scroll.replaceChildren(...(shown.length
        ? [h("div", "msg-sec", "Pick a person"), ...shown.map((p) => personRow(p, q))]
        : [h("p", "msg-empty", `No one matches "${q}".`)]));
    };
    filter.addEventListener("input", render);
    render();
  }

  async function openDirect(userId) {
    try {
      const { id } = await apiOpenDirect(userId);
      if (!destroyed) openChat(id);
    } catch (err) {
      if (!destroyed) showList(friendlyError(err, "Could not open that chat."));
    }
  }

  // ---------- group form ----------
  async function showGroupForm() {
    const name = h("input", "msg-field");
    name.placeholder = "Group name, e.g. Bldg 4 flood";
    name.maxLength = MAX_GROUP_NAME;
    name.setAttribute("aria-label", "Group name");
    const status = h("p", "msg-note");
    status.setAttribute("role", "status");
    const create = button("msg-btn primary", "Start group", () => submit());
    create.disabled = true;
    const scroll = h("div", "msg-p-scroll");
    scroll.append(h("p", "msg-empty", "Loading..."));
    const bar = h("div", "msg-composer");
    bar.append(create);
    const tools = h("div", "msg-p-tools");
    tools.append(name);
    show(header("New group", true), tools, scroll, bar);

    let pick = null;
    const check = () => {
      const n = pick ? pick.picked().length : 0;
      create.disabled = !name.value.trim() || n < 2 || n > MAX_GROUP_MEMBERS;
    };
    name.addEventListener("input", check);

    async function submit() {
      create.disabled = true;
      status.textContent = "";
      try {
        const { id } = await apiCreateGroup(name.value.trim(), pick.picked());
        refresh().catch(() => {});
        if (!destroyed) openChat(id);
      } catch (err) {
        if (destroyed) return;
        status.textContent = friendlyError(err, "Could not start the group.");
        tools.append(status);
        check();
      }
    }

    const people = await loadPeople();
    if (destroyed || host.lastChild !== bar) return;
    if (typeof people === "string") return scroll.replaceChildren(h("p", "msg-empty", people));
    pick = pickList(people, { title: "Pick at least two people", onChange: check });
    tools.append(...pick.tools);
    scroll.replaceChildren(...pick.list);
  }

  // ---------- message many (Admin+, Hub tab only) ----------
  async function showBroadcast() {
    const text = h("input", "msg-field");
    text.placeholder = "Message";
    text.maxLength = MAX_BODY;
    text.setAttribute("aria-label", "Message to send");
    const status = h("p", "msg-note");
    status.setAttribute("role", "status");
    let sending = false;
    const send = button("msg-btn primary", "Send", () => submit());
    send.disabled = true;
    const scroll = h("div", "msg-p-scroll");
    scroll.append(h("p", "msg-empty", "Loading..."));
    const bar = h("div", "msg-composer");
    bar.append(text, send);
    const tools = h("div", "msg-p-tools");
    show(header("Message many", true), tools, scroll, bar);

    let pick = null;
    const check = () => {
      send.disabled = sending || !text.value.trim() || !pick || !pick.picked().length;
    };
    text.addEventListener("input", check);

    async function submit() {
      if (sending) return;
      sending = true;
      check();
      status.textContent = "";
      try {
        const { sent } = await apiBroadcastMessage(pick.picked(), text.value.trim());
        refresh().catch(() => {});
        if (!destroyed) showList(`Sent to ${sent} ${sent === 1 ? "person" : "people"}.`);
      } catch (err) {
        if (destroyed) return;
        sending = false;
        status.textContent = friendlyError(err, "Could not send. Try again.");
        tools.append(status);
        check();
      }
    }

    const people = await loadPeople();
    if (destroyed || host.lastChild !== bar) return;
    if (typeof people === "string") return scroll.replaceChildren(h("p", "msg-empty", people));
    pick = pickList(people, { title: "Pick people", bulk: true, onChange: check });
    tools.append(...pick.tools);
    scroll.replaceChildren(...pick.list);
  }

  // ---------- chat ----------
  function openChat(id) {
    stopSearch();
    leaveChat();
    fillList = null;
    host.replaceChildren();
    chat = mountChat(host, {
      conversationId: id,
      onBack: () => showList(),
      onEnded: (note) => showList(note),
    });
  }

  // ---------- wiring ----------
  const onKeydown = (e) => { if (e.key === "Escape" && onClose) onClose(); };
  document.addEventListener("keydown", onKeydown);
  const unsubscribe = onChange(() => { if (fillList && query.trim().length < SEARCH_MIN_CHARS) fillList(); });

  host.classList.add("msg-panel");
  showList();

  return {
    openChat,
    destroy() {
      if (destroyed) return;
      destroyed = true;
      stopSearch();
      document.removeEventListener("keydown", onKeydown);
      unsubscribe();
      leaveChat();
      host.replaceChildren();
      host.classList.remove("msg-panel");
    },
  };
}

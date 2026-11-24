// View: the floating message bubble (a chat head that lives inside the app).
//
// Layer: views. Owns #msg-bubble, #msg-trash and #msg-float from the shell.
// `auth.js` calls mountMessages() on sign-in / boot and unmountMessages() on
// sign-out, so nothing of one person's chats survives for the next person on a
// shared phone. The bubble is a <button> (badge is a <span> inside: no nested
// buttons); drag uses Pointer Events; position goes through CSSOM because the
// CSP drops style= attributes, states go through classes.

import { startMessages, stopMessages, getState, onChange } from "../messagesStore.js";
import { mountMessagePanel } from "./messagePanel.js";

const POS_KEY = "techfm.msgBubble.pos";
const AWAY_KEY = "techfm.msgBubble.away";
const SIZE = 56;
const GAP = 8;
const TAP_PX = 6; // under this much movement a press is a tap, not a drag
const SHEET_BELOW = 600; // px: the panel is a bottom sheet under this width
const TRASH_SIZE = 64;
const TRASH_BOTTOM = 24;
const TRASH_HOT_PX = 56; // bubble centre this close to the trashcan centre = hot

const bubble = document.getElementById("msg-bubble");
const badge = document.getElementById("msg-bubble-badge");
const trash = document.getElementById("msg-trash");
const float = document.getElementById("msg-float");

let mounted = false;
let away = false; // put in the trashcan: stays away until the next sign-in
let tutorial = false;
let panel = null; // handle from mountMessagePanel while the floating panel is open
let hubOpener = null;
let pos = { side: "right", y: 0 };
let cur = { x: 0, y: 0 };
let drag = null; // { offX, offY, startX, startY, moved } during a press
let unsubscribe = null;

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

export function snapSide(centerX, viewportWidth) {
  return centerX < viewportWidth / 2 ? "left" : "right";
}

export function badgeText(n) {
  return n <= 0 ? "" : n > 9 ? "9+" : String(n);
}

export function setHubOpener(fn) {
  hubOpener = fn;
}

// --- storage (every access guarded: private windows throw) ----------------

function readAway() {
  try { return localStorage.getItem(AWAY_KEY) === "1"; } catch { return false; }
}

function writeAway(on) {
  try {
    if (on) localStorage.setItem(AWAY_KEY, "1");
    else localStorage.removeItem(AWAY_KEY);
  } catch { /* the flag is a convenience */ }
}

function readPos() {
  try {
    const p = JSON.parse(localStorage.getItem(POS_KEY));
    if ((p?.side === "left" || p?.side === "right") && Number.isFinite(p.y)) return p;
  } catch { /* fall through to the default */ }
  return { side: "right", y: Math.round(window.innerHeight * 0.65) };
}

function writePos() {
  try { localStorage.setItem(POS_KEY, JSON.stringify(pos)); } catch { /* ignore */ }
}

// --- placement -------------------------------------------------------------

const clampY = (y) => clamp(y, GAP, Math.max(GAP, window.innerHeight - SIZE - GAP));
const homeX = (side) => (side === "left" ? GAP : window.innerWidth - SIZE - GAP);

function setXY(x, y) {
  cur = { x: Math.round(x), y: Math.round(y) };
  bubble.style.transform = `translate(${cur.x}px, ${cur.y}px)`;
}

// The stored y is never overwritten by a clamp, so a rotate and back restores it.
function place() {
  setXY(homeX(pos.side), clampY(pos.y));
  for (const el of [bubble, float]) {
    el.classList.toggle("on-left", pos.side === "left");
    el.classList.toggle("on-right", pos.side === "right");
  }
  placeFloat();
}

// The approved preview's placePanel(): beside the bubble, bottoms aligned,
// clamped on screen. A fixed host with no inset would sit below the page.
function placeFloat() {
  float.style.left = float.style.right = float.style.top = "";
  if (!panel || isSheet()) return; // the sheet positions itself in CSS
  const h = float.offsetHeight || Math.min(560, window.innerHeight - 16);
  float.style.top = `${clamp(cur.y + SIZE - h, GAP, window.innerHeight - h - GAP)}px`;
  float.style[pos.side] = `${SIZE + GAP * 2}px`;
}

// --- visibility ------------------------------------------------------------

const isSheet = () => window.innerWidth < SHEET_BELOW;

function sync() {
  const open = mounted && panel !== null;
  const sheet = isSheet();
  bubble.hidden = !mounted || away || tutorial || (sheet && open);
  float.hidden = !open || tutorial;
  float.classList.toggle("sheet", sheet);
  placeFloat(); // after un-hiding, so offsetHeight is real
  if (!mounted) trash.hidden = true;
}

function renderBadge() {
  const n = getState().unreadPeople || 0;
  badge.textContent = badgeText(n);
  badge.hidden = n === 0;
  bubble.classList.toggle("unread", n > 0);
  bubble.setAttribute(
    "aria-label",
    n ? `Messages, ${n} ${n === 1 ? "person" : "people"} unread` : "Messages",
  );
}

// --- panel -----------------------------------------------------------------

function openPanel(chatId) {
  if (!panel) panel = mountMessagePanel(float, { onClose: closePanel });
  if (chatId) panel.openChat(chatId);
  sync();
}

function closePanel() {
  if (panel) panel.destroy();
  panel = null;
  float.replaceChildren();
  sync();
}

export function openMessages(chatId = null) {
  if (!mounted) return;
  if (away && hubOpener) hubOpener(chatId);
  else openPanel(chatId);
}

// --- drag ------------------------------------------------------------------

function trashCentre() {
  const r = trash.getBoundingClientRect();
  if (r.width) return { x: r.left + r.width / 2, y: r.top + r.height / 2 };
  return { x: window.innerWidth / 2, y: window.innerHeight - TRASH_BOTTOM - TRASH_SIZE / 2 };
}

function overTrash() {
  const t = trashCentre();
  return Math.hypot(cur.x + SIZE / 2 - t.x, cur.y + SIZE / 2 - t.y) < TRASH_HOT_PX;
}

function endDrag() {
  drag = null;
  trash.hidden = true;
  trash.classList.remove("over");
  bubble.classList.remove("dragging");
}

function onPointerDown(e) {
  if (e.button > 0) return;
  drag = { offX: e.clientX - cur.x, offY: e.clientY - cur.y, startX: e.clientX, startY: e.clientY, moved: false };
  try { bubble.setPointerCapture(e.pointerId); } catch { /* synthetic / unsupported */ }
}

function onPointerMove(e) {
  if (!drag) return;
  if (!drag.moved) {
    if (Math.hypot(e.clientX - drag.startX, e.clientY - drag.startY) < TAP_PX) return;
    drag.moved = true;
    trash.hidden = false;
    bubble.classList.add("dragging");
  }
  setXY(
    clamp(e.clientX - drag.offX, 0, window.innerWidth - SIZE),
    clamp(e.clientY - drag.offY, 0, window.innerHeight - SIZE),
  );
  trash.classList.toggle("over", overTrash());
}

function onPointerUp() {
  if (!drag) return;
  const { moved } = drag;
  const dropped = moved && overTrash();
  endDrag();
  if (!moved) { togglePanel(); return; }
  if (dropped) { putAway(); return; }
  pos = { side: snapSide(cur.x + SIZE / 2, window.innerWidth), y: clampY(cur.y) };
  writePos();
  place();
}

function onPointerCancel() {
  if (!drag) return;
  endDrag();
  place();
}

// A pointer tap is handled on pointerup; this click is the keyboard path
// (Enter / Space fire click with detail 0).
function onClick(e) {
  if (e.detail === 0) togglePanel();
}

function togglePanel() {
  if (panel) closePanel();
  else openMessages();
}

function putAway() {
  away = true;
  writeAway(true);
  closePanel();
  place();
}

// --- lifecycle -------------------------------------------------------------

const onResize = () => { if (mounted) { place(); sync(); } };
const onTutorialStart = () => { tutorial = true; sync(); };
const onTutorialEnd = () => { tutorial = false; sync(); };
const onSwMessage = (e) => {
  if (e.data?.type === "open-chat" && e.data.chat) openMessages(String(e.data.chat));
};

const bubbleEvents = [
  ["pointerdown", onPointerDown], ["pointermove", onPointerMove],
  ["pointerup", onPointerUp], ["pointercancel", onPointerCancel], ["click", onClick],
];

// `resume` is true for a page reload (the put-away flag survives it) and false
// for a real sign-in (the flag clears).
export function mountMessages({ resume = false } = {}) {
  unmountMessages();
  if (!resume) writeAway(false);
  away = readAway();
  tutorial = false;
  mounted = true;
  pos = readPos();
  bubbleEvents.forEach(([t, fn]) => bubble.addEventListener(t, fn));
  window.addEventListener("resize", onResize);
  document.addEventListener("tutorial:start", onTutorialStart);
  document.addEventListener("tutorial:end", onTutorialEnd);
  navigator.serviceWorker?.addEventListener?.("message", onSwMessage);
  unsubscribe = onChange(renderBadge);
  renderBadge();
  place();
  sync();
  startMessages().then(() => { if (mounted) renderBadge(); }, () => {});

  const params = new URLSearchParams(window.location.search);
  const chat = params.get("chat");
  if (chat) {
    params.delete("chat");
    const qs = params.toString();
    window.history.replaceState({}, "", window.location.pathname + (qs ? `?${qs}` : "") + window.location.hash);
    openMessages(chat);
  }
}

// Sign-out: nothing of the previous person may stay on screen or in memory.
export function unmountMessages() {
  if (panel) panel.destroy();
  panel = null;
  float.replaceChildren();
  stopMessages();
  bubbleEvents.forEach(([t, fn]) => bubble.removeEventListener(t, fn));
  window.removeEventListener("resize", onResize);
  document.removeEventListener("tutorial:start", onTutorialStart);
  document.removeEventListener("tutorial:end", onTutorialEnd);
  navigator.serviceWorker?.removeEventListener?.("message", onSwMessage);
  if (unsubscribe) unsubscribe();
  unsubscribe = null;
  drag = null;
  mounted = false;
  tutorial = false;
  badge.textContent = "";
  badge.hidden = true;
  bubble.classList.remove("unread", "dragging");
  bubble.setAttribute("aria-label", "Messages");
  trash.classList.remove("over");
  bubble.hidden = true;
  float.hidden = true;
  trash.hidden = true;
  document.dispatchEvent(new Event("messages:stop")); // the Hub tab drops its panel too
}

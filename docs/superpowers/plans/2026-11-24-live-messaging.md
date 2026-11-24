# Live Messaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** One-to-one chats, temporary groups, search, live delivery and push, reached through a floating bubble and a User Hub tab.

**Architecture:** Messages are saved over REST; the server then pings only the chat's members over the existing `/ws` with a content-free `message.changed` envelope and they refetch. Push covers the app-closed case. One panel component renders in two hosts (floating panel, Hub tab).

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Postgres; vanilla ES modules, Vitest + MSW; existing Web Push and realtime layers. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-24-live-messaging-design.md` (features, data, routes, edge rules), `docs/superpowers/specs/2026-11-24-message-bubble-design.md` (bubble values), `docs/superpowers/specs/2026-11-24-live-messaging-preview.html` (approved look, copy and interaction; port its CSS and wording).

## Global Constraints

- Message text never appears on the socket, in a push payload, or in a log line.
- A non-member gets 404 from every chat route, never 403.
- Bodies are rendered with `textContent`, never as HTML.
- CSP drops `style=` attributes: classes for states, CSSOM (`el.style.x = …`) for position.
- No `<button>` inside a `<button>`. No sideways scrolling at any width.
- Files under 500 lines (not `styles.css`); split rather than grow.
- pytest runs from `backend/` with `.\venv\Scripts\python.exe -m pytest`; route tests go through a real `TestClient`.
- Vitest runs from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (uppercase drive); load view modules with `importView` inside the test.
- Shared checkout: stage explicit paths only, never `git add -A`. No `Co-Authored-By` trailer.
- Every new route joins the `CATALOGUE` in `backend/scripts/memprobe_routes.py`; every new `api.js` wrapper gets a row in `tests/frontend/helpers/endpointTable.js`.
- Team Lead = stored role `supervisor` (`roles.ROLE_SUPERVISOR`).

## Review Focus

1. **Send tapped twice on a slow connection** → one message. (Task 8)
2. **Two people start their first chat with each other at the same moment** → one chat, both land in it. (Task 4)
3. **The open chat is ended or expires underneath the reader** → back to the list with a short note, no error screen. (Task 8)
4. **A message that is HTML, emoji, or one very long unbroken word** → shown literally, wraps inside the bubble. (Task 8)
5. **Sign out on a shared phone, someone else signs in** → nothing of the first person's chats remains in memory or on screen. (Task 7)
6. **Two people have the same chat open** → reads settle after one round; no endless refetch loop. (Tasks 3, 4, 8)

---

## File map

| File | Responsibility |
|---|---|
| `backend/app/models_messages.py` (new) | `Conversation`, `ConversationMember`, `Message`; imported at the foot of `models.py` beside `models_smr` |
| `backend/alembic/versions/<rev>_add_messaging.py` (new) | Three tables, down-revision `d5f7b9c1e3a5` |
| `backend/app/domain/messages.py` (new) | Pure rules and constants |
| `backend/app/services/messages.py` (new) | All queries and writes, the sweep |
| `backend/app/schemas/messages.py` (new) | Request / response models |
| `backend/app/routers/messages.py` (new) | `/messages` routes |
| `backend/app/routers/_message_events.py` (new) | The one `message.changed` emitter |
| `backend/app/domain/realtime.py`, `services/realtime.py` | Event name, audience, targeted fan-out |
| `backend/app/services/push.py`, `static/service-worker.js` | Optional `chat` in the payload; tap opens that chat |
| `backend/static/api.js` | Eight wrappers |
| `backend/static/messagesStore.js` (new) | Chat list + unread state, realtime subscription |
| `backend/static/views/messagePanel.js`, `messagePanelChat.js` (new) | Panel shell + list/search/pickers; chat view |
| `backend/static/views/messageBubble.js` (new) | Bubble, trashcan, floating host |
| `backend/static/views/hubMessages.js` (new) | Hub tab mount / destroy / open-chat (`userHub.js` is at the 500-line cap) |
| `backend/static/shell-tail.html`, `pages/user-hub.html`, `views/userHub.js`, `views/auth.js`, `tutorial.js`, `styles.css` | Wiring |

---

### Task 1: Tables and pure rules

**Goal:** Schema exists and the rules that need no database are tested.

**Files:** create `app/models_messages.py`, the Alembic revision, `app/domain/messages.py`, `tests/test_messages_domain.py`; modify `app/models.py` (foot import).

**Produces:**
- Models per spec "Data". `Conversation.id` UUID; `Message.id` `BigInteger` identity; `ConversationMember.last_read_message_id` nullable `BigInteger` (no FK, so expiry deletes cannot fail on it); all FKs to conversations `ondelete="CASCADE"`.
- `domain/messages.py`: `MAX_BODY = 2000`, `MAX_GROUP_NAME = 60`, `MAX_GROUP_MEMBERS = 30`, `MIN_GROUP_OTHERS = 2`, `DIRECT_RETENTION_DAYS = 90`, `GROUP_QUIET_DAYS = 7`, `SEARCH_MIN_CHARS = 2`, `SEARCH_MAX_ROWS = 30`, `PAGE_SIZE = 50`
- `can_start_group(role: str) -> bool`
- `direct_key(a: UUID, b: UUID) -> str` — `"<low>:<high>"` by string order
- `clean_body(text: str) -> str` — strips; raises `InvalidMessageError` when empty or over `MAX_BODY`
- `clean_group_name(text: str) -> str` — same shape, `MAX_GROUP_NAME`
- `unread_people(sender_ids: Iterable[UUID]) -> int` — distinct count
- `direct_cutoff(now) -> datetime`, `group_cutoff(now) -> datetime`
- In `domain/errors.py`: `ConversationNotFoundError`, `InvalidMessageError`, `GroupPermissionError`; map them in `routers/_errors.to_http` to 404 / 422 / 403.

**Steps:**
- [ ] Write `test_messages_domain.py`: `direct_key(a, b) == direct_key(b, a)`; `clean_body("  hi ") == "hi"`; `clean_body("   ")` and a 2,001-character body raise; `can_start_group("technician") is False`, `"supervisor"`, `"techfm_oa"`, `"admin"`, `"owner"` True; `unread_people([x, x, y]) == 2`; cut-offs are `now - 90 days` and `now - 7 days`.
- [ ] Run it: FAIL (module missing).
- [ ] Write the domain module, errors and mappings; run: PASS.
- [ ] Write models + revision; `.\venv\Scripts\python.exe -m alembic upgrade head` then `downgrade -1` then `upgrade head`: all clean.
- [ ] Commit `feat(messages): tables and domain rules`.

### Task 2: Targeted realtime emit

**Goal:** An envelope can be aimed at named users without changing the wire.

**Files:** modify `app/domain/realtime.py`, `app/services/realtime.py`; create `app/routers/_message_events.py`; tests in `tests/test_realtime_registry.py`, `tests/test_realtime_emit.py`.

**Produces:**
- `EVENT_MESSAGE_CHANGED = "message.changed"`, audience `roles.ROLE_TECHNICIAN`, added to `__all__`.
- `realtime.emit(envelope, *, user_ids: Iterable | None = None) -> bool` — the handoff holds `(envelope, frozenset[str] | None)`; `_fan_out(envelope, user_ids=None)` skips a connection when `user_ids is not None and connection.user_id not in user_ids`. Ids are stringified (`Connection.user_id` is a `str`).
- `_message_events.emit_message_changed(conversation_id, user_ids) -> None`, modelled on `_attendance_events.py`.

**Steps:**
- [ ] Tests: two registered connections for users A and B; `emit(env, user_ids=[A])` then drain → only A's queue has it; `emit(env)` still reaches both; the queued frame has exactly the keys `type`, `id`, `req`; `audience_allows("message.changed", "technician")`. Extend the pinned emitter set in `test_realtime_emit.py` with `_message_events.emit_message_changed`.
- [ ] Run: FAIL. Implement. Run both files plus `tests/test_realtime_endpoint.py`: PASS.
- [ ] Commit `feat(realtime): targeted emit and message.changed`.

### Task 3: Message service

**Goal:** Every read and write, with membership enforced in one place.

**Files:** create `app/services/messages.py`, `tests/test_messages_service.py`.

**Consumes:** Task 1.

**Produces** (all take `db, user` first; every function that names a conversation raises `ConversationNotFoundError` for a non-member):
- `list_conversations(db, user) -> dict` — `{"conversations": [...], "unread_people": int}`; newest `last_message_at` first; direct chats with zero messages omitted; each row: `id, kind, name, starter_id, member_count, last_message, unread_count, unread_sender_ids`. A direct chat's `name` is the other member's `full_name`.
- `get_conversation(db, user, conversation_id, before: int | None = None) -> dict` — newest `PAGE_SIZE` messages in ascending order, `has_more`, `members`, `starter_name`, `seen_message_id` (direct only: the other member's `last_read_message_id`).
- `send_message(db, user, conversation_id, body) -> tuple[Message, list[UUID]]` — returns the member ids; sets `last_message_at`; advances the sender's own read mark.
- `mark_read(db, user, conversation_id, up_to: int) -> list[UUID]` — never lowers the mark; returns `[]` when the mark did not move (the route then emits nothing).
- `get_or_create_direct(db, user, other_user_id) -> Conversation` — archived or self target raises `UserNotFoundError`; on `IntegrityError` for `direct_key`, roll back and load the existing row.
- `create_group(db, user, name, member_ids) -> Conversation` — `GroupPermissionError` below Team Lead; `InvalidMessageError` for fewer than 2 others, more than 30, or any archived/unknown id; the starter is always a member.
- `end_group(db, user, conversation_id) -> list[UUID]` — starter only (`GroupPermissionError` otherwise), hard delete, returns the former member ids.
- `search(db, user, q) -> dict` — `{"people", "conversations", "messages"}`; uses the existing `services/_like.py` escaping; only the caller's chats.
- `list_people(db, user) -> list[User]` — active users except the caller, by name.
- `sweep(db, now) -> dict` — `{"messages_deleted", "groups_deleted"}`; `maybe_sweep(db, now) -> None` runs `sweep` at most once per 24 h per process (module-level timestamp).

**Steps:**
- [ ] Tests, one per behaviour: non-member gets `ConversationNotFoundError` from get/send/read/end; direct chat is unique both ways and after a simulated `IntegrityError`; a group with two unread writers gives `unread_people == 2` and `unread_count == 2`; own messages never count as unread; `mark_read` with a lower or equal id changes nothing and returns `[]`, a higher id returns the member ids; `seen_message_id` follows the other reader; technician cannot create a group; group of one other is rejected; non-starter cannot end; ending removes messages; `sweep` at `now` deletes a direct message 91 days old, keeps one 89 days old, deletes a group quiet 8 days, keeps one quiet 6, deletes an empty group created 8 days ago; search for `"gasket"` finds a message in my chat and not one in a chat I am not in; a `%` in the query matches literally; archived user absent from `list_people`.
- [ ] Run: FAIL. Implement. Run: PASS.
- [ ] Commit `feat(messages): service`.

### Task 4: Routes

**Goal:** The nine routes in the spec's table, emitting after each write.

**Files:** create `app/schemas/messages.py`, `app/routers/messages.py`, `tests/test_messages_routes.py`; modify `app/main.py` (include router), `scripts/memprobe_routes.py` (`CATALOGUE`), `tests/test_route_role_gates.py` (only if its lists flag the new routes).

**Consumes:** Tasks 2–3.

**Produces:** response shapes exactly as the service dicts; request bodies `SendRequest{body}`, `ReadRequest{up_to: int}`, `DirectRequest{user_id}`, `GroupRequest{name, member_ids}`; `PersonOut{id, name, role_label}`. `POST /messages/direct` returns `{id}`; `POST /messages/groups` returns `{id}`; send returns the `MessageOut`.

- Emit `emit_message_changed(conversation_id, member_ids)` after: send, read **only when `mark_read` returned ids**, group create, group end.
- `GET /messages/conversations` calls `maybe_sweep` before listing. This is the only sweep trigger (the first list call after a restart sweeps); no lifespan hook.
- `before` and `up_to` are plain `int` with manual validation (int `Literal`/constrained Query params 422 on this pinned FastAPI).

**Steps:**
- [ ] Tests through `TestClient`: signed-out → 401 on each route; non-member → 404 on get/send/read/delete; technician `POST /messages/groups` → 403; blank body → 422; a full send → list round trip shows the message and `unread_people == 1` for the recipient; send calls the emitter with exactly the member ids (monkeypatch `_message_events.realtime_service.emit`, assert `user_ids`); a read that moves the mark emits once, the same read repeated emits nothing (Review Focus 6); two interleaved `POST /messages/direct` for the same pair return the same id (Review Focus 2); `q` of one character → 422.
- [ ] Run: FAIL. Implement. Run this file plus `tests/test_memprobe.py`, `tests/test_route_role_gates.py`, `tests/test_realtime_emit.py`: PASS.
- [ ] Commit `feat(messages): routes`.

### Task 5: Push on a new message

**Goal:** Members other than the sender get "New message from <name>"; a tap opens that chat.

**Files:** modify `app/services/push.py`, `app/domain/notifications.py`, `app/routers/messages.py`, `static/service-worker.js`, `docs/notification-events.md`; tests in `tests/test_push_subscriptions.py`, `tests/test_notifications_domain.py`, `tests/frontend/unit/serviceWorker.test.js`.

**Produces:**
- `notifications.build_chat_message(sender_name: str) -> tuple[str, str]` → `("TechFM", f"New message from {sender_name}")`.
- `push.send_to_users(db, user_ids, title, body, *, chat: str | None = None)` — when given, the JSON payload gains `"chat": "<conversation id>"`.
- Delivery runs after the response, never inside the send: resolve recipient ids and the sender name in the request, then queue through `BackgroundTasks` the way `services/notifications.py` does (`_deliver` gains the optional `chat`; own session, plain ids and strings only).
- Service worker: `tag` is `chat-<id>` with `renotify: true` when the payload has `chat` (a second message in the same chat alerts again), else unchanged; the notification's `data` carries `chat`; on click, a focused-or-first window gets `postMessage({type: "open-chat", chat})`, and with no window it opens `/?chat=<id>`. Every push still shows a notification.

**Steps:**
- [ ] Tests: `build_chat_message("Dana Ortiz")` body equals `"New message from Dana Ortiz"`; sending a message whose text is `"SECRET"` in a group named `"HIDDEN"` produces a payload containing neither word; the sender's own subscription is not in the fan-out; the send route queues a background task and calls `push.send_to_users` zero times before returning; SW test: payload with `chat` → tag `chat-<id>` and `renotify: true`, click posts `open-chat`; payload without → old behaviour.
- [ ] Run: FAIL. Implement; push failures are caught and logged, never failing the send. Run: PASS.
- [ ] Add the row to `docs/notification-events.md`. Commit `feat(messages): push on new message`.

### Task 6: API wrappers

**Goal:** Frontend can call every route.

**Files:** modify `static/api.js`, `tests/frontend/helpers/endpointTable.js`, `tests/frontend/helpers/handlers.js`; create `tests/frontend/helpers/messages.js` (factories: `conversation()`, `message()`, `person()`).

**Produces:** `apiListConversations()`, `apiGetConversation(id, { before } = {})`, `apiSendMessage(id, body)`, `apiMarkConversationRead(id, upTo)`, `apiOpenDirect(userId)`, `apiCreateGroup(name, memberIds)`, `apiEndGroup(id)`, `apiSearchMessages(q)`, `apiListMessagePeople()`. Default MSW handlers return an empty list, `unread_people: 0`; the `GET /messages/conversations` default lives in `pageHandlers()` because it fires at sign-in.

**Steps:**
- [ ] Add the nine rows to `endpointTable.js`; run `tests/frontend/unit/api.endpoints.test.js`: FAIL.
- [ ] Add wrappers and default handlers; run `tests/frontend/unit/api.*.test.js`: PASS.
- [ ] Commit `feat(messages): api wrappers`.

### Task 7: Messages store

**Goal:** One in-memory source for the list and the badge, kept fresh by realtime.

**Files:** create `static/messagesStore.js`, `tests/frontend/unit/messagesStore.test.js`.

**Consumes:** Task 6; `subscribe` from `realtime.js`.

**Produces:**
- `startMessages() -> Promise<void>` — first fetch, subscribes to `message.changed` (event and reconnect both refetch; no `activePage` gate).
- `stopMessages() -> void` — unsubscribes, empties state, notifies listeners.
- `getState() -> { conversations, unreadPeople }`
- `onChange(listener) -> unsubscribe` — also called with `{ conversationId }` of the triggering envelope so an open chat can refetch itself.
- `refresh() -> Promise<void>` — one in flight plus one rerun, like the other live views.

**Steps:**
- [ ] Tests with the fake socket helper: start fetches once; a `message.changed` envelope refetches and listeners get the id; five envelopes in a burst cause at most two fetches; a reconnect refetches; after `stopMessages()` state is empty, a late response is ignored, and an envelope fetches nothing (Review Focus 5).
- [ ] Run: FAIL. Implement. Run: PASS.
- [ ] Commit `feat(messages): store`.

### Task 8: Panel

**Goal:** The approved panel, mountable in any host.

**Files:** create `static/views/messagePanel.js` (shell, list, search, person picker, group form), `static/views/messagePanelChat.js` (chat view), `tests/frontend/views/messagePanel.test.js`, `messagePanelChat.test.js`; modify `styles.css` (port the preview's panel CSS as `.msg-*` classes).

**Consumes:** Tasks 6–7; `getCurrentUser`, `roles.js`.

**Produces:**
- `mountMessagePanel(host: HTMLElement, { onClose = null } = {}) -> { openChat(id), destroy() }` — `onClose` null hides the ✕ (Hub tab).
- Wording, order and states exactly as the preview: "Messages", "Search people and messages", "New chat", "New group" (Team Lead+ only), sections "People and groups" / "Messages", "Nothing found for …", "Temporary group · N people", the started-by line, "End group", "Sent" / "Seen", "Pick at least two people", "Start group".
- Not in the preview (approved by the user 2026-11-24): a "Load earlier messages" button at the top of a chat when `has_more`, fetching with `before` = the oldest loaded id and keeping the scroll position.
- Read rule: post a read only while `document.visibilityState === "visible"` and the chat view is on screen, and only when the newest message id is past the last id this client posted or the server returned as its own mark. On `visibilitychange` to visible, an open chat marks read then.

**Steps:**
- [ ] Tests: list rows sort newest first with unread counts; typing in search keeps focus in the box and shows both sections; search debounces to one request per pause; New group absent for a technician, present for a supervisor; Start group disabled until a name and two people; opening a chat calls `apiMarkConversationRead` with the newest id; a refetch with no newer message posts no read (Review Focus 6); with the page hidden a new message posts no read, and becoming visible posts one; "Load earlier messages" shows only when `has_more`, prepends the older page and keeps typed text; a `message.changed` for the open chat appends the new message without losing typed text; "Seen" appears when `seen_message_id` reaches my last message, and never in a group; End group shows only for the starter; Send disabled while a send is in flight, so two fast taps post once (Review Focus 1); a 404 on fetch or send returns to the list with "This chat has ended." (Review Focus 3); a body of `<b>x</b>` renders as that literal text with no `<b>` element, and the message element has `overflow-wrap: anywhere` via its class (Review Focus 4); Enter sends, Escape calls `onClose`.
- [ ] Run: FAIL. Implement. Run both files plus `tests/frontend/unit/staticImports.test.js`: PASS.
- [ ] Commit `feat(messages): panel`.

### Task 9: Bubble

**Goal:** The approved bubble, hosting the panel.

**Files:** create `static/views/messageBubble.js`, `tests/frontend/views/messageBubble.test.js`; modify `static/shell-tail.html` (bubble button, trashcan, floating panel node, all `hidden`), `styles.css` (port the preview's bubble/trash CSS), `static/tutorial.js` (dispatch `tutorial:start` on `document` where `running` is set, mirroring `tutorial:end`), `static/views/auth.js` (call `mountMessages({ resume })` after `connectRealtime()`, `unmountMessages()` beside `disconnectRealtime()`), `static/main.js` (side-effect import).

**Consumes:** Tasks 7–8.

**Produces:**
- `mountMessages({ resume = false } = {})` — clears the put-away flag only when `resume` is false (a real sign-in; `enterApp` also runs on every reload), `startMessages()`, shows the bubble, opens `?chat=<id>` if present and strips it from the URL, listens for the service worker's `open-chat` message.
- `unmountMessages()` — hides bubble and panel, `stopMessages()`.
- `openMessages(chatId = null)` — opens the floating panel; when the bubble is put away it calls a registered Hub opener instead. `setHubOpener(fn)` is exported for Task 10 to fill; with none registered it falls back to the floating panel.
- Stacking: bubble, trashcan and floating panel take one z-index below the modal layer and the toasts, above page content and the nav (read the current values in `styles.css`, do not guess).
- `localStorage` keys `techfm.msgBubble.pos` (`{side, y}`) and `techfm.msgBubble.away` (`"1"`).
- Pure helpers exported for tests: `snapSide(centerX, viewportWidth) -> "left" | "right"`, `badgeText(n) -> string` (`""` at 0, `"9+"` past 9).

**Steps:**
- [ ] Tests: `snapSide(100, 390) === "left"`, `snapSide(300, 390) === "right"`; `badgeText(0) === ""`, `(3) === "3"`, `(12) === "9+"`; badge sits on the side away from the edge (class `on-left` / `on-right`); unread > 0 adds the `unread` class and an aria-label naming the count; under 6 px of movement opens the panel, more does not; a drop on the trashcan hides the bubble and sets the flag, `mountMessages()` clears it, and `mountMessages({ resume: true })` leaves it set; with the bubble put away `openMessages("c1")` calls the registered Hub opener with `"c1"`; the bubble's z-index rule is lower than the modal layer's; `tutorial:start` hides bubble and panel, `tutorial:end` restores; `unmountMessages()` leaves nothing visible; under 600 px wide the open panel has the sheet class and the bubble is hidden; resize re-clamps inside the viewport; position is set through `style.transform`, with no `style` attribute in the shell markup.
- [ ] Run: FAIL. Implement. Run this file plus `tests/frontend/unit/tutorial.test.js`, `tests/frontend/helpers/shell.test.js`, and the sign-in request pins the new boot fetch can trip — `tests/frontend/views/auth.test.js`, `nav.test.js`, `tutorialLockdown.test.js`, `tutorialStarterFlow.test.js`, `main.test.js`: PASS.
- [ ] Commit `feat(messages): bubble`.

### Task 10: Hub tab, docs, full check

**Goal:** Messages reachable from the User Hub for every role; docs current; everything green.

**Files:** modify `static/pages/user-hub.html` (tab `hub-tab-messages` / `data-hub-tab="messages"` / panel `hub-tabpanel-messages`, after My Work Orders, not role-hidden), create `static/views/hubMessages.js` (`activate(panel)`, `deactivate()`, `openChat(id)`; registers `setHubOpener` so a notification tap with the bubble put away shows the User Hub page, selects the Messages tab and opens that chat), `static/views/userHub.js` (panel map entry and the two calls only — it is at 500 lines, so nothing else lands there), `tests/frontend/views/hubIdsCensus.test.js`, a new `tests/frontend/views/hubMessages.test.js`; `docs/current-state.md`, `docs/open-work.md`.

**Steps:**
- [ ] Tests: the tab is visible to a technician; activating it mounts a panel with no ✕; leaving it destroys the panel; the mobile tab picker lists Messages; the Hub opener called with a chat id selects the Messages tab and opens that chat; `userHub.js` is still at or under 500 lines.
- [ ] Run: FAIL. Implement. Run: PASS.
- [ ] `docs/current-state.md`: a short Messaging section (tables, the targeted-emit rule, retention numbers, name-only push, bubble storage keys) and the realtime section's emitter list. `docs/open-work.md`: add the spec's "Non-goals (later)" as backlog lines and "Messages tutorial script". Stay inside each doc's budget.
- [ ] Full runs: `.\venv\Scripts\python.exe -m pytest -q` from `backend/`; `npx vitest run` from the repo root in PowerShell. Expected: green apart from the known environmental failures (cascade tests on the dev DB).
- [ ] Commit `feat(messages): hub tab and docs`. Do **not** push: pushing `main` deploys, and the in-app check on a phone and a desktop is the user's.

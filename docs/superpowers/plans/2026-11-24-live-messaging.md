# Live Messaging Implementation Plan

> **For the orchestrator:** this plan runs as one parallel wave of scoped sub-agents, then an inline test-and-review phase. Invoke the `swarming` skill before spawning. Agents are general-purpose on Sonnet 5.5, no forks.

**Goal:** One-to-one chats, temporary groups, search, live delivery and push, reached through a floating bubble and a User Hub tab.

**Architecture:** Messages are saved over REST; the server then pings only the chat's members over the existing `/ws` with a content-free `message.changed` envelope and they refetch. Push covers the app-closed case. One panel component renders in two hosts (floating panel, Hub tab).

**Tech Stack:** FastAPI, SQLAlchemy, Alembic, Postgres; vanilla ES modules, Vitest + MSW; existing Web Push and realtime layers. No new dependencies.

**Spec:** `docs/superpowers/specs/2026-11-24-live-messaging-design.md` (features, data, routes, edge rules), `docs/superpowers/specs/2026-11-24-message-bubble-design.md` (bubble values), `docs/superpowers/specs/2026-11-24-live-messaging-preview.html` (approved look, copy and interaction; port its CSS and wording).

## How this runs

| Phase | Who | What |
|---|---|---|
| 1. Build | 13 agents, spawned in one message | Each writes its unit's code **and** tests against the Contracts below. |
| 2. Check | Orchestrator, inline | Only after **all 13** report: migration round trip, pytest, Vitest, fixes. |
| 3. Review | Orchestrator, inline | Review Focus items against the real code, then commits and docs. |

**Agent rules (paste into every brief, with Global Constraints, the Contracts section and the unit's own block):**
- Touch only the files your unit owns. Need a change elsewhere → say so in your report, do not make it.
- Run nothing: no pytest, Vitest, alembic, server or git command. Reading code is fine.
- Build to the Contracts exactly; another agent is writing the other side at the same moment. A contract that cannot work → stop and report, do not improvise a different shape.
- Report: files written, any contract doubt, anything you could not finish.

## Global Constraints

- Message text never appears on the socket, in a push payload, or in a log line.
- A non-member gets 404 from every chat route, never 403.
- Bodies are rendered with `textContent`, never as HTML.
- CSP drops `style=` attributes: classes for states, CSSOM (`el.style.x = …`) for position.
- No `<button>` inside a `<button>`. No sideways scrolling at any width.
- Files under 500 lines (not `styles.css`); split rather than grow.
- Route tests go through a real `TestClient`. Vitest tests load view modules with `importView` inside the test.
- Team Lead = stored role `supervisor` (`roles.ROLE_SUPERVISOR`).
- Shared checkout: only the orchestrator stages and commits, explicit paths, never `git add -A`. No `Co-Authored-By` trailer.

## Review Focus

1. **Send tapped twice on a slow connection** → one message. (U10)
2. **Two people start their first chat with each other at the same moment** → one chat, both land in it. (U3, U4)
3. **The open chat is ended or expires underneath the reader** → back to the list with a short note, no error screen. (U10)
4. **A message that is HTML, emoji, or one very long unbroken word** → shown literally, wraps inside the bubble. (U10, U11)
5. **Sign out on a shared phone, someone else signs in** → nothing of the first person's chats remains in memory or on screen. (U8, U12)
6. **Two people have the same chat open** → reads settle after one round; no endless refetch loop. (U3, U4, U10)

---

## Contracts

**Domain (`app/domain/messages.py`)** — `MAX_BODY = 2000`, `MAX_GROUP_NAME = 60`, `MAX_GROUP_MEMBERS = 30`, `MIN_GROUP_OTHERS = 2`, `DIRECT_RETENTION_DAYS = 90`, `GROUP_QUIET_DAYS = 7`, `SEARCH_MIN_CHARS = 2`, `SEARCH_MAX_ROWS = 30`, `PAGE_SIZE = 50`; `can_start_group(role) -> bool`; `direct_key(a, b) -> str` (`"<low>:<high>"` by string order); `clean_body(text) -> str` and `clean_group_name(text) -> str` (strip; raise `InvalidMessageError` when empty or too long); `unread_people(sender_ids) -> int` (distinct); `direct_cutoff(now)`, `group_cutoff(now)`.

**Errors (`app/domain/errors.py`)** — `ConversationNotFoundError` → 404, `InvalidMessageError` → 422, `GroupPermissionError` → 403, mapped in `routers/_errors.to_http`. Existing `UserNotFoundError` → 404.

**Models (`app/models_messages.py`)** — `Conversation(id UUID, kind, name, created_by, created_at, last_message_at, direct_key unique nullable)`, `ConversationMember(conversation_id, user_id, last_read_message_id BigInteger nullable, no FK)`, `Message(id BigInteger identity, conversation_id, sender_id, body, created_at)`; index (`conversation_id`, `id`); every FK to conversations `ondelete="CASCADE"`.

**Service (`app/services/messages.py`)** — all take `db, user` first; any function naming a conversation raises `ConversationNotFoundError` for a non-member.

| Function | Returns / rule |
|---|---|
| `list_conversations(db, user)` | `{"conversations": [ConversationRow], "unread_people": int}`; newest `last_message_at` first; direct chats with zero messages omitted |
| `get_conversation(db, user, conversation_id, before=None)` | `ConversationDetail`; newest `PAGE_SIZE` messages older than `before`, ascending |
| `send_message(db, user, conversation_id, body)` | `(MessageOut dict, member_ids)`; sets `last_message_at`; advances the sender's read mark |
| `mark_read(db, user, conversation_id, up_to)` | member ids, or `[]` when the mark did not move; never lowers it |
| `get_or_create_direct(db, user, other_user_id)` | `Conversation`; archived or self → `UserNotFoundError`; on `IntegrityError` for `direct_key`, roll back and load the existing row |
| `create_group(db, user, name, member_ids)` | `(Conversation, member_ids)`; `GroupPermissionError` below Team Lead; `InvalidMessageError` for < 2 others, > 30, archived/unknown id; starter always a member |
| `end_group(db, user, conversation_id)` | former member ids; starter only (`GroupPermissionError`); hard delete |
| `search(db, user, q)` | `SearchResult`; `services/_like.py` escaping; only the caller's chats |
| `list_people(db, user)` | `[PersonOut dict]`; active users except the caller, by name |
| `sweep(db, now)` / `maybe_sweep(db, now)` | `{"messages_deleted", "groups_deleted"}` / at most once per 24 h per process |

**JSON shapes** (service dicts = response bodies = frontend factories):

| Name | Fields |
|---|---|
| `PersonOut` | `id, name, role_label` |
| `MessageOut` | `id` (int), `sender_id, sender_name, body, created_at` (ISO) |
| `ConversationRow` | `id, kind, name` (direct: the other member's `full_name`), `starter_id, member_count, last_message` (`MessageOut` or null), `unread_count, unread_sender_ids` |
| `ConversationDetail` | `id, kind, name, starter_id, starter_name, members` (`[PersonOut]`), `messages` (`[MessageOut]`), `has_more, seen_message_id` (direct only: the other member's mark; else null), `my_read_message_id` |
| `SearchResult` | `people` (`[PersonOut]`), `conversations` (`[ConversationRow]`), `messages` (`[{conversation_id, conversation_name, message: MessageOut}]`) |

**Routes and wrappers:**

| Route | Body → response | `api.js` wrapper |
|---|---|---|
| `GET /messages/conversations` | → list dict | `apiListConversations()` |
| `GET /messages/conversations/{id}?before=` | → `ConversationDetail` | `apiGetConversation(id, { before } = {})` |
| `POST /messages/conversations/{id}/messages` | `{body}` → `MessageOut` | `apiSendMessage(id, body)` |
| `POST /messages/conversations/{id}/read` | `{up_to}` → `{my_read_message_id}` | `apiMarkConversationRead(id, upTo)` |
| `POST /messages/direct` | `{user_id}` → `{id}` | `apiOpenDirect(userId)` |
| `POST /messages/groups` | `{name, member_ids}` → `{id}` | `apiCreateGroup(name, memberIds)` |
| `DELETE /messages/groups/{id}` | → 204 | `apiEndGroup(id)` |
| `GET /messages/search?q=` | → `SearchResult` | `apiSearchMessages(q)` |
| `GET /messages/people` | → `{people: [PersonOut]}` | `apiListMessagePeople()` |

**Realtime** — `domain/realtime.EVENT_MESSAGE_CHANGED = "message.changed"`, audience `roles.ROLE_TECHNICIAN`. `services/realtime.emit(envelope, *, user_ids: Iterable | None = None) -> bool`. `routers/_message_events.emit_message_changed(conversation_id, user_ids) -> None`.

**Push** — `domain/notifications.build_chat_message(sender_name) -> ("TechFM", f"New message from {sender_name}")`. `services/push.send_to_users(db, user_ids, title, body, *, chat: str | None = None)`; payload gains `"chat"` when given. `services/notifications.notify_chat_message(background, *, recipient_ids, sender_name, conversation_id) -> None` queues delivery after the response. Service worker: click posts `{type: "open-chat", chat}` to a focused-or-first window, or opens `/?chat=<id>`.

**Frontend:**

| Module | Exports |
|---|---|
| `static/messagesStore.js` | `startMessages() -> Promise<void>`, `stopMessages()`, `getState() -> { conversations, unreadPeople }`, `onChange(listener) -> unsubscribe` (listener gets `{ conversationId }`, null when not from an envelope), `refresh() -> Promise<void>` |
| `static/views/messagePanel.js` | `mountMessagePanel(host, { onClose = null } = {}) -> { openChat(id), destroy() }` — `onClose` null hides the ✕ |
| `static/views/messagePanelChat.js` | `mountChat(host, { conversationId, onBack, onEnded }) -> { destroy() }` — `onEnded(note)` on a 404 |
| `static/views/messageBubble.js` | `mountMessages({ resume = false } = {})`, `unmountMessages()`, `openMessages(chatId = null)`, `setHubOpener(fn)`, `snapSide(centerX, viewportWidth)`, `badgeText(n)` |
| `static/views/hubMessages.js` | `activate(panel)`, `deactivate()`, `openChat(id)` |
| `tests/frontend/helpers/messages.js` | factories `conversation()`, `message()`, `person()`, `conversationDetail()` |

**CSS classes** — every class in the preview is ported as `msg-` + the preview's name (`.conv` → `.msg-conv`, `.thread` → `.msg-thread`, `.composer` → `.msg-composer`, …). Shell ids: `msg-bubble` (button), `msg-bubble-badge`, `msg-trash`, `msg-float` (floating panel host). State classes: `on-left` / `on-right`, `unread`, `over` (trashcan hot), `sheet` (under 600 px), `mine` (own message).

**localStorage** — `techfm.msgBubble.pos` (`{side, y}`), `techfm.msgBubble.away` (`"1"`).

---

## Phase 1 — units (all concurrent)

Each unit owns its files outright; no file appears twice.

### U1: Tables and pure rules
**Owns:** `app/models_messages.py`, `alembic/versions/<rev>_add_messaging.py` (down-revision `d5f7b9c1e3a5`), `app/domain/messages.py`, `app/domain/errors.py`, `app/routers/_errors.py`, `app/models.py` (foot import beside `models_smr`), `tests/test_messages_domain.py`.
**Tests:** `direct_key(a, b) == direct_key(b, a)`; `clean_body("  hi ") == "hi"`; blank and 2,001-character bodies raise; `can_start_group` False for `technician`, True for `supervisor`, `techfm_oa`, `admin`, `owner`; `unread_people([x, x, y]) == 2`; cut-offs are `now - 90 days` / `now - 7 days`.

### U2: Targeted realtime emit
**Owns:** `app/domain/realtime.py`, `app/services/realtime.py`, `app/routers/_message_events.py`, `tests/test_realtime_registry.py`, `tests/test_realtime_emit.py`.
**Build:** the handoff holds `(envelope, frozenset[str] | None)`; `_fan_out(envelope, user_ids=None)` skips a connection when `user_ids is not None and connection.user_id not in user_ids`; ids stringified. `_message_events` modelled on `_attendance_events.py`. Event added to `__all__`.
**Tests:** `emit(env, user_ids=[A])` reaches only A; `emit(env)` still reaches both; the frame has exactly `type`, `id`, `req`; `audience_allows("message.changed", "technician")`; pinned emitter set gains `emit_message_changed`.

### U3: Message service
**Owns:** `app/services/messages.py`, `tests/test_messages_service.py`.
**Tests, one per behaviour:** non-member gets `ConversationNotFoundError` from get/send/read/end; direct chat unique both ways and after a simulated `IntegrityError`; two unread group writers give `unread_people == 2`, `unread_count == 2` (a never-opened chat has a null mark — count from 0); own messages never unread; `mark_read` with a lower or equal id changes nothing and returns `[]`, a higher id returns the member ids; `seen_message_id` follows the other reader; technician cannot create a group; group of one other rejected; non-starter cannot end; ending removes messages; `sweep` deletes a direct message 91 days old, keeps 89, deletes a group quiet 8 days, keeps 6, deletes an empty group created 8 days ago; search for `"gasket"` finds my message and not one in a chat I am not in; `%` matches literally; archived user absent from `list_people`.

### U4: Routes
**Owns:** `app/schemas/messages.py`, `app/routers/messages.py`, `app/main.py` (include router), `scripts/memprobe_routes.py` (`CATALOGUE`), `tests/test_messages_routes.py`, `tests/test_route_role_gates.py` (only if its lists flag the new routes).
**Build:** emit `emit_message_changed` after send, read **only when `mark_read` returned ids**, group create, group end. Send also calls `notify_chat_message` with members minus the sender. `GET /messages/conversations` calls `maybe_sweep` first — the only sweep trigger, no lifespan hook. `before` and `up_to` are plain `int` with manual validation (int `Literal`/constrained Query params 422 on this pinned FastAPI).
**Tests:** signed-out → 401 on each route; non-member → 404 on get/send/read/delete; technician `POST /messages/groups` → 403; blank body → 422; send → list round trip shows the message and `unread_people == 1` for the recipient; send calls the emitter with exactly the member ids (monkeypatch `_message_events.realtime_service.emit`); a read that moves the mark emits once, the same read repeated emits nothing; two interleaved `POST /messages/direct` for one pair return the same id; one-character `q` → 422; send queues `notify_chat_message` without the sender's id.

### U5: Push backend
**Owns:** `app/services/push.py`, `app/services/notifications.py`, `app/domain/notifications.py`, `docs/notification-events.md`, `tests/test_push_subscriptions.py`, `tests/test_notifications_domain.py`.
**Build:** `_deliver` gains the optional `chat`; own session, plain ids and strings only; failures logged, never raised.
**Tests:** `build_chat_message("Dana Ortiz")` body is `"New message from Dana Ortiz"`; a payload built for a message `"SECRET"` in a group `"HIDDEN"` contains neither word; payload has `chat` only when given; `notify_chat_message` adds a background task and calls `push.send_to_users` zero times itself.

### U6: Service worker
**Owns:** `static/service-worker.js`, `tests/frontend/unit/serviceWorker.test.js`.
**Build:** with `chat` in the payload: `tag` `chat-<id>`, `renotify: true`, `data.chat`; else unchanged. Every push still shows a notification.
**Tests:** payload with `chat` → that tag and `renotify`, click posts `open-chat`; no window → opens `/?chat=<id>`; payload without → old behaviour.

### U7: API wrappers and test helpers
**Owns:** `static/api.js`, `tests/frontend/helpers/endpointTable.js`, `tests/frontend/helpers/handlers.js`, `tests/frontend/helpers/messages.js`.
**Build:** nine wrappers, nine endpoint rows, factories. Default MSW handlers return an empty list and `unread_people: 0`; the `GET /messages/conversations` default lives in `pageHandlers()` because it fires at sign-in.

### U8: Messages store
**Owns:** `static/messagesStore.js`, `tests/frontend/unit/messagesStore.test.js`.
**Build:** subscribes to `message.changed` (event and reconnect both refetch; no `activePage` gate); one fetch in flight plus one rerun, like the other live views; `stopMessages()` unsubscribes, empties state, notifies listeners.
**Tests** (fake socket helper): start fetches once; an envelope refetches and listeners get the id; five envelopes in a burst cause at most two fetches; a reconnect refetches; after `stopMessages()` state is empty, a late response is ignored, an envelope fetches nothing.

### U9: Panel shell
**Owns:** `static/views/messagePanel.js`, `tests/frontend/views/messagePanel.test.js`.
**Build:** shell, list, search, person picker, group form; opens a chat through `mountChat`. Wording and order exactly as the preview: "Messages", "Search people and messages", "New chat", "New group" (Team Lead+ only), sections "People and groups" / "Messages", "Nothing found for …", "Pick at least two people", "Start group".
**Tests:** rows sort newest first with unread counts; typing in search keeps focus and shows both sections; search debounces to one request per pause; New group absent for a technician, present for a supervisor; Start group disabled until a name and two people; `onEnded` returns to the list showing the note; Escape calls `onClose`; `onClose` null → no ✕.

### U10: Chat view
**Owns:** `static/views/messagePanelChat.js`, `tests/frontend/views/messagePanelChat.test.js`.
**Build:** preview wording: "Temporary group · N people", the started-by line, "End group", "Sent" / "Seen". Not in the preview (approved by the user 2026-11-24): a "Load earlier messages" button at the top when `has_more`, fetching with `before` = the oldest loaded id and keeping the scroll position. **Read rule:** post a read only while `document.visibilityState === "visible"` and the chat view is on screen, and only when the newest message id is past `my_read_message_id` / the last id this client posted. On `visibilitychange` to visible, an open chat marks read then.
**Tests:** opening calls `apiMarkConversationRead` with the newest id; a refetch with no newer message posts no read; page hidden + new message posts no read, becoming visible posts one; a `message.changed` for this chat appends the message without losing typed text; "Load earlier messages" only when `has_more`, prepends and keeps typed text; "Seen" when `seen_message_id` reaches my last message, never in a group; End group only for the starter; Send disabled while in flight, so two fast taps post once; a 404 on fetch or send calls `onEnded("This chat has ended.")`; a body of `<b>x</b>` renders as literal text with no `<b>` element; Enter sends.

### U11: Styles
**Owns:** `static/styles.css`.
**Build:** port the preview's panel, bubble and trashcan CSS under the Contracts class names; bubble values from the bubble spec. `.msg-msg` has `overflow-wrap: anywhere`. Stacking: bubble, trashcan and floating panel take one z-index below the modal layer and the toasts, above page content and the nav (read the current values in `styles.css`, do not guess). No pulse under reduced-motion.

### U12: Bubble and wiring
**Owns:** `static/views/messageBubble.js`, `tests/frontend/views/messageBubble.test.js`, `static/shell-tail.html` (bubble button, trashcan, floating panel node, all `hidden`, no `style` attribute), `static/tutorial.js` (dispatch `tutorial:start` on `document` where `running` is set, mirroring `tutorial:end`), `static/views/auth.js` (`mountMessages({ resume })` after `connectRealtime()`, `unmountMessages()` beside `disconnectRealtime()`), `static/main.js` (side-effect import).
**Build:** `mountMessages` clears the put-away flag only when `resume` is false (`enterApp` also runs on every reload), starts the store, shows the bubble, opens `?chat=<id>` if present and strips it from the URL, listens for the service worker's `open-chat`. `openMessages` opens the floating panel; with the bubble put away it calls the registered Hub opener, falling back to the floating panel when none is registered.
**Tests:** `snapSide(100, 390) === "left"`, `(300, 390) === "right"`; `badgeText(0) === ""`, `(3) === "3"`, `(12) === "9+"`; badge class `on-left` / `on-right` away from the edge; unread > 0 adds `unread` and an aria-label naming the count; under 6 px of movement opens the panel, more does not; a drop on the trashcan hides the bubble and sets the flag, `mountMessages()` clears it, `mountMessages({ resume: true })` leaves it; put away, `openMessages("c1")` calls the Hub opener with `"c1"`; `tutorial:start` hides bubble and panel, `tutorial:end` restores; `unmountMessages()` leaves nothing visible; under 600 px the open panel has `sheet` and the bubble is hidden; resize re-clamps; position goes through `style.transform`.

### U13: Hub tab
**Owns:** `static/views/hubMessages.js`, `static/pages/user-hub.html` (tab `hub-tab-messages` / `data-hub-tab="messages"` / panel `hub-tabpanel-messages`, after My Work Orders, not role-hidden), `static/views/userHub.js` (panel map entry and the two calls only — it is at 500 lines), `tests/frontend/views/hubIdsCensus.test.js`, `tests/frontend/views/hubMessages.test.js`.
**Build:** `hubMessages` registers `setHubOpener` so a notification tap with the bubble put away shows the User Hub page, selects the Messages tab and opens that chat.
**Tests:** tab visible to a technician; activating mounts a panel with no ✕; leaving destroys it; the mobile tab picker lists Messages; the Hub opener with a chat id selects the tab and opens that chat.

---

## Phase 2 — check (orchestrator, after all 13 reports)

- [ ] Read every report; settle contract doubts and requested out-of-scope edits before running anything.
- [ ] From `backend/`: `.\venv\Scripts\python.exe -m alembic upgrade head`, `downgrade -1`, `upgrade head`: all clean.
- [ ] pytest, targeted: `test_messages_domain.py`, `test_messages_service.py`, `test_messages_routes.py`, `test_realtime_registry.py`, `test_realtime_emit.py`, `test_realtime_endpoint.py`, `test_push_subscriptions.py`, `test_notifications_domain.py`, `test_memprobe.py`, `test_route_role_gates.py`.
- [ ] Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (uppercase drive): the new unit and view tests, `api.*.test.js`, `staticImports.test.js`, `serviceWorker.test.js`, `tutorial.test.js`, `helpers/shell.test.js`, `hubIdsCensus.test.js`, and the sign-in request pins the new boot fetch can trip — `auth.test.js`, `nav.test.js`, `tutorialLockdown.test.js`, `tutorialStarterFlow.test.js`, `main.test.js`.
- [ ] Fix failures inline; a mismatch between two units is fixed on the side that left the Contracts.
- [ ] Full runs: `.\venv\Scripts\python.exe -m pytest -q` from `backend/`; `npx vitest run`. Expected: green apart from the known environmental failures (cascade tests on the dev DB).

## Phase 3 — review, docs, commit (orchestrator, inline)

- [ ] Walk Review Focus 1–6 in the real code, not the tests. Check Global Constraints by grep: no message body in a log call, envelope or push payload; no `innerHTML` in the `message*` modules; no file over 500 lines (`userHub.js` included); no `style=` in the shell markup.
- [ ] `docs/current-state.md`: a short Messaging section (tables, the targeted-emit rule, retention numbers, name-only push, bubble storage keys) and the realtime section's emitter list. `docs/open-work.md`: the spec's "Non-goals (later)" as backlog lines and "Messages tutorial script". Stay inside each doc's budget.
- [ ] Commit by layer, explicit paths: `feat(messages): tables, service and routes`, `feat(messages): realtime and push`, `feat(messages): panel, bubble and hub tab`, `docs(messages): current state and backlog`.
- [ ] Do **not** push: pushing `main` deploys, and the in-app check on a phone and a desktop is the user's.

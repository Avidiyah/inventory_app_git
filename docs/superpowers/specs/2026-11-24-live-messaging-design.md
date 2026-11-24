# Live messaging — design

2026-11-24. Bubble look and behaviour: `2026-11-24-message-bubble-design.md`
(approved). Panel look: `2026-11-24-live-messaging-preview.html` (approved
clickable mock; open the file in a browser). This doc covers features, data
and delivery. "Mine" marks the assistant's calls; everything else is the
user's decision.

## Intent

Crew members message each other inside TechFM instead of leaving the app:
one-to-one chats, short-lived group chats for a job, search, and a floating
bubble that is always one tap away.

## Goals

| Feature | Rule |
|---|---|
| One-to-one chats | Anyone active can message anyone active. One chat per pair. |
| Temporary groups | Team Lead+ (`supervisor` rank) starts one: a name plus at least two other people. |
| Group ending | The starter taps End group, or 7 days pass with no message. The group and its messages are **deleted for good**. |
| List | Newest first, last-message snippet, unread dot with count. |
| Unread badge | Distinct people with unopened messages to you; each unread writer in a group counts separately. |
| Seen | "Sent" then "Seen" under your last message, one-to-one only (mine: groups show nothing). |
| Search | One box: people (including ones never messaged), group names, message text in your own chats. |
| Live delivery | New messages appear without a reload while the app is open. |
| Push | App closed: "New message from <sender name>". **Name only, never message text or group name.** Tap opens that chat. |
| History | One-to-one messages are erased 90 days after they were sent. |
| Privacy | Only members can read a chat. No Owner or Admin oversight. |
| Entry points | Bubble on every page; a Messages tab in the User Hub for every role. Same panel in both. |
| Text only | Up to 2,000 characters. |

## Non-goals (later)

Photos, work-order links, typing dots, reactions, editing or deleting a sent
message, muting, adding or removing group members after start, leaving a
group, a native over-other-apps bubble.

## Anti-goals

- Message text on the socket, in a push payload, or in a log line.
- Any route that returns a chat to a non-member (answer 404, not 403).
- The bubble showing during a tutorial or above a modal pop-up.

## Approaches

| Option | Trade-off | Verdict |
|---|---|---|
| A. REST send, ping the members, they refetch | Fits the existing invalidation pattern; sends keep auth, rate limit, logging; dead-spot recovery is free. About half a second behind instant. | **Picked** |
| B. Same, ping everyone | No realtime change, but every device refetches on every message. | Rejected |
| C. Text on the socket both ways | Instant, typing dots possible; breaks the no-content envelope rule and skips HTTP middleware. | Rejected |

## Data (one Alembic revision)

| Table | Columns |
|---|---|
| `conversations` | `id`, `kind` (`direct` / `group`), `name` (group only, ≤ 60), `created_by`, `created_at`, `last_message_at`, `direct_key` (`"<low id>:<high id>"`, unique, null for groups) |
| `conversation_members` | PK (`conversation_id`, `user_id`), `last_read_message_id` nullable |
| `messages` | `id` (increasing), `conversation_id` (cascade delete), `sender_id`, `body`, `created_at`; index (`conversation_id`, `id`) |

- Unread for me = messages with `id > last_read_message_id` not sent by me.
- Seen = the other member's `last_read_message_id` ≥ my last message's id.
- `direct_key` makes get-or-create race-safe.

## Routes (`/messages`, any signed-in role unless noted)

| Route | Does |
|---|---|
| `GET /messages/conversations` | My chats with last message, unread count; top-level `unread_people` for the badge |
| `GET /messages/conversations/{id}` | A page of messages (50, older via `before`), plus seen state |
| `POST /messages/conversations/{id}/messages` | Send |
| `POST /messages/conversations/{id}/read` | Mark read up to a message id (never moves backwards) |
| `POST /messages/direct` | Get or create the chat with one user |
| `POST /messages/groups` | Team Lead+: name + member ids |
| `DELETE /messages/groups/{id}` | Starter only: hard delete |
| `GET /messages/search?q=` | People + my chats + my messages; at least 2 characters, capped at 30 rows; case-insensitive substring |
| `GET /messages/people` | Active users to pick from: id, name, role label only |

Rules live in a `services/messages.py`; pure rules (who may start a group,
unread-people count, expiry cut-offs) in `domain/messages.py`.

## Delivery

- New event `message.changed`, `id` = conversation id, audience every role.
- **New: targeted emit.** The recipient user ids travel beside the envelope
  inside the server and never onto the wire; fan-out skips connections whose
  `user_id` is not listed. Existing role-audience events are unchanged. The
  three-field envelope stays exactly as is.
- Emitted to all members (sender included, for their other devices) on: send,
  read, group created, group ended. `test_realtime_emit.py` pins the emitter
  set and must be updated.
- Client: on the event, refetch the list (badge) and, if that chat is open,
  its messages. A reconnect recovery refetches both.
- `realtime.js` `subscribe` already notifies on every page (views gate
  themselves on `activePage`); the messages store simply does not gate.
- Push: `send_to_users` to members minus the sender, body
  `New message from <name>`. The service worker already handles
  `notificationclick`; extend it to open the app at that chat. The
  notification is **always shown**, even with TechFM open: iOS revokes push
  permission from an app that receives a push and shows nothing. Add the
  trigger to `docs/notification-events.md`.

## Clean-up

One sweep function: delete direct messages older than 90 days; delete groups
whose last message (or creation, if empty) is older than 7 days. Mine: no new
scheduler — run it from the conversation-list route at most once a day per
process (the first list call after a restart sweeps).
`# ponytail:` ceiling is a sleepy server sweeping late; move to a timed task
if exact expiry ever matters. A direct chat with no messages left drops out
of the list but its row may stay.

## Frontend

- Bubble module owns its node (CSSOM for position; CSP drops `style=`).
  Hidden when signed out, while `isTutorialRunning()`, and after being
  dropped on the trashcan. Put-away flag and position in `localStorage`; the
  sign-in handler clears the flag.
- Panel module renders into either host: the floating panel (desktop: 360 px
  beside the bubble; under 600 px wide: full-screen sheet, bubble hidden) or
  the Hub tab panel `hub-tabpanel-messages`.
- Views: list + search, chat, new chat (person picker), new group (Team Lead+
  only; the server enforces it too).
- Build DOM with `textContent`; message bodies are never HTML.
- Opening a chat marks it read. Sending is optimistic only to the extent of
  clearing the box after the server accepts.
- Files stay under 500 lines; split bubble, panel, and API/state.
- Tutorials: a short Messages script is a later tutorial batch, not this work.

## Edge rules (mine)

| Case | Rule |
|---|---|
| Archived user | Cannot be picked or messaged; their old chats stay readable until expiry |
| Starter archived | The group lives on until its 7 quiet days |
| Empty or whitespace message | Rejected (422) |
| Group member cap | 30 |
| Sending to an ended group | 404; the client returns to the list with a short note |
| Logged in on two devices | Read on one clears the badge on the other via the read event |

## Testing

- pytest: membership 404s, Team Lead gate, direct-chat uniqueness, unread
  people count (group writers counted separately), read never regresses,
  sweep cut-offs, targeted emit reaches only listed users, emitter set, push
  body carries the name only. Routes through a real `TestClient`.
- Vitest: bubble snap side, badge corner, trash flag, tutorial hide; panel
  list / chat / search / group form; `staticImports` guard.
- In-app check on a phone and desktop is the user's.

## Left to the builder

- Module and file names; stacking order against nav, toasts and modals.
- Whether `GET /messages/people` reuses an existing user query.
- How the Hub tab deep-links to a chat from a notification tap.

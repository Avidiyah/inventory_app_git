// Live-messaging factories, in the exact JSON shapes the /messages routes
// return (spec 2026-11-24-live-messaging-design). Every field has a default;
// a test overrides only what it asserts on. Conversation ids are UUIDs and
// message ids are integers, as on the server.

let seq = 0;
const next = () => (seq += 1);
const uuid = (n) => `20000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

export function person(overrides = {}) {
  const n = next();
  return { id: uuid(1000 + n), name: `Person ${n}`, role_label: "Technician", ...overrides };
}

export function message(overrides = {}) {
  const n = next();
  return {
    id: n, sender_id: uuid(1000 + n), sender_name: `Person ${n}`, body: `Message ${n}`,
    created_at: "2026-11-24T12:00:00Z", ...overrides,
  };
}

export function conversation(overrides = {}) {
  const n = next();
  return {
    id: uuid(n), kind: "direct", name: `Person ${n}`, starter_id: null, member_count: 2,
    last_message: null, unread_count: 0, unread_sender_ids: [], ...overrides,
  };
}

export function conversationDetail(overrides = {}) {
  const n = next();
  return {
    id: uuid(n), kind: "direct", name: `Person ${n}`, starter_id: null, starter_name: null,
    members: [person(), person()], messages: [], has_more: false,
    seen_message_id: null, my_read_message_id: null, ...overrides,
  };
}

// Factories, not fixture files: every field gets a sane default and the test
// overrides only what it is asserting on. Adding a field to the API shape is
// then one edit here, not one per test.

let seq = 0;

export function user(overrides = {}) {
  seq += 1;
  return {
    id: seq,
    username: `user${seq}`,
    full_name: `Test User ${seq}`,
    first_name: "Test",
    last_name: `User ${seq}`,
    role: "technician",
    ...overrides,
  };
}

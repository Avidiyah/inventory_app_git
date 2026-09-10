// Role gating is a first-class test dimension here, so priming the session is
// a one-liner rather than boilerplate in every test.

import { user } from "./factories.js";

// state.js is a module singleton and setup.js resets the module registry per
// test, so state.js MUST be imported inside the test's generation -- a static
// import at the top of this file would prime a different copy of the module
// than the view under test reads from.
//
// The relative specifier here and the file:// URL `mountView` imports with
// resolve to the same module id under Vitest, so this really does prime the
// copy the view reads -- verified, not assumed.
export async function setTestUser(overrides = {}) {
  const state = await import("../../../backend/static/state.js");
  const current = user(overrides);
  state.setCurrentUser(current);
  return current;
}

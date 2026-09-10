// MSW intercepts at the `fetch` boundary so the REAL api.js executes --
// content-type handling, the 204 short-circuit, the {status, detail} throw
// shape, the 401 hook. Mocking api.js itself would test a fiction.

import { setupServer } from "msw/node";

// Handler paths are RELATIVE ("/work-orders/:id") and match as-is: jsdom's
// default document URL supplies the origin, and api.js issues relative
// fetches. No absolute-URL form or `environmentOptions.jsdom.url` is needed.

// Deliberately empty. A default that quietly answers every request turns an
// un-stubbed endpoint into a silent pass; tests declare what they need with
// server.use(). Shared defaults get added here per phase as they earn it.
export const defaultHandlers = [];

export const server = setupServer(...defaultHandlers);

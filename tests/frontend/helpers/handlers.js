// MSW intercepts at the `fetch` boundary so the REAL api.js executes --
// content-type handling, the 204 short-circuit, the {status, detail} throw
// shape, the 401 hook. Mocking api.js itself would test a fiction.

import { http, HttpResponse } from "msw";
import { setupServer } from "msw/node";
import { attendanceMe, filterOptions, hubPayload } from "./factories.js";

// Handler paths are RELATIVE ("/work-orders/:id") and match as-is: jsdom's
// default document URL supplies the origin, and api.js issues relative
// fetches. No absolute-URL form or `environmentOptions.jsdom.url` is needed.

// Deliberately empty. A default that quietly answers every request turns an
// un-stubbed endpoint into a silent pass; tests declare what they need with
// server.use(). Shared defaults get added here per phase as they earn it.
export const defaultHandlers = [];

export const server = setupServer(...defaultHandlers);

// Every endpoint a `PAGE_LOADERS` entry in `views/nav.js` can fire, answered
// with the empty-but-valid form.
//
// An opt-in bundle, NOT a default: a test that wants to assert on one of
// these still registers its own handler afterwards (`server.use` puts later
// handlers first), and a test that never navigates keeps the strict
// `onUnhandledRequest: "error"` behaviour the suite is built on.
//
// The point is boot noise, not coverage. `showPage()` *calls* the page's
// loader, so a nav test that swaps to Mass Stage fires three requests it is
// not asserting on; without this bundle it fails on an unhandled request
// rather than on its assertion.
//
// Kept in `PAGE_LOADERS` order, with the page each row serves named. A page
// absent from that map (`create-item`, `create-user`) renders from state it
// already holds and fires nothing; `saved-items` is in the map but its loader
// deliberately makes no request (see `views/items.js::loadItems`).
export function pageHandlers() {
  return [
    // transaction -> enterTransactionPage -> refreshWoCards
    // work-orders -> loadWorkOrders -> ensureReferenceData + the list
    // admin-review -> loadAdminReview (?status=review; MSW matches on path)
    // mass-stage -> loadStages
    // tools -> loadTools
    //
    // Order matters: MSW takes the first matching handler, so the two
    // specific /work-orders/ and /items/ paths precede the collection roots.
    http.get("/work-orders/filter-options", () => HttpResponse.json(filterOptions())),
    http.get("/work-orders/", () => HttpResponse.json([])),
    http.get("/items/low-stock", () => HttpResponse.json([])),
    http.get("/items/", () => HttpResponse.json([])),
    http.get("/users/", () => HttpResponse.json([])),
    http.get("/mass-stages/", () => HttpResponse.json([])),
    http.get("/tools/", () => HttpResponse.json([])),

    // user-hub -> loadUserHub
    http.get("/hub", () => HttpResponse.json(hubPayload())),
    // loadUserHub also fetches the caller's own punch for the Home tab.
    http.get("/attendance/me", () => HttpResponse.json(attendanceMe())),

    // history -> loadHistory (the paged envelope, not a bare array)
    http.get("/transactions/", () =>
      HttpResponse.json({ items: [], total: 0, page: 1, page_size: 20 })),

    // user-requests -> loadUserRequests, which also fires the tab counts
    http.get("/user-requests/counts", () => HttpResponse.json({})),
    http.get("/user-requests/", () => HttpResponse.json([])),

    // integrations -> loadIntegrationsPage -> refreshNetFacilitiesCloudSession.
    // `available: false` is the no-integration form: the card renders its
    // disabled state and starts no poll.
    http.get("/integrations/netfacilities/cloud/session", () =>
      HttpResponse.json({ available: false, status: null })),
  ];
}

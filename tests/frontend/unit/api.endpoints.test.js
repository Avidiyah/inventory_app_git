import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { installFetchSpy, restoreFetchSpy } from "../helpers/fetchSpy.js";
import { ENDPOINTS } from "../helpers/endpointTable.js";

let api;
let calls;

beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
  // A catch-all so the sweep needs no per-row handler. Every wrapper under
  // test is expected to reach the network exactly once.
  server.use(http.all("*", () => HttpResponse.json({})));
  calls = installFetchSpy();
});

afterEach(() => {
  restoreFetchSpy();
});

describe("every wrapper sends the request its row describes", () => {
  it.each(ENDPOINTS)("$fn", async (row) => {
    await api[row.fn](...row.args);
    expect(calls).toHaveLength(1);
    const { url, init } = calls[0];
    expect(url).toBe(row.url);
    expect(init.method ?? "GET").toBe(row.method ?? "GET");
    expect(init.credentials).toBe("include");
    if (row.cache) expect(init.cache).toBe(row.cache);
    if (row.multipart) {
      // The browser has to add the multipart boundary itself, so the wrapper
      // must NOT set a Content-Type of its own.
      expect(init.body).toBeInstanceOf(FormData);
      expect(init.headers).toBeUndefined();
    } else if (row.body === undefined) {
      expect(init.body).toBeUndefined();
    } else {
      expect(init.headers?.["Content-Type"]).toBe("application/json");
      expect(JSON.parse(init.body)).toEqual(row.body);
    }
  });
});

describe("the table cannot silently fall behind api.js", () => {
  it("has a row for every exported wrapper", async () => {
    const exported = Object.keys(api).filter((name) => name.startsWith("api"));
    const covered = new Set(ENDPOINTS.map((row) => row.fn));
    const missing = exported.filter((name) => !covered.has(name));
    expect(missing, `add a row to helpers/endpointTable.js for: ${missing.join(", ")}`).toEqual([]);
  });

  it("has no row for a wrapper that no longer exists", () => {
    const stale = ENDPOINTS.map((row) => row.fn).filter((name) => typeof api[name] !== "function");
    expect(stale).toEqual([]);
  });
});

describe("docs/endpoint-map.md", () => {
  // Known gap, filed in docs/open-work.md (Task 13). `apiGetHubAdmin` is live
  // -- GET /hub/admin, called by views/userHub.js -- but the map never names
  // it. Listing it here keeps the suite green while the gap stays visible; the
  // fix is a doc edit, which P1 does not make.
  const KNOWN_UNDOCUMENTED = ["apiGetHubAdmin"];

  it("names every exported wrapper", async () => {
    const { readFileSync } = await import("node:fs");
    // Name-level, not path-level: the doc is prose in a table and a reformat
    // must not turn CI red. A wrapper missing here means an endpoint shipped
    // without a documentation row.
    const doc = readFileSync("docs/endpoint-map.md", "utf8");
    const documented = new Set(doc.match(/\bapi[A-Z]\w+/g) ?? []);
    const undocumented = Object.keys(api)
      .filter((name) => name.startsWith("api"))
      .filter((name) => !documented.has(name));
    expect(undocumented, `add these to docs/endpoint-map.md: ${undocumented.join(", ")}`)
      .toEqual(KNOWN_UNDOCUMENTED);
  });
});

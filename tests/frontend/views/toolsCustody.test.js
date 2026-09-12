// Characterization coverage for the user-first half of views/tools.js: what
// `loadTools` fetches and paints per role, the user picker (search, keyboard,
// dismissal), the selected user's card, and the Check In hand-off into
// toolReturn.js.
//
// The checkout picker and both custody editors' own ladders are in
// toolsCheckout.test.js; the inventory table is in toolsInventory.test.js.

import { afterEach, describe, expect, it } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "../helpers/handlers.js";
import {
  checkinBtn, chooseUser, el, headers, holdingRows, mountTools, openTools,
  requestFor, restoreTools, rows, userOptions,
} from "../helpers/tools.js";
import { tool, toolCustodyEntry, user as userFactory } from "../helpers/factories.js";

afterEach(() => restoreTools());

const MANAGERS = [["techfm_oa"], ["admin"], ["owner"]];
const NON_MANAGERS = [["supervisor"], ["technician"]];

const failing = (path, detail, status = 500) =>
  http.get(path, () => HttpResponse.json({ detail }, { status }));

const optionNames = () =>
  userOptions().map((option) => option.querySelector(".manual-item-name").textContent);

const holdingText = (index = 0) =>
  Array.from(holdingRows()[index].querySelectorAll(".tool-holding-detail > *")).map((n) => n.textContent);

// A tool one user is holding, plus that user -- the shape most custody
// assertions need.
function heldBy(user, { quantity = "1", ...overrides } = {}) {
  return tool({
    name: "Drill", barcode: "T1", quantity: "3",
    custody: [toolCustodyEntry({ user_id: user.id, user_name: user.full_name, quantity })],
    ...overrides,
  });
}

describe("loadTools by role", () => {
  it.each(MANAGERS)("%s fetches tools and users, shows the picker and waits for a search", async (role) => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const { mod } = await mountTools({ role, tools: [tool()], users: [holder] });
    await mod.loadTools();

    // No `include_archived`: the picker is an ACTIVE-user search.
    expect(requestFor("/tools/", "GET").url).toBe("/tools/");
    expect(requestFor("/users/", "GET").url).toBe("/users/");
    expect(el.picker().hidden).toBe(false);
    expect(el.custodyMessage().textContent).toBe("Search for a user to view tool custody.");
    expect(el.custodyMessage().className).toBe("");
    expect(el.userCard().hidden).toBe(true);
    expect(headers()).toEqual(["Barcode", "Name", "On Hand", "Checked Out", "Actions"]);
  });

  it.each(NON_MANAGERS)("%s fetches only tools, hides the picker and opens their own card", async (role) => {
    const { mod, currentUser } = await mountTools({ role, tools: [tool()] });
    await mod.loadTools();

    expect(requestFor("/users/", "GET")).toBeNull();
    expect(el.picker().hidden).toBe(true);
    expect(el.custodyMessage().textContent).toBe("");
    expect(el.userCard().hidden).toBe(false);
    expect(el.userName().textContent).toBe(currentUser.full_name);
    expect(el.checkoutControls().hidden).toBe(true);
    expect(headers()).toEqual(["Barcode", "Name", "On Hand", "Checked Out"]);
  });

  it.each([["admin", 5], ["technician", 4]])(
    "%s sees a %i-column skeleton while the fetch is in flight", async (role, columns) => {
      const { mod } = await mountTools({ role, users: [] });
      const loading = mod.loadTools();
      expect(rows()).toHaveLength(5);
      expect(rows()[0].className).toBe("skel-row");
      expect(rows()[0].querySelectorAll("td")).toHaveLength(columns);
      expect(el.custodyMessage().textContent).toBe("Loading tool custody…");
      await loading;
    });

  it.each([["admin"], ["technician"]])(
    "a failed /tools/ writes one error row for %s — always colspan 5", async (role) => {
      const { mod } = await mountTools({
        role, users: [], handlers: [failing("/tools/", "Tools are down")],
      });
      await mod.loadTools();

      const cells = rows()[0].querySelectorAll("td");
      expect(cells).toHaveLength(1);
      // N-P6-CHARACTERIZED: the row is hardcoded to 5, so on a non-manager's
      // four-column table it spans one column too many -- and renderTools
      // never runs on this branch, so the header row is empty either way.
      expect(cells[0].getAttribute("colspan")).toBe("5");
      expect(cells[0].className).toBe("error");
      expect(cells[0].textContent).toBe("Tools are down");
      expect(headers()).toEqual([]);
      expect(el.custodyMessage().textContent).toBe("Tools are down");
      expect(el.custodyMessage().className).toBe("error");

      const state = await import("../../../backend/static/state.js");
      expect(state.getTools()).toEqual([]);
    });

  it("a failed /users/ clears the roster and the selection but keeps the table", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const { mod } = await openTools({ role: "admin", tools: [tool()], users: [holder] });
    await chooseUser(holder);
    expect(el.userCard().hidden).toBe(false);

    server.use(failing("/users/", "Users are down"));
    await mod.loadTools();

    expect(el.custodyMessage().textContent).toBe("Users are down");
    expect(el.custodyMessage().className).toBe("error");
    expect(el.userCard().hidden).toBe(true);
    expect(rows()).toHaveLength(1);
    await userEvent.setup().click(el.userSearch());
    expect(el.userResults().textContent).toBe("No matching active users.");
  });

  it("drops archived users and name-sorts the rest", async () => {
    const users = [
      userFactory({ full_name: "Zoe Zed" }),
      userFactory({ full_name: "Gone Away", archived_at: "2026-01-01T00:00:00Z" }),
      userFactory({ full_name: "Abe Able" }),
    ];
    await openTools({ role: "admin", users });
    await userEvent.setup().click(el.userSearch());
    expect(optionNames()).toEqual(["Abe Able", "Zoe Zed"]);
  });

  it("clears a selected user who is gone from the next load", async () => {
    const abe = userFactory({ full_name: "Abe Able" });
    const zoe = userFactory({ full_name: "Zoe Zed" });
    const { mod } = await openTools({ role: "admin", users: [abe, zoe] });
    await chooseUser(abe);
    expect(el.userCard().hidden).toBe(false);

    server.use(http.get("/users/", () => HttpResponse.json([zoe])));
    await mod.loadTools();

    expect(el.userCard().hidden).toBe(true);
    expect(el.custodyMessage().textContent).toBe("Search for a user to view tool custody.");
  });

  it("keeps a still-present selection across a reload, with no message", async () => {
    const abe = userFactory({ full_name: "Abe Able" });
    const { mod } = await openTools({ role: "admin", users: [abe] });
    await chooseUser(abe);
    await mod.loadTools();
    expect(el.userCard().hidden).toBe(false);
    expect(el.custodyMessage().textContent).toBe("");
  });
});

describe("the user picker", () => {
  const roster = (count) =>
    Array.from({ length: count }, (_, i) => userFactory({ full_name: `User ${String(i).padStart(2, "0")}` }));

  it("focus lists everyone, capped at eight", async () => {
    await openTools({ role: "admin", users: roster(10) });
    await userEvent.setup().click(el.userSearch());
    expect(el.userResults().hidden).toBe(false);
    expect(el.userSearch().getAttribute("aria-expanded")).toBe("true");
    expect(userOptions()).toHaveLength(8);
    expect(optionNames()[0]).toBe("User 00");
  });

  it("typing filters through filterRanked, and a miss says so", async () => {
    const users = [userFactory({ full_name: "Abe Able" }), userFactory({ full_name: "Zoe Zed" })];
    await openTools({ role: "admin", users });
    const user = userEvent.setup();
    await user.click(el.userSearch());
    await user.type(el.userSearch(), "zo");
    expect(optionNames()).toEqual(["Zoe Zed"]);
    await user.clear(el.userSearch());
    await user.type(el.userSearch(), "nobody");
    expect(userOptions()).toHaveLength(0);
    expect(el.userResults().textContent).toBe("No matching active users.");
  });

  it("renders the role label on each option", async () => {
    const users = [userFactory({ full_name: "Ann Holder", role: "techfm_oa" })];
    await openTools({ role: "admin", users });
    await userEvent.setup().click(el.userSearch());
    expect(userOptions()[0].querySelector(".manual-item-meta").textContent).toBe("TechFM OA");
    expect(userOptions()[0].id).toBe(`tool-user-option-${users[0].id}`);
  });

  it("ArrowDown and ArrowUp wrap, tracking aria-activedescendant and .is-active", async () => {
    const users = [userFactory({ full_name: "Abe Able" }), userFactory({ full_name: "Zoe Zed" })];
    await openTools({ role: "admin", users });
    const user = userEvent.setup();
    await user.click(el.userSearch());

    await user.keyboard("{ArrowDown}");
    expect(el.userSearch().getAttribute("aria-activedescendant")).toBe(`tool-user-option-${users[0].id}`);
    expect(userOptions()[0].classList.contains("is-active")).toBe(true);
    expect(userOptions()[0].getAttribute("aria-selected")).toBe("true");

    await user.keyboard("{ArrowDown}{ArrowDown}");   // past the end, back to the first
    expect(el.userSearch().getAttribute("aria-activedescendant")).toBe(`tool-user-option-${users[0].id}`);

    await user.keyboard("{ArrowUp}");                // before the first, round to the last
    expect(el.userSearch().getAttribute("aria-activedescendant")).toBe(`tool-user-option-${users[1].id}`);
    expect(userOptions()[0].classList.contains("is-active")).toBe(false);
  });

  it("ArrowDown opens the results when they are hidden", async () => {
    const users = [userFactory({ full_name: "Abe Able" })];
    await openTools({ role: "admin", users });
    const user = userEvent.setup();
    el.userSearch().focus();
    el.userResults().hidden = true;
    await user.keyboard("{ArrowDown}");
    expect(el.userResults().hidden).toBe(false);
    expect(userOptions()[0].classList.contains("is-active")).toBe(true);
  });

  it("Enter picks the active option; with none active it does nothing", async () => {
    const users = [userFactory({ full_name: "Abe Able" }), userFactory({ full_name: "Zoe Zed" })];
    await openTools({ role: "admin", users });
    const user = userEvent.setup();
    await user.click(el.userSearch());

    await user.keyboard("{Enter}");
    expect(el.userCard().hidden).toBe(true);

    await user.keyboard("{ArrowDown}{ArrowDown}{Enter}");
    expect(el.userCard().hidden).toBe(false);
    expect(el.userName().textContent).toBe("Zoe Zed");
    expect(el.userSearch().value).toBe("Zoe Zed");
  });

  it("Escape hides the results and drops the active descendant", async () => {
    await openTools({ role: "admin", users: [userFactory({ full_name: "Abe Able" })] });
    const user = userEvent.setup();
    await user.click(el.userSearch());
    await user.keyboard("{ArrowDown}");
    await user.keyboard("{Escape}");
    expect(el.userResults().hidden).toBe(true);
    expect(el.userResults().innerHTML).toBe("");
    expect(el.userSearch().getAttribute("aria-expanded")).toBe("false");
    expect(el.userSearch().hasAttribute("aria-activedescendant")).toBe(false);
  });

  it("editing the chosen name clears the selection and closes the editors", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    await openTools({ role: "admin", tools: [heldBy(holder)], users: [holder] });
    const user = await chooseUser(holder);
    await user.click(checkinBtn());
    expect(el.returnSection().hidden).toBe(false);

    await user.type(el.userSearch(), "x");
    expect(el.userCard().hidden).toBe(true);
    expect(el.returnSection().hidden).toBe(true);
    expect(el.holdings().innerHTML).toBe("");
    expect(el.checkoutSearch().value).toBe("");
  });

  it("a click outside the picker hides its results; one outside the checkout controls hides theirs", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    await openTools({ role: "admin", tools: [tool()], users: [holder] });
    const user = userEvent.setup();

    await user.click(el.userSearch());
    expect(el.userResults().hidden).toBe(false);
    await user.click(document.body);
    expect(el.userResults().hidden).toBe(true);

    await chooseUser(holder, user);
    await user.click(el.checkoutSearch());
    expect(el.checkoutResults().hidden).toBe(false);
    await user.click(document.body);
    expect(el.checkoutResults().hidden).toBe(true);
  });
});

describe("the selected user's card", () => {
  it("names the user, their role and their creation date, and takes focus", async () => {
    const created = "2026-03-04T15:30:00Z";
    const holder = userFactory({ full_name: "Ann Holder", role: "supervisor", created_at: created });
    await openTools({ role: "admin", users: [holder] });
    await chooseUser(holder);

    expect(el.userName().textContent).toBe("Ann Holder");
    expect(el.userMeta().textContent).toBe(`Supervisor · Created ${new Date(created).toLocaleString()}`);
    expect(el.userStatus().textContent).toBe("Active");
    expect(document.activeElement).toBe(el.userCard());
    expect(el.custodyMessage().textContent).toBe("");
  });

  it.each([["a null date", null], ["an unparseable date", "not-a-date"]])(
    "%s reads 'Created date unavailable'", async (_label, created) => {
      const holder = userFactory({ full_name: "Ann Holder", role: "admin", created_at: created });
      await openTools({ role: "owner", users: [holder] });
      await chooseUser(holder);
      expect(el.userMeta().textContent).toBe("Admin · Created date unavailable");
    });

  it("counts one holding in the singular and reports the checked-out balance", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const drill = heldBy(holder, { quantity: "2" });
    await openTools({ role: "admin", tools: [drill], users: [holder] });
    await chooseUser(holder);

    expect(el.custodyCount().textContent).toBe("1 tool record currently checked out");
    expect(holdingRows()).toHaveLength(1);
    // The row reports the CHECKED-OUT balance, not the tool's on-hand count.
    expect(holdingText()).toEqual(["Drill", "Barcode: T1", "Checked out: 2"]);
    expect(checkinBtn().dataset.toolId).toBe(drill.id);
  });

  it("counts two holdings in the plural, and only the tools this user holds", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const other = userFactory({ full_name: "Bob Other" });
    const drill = heldBy(holder, { quantity: "2" });
    const saw = tool({
      name: "Saw", barcode: "T2", quantity: "1",
      custody: [toolCustodyEntry({ user_id: holder.id, user_name: "Ann Holder", quantity: "1" })],
    });
    const theirs = tool({
      name: "Ladder", barcode: "T3", quantity: "1",
      custody: [toolCustodyEntry({ user_id: other.id, user_name: "Bob Other", quantity: "1" })],
    });

    await openTools({ role: "admin", tools: [drill, saw, theirs], users: [holder, other] });
    await chooseUser(holder);
    expect(el.custodyCount().textContent).toBe("2 tool records currently checked out");
    expect(holdingRows()).toHaveLength(2);
    expect(holdingText(1)[0]).toBe("Saw");
  });

  it("says so when the user holds nothing", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    await openTools({ role: "admin", tools: [tool()], users: [holder] });
    await chooseUser(holder);
    expect(el.custodyCount().textContent).toBe("0 tool records currently checked out");
    expect(el.holdings().textContent).toBe("No tools currently checked out.");
    expect(holdingRows()).toHaveLength(0);
  });

  it("shows the checkout controls to a custody manager", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    await openTools({ role: "techfm_oa", users: [holder] });
    await chooseUser(holder);
    expect(el.checkoutControls().hidden).toBe(false);
  });

  it("hides them on a supervisor's own card", async () => {
    await openTools({ role: "supervisor" });
    expect(el.userCard().hidden).toBe(false);
    expect(el.checkoutControls().hidden).toBe(true);
  });

  it("escapes a holding's tool name and barcode", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const nasty = heldBy(holder, { name: '<img src=x onerror="boom">', barcode: "<b>T1</b>" });
    await openTools({ role: "admin", tools: [nasty], users: [holder] });
    await chooseUser(holder);
    expect(el.holdings().querySelector("img")).toBeNull();
    expect(holdingText()[0]).toBe('<img src=x onerror="boom">');
    expect(holdingText()[1]).toBe("Barcode: <b>T1</b>");
  });
});

describe("Check In hands off to toolReturn.js", () => {
  it("opens the return editor against the holding, prefilled to the outstanding balance", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const drill = heldBy(holder, { quantity: "2" });
    await openTools({ role: "admin", tools: [drill], users: [holder] });
    const user = await chooseUser(holder);

    await user.click(checkinBtn());
    expect(el.returnSection().hidden).toBe(false);
    expect(el.returnSelected().textContent).toBe("Drill (T1)");
    expect(el.returnUserSummary().textContent).toBe("Ann Holder has 2 checked out");
    expect(el.returnQuantity().value).toBe("2");
    expect(el.returnQuantity().max).toBe("2");
    expect(el.returnWorkOrder().value).toBe("");
    expect(el.returnMessage().textContent).toBe("");
  });

  it("closes an open checkout editor first", async () => {
    const holder = userFactory({ full_name: "Ann Holder" });
    const drill = heldBy(holder);
    await openTools({ role: "admin", tools: [drill], users: [holder] });
    const user = await chooseUser(holder);

    await user.click(el.checkoutSearch());
    await user.click(el.checkoutResults().querySelector("[data-checkout-tool-id]"));
    expect(el.checkoutSection().hidden).toBe(false);

    await user.click(checkinBtn());
    expect(el.checkoutSection().hidden).toBe(true);
    expect(el.returnSection().hidden).toBe(false);
  });

  it("ignores a Check In whose tool is not in the cache", async () => {
    // The guard `tool && custody` can only be missed by a button the render
    // did not produce, so the test fabricates one -- what is pinned is that
    // the delegation refuses it rather than opening an empty editor.
    const holder = userFactory({ full_name: "Ann Holder" });
    await openTools({ role: "admin", tools: [heldBy(holder)], users: [holder] });
    const user = await chooseUser(holder);

    const stray = document.createElement("button");
    stray.className = "tool-checkin-btn";
    stray.dataset.toolId = "no-such-tool";
    el.holdings().appendChild(stray);
    await user.click(stray);
    expect(el.returnSection().hidden).toBe(true);
  });
});

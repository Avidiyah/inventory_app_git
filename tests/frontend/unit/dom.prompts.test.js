import { beforeEach, describe, expect, it } from "vitest";
import userEvent from "@testing-library/user-event";
import { mountView } from "../helpers/shell.js";

let dom;
let user;
beforeEach(async () => {
  user = userEvent.setup({ document });
  dom = await mountView("dom.js");
});

const el = (id) => document.getElementById(id);

describe("promptPasswordReset", () => {
  it("titles the dialog with the username and starts empty", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    expect(el("pw-reset-title").textContent).toBe('New password for "jsmith"');
    expect(el("pw-reset-new").value).toBe("");
    expect(el("pw-reset-overlay").hidden).toBe(false);
    await user.click(el("pw-reset-cancel"));
    await pending;
  });

  it("resolves the password when both fields match", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter2");
    await user.click(el("pw-reset-save"));
    await expect(pending).resolves.toBe("hunter2");
  });

  it("refuses a password under four characters and stays open", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "abc");
    await user.type(el("pw-reset-confirm"), "abc");
    await user.click(el("pw-reset-save"));
    expect(el("pw-reset-message").textContent).toBe("Password must be at least 4 characters.");
    expect(el("pw-reset-overlay").hidden).toBe(false);
    await user.click(el("pw-reset-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("refuses a mismatched pair -- the whole reason this replaced prompt()", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter3");
    await user.click(el("pw-reset-save"));
    expect(el("pw-reset-message").textContent).toBe("Passwords do not match.");
    await user.click(el("pw-reset-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("submits on Enter from either field", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter2{Enter}");
    await expect(pending).resolves.toBe("hunter2");
  });

  it("resolves null on Escape", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBeNull();
  });

  it("leaves no plaintext password in the DOM afterwards", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.type(el("pw-reset-new"), "hunter2");
    await user.type(el("pw-reset-confirm"), "hunter2");
    await user.click(el("pw-reset-save"));
    await pending;
    expect(el("pw-reset-new").value).toBe("");
    expect(el("pw-reset-confirm").value).toBe("");
    expect(el("pw-reset-new").type).toBe("password");
  });

  it("toggles visibility and re-hides on close", async () => {
    const pending = dom.promptPasswordReset("jsmith");
    await user.click(el("pw-reset-toggle"));
    expect(el("pw-reset-new").type).toBe("text");
    await user.click(el("pw-reset-cancel"));
    await pending;
    expect(el("pw-reset-new").type).toBe("password");
  });
});

describe("promptUserName", () => {
  it("hides the username field unless allowUsername is set", async () => {
    const pending = dom.promptUserName({ first_name: "Jo", last_name: "Smith", username: "jsmith" });
    expect(el("user-name-username").hidden).toBe(true);
    await user.click(el("user-name-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves first and last name only", async () => {
    const pending = dom.promptUserName({ first_name: "Jo", last_name: "Smith" });
    await user.clear(el("user-name-first"));
    await user.type(el("user-name-first"), "Joanne");
    await user.click(el("user-name-save"));
    await expect(pending).resolves.toEqual({ firstName: "Joanne", lastName: "Smith" });
  });

  it("includes the username when allowed", async () => {
    const pending = dom.promptUserName(
      { first_name: "Jo", last_name: "Smith", username: "jsmith" }, { allowUsername: true });
    expect(el("user-name-username").hidden).toBe(false);
    await user.click(el("user-name-save"));
    await expect(pending).resolves.toEqual({ firstName: "Jo", lastName: "Smith", username: "jsmith" });
  });

  it("requires both names -- the legacy NULL-name case this exists for", async () => {
    const pending = dom.promptUserName({ first_name: null, last_name: null });
    await user.click(el("user-name-save"));
    expect(el("user-name-message").textContent).toBe("First name and last name are required.");
    await user.click(el("user-name-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("requires a username when the field is shown", async () => {
    const pending = dom.promptUserName(
      { first_name: "Jo", last_name: "Smith", username: "jsmith" }, { allowUsername: true });
    await user.clear(el("user-name-username"));
    await user.click(el("user-name-save"));
    expect(el("user-name-message").textContent).toBe("Username is required.");
    await user.click(el("user-name-cancel"));
    await pending;
  });
});

describe("promptUserRole", () => {
  // Options are `{value, label, description}` objects, not bare role strings
  // (dom.js:442) -- a string list renders `value="undefined"` options.
  const ROLES = [
    { value: "supervisor", label: "Supervisor" },
    { value: "technician", label: "Technician" },
  ];

  it("offers exactly the roles it is given", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ROLES);
    const options = [...el("user-role-select").options].map((o) => o.value);
    expect(options).toEqual(["supervisor", "technician"]);
    await user.click(el("user-role-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves the chosen role", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ROLES);
    await user.selectOptions(el("user-role-select"), "supervisor");
    await user.click(el("user-role-save"));
    await expect(pending).resolves.toBe("supervisor");
  });

  it("treats saving the role the user already holds as a cancel", async () => {
    // Re-saving would revoke the user's sessions for no change (dom.js:481).
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ROLES);
    await user.click(el("user-role-save"));
    await expect(pending).resolves.toBeNull();
  });

  it("refuses an empty selection", async () => {
    // The dialog preselects the role the user already holds, so the blank
    // option only stays selected for a user whose role is not on offer.
    const pending = dom.promptUserRole(
      { id: 1, role: "owner" },
      [{ value: "", label: "Choose a role" }, ...ROLES],
    );
    await user.click(el("user-role-save"));
    expect(el("user-role-message").textContent).toBe("Select a role.");
    await user.click(el("user-role-cancel"));
    await expect(pending).resolves.toBeNull();
  });

  it("resolves null without showing a dialog when there are no assignable roles", async () => {
    await expect(dom.promptUserRole({ id: 1, role: "owner" }, [])).resolves.toBeNull();
    expect(el("user-role-overlay").hidden).toBe(true);
  });

  it("resolves null on Escape", async () => {
    const pending = dom.promptUserRole({ id: 1, role: "technician" }, ROLES);
    await user.keyboard("{Escape}");
    await expect(pending).resolves.toBeNull();
  });
});

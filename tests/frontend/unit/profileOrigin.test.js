// The remembered profile → work-order hand-off: read many times, taken once.
import { beforeEach, describe, expect, it } from "vitest";
import {
  clearProfileOrigin, peekProfileOrigin, setProfileOrigin, takeProfileOrigin,
} from "../../../backend/static/views/profileOrigin.js";

const ORIGIN = { page: "users", userId: "u1", week: "2026-09-14" };
beforeEach(() => clearProfileOrigin());

describe("profileOrigin", () => {
  it("starts empty and peek does not consume", () => {
    expect(peekProfileOrigin()).toBeNull();
    setProfileOrigin(ORIGIN);
    expect(peekProfileOrigin()).toEqual(ORIGIN);
    expect(peekProfileOrigin()).toEqual(ORIGIN);
  });
  it("take returns the origin once", () => {
    setProfileOrigin(ORIGIN);
    expect(takeProfileOrigin()).toEqual(ORIGIN);
    expect(takeProfileOrigin()).toBeNull();
  });
  it("clear drops it", () => {
    setProfileOrigin(ORIGIN);
    clearProfileOrigin();
    expect(peekProfileOrigin()).toBeNull();
  });
});

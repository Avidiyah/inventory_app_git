# Session handoff: live rendering W2 built, W3 spec drafted (2026-11-15)

## State

- `main` is **15 commits ahead of origin, nothing pushed**. That covers W1 (Stage 1 list, `b433dff`) and all of W2. Pushing deploys.
- W2 plan `docs/superpowers/plans/2026-11-15-work-order-live-card-body.md`: Tasks 0–5 done, each reviewed by a separate agent.
  - T0 idiomorph 0.8.0 `290f203` (owner accepted the 3 extra changelog entries) · T1 `ea24066` · T2 `99eb346` · T3 `63214d1` + `9c93cbc` · T4 `8c074a5` + `09f201e` · T5 backend emits `74bed93` + `fc6febe` · final-review fix `7968348` · stale solo-card test `576a2d9`.
  - Last runs: Vitest W2 suite 1,443/1,443; 0.8.0 rerun 106/106; `test_realtime_emit.py` 40/40; `test_work_orders_router.py` 15/15.
  - Gaps that only a phone can close: refocus after a move (risk 24), iOS reading position (25), touch press/release.

## Bug report: RESOLVED — owner confirmed they tested production by mistake. Not a defect.

(Kept for the local-test recipe below.)

The owner tested two devices: the list updated live, but an open card did not. A status change appeared only after tapping a tab; added materials and notes never appeared without reloading.

**Leading hypothesis (not yet confirmed with the owner):** the test ran against **production**, which has neither W1 nor W2. The behaviour seen is exactly the old code: held cards defer, and material routes send no event. Evidence:
- nothing is pushed;
- the local host server (PID 14236) listens on `127.0.0.1` only, so a second device cannot reach it;
- that server started 2026-11-14 17:33 with no `--reload`, so it also lacks T5's emits.

**Next steps**
1. Ask the owner which URL each device used.
2. If production: test locally instead. Restart uvicorn bound to the LAN (`--host 0.0.0.0`, accepting the exposure), or use two browsers on one machine. Hard-reload both.
3. If the bug still reproduces locally, debug `refreshCardLive` in `workOrderList.js` → `patchBodyLive` (`workOrderLiveBody.js`). Suspect `deferred` staying true, since a tab tap runs the `missedUpdate` catch-up.

## W3–W7 roadmap (owner-approved)

W3 save-time conflict check · ~~W4 request section in the card~~ (dropped 2026-11-15: the section was hidden in `ac95d23`; requests logged as IMP-042 in `docs/open-work.md`) · W5 Requests page · W6 Low Stock + SMR Admin Review · W7 User Hub. Process: spec, then owner OK, then plan, then owner OK, for each W in turn.

- **W3 spec drafted:** `docs/superpowers/specs/2026-11-15-work-order-save-conflict-check-design.md` (1,722 words), **awaiting owner review**.
  - Owner picks: per-field expected values; Keep theirs / Save mine with name + age; per-field stamp table; protects Edit details, material quantity/billing, labor minutes.
  - Author's calls are listed at the end of the spec for the owner to accept or overrule.
- After the W3 OK: write the W3 plan at W2's rigor (risk register, review focus, census tests, phone gate), then the W4 spec.

## Push gate

The owner's two-login phone check (table at the end of the W2 plan) gates the push, plus CI green after it.

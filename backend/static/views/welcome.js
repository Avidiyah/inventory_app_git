// View helper: the one-time welcome, then the clock-in prompt.
//
// Layer: views. Called by auth.js's enterApp. "Once ever" is decided by the
// server: claimSeen resolves true only for the call that set seen_at, and it is
// awaited before anything is drawn, so a second device, a closed tab or a
// sign-out mid-tour never replays it. Any failure shows nothing and the
// clock-in prompt still follows (never a dead sign-in).

import { getCurrentUser } from "../state.js";
import { startTutorial } from "../tutorial.js";
import { claimSeen, hasSeen, loadProgress } from "../tutorialProgress.js";
import { maybePromptClockIn } from "./clockInPrompt.js";
import { maybeWarnStorage } from "./storageWarning.js";
import { setTutorialsSub } from "./hubTutorials.js";

async function due(user) {
  await loadProgress();
  if (getCurrentUser() !== user || hasSeen("welcome")) return false;
  return (await claimSeen("welcome")) && getCurrentUser() === user;
}

// `plain`: the landing was the usual role landing (not a resumed batch or a
// shared work-order link). Resolves with the tour's end reason, or null.
async function tour(user, plain) {
  if (!plain || !(await due(user))) return null;
  return new Promise((resolve) => { void startTutorial("welcome", "welcome", { onEnd: resolve }); });
}

export async function runWelcomeThenClockIn(user, { plain }) {
  try {
    const reason = await tour(user, plain);
    // Finishing leaves the person on Tutorials > Starter (the player put the Hub tab back).
    if (reason === "done" && getCurrentUser() === user) {
      setTutorialsSub("starter");
      document.getElementById("hub-tab-tutorials")?.click();
    }
  } catch (err) {
    console.error("welcome failed", err);
  }
  if (getCurrentUser() === user) await maybePromptClockIn(user);
  if (getCurrentUser() === user) await maybeWarnStorage(user);
}

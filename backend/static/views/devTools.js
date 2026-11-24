// View: the Owner's Dev Tools switches (the push test button is views/push.js).
//
// `#smr-switch` turns the SMR27 audit on or off for everyone. Off, the server
// answers 404 on every /work-orders/smr/* route and canAccessPage hides the
// SMR27 and SMR Admin Review pages; other signed-in users see the change on
// their next sign-in or reload.

import { apiSetSmrSwitch } from "../api.js";
import { setMessage } from "../dom.js";
import { friendlyError } from "../format.js";
import { getRole, isSmrEnabled, setSmrEnabled } from "../state.js";
import { applyRoleVisibility } from "./nav.js";

const smrSwitch = document.getElementById("smr-switch");
const smrMessage = document.getElementById("smr-switch-message");

export function loadDevTools() {
  if (smrSwitch) smrSwitch.checked = isSmrEnabled();
  if (smrMessage) setMessage(smrMessage, "", "");
}

async function handleSmrSwitch() {
  const wanted = smrSwitch.checked;
  smrSwitch.disabled = true;
  try {
    const { enabled } = await apiSetSmrSwitch(wanted);
    setSmrEnabled(enabled);
    smrSwitch.checked = enabled;
    applyRoleVisibility(getRole());
    setMessage(smrMessage, enabled ? "SMR27 is on for everyone." : "SMR27 is hidden for everyone.", "success");
  } catch (err) {
    smrSwitch.checked = !wanted;
    setMessage(smrMessage, friendlyError(err, "Could not change the SMR27 switch."), "error");
  } finally {
    smrSwitch.disabled = false;
  }
}

if (smrSwitch) smrSwitch.addEventListener("change", handleSmrSwitch);

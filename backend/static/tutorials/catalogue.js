// One flat list of every tutorial script, each tagged with its page (0b spec
// 5.8). Imports the registry only; the scripts files are data, no sample is run.

import { TUTORIALS } from "./index.js";

export function catalogue(tutorials = TUTORIALS) {
  return Object.entries(tutorials).flatMap(([page, { scripts }]) =>
    scripts.map((script) => ({ page, ...script })));
}

import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { expect, it } from "vitest";
import { NAV_GROUPS, presentedNavigation } from "./nav-sections";

it("keeps the API navigation vocabulary aligned with the actual registry", () => {
  const source = readFileSync(
    resolve(process.cwd(), "../backend/app/schemas/console_presentation.py"),
    "utf8",
  );
  const union = source.match(/NavigationEntry = Literal\[([\s\S]*?)\]/)?.[1] ?? "";
  const backend = [...union.matchAll(/"([^"]+)"/g)].map((match) => match[1]);
  const frontend = NAV_GROUPS.filter((group) => !group.adminOnly && !group.switcherOnly).flatMap(
    (group) => group.items.map((item) => item.labelKey),
  );
  expect(backend.sort()).toEqual(frontend.sort());
});
it("keeps the unchanged default and identity/admin navigation", () => {
  expect(presentedNavigation(NAV_GROUPS, null)).toEqual(NAV_GROUPS);
  expect(
    presentedNavigation(NAV_GROUPS, []).every((group) => group.adminOnly || group.switcherOnly),
  ).toBe(true);
});
it("keeps Documents visible without a collapsed builder section in the simple preset", () => {
  const groups = presentedNavigation(NAV_GROUPS, ["chat", "inbox", "allProjects", "documents"]);
  const knowledge = groups.find((group) => group.labelKey === "knowledge");
  expect(knowledge?.collapsible).toBe(false);
  expect(knowledge?.items.map((item) => item.labelKey)).toEqual(["documents"]);
});

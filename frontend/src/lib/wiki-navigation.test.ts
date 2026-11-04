import { expect, it } from "vitest";
import { parseWikiPage } from "./wiki-graph";
import { filterWikiPages, inWikiFolder } from "./wiki-navigation";

it("filters nested folders on path boundaries and combines search with group visibility", () => {
  const a = parseWikiPage(
    "notes/research/a.md",
    "---\ntags: [science]\naliases: Discovery\n---\n# Alpha",
  );
  const b = parseWikiPage("notes-old/b.md", "# Beta");
  expect(inWikiFolder(a.path, "/notes/")).toBe(true);
  expect(inWikiFolder(b.path, "notes")).toBe(false);
  expect(filterWikiPages([a, b], " discovery ", "notes", new Set(), "folder")).toEqual([a]);
  expect(filterWikiPages([a, b], "#SCIENCE", null, new Set(), "tag")).toEqual([a]);
  expect(filterWikiPages([a, b], "", null, new Set(["science"]), "tag")).toEqual([b]);
  expect(filterWikiPages([a, b], "", null, new Set(["notes/research"]), "folder")).toEqual([b]);
});

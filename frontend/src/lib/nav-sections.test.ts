import { describe, expect, it } from "vitest";

import { navSectionFor } from "./nav-sections";

describe("navSectionFor", () => {
  it("names the entry and its group's hue, and says when the path is the section's own page", () => {
    expect(navSectionFor("/agents")).toMatchObject({ domain: "build", isRoot: true });
    expect(navSectionFor("/agents")?.item.href).toBe("/agents");
    expect(navSectionFor("/rag")).toMatchObject({ domain: "knowledge", isRoot: true });
    expect(navSectionFor("/vault")).toMatchObject({ domain: "workspace", isRoot: true });
    expect(navSectionFor("/dashboard")).toMatchObject({ domain: "use", isRoot: true });
  });

  it("places a sub-page in its section without calling it the section's page", () => {
    expect(navSectionFor("/agents/abc")).toMatchObject({ domain: "build", isRoot: false });
  });

  it("strips a locale prefix before it decides", () => {
    expect(navSectionFor("/pl/skills")).toMatchObject({ domain: "build", isRoot: true });
  });

  it("answers null outside every section", () => {
    expect(navSectionFor("/settings/profile")).toBeNull();
  });
});

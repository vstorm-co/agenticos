import { describe, expect, it } from "vitest";

import { ROUTES } from "./constants";

/**
 * The app's own URLs.
 *
 * Every link in the product comes from here, which is what keeps a renamed page
 * from leaving dead links behind. The builders are the part worth asserting: a
 * missing slash produces `/orgsx/members`, and nothing in a click-through would
 * say so before somebody hit a 404.
 */
describe("ROUTES", () => {
  it("builds every parameterised route from its id", () => {
    expect(ROUTES.AGENT_DETAIL("a1")).toBe("/agents/a1");
    expect(ROUTES.KB_DETAIL("kb1")).toBe("/kb/kb1");
    expect(ROUTES.ORG_MEMBERS("o1")).toBe("/orgs/o1/members");
    expect(ROUTES.ORG_ROLES("o1")).toBe("/orgs/o1/roles");
    expect(ROUTES.ORG_SETTINGS("o1")).toBe("/orgs/o1/settings");
  });

  it("nests each parameterised route under the listing it belongs to", () => {
    // Which is what makes the sidebar's active-route matching work: opening one
    // agent has to keep Agents highlighted.
    expect(ROUTES.AGENT_DETAIL("a1").startsWith(`${ROUTES.AGENTS}/`)).toBe(true);
    expect(ROUTES.KB_DETAIL("kb1").startsWith(`${ROUTES.KB}/`)).toBe(true);
    expect(ROUTES.ORG_MEMBERS("o1").startsWith(`${ROUTES.ORGS}/`)).toBe(true);
  });

  it("gives every static route an absolute path", () => {
    for (const [name, value] of Object.entries(ROUTES)) {
      if (typeof value !== "string") continue;
      expect(value.startsWith("/"), name).toBe(true);
    }
  });
});

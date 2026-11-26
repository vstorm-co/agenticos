import { describe, expect, it } from "vitest";

import { agentBinding } from "./agent-collections";
import type { KnowledgeBase } from "@/types/knowledge-base";

function base(overrides: Partial<KnowledgeBase>): KnowledgeBase {
  return { id: "kb-1", scope: "org", organization_id: "org-a", ...overrides } as KnowledgeBase;
}

describe("which collections an agent can bind", () => {
  it("binds its organization's bases", () => {
    expect(agentBinding(base({ scope: "org" }), "org-a")).toBe("bindable");
  });

  it("binds a personal base made in its organization", () => {
    expect(agentBinding(base({ scope: "personal" }), "org-a")).toBe("bindable");
  });

  it("refuses a personal base made in another organization", () => {
    expect(agentBinding(base({ scope: "personal", organization_id: "org-b" }), "org-a")).toBe(
      "otherOrganization",
    );
  });

  it("refuses a personal base that names no organization", () => {
    expect(agentBinding(base({ scope: "personal", organization_id: null }), "org-a")).toBe(
      "otherOrganization",
    );
  });

  it("refuses an app-scoped base", () => {
    expect(agentBinding(base({ scope: "app", organization_id: null }), "org-a")).toBe("app");
  });
});

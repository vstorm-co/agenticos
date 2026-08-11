import { describe, expect, it } from "vitest";

import { ROUTES } from "@/lib/constants";
import {
  canOfferFlow,
  FLOWS,
  flowForPage,
  stepsForFlow,
  type FlowId,
} from "@/lib/onboarding/flows";
import { KB_DETAIL, ORG_MEMBERS, ORG_ROLES } from "@/lib/onboarding/tour";
import { Perm } from "@/types/permissions";

const allow = () => true;
const deny = () => false;

describe("FLOWS", () => {
  it("gives every flow a single interactive step that points at its create trigger", () => {
    const targets: Record<FlowId, string> = {
      "create-skill": "skills-new",
      "create-kb": "knowledge-new",
      "create-mcp": "mcp-add",
      "create-org": "orgs-new",
    };
    for (const [id, target] of Object.entries(targets)) {
      const flow = FLOWS[id as FlowId];
      expect(flow.steps).toHaveLength(1);
      const step = flow.steps[0];
      expect(step?.interactive).toBe(true);
      expect(step?.target).toBe(target);
      expect(step?.signal?.kind).toBe("created");
    }
  });

  it("gates every create but an organization on an edit permission", () => {
    expect(FLOWS["create-skill"].permission).toBe(Perm.skillsEdit);
    expect(FLOWS["create-kb"].permission).toBe(Perm.collectionsEdit);
    expect(FLOWS["create-mcp"].permission).toBe(Perm.connectionsManage);
    // Anyone may create an organization, so its offer carries no permission.
    expect(FLOWS["create-org"].permission).toBeUndefined();
  });
});

describe("flowForPage", () => {
  it("maps each section, collapsing its detail routes onto the same flow", () => {
    expect(flowForPage(ROUTES.SKILLS)).toBe("create-skill");
    expect(flowForPage(ROUTES.RAG)).toBe("create-kb");
    expect(flowForPage(KB_DETAIL)).toBe("create-kb");
    expect(flowForPage(ROUTES.MCP_SERVERS)).toBe("create-mcp");
    expect(flowForPage(ROUTES.ORGS)).toBe("create-org");
    expect(flowForPage(ORG_MEMBERS)).toBe("create-org");
    expect(flowForPage(ORG_ROLES)).toBe("create-org");
  });

  it("offers nothing on a page with no create — the dashboard, and Agents for now", () => {
    expect(flowForPage(ROUTES.DASHBOARD)).toBeNull();
    // Agents has no guided flow yet; its "?" walk ends without an offer.
    expect(flowForPage(ROUTES.AGENTS)).toBeNull();
  });
});

describe("stepsForFlow", () => {
  it("keeps a step whose permission the caller holds", () => {
    expect(stepsForFlow(FLOWS["create-skill"], allow)).toHaveLength(1);
  });

  it("drops a step whose permission the caller lacks", () => {
    expect(stepsForFlow(FLOWS["create-skill"], deny)).toHaveLength(0);
  });

  it("keeps an unpermissioned step whatever the caller holds", () => {
    // The organization step names no permission, so a caller who can do nothing
    // still keeps it.
    expect(stepsForFlow(FLOWS["create-org"], deny)).toHaveLength(1);
  });
});

describe("canOfferFlow", () => {
  it("offers a permissioned flow only to a caller who holds it", () => {
    expect(canOfferFlow(FLOWS["create-skill"], allow)).toBe(true);
    expect(canOfferFlow(FLOWS["create-skill"], deny)).toBe(false);
  });

  it("offers an unpermissioned flow to anyone", () => {
    expect(canOfferFlow(FLOWS["create-org"], deny)).toBe(true);
  });
});

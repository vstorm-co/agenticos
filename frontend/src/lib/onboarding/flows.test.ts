import { describe, expect, it } from "vitest";

import { ROUTES } from "@/lib/constants";
import {
  canOfferFlow,
  FLOWS,
  flowForPage,
  stepsForFlow,
  type FlowId,
  type OrgState,
} from "@/lib/onboarding/flows";
import { AGENT_BUILDER, KB_DETAIL, ORG_MEMBERS, ORG_ROLES } from "@/lib/onboarding/tour";
import { Perm, type Permission } from "@/types/permissions";

const allow = () => true;
const deny = () => false;
const NO_MODEL: OrgState = { hasRunnableModel: false };
const HAS_MODEL: OrgState = { hasRunnableModel: true };

describe("FLOWS", () => {
  it("gives each per-section flow one step that points at its create trigger", () => {
    const targets: Partial<Record<FlowId, string>> = {
      "create-skill": "skills-new",
      "create-kb": "knowledge-new",
      "create-mcp": "mcp-add",
      "create-org": "orgs-new",
    };
    for (const [id, target] of Object.entries(targets)) {
      const flow = FLOWS[id as FlowId];
      expect(flow.steps).toHaveLength(1);
      const step = flow.steps[0];
      expect(step?.target).toBe(target);
      expect(step?.signal?.kind).toBe("created");
    }
  });

  it("walks the agent flow from create to publish", () => {
    const ids = FLOWS["create-agent"].steps.map((step) => step.id);
    expect(ids).toEqual([
      "flow-agent-create",
      "flow-agent-instructions",
      "flow-agent-model-add",
      "flow-agent-model-pick",
      "flow-agent-publish",
    ]);
  });

  it("gates each create on the permission that performs it", () => {
    expect(FLOWS["create-agent"].permission).toBe(Perm.agentsEdit);
    expect(FLOWS["create-skill"].permission).toBe(Perm.skillsEdit);
    expect(FLOWS["create-kb"].permission).toBe(Perm.collectionsEdit);
    expect(FLOWS["create-mcp"].permission).toBe(Perm.connectionsManage);
    // Anyone may create an organization, so its offer carries no permission.
    expect(FLOWS["create-org"].permission).toBeUndefined();
  });
});

describe("flowForPage", () => {
  it("maps each section, collapsing its detail routes onto the same flow", () => {
    expect(flowForPage(ROUTES.AGENTS)).toBe("create-agent");
    // An Agents "?" that walked into the builder still offers the agent flow.
    expect(flowForPage(AGENT_BUILDER)).toBe("create-agent");
    expect(flowForPage(ROUTES.SKILLS)).toBe("create-skill");
    expect(flowForPage(ROUTES.RAG)).toBe("create-kb");
    expect(flowForPage(KB_DETAIL)).toBe("create-kb");
    expect(flowForPage(ROUTES.MCP_SERVERS)).toBe("create-mcp");
    expect(flowForPage(ROUTES.ORGS)).toBe("create-org");
    expect(flowForPage(ORG_MEMBERS)).toBe("create-org");
    expect(flowForPage(ORG_ROLES)).toBe("create-org");
  });

  it("offers nothing on a page with no create", () => {
    expect(flowForPage(ROUTES.DASHBOARD)).toBeNull();
  });
});

describe("stepsForFlow", () => {
  it("keeps a step whose permission the caller holds", () => {
    expect(stepsForFlow(FLOWS["create-skill"], NO_MODEL, allow)).toHaveLength(1);
  });

  it("drops a step whose permission the caller lacks", () => {
    expect(stepsForFlow(FLOWS["create-skill"], NO_MODEL, deny)).toHaveLength(0);
  });

  it("keeps an unpermissioned step whatever the caller holds", () => {
    // The organization step names no permission, so a caller who can do nothing
    // still keeps it.
    expect(stepsForFlow(FLOWS["create-org"], NO_MODEL, deny)).toHaveLength(1);
  });

  it("teaches adding a model when the organization has none", () => {
    const ids = stepsForFlow(FLOWS["create-agent"], NO_MODEL, allow).map((step) => step.id);
    expect(ids).toContain("flow-agent-model-add");
    expect(ids).not.toContain("flow-agent-model-pick");
  });

  it("only shows where to pick a model when the organization has one", () => {
    const ids = stepsForFlow(FLOWS["create-agent"], HAS_MODEL, allow).map((step) => step.id);
    expect(ids).toContain("flow-agent-model-pick");
    expect(ids).not.toContain("flow-agent-model-add");
  });

  it("drops publish for a caller who may build but not publish", () => {
    const canButNotPublish = (permission: Permission) => permission !== Perm.agentsPublish;
    const ids = stepsForFlow(FLOWS["create-agent"], NO_MODEL, canButNotPublish).map(
      (step) => step.id,
    );
    expect(ids).not.toContain("flow-agent-publish");
    expect(ids).toContain("flow-agent-create");
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

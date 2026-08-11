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
const EMPTY: OrgState = {
  hasRunnableModel: false,
  hasKnowledgeBase: false,
  hasSkill: false,
  hasOrgMcp: false,
  hasPublishedAgent: false,
};
const HAS_MODEL: OrgState = {
  hasRunnableModel: true,
  hasKnowledgeBase: false,
  hasSkill: false,
  hasOrgMcp: false,
  hasPublishedAgent: false,
};
const STOCKED: OrgState = {
  hasRunnableModel: true,
  hasKnowledgeBase: true,
  hasSkill: true,
  hasOrgMcp: true,
  hasPublishedAgent: true,
};
const NO_CHOICES: Record<string, "yes" | "skip"> = {};

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

  it("walks the agent flow from create to publish, with a fork and detour per section", () => {
    const ids = FLOWS["create-agent"].steps.map((step) => step.id);
    expect(ids).toEqual([
      "flow-agent-create",
      "flow-agent-instructions",
      "flow-agent-model-add",
      "flow-agent-model-pick",
      "flow-agent-model-none",
      "flow-agent-knowledge",
      "flow-agent-knowledge-ask",
      "flow-agent-knowledge-create",
      "flow-agent-knowledge-return-nav",
      "flow-agent-knowledge-return-edit",
      "flow-agent-knowledge-attach",
      "flow-agent-skills",
      "flow-agent-skills-ask",
      "flow-agent-skills-create",
      "flow-agent-skills-return-nav",
      "flow-agent-skills-return-edit",
      "flow-agent-skills-attach",
      "flow-agent-tools",
      "flow-agent-mcp",
      "flow-agent-mcp-ask",
      "flow-agent-mcp-connect",
      "flow-agent-publish",
      "flow-agent-run-pick",
      "flow-agent-run-send",
    ]);
  });

  it("carries the run into chat: publish waits, then pick the built agent and send", () => {
    const byId = new Map(FLOWS["create-agent"].steps.map((step) => [step.id, step]));
    // Publish advances on the publish landing, not the click, so the chat steps
    // that follow have a published version to address.
    expect(byId.get("flow-agent-publish")?.signal).toEqual({ kind: "published" });
    const pick = byId.get("flow-agent-run-pick");
    expect(pick?.page).toBe(ROUTES.CHAT);
    expect(pick?.signal).toEqual({ kind: "selected" });
    const send = byId.get("flow-agent-run-send");
    expect(send?.page).toBe(ROUTES.CHAT);
    expect(send?.signal).toEqual({ kind: "sent" });
    // The whole tail is gated on publish: a caller who cannot publish has no
    // published agent to run, so it must drop with the publish step.
    for (const id of ["flow-agent-publish", "flow-agent-run-pick", "flow-agent-run-send"]) {
      expect(byId.get(id)?.permission).toBe(Perm.agentsPublish);
    }
  });

  it("asks about a missing resource on that resource's own screen", () => {
    const byId = new Map(FLOWS["create-agent"].steps.map((step) => [step.id, step]));
    // The fork navigates to the section first, so the question lands where the
    // answer happens rather than over the builder.
    expect(byId.get("flow-agent-knowledge-ask")?.page).toBe(ROUTES.RAG);
    expect(byId.get("flow-agent-skills-ask")?.page).toBe(ROUTES.SKILLS);
    // MCP connects inline, so its "screen" is the Toolbox tab it reveals.
    expect(byId.get("flow-agent-mcp-ask")?.activate).toBe("agent-tab-toolbox");
  });

  it("teaches the return leg by click, not by navigating for the reader", () => {
    const byId = new Map(FLOWS["create-agent"].steps.map((step) => [step.id, step]));
    const nav = byId.get("flow-agent-knowledge-return-nav");
    // No page of its own — the reader clicks the sidebar and the arrival advances it.
    expect(nav?.page).toBeUndefined();
    expect(nav?.target).toBe("nav-agents");
    expect(nav?.signal).toEqual({ kind: "arrived", page: ROUTES.AGENTS });

    const edit = byId.get("flow-agent-knowledge-return-edit");
    expect(edit?.dynamicTarget).toBe("createdAgentEdit");
    expect(edit?.signal).toEqual({ kind: "arrived", page: AGENT_BUILDER });
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

  it("offers the guided chat run on the chat page", () => {
    expect(flowForPage(ROUTES.CHAT)).toBe("explore-chat");
  });

  it("offers nothing on a page with no create", () => {
    expect(flowForPage(ROUTES.DASHBOARD)).toBeNull();
  });
});

describe("explore-chat", () => {
  it("opens with a build-an-agent fork, then a signal-less run of the chat controls", () => {
    const flow = FLOWS["explore-chat"];
    // The offer itself is ungated — anyone signed in can chat.
    expect(flow.permission).toBeUndefined();
    expect(flow.steps.map((step) => step.id)).toEqual([
      "flow-chat-needs-agent",
      "flow-chat-start",
      "flow-chat-agent",
      "flow-chat-controls",
      "flow-chat-composer",
    ]);
    // Nothing is created here, so every step lives on the chat page and advances on
    // a click rather than a resource appearing.
    for (const step of flow.steps) {
      expect(step.signal).toBeUndefined();
      expect(step.page).toBe(ROUTES.CHAT);
    }
  });

  it("asks to build an agent first when none is published, and hands off to create-agent", () => {
    const fork = FLOWS["explore-chat"].steps[0];
    expect(fork?.question).toBe(true);
    // Yes starts the create-agent flow rather than revealing a detour in this one.
    expect(fork?.opensFlow).toBe("create-agent");
    // Gated on the permission that create needs, and shown only when there is no
    // published agent to chat with.
    expect(fork?.permission).toBe(Perm.agentsEdit);
    expect(fork?.include?.({ ...EMPTY, hasPublishedAgent: true }, allow)).toBe(false);
    expect(fork?.include?.({ ...EMPTY, hasPublishedAgent: false }, allow)).toBe(true);
  });

  it("drops the build-an-agent fork for a reader who cannot create one", () => {
    // No `agents:edit`, so the fork that would open create-agent is not offered —
    // the reader gets the descriptive tour, not a flow they could not run.
    const canButNotAgentsEdit = (permission: Permission) => permission !== Perm.agentsEdit;
    const ids = stepsForFlow(FLOWS["explore-chat"], EMPTY, canButNotAgentsEdit, NO_CHOICES).map(
      (s) => s.id,
    );
    expect(ids).not.toContain("flow-chat-needs-agent");
    expect(ids[0]).toBe("flow-chat-start");
  });
});

describe("stepsForFlow", () => {
  it("keeps a step whose permission the caller holds", () => {
    expect(stepsForFlow(FLOWS["create-skill"], EMPTY, allow, NO_CHOICES)).toHaveLength(1);
  });

  it("drops a step whose permission the caller lacks", () => {
    expect(stepsForFlow(FLOWS["create-skill"], EMPTY, deny, NO_CHOICES)).toHaveLength(0);
  });

  it("keeps an unpermissioned step whatever the caller holds", () => {
    // The organization step names no permission, so a caller who can do nothing
    // still keeps it.
    expect(stepsForFlow(FLOWS["create-org"], EMPTY, deny, NO_CHOICES)).toHaveLength(1);
  });

  it("teaches adding a model when the organization has none", () => {
    const ids = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, NO_CHOICES).map(
      (step) => step.id,
    );
    expect(ids).toContain("flow-agent-model-add");
    expect(ids).not.toContain("flow-agent-model-pick");
  });

  it("only shows where to pick a model when the organization has one", () => {
    const ids = stepsForFlow(FLOWS["create-agent"], HAS_MODEL, allow, NO_CHOICES).map(
      (step) => step.id,
    );
    expect(ids).toContain("flow-agent-model-pick");
    expect(ids).not.toContain("flow-agent-model-add");
  });

  it("does not walk a caller who cannot manage connections to add a model", () => {
    // Adding a model is connections:manage; a builder without it would be led to
    // a control the server hides. The step drops rather than dead-ending them.
    const canButNotConnections = (permission: Permission) => permission !== Perm.connectionsManage;
    const ids = stepsForFlow(FLOWS["create-agent"], EMPTY, canButNotConnections, NO_CHOICES).map(
      (step) => step.id,
    );
    expect(ids).not.toContain("flow-agent-model-add");
  });

  it("shows the model dead-end step only when the org has none and the caller cannot add one", () => {
    // No model and no connections:manage: neither add (permission) nor pick (state)
    // would show, so a bare walk would reach Publish with no model. The
    // informational step stands in, rather than the reader being led there in
    // silence.
    const canButNotConnections = (permission: Permission) => permission !== Perm.connectionsManage;
    const stranded = stepsForFlow(
      FLOWS["create-agent"],
      EMPTY,
      canButNotConnections,
      NO_CHOICES,
    ).map((s) => s.id);
    expect(stranded).toContain("flow-agent-model-none");
    expect(stranded).not.toContain("flow-agent-model-add");
    expect(stranded).not.toContain("flow-agent-model-pick");

    // A caller who can add one is taught to, never told to wait.
    const canAdd = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, NO_CHOICES).map((s) => s.id);
    expect(canAdd).toContain("flow-agent-model-add");
    expect(canAdd).not.toContain("flow-agent-model-none");

    // With a model already, neither the add nor the dead-end shows — just the pick.
    const stocked = stepsForFlow(
      FLOWS["create-agent"],
      STOCKED,
      canButNotConnections,
      NO_CHOICES,
    ).map((s) => s.id);
    expect(stocked).toContain("flow-agent-model-pick");
    expect(stocked).not.toContain("flow-agent-model-none");
  });

  it("drops publish and the chat run for a caller who may build but not publish", () => {
    const canButNotPublish = (permission: Permission) => permission !== Perm.agentsPublish;
    const ids = stepsForFlow(FLOWS["create-agent"], EMPTY, canButNotPublish, NO_CHOICES).map(
      (step) => step.id,
    );
    expect(ids).not.toContain("flow-agent-publish");
    // The run tail is gated on publish too, so it drops with it rather than
    // walking a non-publisher to a chat with no published agent to address.
    expect(ids).not.toContain("flow-agent-run-pick");
    expect(ids).not.toContain("flow-agent-run-send");
    expect(ids).toContain("flow-agent-create");
  });

  it("asks to create a knowledge base when the org has none, and only points at it when it has one", () => {
    const empty = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, NO_CHOICES).map((s) => s.id);
    expect(empty).toContain("flow-agent-knowledge-ask");
    expect(empty).not.toContain("flow-agent-knowledge");

    const stocked = stepsForFlow(FLOWS["create-agent"], STOCKED, allow, NO_CHOICES).map(
      (s) => s.id,
    );
    expect(stocked).toContain("flow-agent-knowledge");
    expect(stocked).not.toContain("flow-agent-knowledge-ask");
  });

  it("hides the knowledge fork from a caller who could not create a base", () => {
    // No `collections:edit` and no base to attach, so the whole section drops
    // rather than asking about a create the server would refuse.
    const canButNotCollections = (permission: Permission) => permission !== Perm.collectionsEdit;
    const ids = stepsForFlow(FLOWS["create-agent"], EMPTY, canButNotCollections, NO_CHOICES).map(
      (s) => s.id,
    );
    expect(ids).not.toContain("flow-agent-knowledge-ask");
    expect(ids).not.toContain("flow-agent-knowledge");
  });

  it("opens the knowledge detour only once the fork is answered yes", () => {
    const detour = [
      "flow-agent-knowledge-create",
      "flow-agent-knowledge-return-nav",
      "flow-agent-knowledge-return-edit",
      "flow-agent-knowledge-attach",
    ];

    const unasked = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, NO_CHOICES).map((s) => s.id);
    for (const id of detour) expect(unasked).not.toContain(id);

    const skipped = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, {
      "flow-agent-knowledge-ask": "skip",
    }).map((s) => s.id);
    for (const id of detour) expect(skipped).not.toContain(id);

    const yes = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, {
      "flow-agent-knowledge-ask": "yes",
    }).map((s) => s.id);
    // The detour appears, in order, immediately after the fork it answers.
    const ask = yes.indexOf("flow-agent-knowledge-ask");
    expect(yes.slice(ask + 1, ask + 1 + detour.length)).toEqual(detour);
  });

  it("opens the skills detour the same way, independently of the knowledge one", () => {
    const yes = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, {
      "flow-agent-skills-ask": "yes",
    }).map((s) => s.id);
    expect(yes).toContain("flow-agent-skills-create");
    // Answering the skills fork does not conjure the knowledge detour.
    expect(yes).not.toContain("flow-agent-knowledge-create");
  });

  it("asks to connect an MCP server when the org has none, and only points at it when it has one", () => {
    const empty = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, NO_CHOICES).map((s) => s.id);
    expect(empty).toContain("flow-agent-mcp-ask");
    expect(empty).not.toContain("flow-agent-mcp");

    const stocked = stepsForFlow(FLOWS["create-agent"], STOCKED, allow, NO_CHOICES).map(
      (s) => s.id,
    );
    expect(stocked).toContain("flow-agent-mcp");
    expect(stocked).not.toContain("flow-agent-mcp-ask");
  });

  it("hides the MCP fork from a caller who cannot manage connections", () => {
    // No `connections:manage` and no connection to attach, so the whole section
    // drops rather than asking about a connect the server would refuse.
    const canButNotConnections = (permission: Permission) => permission !== Perm.connectionsManage;
    const ids = stepsForFlow(FLOWS["create-agent"], EMPTY, canButNotConnections, NO_CHOICES).map(
      (s) => s.id,
    );
    expect(ids).not.toContain("flow-agent-mcp-ask");
    expect(ids).not.toContain("flow-agent-mcp");
  });

  it("opens the MCP connect step only once the fork is answered yes, and it stays in the builder", () => {
    const unasked = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, NO_CHOICES).map((s) => s.id);
    expect(unasked).not.toContain("flow-agent-mcp-connect");

    const skipped = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, {
      "flow-agent-mcp-ask": "skip",
    }).map((s) => s.id);
    expect(skipped).not.toContain("flow-agent-mcp-connect");

    const yes = stepsForFlow(FLOWS["create-agent"], EMPTY, allow, { "flow-agent-mcp-ask": "yes" });
    const ids = yes.map((s) => s.id);
    // The connect step appears immediately after the fork it answers.
    const ask = ids.indexOf("flow-agent-mcp-ask");
    expect(ids[ask + 1]).toBe("flow-agent-mcp-connect");
    // Inline, so it carries no `arrived` return leg — it names a builder page and a
    // `created` signal, and the reader never leaves to make the connection.
    const connect = yes.find((s) => s.id === "flow-agent-mcp-connect");
    expect(connect?.signal).toEqual({ kind: "created", resource: "orgMcp" });
    expect(connect?.page).toBe(AGENT_BUILDER);
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

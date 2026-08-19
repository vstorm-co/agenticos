import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { SpecialistList } from "./specialist-list";
import { newSpecialist } from "@/lib/agent-spec";
import type { KnowledgeBase } from "@/types/knowledge-base";
import type { ModelProfile, SkillSummary } from "@/types/providers";
import type { CapabilityBindingSpec, CapabilityCatalogEntry, SpecialistSpec } from "@/types/agents";

const state = vi.hoisted(() => ({
  profiles: [] as ModelProfile[],
  collections: [] as KnowledgeBase[],
  skills: [] as SkillSummary[],
  promote: { mutate: vi.fn(), isPending: false },
  canEdit: true,
}));

// The editor reads three catalogs the Builder around it has already fetched.
// None of them is this file's subject, and each has its own picker's tests.
vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    catalog: [],
    profiles: state.profiles,
    isLoading: false,
    createProfile: { mutateAsync: vi.fn(), isPending: false },
    deleteProfile: { mutate: vi.fn(), isPending: false },
  }),
  useKnowledgeBases: () => ({ kbs: state.collections, isLoading: false }),
  useSkills: () => ({ skills: state.skills, total: state.skills.length, isLoading: false }),
  useSecrets: () => ({ secrets: [], isLoading: false, listError: null }),
  useProviderModels: () => ({ models: [], source: null, isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
  useAgents: () => ({ promote: state.promote }),
  usePermissions: () => ({ can: () => state.canEdit }),
}));

vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CHARTS: CapabilityCatalogEntry = {
  id: "charts",
  name: "Charts",
  category: "analysis",
  description: "Draw a chart so the user can see the numbers.",
  side_effecting: false,
  scopes: [],
  tools: [{ id: "create_chart", name: "create_chart", description: "Draw a chart." }],
  contracts: [],
  config_schema: null,
  requires_secret: null,
};

const CLOCK: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "clock",
  name: "Clock",
  description: "Tell the agent what day it is.",
  tools: [{ id: "now", name: "now", description: "The current time." }],
};

const DELEGATION: CapabilityCatalogEntry = {
  ...CHARTS,
  id: "subagents",
  name: "Delegation",
  category: "orchestration",
  description: "Hand work to other agents.",
  tools: [],
};

function bound(id: string): CapabilityBindingSpec {
  return {
    id,
    config: {},
    approval: "default",
    tool_approval: {},
    tool_overrides: {},
    secret_id: null,
    enabled: true,
  };
}

function specialist(overrides: Partial<SpecialistSpec> = {}): SpecialistSpec {
  return { ...newSpecialist(), name: "researcher", description: "Researches.", ...overrides };
}

function mount({
  specialists = [] as SpecialistSpec[],
  catalog = [CHARTS],
  clashes = new Set<string>(),
  parentModelProfileId = null as string | null,
  disabled = false,
  onChange = vi.fn(),
}: {
  specialists?: SpecialistSpec[];
  catalog?: CapabilityCatalogEntry[];
  clashes?: Set<string>;
  parentModelProfileId?: string | null;
  disabled?: boolean;
  onChange?: (specialists: SpecialistSpec[]) => void;
} = {}) {
  render(
    <SpecialistList
      specialists={specialists}
      onChange={onChange}
      catalog={catalog}
      clashes={clashes}
      parentModelProfileId={parentModelProfileId}
      disabled={disabled}
    />,
  );
  return onChange;
}

beforeEach(() => {
  state.profiles = [
    {
      id: "m1",
      label: "Sonnet",
      provider: "anthropic",
      model: "claude",
      secret_id: null,
      params: {},
      allow_byo: false,
      fallback_profile_ids: [],
    },
  ];
  state.collections = [];
  state.skills = [];
  state.promote = { mutate: vi.fn(), isPending: false };
  state.canEdit = true;
});

describe("SpecialistList", () => {
  it("says a specialist is not versioned, because that is the thing to get wrong", () => {
    // A delegate is pinned and stable; a specialist changes the moment this
    // agent is edited. Presented side by side, a reader assumes the reverse.
    mount();

    expect(screen.getByText(/no version, cannot be pinned/)).toBeVisible();
  });

  it("says what one is for rather than showing an empty list", () => {
    mount();

    expect(screen.getByText(/publishing a whole agent would be too much ceremony/)).toBeVisible();
  });

  it("adding one appends an empty specialist and shows its editor", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByRole("button", { name: "Add a specialist" }));

    expect(onChange).toHaveBeenCalledWith([newSpecialist()]);
  });

  it("edits the specialist on show, not the first one", async () => {
    const onChange = mount({
      specialists: [specialist(), specialist({ name: "writer" })],
    });

    await userEvent.click(screen.getByRole("button", { name: "writer" }));
    await userEvent.type(screen.getByLabelText("Description"), "!");

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({ name: "researcher" }),
      expect.objectContaining({ name: "writer", description: "Researches.!" }),
    ]);
  });

  it("names a specialist nobody has named yet", () => {
    mount({ specialists: [specialist({ name: "" })] });

    expect(screen.getByRole("button", { name: "New specialist" })).toBeVisible();
  });

  it("offers a way out of one that was just added, without scrolling for it", () => {
    // Adding a specialist is one click and produces an entry that is already
    // invalid. The discard used to be below the instructions, the model, the
    // capabilities, the collections and the skills - so on a real screen the
    // button was off the bottom and adding one read as a one-way door.
    const onChange = mount({ specialists: [specialist({ name: "" })] });
    const remove = screen.getByRole("button", { name: "Remove this specialist" });
    const name = screen.getByLabelText("Name");

    // Ordered by the DOM, which is what "reachable without scrolling" means here.
    expect(remove.compareDocumentPosition(name) & Node.DOCUMENT_POSITION_FOLLOWING).toBeTruthy();
    expect(onChange).not.toHaveBeenCalled();
  });

  it("removes the one on show and falls back to the first", async () => {
    const onChange = mount({ specialists: [specialist(), specialist({ name: "writer" })] });

    await userEvent.click(screen.getByRole("button", { name: "writer" }));
    await userEvent.click(screen.getByRole("button", { name: "Remove this specialist" }));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ name: "researcher" })]);
  });
});

describe("the name, which the parent's model emits verbatim", () => {
  it("refuses what a tool argument cannot carry", async () => {
    mount({ specialists: [specialist({ name: "two words" })] });

    expect(screen.getByText(/Letters, digits, underscores and dashes only/)).toBeVisible();
    expect(screen.getByLabelText("Name")).toBeInvalid();
  });

  it("says nothing about the name until somebody has been at it", async () => {
    // A specialist starts with an empty name, so the error was on screen before
    // anybody had typed - a form scolding somebody for a field they have not
    // reached. Publish still refuses it and the Issues count still counts it.
    mount({ specialists: [specialist({ name: "" })] });

    expect(screen.queryByText(/cannot address is one it cannot use/)).toBeNull();
  });

  it("says a blank name is a specialist the model cannot address, once it is theirs", async () => {
    mount({ specialists: [specialist({ name: "" })] });

    await userEvent.click(screen.getByLabelText("Name"));
    await userEvent.tab();

    expect(screen.getByText(/cannot address is one it cannot use/)).toBeVisible();
  });

  it("says so straight away for a name that was typed and is wrong", async () => {
    // Nothing deferred here: the value came from somebody, so the objection is
    // about what they wrote rather than about what they have not written.
    mount({ specialists: [specialist({ name: "Not A Handle" })] });

    expect(screen.getByText(/Letters, digits, underscores and dashes only/)).toBeVisible();
  });

  it("stores what was typed, so a name can be corrected in place", async () => {
    const onChange = mount({ specialists: [specialist({ name: "researcher" })] });

    await userEvent.type(screen.getByLabelText("Name"), "_2");

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ name: "researcher_" })]);
  });

  it("names a collision with a delegate, which publishing refuses", () => {
    mount({ specialists: [specialist()], clashes: new Set(["researcher"]) });

    expect(screen.getByText(/also called researcher/)).toBeVisible();
  });

  it("says nothing about a collision while the name is not yet legal", () => {
    // One refusal at a time: the pattern error is the one to fix first, and two
    // red lines under one field read as two separate problems.
    mount({ specialists: [specialist({ name: "two words" })], clashes: new Set(["two words"]) });

    expect(screen.queryByText(/also called/)).toBeNull();
  });
});

describe("what a specialist can do", () => {
  it("grants a capability from the same catalog the agent uses", async () => {
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.click(screen.getByRole("switch", { name: "Give this specialist Charts" }));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        capabilities: [expect.objectContaining({ id: "charts", enabled: true })],
      }),
    ]);
  });

  it("configures it with the same panel, not a second editor", () => {
    // A specialist carries real bindings, validated at publish exactly as an
    // agent's are, so a copy of this panel would be a second set of defaults
    // for approval, secrets and tool text.
    mount({
      specialists: [specialist({ capabilities: [bound("charts")] })],
    });

    // Settings and Tools are two tabs on that panel, so the tool is one click in -
    // the same panel a parent's own capability gets, tabs and all.
    const panel = screen.getByRole("group", { name: "Charts" });
    expect(within(panel).getByLabelText("Human approval")).toBeVisible();
    fireEvent.mouseDown(within(panel).getByRole("tab", { name: "Tools" }));
    expect(within(panel).getByText("create_chart")).toBeVisible();
  });

  it("does not offer delegation to a specialist", () => {
    // A specialist does not delegate further: nesting is what `max_depth`
    // bounds, and it is bounded for published delegates, which are reviewable.
    mount({ specialists: [specialist()], catalog: [CHARTS, DELEGATION] });

    expect(screen.queryByRole("switch", { name: /Delegation/ })).toBeNull();
  });

  it("binds a skill together with the capability that reads it", async () => {
    // Bound without it the skills are fetched and thrown away - an agent that
    // silently knows nothing, one level further down where nobody would look.
    state.skills = [
      {
        id: "s1",
        name: "Refunds",
        description: "How refunds work here.",
        category: null,
        enabled: true,
        file_count: 0,
        built_in: false,
      },
    ];
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.click(screen.getByRole("checkbox", { name: "Refunds" }));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        skill_ids: ["s1"],
        capabilities: [expect.objectContaining({ id: "skills" })],
      }),
    ]);
  });

  it("detaches a collection that was attached", async () => {
    state.collections = [
      {
        id: "kb1",
        name: "Policies",
        description: null,
        embedding_model: "text-embedding-3-small",
        document_count: 2,
        indexed_count: 2,
        chunk_count: 10,
        is_default: false,
      } as KnowledgeBase,
    ];
    const onChange = mount({ specialists: [specialist({ collection_ids: ["kb1"] })] });

    await userEvent.click(screen.getByRole("checkbox", { name: "Policies" }));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ collection_ids: [] })]);
  });

  it("configures the capability it names, and leaves the other one alone", async () => {
    // The panel is `CapabilityDetail`, one level down: a specialist's approval
    // mode is the agent's approval mode, and a second implementation of it would
    // be a second set of defaults. Two bindings, because an edit that rewrote
    // both would look identical with one.
    const onChange = mount({
      catalog: [CHARTS, CLOCK],
      specialists: [specialist({ capabilities: [bound("charts"), bound("clock")] })],
    });

    const panel = screen.getByRole("group", { name: "Clock" });
    await userEvent.click(within(panel).getByLabelText("Human approval"));
    await userEvent.click(screen.getByRole("option", { name: "Always ask" }));

    expect(onChange).toHaveBeenCalledWith([
      expect.objectContaining({
        capabilities: [bound("charts"), { ...bound("clock"), approval: "required" }],
      }),
    ]);
  });

  it("attaches a collection to the specialist alone", async () => {
    state.collections = [
      {
        id: "kb1",
        name: "Policies",
        description: null,
        embedding_model: "text-embedding-3-small",
        document_count: 2,
        indexed_count: 2,
        chunk_count: 10,
        is_default: false,
      } as KnowledgeBase,
    ];
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.click(screen.getByRole("checkbox", { name: "Policies" }));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ collection_ids: ["kb1"] })]);
  });
});

describe("the rest of a specialist's own settings", () => {
  it("stores a step cap of its own, and nothing when it is cleared", async () => {
    const onChange = mount({ specialists: [specialist({ max_steps: 5 })] });

    await userEvent.clear(screen.getByLabelText("Max steps"));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ max_steps: null })]);
  });

  it("stores a step cap that was typed in", async () => {
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.type(screen.getByLabelText("Max steps"), "8");

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ max_steps: 8 })]);
  });

  it("stores the model it runs on", async () => {
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.click(screen.getByRole("radio", { name: /Sonnet/ }));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ model_profile_id: "m1" })]);
  });

  it("stores its instructions, which is where its behaviour lives", async () => {
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.type(screen.getByLabelText("Instructions"), "Cite sources.");

    expect(onChange).toHaveBeenCalled();
  });

  it("stores a mode override for this specialist alone", async () => {
    const onChange = mount({ specialists: [specialist()] });

    await userEvent.click(screen.getByRole("combobox", { name: "When it hands back" }));
    await userEvent.click(screen.getByRole("option", { name: "Let the model decide" }));

    expect(onChange).toHaveBeenCalledWith([expect.objectContaining({ preferred_mode: "auto" })]);
  });

  it("is inert for somebody who may not edit the agent", () => {
    mount({ specialists: [specialist()], disabled: true });

    expect(screen.getByRole("button", { name: "Add a specialist" })).toBeDisabled();
    expect(screen.getByLabelText("Name")).toBeDisabled();
    expect(screen.getByLabelText("Instructions")).toBeDisabled();
    expect(screen.getByRole("switch", { name: "Give this specialist Charts" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Remove this specialist" })).toBeDisabled();
  });

  it("promotes a specialist with the parent's model as the fallback", async () => {
    // A specialist on "the same model as its parent" (null model_profile_id) needs
    // a concrete one as a standalone agent, and the parent's is it.
    const spec = specialist({ instructions: "Summarise in three bullets." });
    // The mutate stand-in reports success, so the panel's own toast runs.
    state.promote.mutate.mockImplementation((_input, opts) => opts.onSuccess({ name: spec.name }));
    mount({ specialists: [spec], parentModelProfileId: "m1" });

    await userEvent.click(screen.getByRole("button", { name: "Promote to a draft agent" }));

    expect(state.promote.mutate).toHaveBeenCalledWith(
      { specialist: spec, fallbackModelProfileId: "m1" },
      expect.anything(),
    );
    expect(toast.success).toHaveBeenCalledWith("Promoted researcher to a draft agent");
  });

  it("surfaces the reason a promotion was refused", async () => {
    // The name derives the new agent's handle, which can already be taken - the
    // server says which, and the author needs to read it.
    state.promote.mutate.mockImplementation((_input, opts) =>
      opts.onError(new Error("The handle @researcher is already taken.")),
    );
    mount({ specialists: [specialist()], parentModelProfileId: null });

    await userEvent.click(screen.getByRole("button", { name: "Promote to a draft agent" }));

    expect(toast.error).toHaveBeenCalledWith("The handle @researcher is already taken.");
  });

  it("does not offer to promote to somebody who may not create an agent", () => {
    // Not rendered, rather than rendered and then refused: promoting creates an
    // agent, which takes agents:edit.
    state.canEdit = false;
    mount({ specialists: [specialist()] });

    expect(screen.queryByRole("button", { name: "Promote to a draft agent" })).toBeNull();
  });
});

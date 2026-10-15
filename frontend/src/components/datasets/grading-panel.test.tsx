import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import { DEFAULT_SCORING } from "@/lib/scoring";
import type { Agent } from "@/types/agents";
import type { Dataset } from "@/types/datasets";
import type { DatasetScoring } from "@/types/scoring";
import { GradingPanel } from "./grading-panel";

const state = vi.hoisted(() => ({
  save: vi.fn(),
  create: vi.fn(),
  judges: [] as Partial<Agent>[],
  perms: new Set<string>(),
}));
vi.mock("@/hooks/use-scoring", () => ({
  useSetScoring: () => ({ mutateAsync: state.save, isPending: false }),
  useCreateJudge: () => ({ mutateAsync: state.create, isPending: false }),
}));
vi.mock("@/hooks/use-agents", () => ({
  useJudges: () => ({ agents: state.judges, total: state.judges.length }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: [{ id: "p1", label: "Claude (prod)" }] }),
}));
const ai = vi.hoisted(() => ({ enabled: true as boolean | null }));
vi.mock("@/hooks/use-organizations", () => ({
  useAiAssistance: () => ({ orgId: "o1", enabled: ai.enabled }),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.perms.has(perm) }),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
import { toast } from "sonner";

const JUDGED: DatasetScoring = {
  ...DEFAULT_SCORING,
  checks: { ...DEFAULT_SCORING.checks, defaults: [{ type: "max_cost_usd", value: 0.05 }] },
  judge: {
    ...DEFAULT_SCORING.judge,
    enabled: true,
    criteria: [{ name: "tone", description: "Polite", required: true }],
  },
};

function dataset(scoring: DatasetScoring, overrides: Partial<Dataset> = {}): Dataset {
  return {
    id: "d1",
    name: "Refunds",
    description: "Returns and refunds",
    visibility: "org",
    owner_user_id: null,
    latest_version: 1,
    case_count: 2,
    can_edit: true,
    scoring,
    judge_name: "Eval judge",
    stats: {
      with_reference: 0,
      with_counter_example: 0,
      with_tool_calls: 0,
      with_checks: 0,
      expectation_mix: [],
      by_source: { manual: 2, import: 0, conversation: 0, synthetic: 0 },
      top_tags: [],
    },
    created_at: "2026-10-01T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

function panel(scoring: DatasetScoring = DEFAULT_SCORING, overrides: Partial<Dataset> = {}) {
  return render(<GradingPanel dataset={dataset(scoring, overrides)} />);
}

/** The card a heading names, so its own Save button is the one pressed. */
const card = (title: string) => screen.getByRole("heading", { name: title }).closest("section")!;
const bar = () => screen.getByRole("region", { name: "Unsaved changes" });
const saveAll = () => within(bar()).getByRole("button", { name: "Save" });
const saved = () => state.save.mock.calls.at(-1)?.[0] as DatasetScoring;

beforeEach(() => {
  vi.clearAllMocks();
  ai.enabled = true;
  state.perms = new Set(["agents:edit", "org:settings"]);
  state.judges = [
    {
      id: "j0",
      name: "Eval judge",
      system_key: "eval_judge",
      kind: "judge",
      published_model: { profile_id: "p1", provider: "openai", model: "gpt-4.1", label: "GPT-4.1" },
    },
    { id: "j1", name: "Refunds judge", system_key: null, kind: "judge" },
  ];
  state.save.mockResolvedValue({});
});

/**
 * How a dataset is graded, in three cards saved together from one bar. The rules
 * and the expected tool calls are on by default; the judge is a decision somebody makes.
 */
describe("GradingPanel", () => {
  it("saves every card's changes together from one bar, which then goes", async () => {
    const { rerender } = panel();
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();

    await userEvent.click(screen.getByRole("switch", { name: "Expected tool calls" }));
    await userEvent.click(screen.getByRole("switch", { name: "Checks: must pass" }));
    await userEvent.click(screen.getByRole("switch", { name: "Reference answer" }));
    expect(within(card("When a case passes")).getByText("Unsaved")).toBeInTheDocument();
    expect(within(card("Judge")).getByText("Unsaved")).toBeInTheDocument();
    expect(within(card("Review by a person")).queryByText("Unsaved")).toBeNull();
    await userEvent.click(saveAll());

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Grading saved"));
    expect(saved().trajectory.enabled).toBe(false);
    expect(saved().checks).toEqual({ enabled: true, required: false, defaults: [] });
    expect(saved().reference.enabled).toBe(true);
    rerender(<GradingPanel dataset={dataset(saved())} />);
    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
  });

  it("discards every card's changes at once", async () => {
    panel(JUDGED);

    await userEvent.click(screen.getByRole("switch", { name: "Expected tool calls" }));
    await userEvent.type(screen.getByRole("textbox", { name: "What the criterion asks" }), "!");
    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.click(within(bar()).getByRole("button", { name: "Discard" }));

    expect(screen.queryByRole("region", { name: "Unsaved changes" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Expected tool calls" })).toBeChecked();
    expect(screen.getByRole("textbox", { name: "What the criterion asks" })).toHaveValue("Polite");
    expect(screen.queryByLabelText("Check 2: what it checks")).toBeNull();
    expect(state.save).not.toHaveBeenCalled();
  });

  it("holds the save shut while the configuration could grade nothing", async () => {
    panel();

    await userEvent.click(screen.getByRole("switch", { name: "Checks" }));
    await userEvent.click(screen.getByRole("switch", { name: "Expected tool calls" }));

    expect(within(bar()).getByRole("alert")).toHaveTextContent("Turn on at least one scorer");
    expect(saveAll()).toBeDisabled();

    await userEvent.click(screen.getByRole("switch", { name: "Judge" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Give the judge at least one criterion");
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it.each([
    [true, "Enable AI assistance"],
    [false, "Ask an admin to enable AI assistance."],
  ])(
    "with AI assistance off, locks the judge card but not the rules (org:settings %s)",
    (maySet, offer) => {
      ai.enabled = false;
      if (!maySet) state.perms.delete("org:settings");
      panel(JUDGED);

      expect(screen.getAllByRole("status")[0]).toHaveTextContent(offer);
      expect(screen.getByRole("switch", { name: "Judge" })).toBeDisabled();
      expect(screen.getByRole("switch", { name: "Reference answer" })).toBeDisabled();
      expect(screen.getByRole("combobox", { name: "Which judge" })).toBeDisabled();
      expect(screen.getByRole("button", { name: "Add criterion" })).toBeDisabled();
      expect(screen.getByRole("switch", { name: "Checks" })).toBeEnabled();
      expect(screen.getByRole("switch", { name: "Expected tool calls" })).toBeEnabled();
    },
  );

  it("configures the judge: its model, its scale and its criteria", async () => {
    panel();

    await userEvent.click(screen.getByRole("switch", { name: "Judge" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Judge's model" }));
    await userEvent.click(screen.getByRole("option", { name: "Claude (prod)" }));
    expect(screen.getByText(/will not compare/)).toBeInTheDocument();
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Top of the scale" }));
    await userEvent.type(screen.getByRole("spinbutton", { name: "Top of the scale" }), "7");
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Passes at" }));
    await userEvent.type(screen.getByRole("spinbutton", { name: "Passes at" }), "6");
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Criterion name" }), "correctness");
    await userEvent.type(screen.getByRole("textbox", { name: "What the criterion asks" }), "Right");
    await userEvent.click(screen.getByRole("switch", { name: "Must pass" }));
    await userEvent.click(saveAll());

    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().judge).toEqual({
      enabled: true,
      agent_id: null,
      model_profile_id: "p1",
      scale_max: 7,
      pass_at: 6,
      criteria: [{ name: "correctness", description: "Right", required: false }],
    });
  });

  it("picks the dataset's own judge once confirmed, and says older scores will not compare", async () => {
    panel(JUDGED);
    expect(screen.queryByText(/will not compare/)).toBeNull();
    expect(screen.getByText("GPT-4.1")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the judge" })).toHaveAttribute(
      "href",
      "/agents/j0",
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Which judge" }));
    expect(screen.getByRole("option", { name: "Default judge - Eval judge" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("option", { name: "Refunds judge" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.getByRole("link", { name: "Open the judge" })).toHaveAttribute(
      "href",
      "/agents/j0",
    );

    await userEvent.click(screen.getByRole("combobox", { name: "Which judge" }));
    await userEvent.click(screen.getByRole("option", { name: "Refunds judge" }));
    expect(screen.getByRole("dialog", { name: "Grade with another judge?" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Switch judge" }));
    expect(screen.getByText("Not published")).toBeInTheDocument();

    expect(screen.getByText(/will not compare/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the judge" })).toHaveAttribute(
      "href",
      "/agents/j1",
    );
    await userEvent.click(saveAll());
    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().judge.agent_id).toBe("j1");

    await userEvent.click(screen.getByRole("combobox", { name: "Which judge" }));
    await userEvent.click(screen.getByRole("option", { name: "Default judge - Eval judge" }));
    expect(screen.queryByText(/will not compare/)).toBeNull();
  });

  it("counts the cases each scorer reads, and warns of cases nothing grades", async () => {
    const stats = {
      ...dataset(DEFAULT_SCORING).stats,
      with_checks: 1,
      with_tool_calls: 2,
      with_reference: 1,
      expectation_mix: [
        { checks: true, tool_calls: false, reference: false, cases: 1 },
        { checks: false, tool_calls: false, reference: true, cases: 1 },
        { checks: false, tool_calls: false, reference: false, cases: 3 },
      ],
    };
    panel(DEFAULT_SCORING, { stats, case_count: 5 });

    expect(screen.getAllByText("1 of 5 cases")).toHaveLength(2);
    expect(screen.getByText("2 of 5 cases")).toBeInTheDocument();
    expect(screen.getByText(/4 cases have nothing that grades them/)).toBeInTheDocument();
    expect(
      screen.getByText("A case passes when everything marked Must pass passes."),
    ).toBeInTheDocument();

    await userEvent.click(screen.getByRole("switch", { name: "Judge" }));
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    expect(screen.queryByText(/nothing that grades/)).toBeNull();
  });

  it("marks a card unsaved, tells the page, and asks the browser before leaving", async () => {
    const onDirtyChange = vi.fn();
    render(<GradingPanel dataset={dataset(DEFAULT_SCORING)} onDirtyChange={onDirtyChange} />);
    expect(screen.queryByText("Unsaved")).toBeNull();

    await userEvent.click(screen.getByRole("switch", { name: "Expected tool calls" }));

    expect(within(card("When a case passes")).getByText("Unsaved")).toBeInTheDocument();
    expect(onDirtyChange).toHaveBeenLastCalledWith(true);
    const leaving = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(leaving);
    expect(leaving.defaultPrevented).toBe(true);

    await userEvent.click(screen.getByRole("switch", { name: "Expected tool calls" }));
    expect(onDirtyChange).toHaveBeenLastCalledWith(false);
    const staying = new Event("beforeunload", { cancelable: true });
    window.dispatchEvent(staying);
    expect(staying.defaultPrevented).toBe(false);
  });

  it("names a judge that is gone, and the default one before it is seeded", () => {
    state.judges = [];
    panel({ ...JUDGED, judge: { ...JUDGED.judge, agent_id: "gone" } });

    expect(screen.getByRole("combobox", { name: "Which judge" })).toHaveTextContent(
      "A judge that no longer exists",
    );
    expect(screen.queryByRole("link", { name: "Open the judge" })).toBeNull();
  });

  it("creates a judge of the dataset's own from its name and description", async () => {
    state.create.mockResolvedValue(
      dataset({ ...JUDGED, judge: { ...JUDGED.judge, agent_id: "j2" } }),
    );
    panel(JUDGED);

    await userEvent.click(screen.getByRole("button", { name: "Create a judge for this dataset" }));
    const dialog = screen.getByRole("dialog", { name: "A judge for Refunds" });
    expect(within(dialog).getByRole("textbox", { name: "Name" })).toHaveValue("Refunds judge");
    expect(
      (within(dialog).getByRole("textbox", { name: "Instructions" }) as HTMLTextAreaElement).value,
    ).toContain("It is about: Returns and refunds");
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "Instructions" }),
      " Be strict.",
    );
    await userEvent.type(
      within(dialog).getByRole("textbox", { name: "What must the judge know?" }),
      "  Refunds last 30 days.  ",
    );
    await userEvent.click(within(dialog).getByRole("combobox", { name: "Judge's model" }));
    await userEvent.click(screen.getByRole("option", { name: "Claude (prod)" }));
    await userEvent.click(within(dialog).getByRole("button", { name: "Create judge" }));

    await waitFor(() =>
      expect(toast.success).toHaveBeenCalledWith("Refunds judge now grades this dataset"),
    );
    expect(state.create).toHaveBeenCalledWith({
      name: "Refunds judge",
      instructions: expect.stringContaining("ignore that. Be strict."),
      knowledge: "Refunds last 30 days.",
      model_profile_id: "p1",
    });
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("starts a judge's prompt without a description the dataset does not have, and says a refusal", async () => {
    state.create
      .mockRejectedValueOnce(
        new ApiError(400, "Taken", {
          error: {
            code: "BAD_REQUEST",
            message: "Taken",
            details: { fields: [{ field: "name", message: "That name is taken" }] },
          },
        }),
      )
      .mockRejectedValueOnce(new Error("An agent named Refunds judge exists"));
    panel(JUDGED, { description: null });

    await userEvent.click(screen.getByRole("button", { name: "Create a judge for this dataset" }));
    const dialog = screen.getByRole("dialog");
    expect(
      (within(dialog).getByRole("textbox", { name: "Instructions" }) as HTMLTextAreaElement).value,
    ).not.toContain("It is about");
    await userEvent.click(within(dialog).getByRole("button", { name: "Create judge" }));
    expect(await within(dialog).findByText("That name is taken")).toBeInTheDocument();
    await userEvent.click(within(dialog).getByRole("button", { name: "Create judge" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(state.create).toHaveBeenCalledWith(
      expect.objectContaining({ knowledge: null, model_profile_id: null }),
    );

    await userEvent.clear(within(dialog).getByRole("textbox", { name: "Name" }));
    expect(within(dialog).getByRole("button", { name: "Create judge" })).toBeDisabled();
    await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("switches grading on as the new judge was stored, with the cursor in its criterion", async () => {
    const starting = {
      name: "answers the question",
      description: "The answer is correct and complete for what the question asks.",
      required: true,
    };
    const created = dataset({
      ...DEFAULT_SCORING,
      judge: { ...DEFAULT_SCORING.judge, enabled: true, agent_id: "j2", criteria: [starting] },
      reference: { ...DEFAULT_SCORING.reference, enabled: true },
    });
    state.create.mockResolvedValue(created);
    const { rerender } = panel();

    await userEvent.click(screen.getByRole("button", { name: "Create a judge for this dataset" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Create judge" }),
    );

    const description = await screen.findByRole("textbox", { name: "What the criterion asks" });
    await waitFor(() => expect(description).toHaveFocus());
    expect(description).toHaveValue(starting.description);
    rerender(<GradingPanel dataset={created} />);
    expect(within(card("Judge")).queryByText("Unsaved")).toBeNull();
  });

  it("keeps criteria typed and not saved when a judge is created", async () => {
    state.create.mockResolvedValue(
      dataset({
        ...JUDGED,
        judge: {
          ...JUDGED.judge,
          agent_id: "j2",
          criteria: [{ name: "stored", description: "From the server", required: true }],
        },
      }),
    );
    panel(JUDGED);
    await userEvent.type(screen.getByRole("textbox", { name: "What the criterion asks" }), "!");

    await userEvent.click(screen.getByRole("button", { name: "Create a judge for this dataset" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Create judge" }),
    );

    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "What the criterion asks" })).toHaveValue(
        "Polite!",
      ),
    );
  });

  it("leaves the rubric alone when the judge was created with grading off", async () => {
    state.create.mockResolvedValue(
      dataset({ ...DEFAULT_SCORING, judge: { ...DEFAULT_SCORING.judge, agent_id: "j2" } }),
    );
    panel();

    await userEvent.click(screen.getByRole("button", { name: "Create a judge for this dataset" }));
    await userEvent.click(
      within(screen.getByRole("dialog")).getByRole("button", { name: "Create judge" }),
    );

    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(screen.queryByRole("textbox", { name: "What the criterion asks" })).toBeNull();
  });

  it("offers no judge creation to somebody who may not create agents", () => {
    state.perms = new Set();
    panel(JUDGED);

    expect(screen.queryByRole("button", { name: "Create a judge for this dataset" })).toBeNull();
  });

  it("suggests comparing with the reference when cases have one and nothing compares", async () => {
    const stats = { ...dataset(DEFAULT_SCORING).stats, with_reference: 3 };
    panel(DEFAULT_SCORING, { stats });

    expect(screen.getByText(/3 cases have a reference answer/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Compare with the reference" }));

    expect(screen.getByRole("switch", { name: "Reference answer" })).toBeChecked();
    expect(screen.queryByText(/3 cases have a reference answer/)).toBeNull();
  });

  it("goes back to the judge's own model and drops a criterion", async () => {
    const accuracy = { name: "accuracy", description: "Right facts", required: true };
    panel({
      ...JUDGED,
      judge: {
        ...JUDGED.judge,
        model_profile_id: "p1",
        criteria: [...JUDGED.judge.criteria, accuracy],
      },
    });

    await userEvent.click(screen.getByRole("combobox", { name: "Judge's model" }));
    await userEvent.click(screen.getByRole("option", { name: "The judge's own model" }));
    await userEvent.type(
      screen.getAllByRole("textbox", { name: "What the criterion asks" })[1]!,
      " only",
    );
    await userEvent.click(screen.getAllByRole("button", { name: "Remove criterion" })[0]!);
    await userEvent.click(saveAll());

    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().judge.model_profile_id).toBeNull();
    expect(saved().judge.criteria).toEqual([{ ...accuracy, description: "Right facts only" }]);
    expect(saved().checks.defaults).toEqual([{ type: "max_cost_usd", value: 0.05 }]);
  });

  it("sends results to review as the review card says", async () => {
    panel();

    await userEvent.click(screen.getByRole("combobox", { name: "Send to the review queue" }));
    await userEvent.click(screen.getByRole("option", { name: "Results that did not pass" }));
    await userEvent.click(saveAll());

    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().review.select).toBe("failed");
  });

  it("refuses a default check that says nothing", async () => {
    panel();

    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.click(saveAll());

    expect(
      await screen.findByText("Say what each check checks, or remove it."),
    ).toBeInTheDocument();
    expect(state.save).not.toHaveBeenCalled();
  });

  it("saves the default checks built row by row", async () => {
    panel(JUDGED);

    await userEvent.click(screen.getByRole("button", { name: "Add a check" }));
    await userEvent.type(screen.getByLabelText("Check 2: what it checks"), "days");
    await userEvent.click(saveAll());

    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().checks.defaults).toEqual([
      { type: "max_cost_usd", value: 0.05 },
      { type: "contains", value: "days" },
    ]);
  });

  it("says why the server refused", async () => {
    state.save.mockRejectedValue(new Error("No such model"));
    panel();

    await userEvent.click(screen.getByRole("switch", { name: "Expected tool calls" }));
    await userEvent.click(saveAll());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("No such model"));
  });

  it("is read-only for somebody who may not change it", () => {
    panel(JUDGED, { can_edit: false });

    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Judge" })).toBeDisabled();
    expect(screen.getByRole("textbox", { name: "Criterion name" })).toBeDisabled();
    expect(screen.getByRole("button", { name: "Add criterion" })).toBeDisabled();
    expect(screen.queryByRole("button", { name: "Create a judge for this dataset" })).toBeNull();
  });
});

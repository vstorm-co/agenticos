import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { DEFAULT_SCORING } from "@/lib/scoring";
import type { DatasetScoring } from "@/types/scoring";
import { ScoringPanel } from "./scoring-panel";

const state = vi.hoisted(() => ({ save: vi.fn() }));
vi.mock("@/hooks/use-scoring", () => ({
  useSetScoring: () => ({ mutateAsync: state.save, isPending: false }),
}));
vi.mock("@/hooks/use-model-providers", () => ({
  useModelProviders: () => ({ profiles: [{ id: "p1", label: "Claude (prod)" }] }),
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

function panel(scoring: DatasetScoring = DEFAULT_SCORING, canEdit = true) {
  return render(<ScoringPanel datasetId="d1" scoring={scoring} canEdit={canEdit} />);
}

const saved = () => state.save.mock.calls.at(-1)?.[0] as DatasetScoring;

beforeEach(() => {
  vi.clearAllMocks();
  state.save.mockResolvedValue({});
});

/**
 * How a dataset is scored, saved as a whole. The rule-based scorers are on by
 * default; the judge and the reference comparison are a decision somebody makes.
 */
describe("ScoringPanel", () => {
  it("saves the scorers as they were switched", async () => {
    panel();

    await userEvent.click(screen.getByRole("switch", { name: "Tool calls" }));
    await userEvent.click(screen.getByRole("switch", { name: "Checks: Required" }));
    await userEvent.click(screen.getByRole("switch", { name: "Reference answer" }));
    await userEvent.click(screen.getByRole("switch", { name: "Reference answer: Required" }));
    await userEvent.click(screen.getByRole("button", { name: "Save scoring" }));

    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("Scoring saved"));
    expect(saved().trajectory.enabled).toBe(false);
    expect(saved().checks).toEqual({ enabled: true, required: false, defaults: [] });
    expect(saved().reference).toEqual({ enabled: true, required: false });
  });

  it("holds the save shut while the configuration could score nothing", async () => {
    panel();

    await userEvent.click(screen.getByRole("switch", { name: "Checks" }));
    await userEvent.click(screen.getByRole("switch", { name: "Tool calls" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Turn on at least one scorer");
    expect(screen.getByRole("button", { name: "Save scoring" })).toBeDisabled();

    await userEvent.click(screen.getByRole("switch", { name: "Judge" }));
    expect(screen.getByRole("alert")).toHaveTextContent("Give the judge at least one criterion");
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("configures the judge: its model, its scale and its rubric", async () => {
    panel();

    await userEvent.click(screen.getByRole("switch", { name: "Judge" }));
    await userEvent.click(screen.getByRole("combobox", { name: "Judge's model" }));
    await userEvent.click(screen.getByRole("option", { name: "Claude (prod)" }));
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Top of the scale" }));
    await userEvent.type(screen.getByRole("spinbutton", { name: "Top of the scale" }), "7");
    await userEvent.clear(screen.getByRole("spinbutton", { name: "Passes at" }));
    await userEvent.type(screen.getByRole("spinbutton", { name: "Passes at" }), "6");
    await userEvent.click(screen.getByRole("button", { name: "Add criterion" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Criterion name" }), "correctness");
    await userEvent.type(screen.getByRole("textbox", { name: "What the criterion asks" }), "Right");
    await userEvent.click(screen.getByRole("switch", { name: "Required" }));
    await userEvent.click(screen.getByRole("button", { name: "Save scoring" }));

    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().judge).toEqual({
      enabled: true,
      model_profile_id: "p1",
      scale_max: 7,
      pass_at: 6,
      criteria: [{ name: "correctness", description: "Right", required: false }],
    });
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
    await userEvent.click(screen.getByRole("option", { name: "The judge agent's own model" }));
    await userEvent.click(screen.getAllByRole("button", { name: "Remove criterion" })[0]!);
    await userEvent.click(screen.getByRole("combobox", { name: "Send to the review queue" }));
    await userEvent.click(screen.getByRole("option", { name: "Results that did not pass" }));
    await userEvent.click(screen.getByRole("button", { name: "Save scoring" }));

    await waitFor(() => expect(state.save).toHaveBeenCalled());
    expect(saved().judge.model_profile_id).toBeNull();
    expect(saved().judge.criteria).toEqual([accuracy]);
    expect(saved().review.select).toBe("failed");
    expect(saved().checks.defaults).toEqual([{ type: "max_cost_usd", value: 0.05 }]);
  });

  it.each([["not json"], ['{"type": "contains"}']])(
    "refuses default checks that are not a JSON list: %s",
    async (written) => {
      panel();
      const box = screen.getByRole("textbox", { name: "Checks every case gets" });

      await userEvent.click(box);
      await userEvent.paste(written);
      await userEvent.click(screen.getByRole("button", { name: "Save scoring" }));

      expect(await screen.findByText("Write the checks as a JSON list")).toBeInTheDocument();
      expect(state.save).not.toHaveBeenCalled();
    },
  );

  it("says why the server refused", async () => {
    state.save.mockRejectedValue(new Error("No such model"));
    panel();

    await userEvent.click(screen.getByRole("button", { name: "Save scoring" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("No such model"));
  });

  it("is read-only for somebody who may not change it", () => {
    panel(JUDGED, false);

    expect(screen.queryByRole("button", { name: "Save scoring" })).toBeNull();
    expect(screen.getByRole("switch", { name: "Judge" })).toBeDisabled();
    const rubric = screen.getByRole("textbox", { name: "Criterion name" });
    expect(rubric).toBeDisabled();
    expect(within(document.body).getByRole("button", { name: "Add criterion" })).toBeDisabled();
  });
});

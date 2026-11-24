import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import type { BrowserTeaching } from "@/lib/browser-teaching-api";
import { TeachingReview, toSkillName } from "./teaching-review";
import { toParameterName } from "./teaching-step-row";

vi.mock("next-intl", () => ({
  useTranslations: () =>
    Object.assign((key: string) => key, { has: (key: string) => key !== "reasons.mystery" }),
}));

const ORIGIN = "https://portal.example.test";

const TEACHING: BrowserTeaching = {
  id: "t1",
  agent_id: "a1",
  run_id: "r1",
  title: "Download invoice",
  allowed_origins: [ORIGIN],
  status: "review",
  revision: 4,
  reason_code: null,
  events: [
    {
      sequence: 1,
      action: "input_parameter",
      origin: ORIGIN,
      target: { role: "textbox", fingerprint: "sha256:synthetic" },
      direction: null,
      human_step: false,
    },
    {
      sequence: 2,
      action: "click",
      origin: ORIGIN,
      target: { role: "button", fingerprint: "sha256:other" },
      direction: null,
      human_step: false,
    },
    {
      sequence: 3,
      action: "checkpoint",
      origin: ORIGIN,
      target: null,
      direction: null,
      human_step: true,
    },
  ],
  review: [{ sequence: 2, label: "Download", parameter: null }],
  parameters: [],
  proposal_name: null,
  proposal_id: null,
  expires_at: "2026-11-18T09:00:00Z",
};

function setup(teaching: BrowserTeaching = TEACHING) {
  const saved = { ...teaching, revision: 5 };
  const saveReview = vi.fn().mockResolvedValue(saved);
  const propose = vi.fn().mockResolvedValue(undefined);
  render(
    <TeachingReview
      teaching={teaching}
      isSaving={false}
      isProposing={false}
      saveReview={saveReview}
      propose={propose}
    />,
  );
  return { saveReview, propose, saved };
}

describe("reviewing a taught task", () => {
  it("lists structural steps only, never a fingerprint", () => {
    setup();

    expect(screen.getAllByTestId("teaching-step")).toHaveLength(3);
    expect(screen.getByText("actions.human")).toBeInTheDocument();
    expect(screen.queryByText(/sha256/)).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("parameter")).toHaveLength(1);
    expect(screen.getByDisplayValue("Download")).toBeInTheDocument();
  });

  it("saves the review, then proposes from the revision the save returned", async () => {
    const { saveReview, propose, saved } = setup();

    fireEvent.change(screen.getAllByLabelText("label")[0]!, {
      target: { value: "Invoice number" },
    });
    fireEvent.change(screen.getByLabelText("parameter"), { target: { value: "Invoice Number" } });
    fireEvent.click(screen.getByRole("button", { name: "propose" }));

    await waitFor(() => expect(propose).toHaveBeenCalledWith("download-invoice", saved));
    expect(saveReview).toHaveBeenCalledWith([
      { sequence: 1, label: "Invoice number", parameter: "invoice_number" },
      { sequence: 2, label: "Download", parameter: null },
    ]);
  });

  it("does not propose when the save was refused", async () => {
    const { saveReview, propose } = setup();
    saveReview.mockResolvedValue(undefined);

    fireEvent.click(screen.getByRole("button", { name: "propose" }));

    await waitFor(() => expect(saveReview).toHaveBeenCalled());
    expect(propose).not.toHaveBeenCalled();
  });

  it("saves a review on its own and drops a cleared label", () => {
    const { saveReview } = setup();

    fireEvent.change(screen.getByDisplayValue("Download"), { target: { value: "" } });
    fireEvent.click(screen.getByRole("button", { name: "saveReview" }));

    expect(saveReview).toHaveBeenCalledWith([]);
  });

  it("refuses to propose without a skill name", () => {
    setup();

    fireEvent.change(screen.getByLabelText("skillName"), { target: { value: "!!" } });

    expect(screen.getByRole("button", { name: "propose" })).toBeDisabled();
  });

  it("names the reason a change was refused", () => {
    setup({ ...TEACHING, reason_code: "budget_exceeded" });
    expect(screen.getByRole("alert")).toHaveTextContent("reasons.budget_exceeded");
  });

  it("falls back to a general reason for a code it does not know", () => {
    setup({ ...TEACHING, reason_code: "mystery" });
    expect(screen.getByRole("alert")).toHaveTextContent("reasons.other");
  });

  it("locks the steps while the proposal is being built", () => {
    setup({ ...TEACHING, status: "proposing" });

    expect(screen.getByRole("status")).toHaveTextContent("proposing");
    expect(screen.queryByRole("button", { name: "propose" })).not.toBeInTheDocument();
    expect(screen.getAllByLabelText("label")[0]).toBeDisabled();
  });

  it("points to the skill changes once proposed, and shows no steps", () => {
    setup({ ...TEACHING, status: "proposed", events: [], review: [], proposal_name: "x" });

    expect(screen.getByRole("link", { name: "openProposals" })).toHaveAttribute("href", "/skills");
    expect(screen.queryByTestId("teaching-step")).not.toBeInTheDocument();
  });
});

describe("names the server accepts", () => {
  it("turns a title into a skill name", () => {
    expect(toSkillName("Download invoice!")).toBe("download-invoice");
    expect(toSkillName("Download ", true)).toBe("download-");
  });

  it("turns typing into a parameter name, or nothing", () => {
    expect(toParameterName("Invoice Number")).toBe("invoice_number");
    expect(toParameterName("42 month")).toBe("month");
    expect(toParameterName("")).toBeNull();
  });
});

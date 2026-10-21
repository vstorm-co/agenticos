import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { CaseProposal } from "@/types/case-generation";
import { GenerationEstimate } from "./generation-estimate";
import { GenerationStatus } from "./generation-status";
import { ProposalRow } from "./proposal-row";

const PROPOSAL: CaseProposal = {
  id: "p1",
  generation_id: "g1",
  origin: "knowledge",
  input: "How long is the return window?",
  history: [],
  reference_answer: "Returns are accepted within 30 days.",
  counter_example: null,
  expected_tool_calls: [{ tool: "search_documents", args: {} }],
  order_mode: "any",
  checks: [],
  tags: ["knowledge"],
  note: "From handbook.md, page 3.",
  source_document_id: "doc",
  source_run_id: null,
  source_conversation_id: null,
  source_message_id: null,
  created_at: "2026-10-13T00:00:00Z",
};

const GENERATION = {
  id: "g1",
  agent_id: "a1",
  sources: ["knowledge" as const],
  requested_count: 20,
  status: "running" as const,
  error: null,
  run_id: null,
  proposed_count: 0,
  accepted_count: 0,
  dismissed_count: 0,
  created_at: "2026-10-13T00:00:00Z",
  finished_at: null,
};

describe("ProposalRow", () => {
  it("says what a draft came from and hands each decision to its caller", async () => {
    const onAccept = vi.fn();
    const onEdit = vi.fn();
    const onDismiss = vi.fn();
    render(
      <ProposalRow
        proposal={PROPOSAL}
        disabled={false}
        onAccept={onAccept}
        onEdit={onEdit}
        onDismiss={onDismiss}
      />,
    );
    for (const text of ["From knowledge", "Reference answer", "1 expected call", "knowledge"]) {
      expect(screen.getByText(text)).toBeInTheDocument();
    }
    expect(screen.getByText("From handbook.md, page 3.")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "Accept this proposed case" }));
    await userEvent.click(screen.getByRole("button", { name: "Edit proposed case" }));
    await userEvent.click(screen.getByRole("button", { name: "Dismiss this proposed case" }));
    expect([onAccept, onEdit, onDismiss].map((fn) => fn.mock.calls.length)).toEqual([1, 1, 1]);
  });

  it("shows no badge or note a bare draft lacks, and locks while deciding", () => {
    render(
      <ProposalRow
        proposal={{
          ...PROPOSAL,
          origin: "red_team",
          reference_answer: null,
          expected_tool_calls: [],
          tags: [],
          note: null,
        }}
        disabled
        onAccept={vi.fn()}
        onEdit={vi.fn()}
        onDismiss={vi.fn()}
      />,
    );
    expect(screen.getByText("Red team")).toBeInTheDocument();
    expect(screen.queryByText("Reference answer")).toBeNull();
    expect(screen.queryByText(/expected call/)).toBeNull();
    expect(screen.getByRole("button", { name: "Accept this proposed case" })).toBeDisabled();
  });
});

describe("GenerationStatus", () => {
  it("says nothing with no generation, or one that finished", () => {
    const { container, rerender } = render(<GenerationStatus generation={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<GenerationStatus generation={{ ...GENERATION, status: "ready" }} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says a generation is running", () => {
    render(<GenerationStatus generation={GENERATION} />);
    expect(screen.getByRole("status")).toHaveTextContent("Drafting 20 cases…");
  });

  it("says why a generation failed, with its run one click away", () => {
    const { rerender } = render(
      <GenerationStatus
        generation={{
          ...GENERATION,
          status: "failed",
          error: "AI assistance is off",
          run_id: "r1",
        }}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent("AI assistance is off");
    expect(screen.getByRole("link", { name: "Open the generator's run" })).toHaveAttribute(
      "href",
      "/runs?run=r1",
    );

    rerender(<GenerationStatus generation={{ ...GENERATION, status: "failed" }} />);
    expect(screen.getByRole("alert")).toHaveTextContent("The generation failed.");
    expect(screen.queryByRole("link")).toBeNull();
  });
});

describe("GenerationEstimate", () => {
  it("states the count, the estimated cost and what each source will draft from", () => {
    render(
      <GenerationEstimate
        estimate={{
          count: 20,
          sources: [
            { source: "knowledge", cases: 10, material: 30 },
            { source: "red_team", cases: 10, material: 0 },
          ],
          excluded_collections: 1,
          estimated_cost_usd: "0.15",
        }}
      />,
    );
    expect(screen.getByText("20 cases, estimated $0.15")).toBeInTheDocument();
    expect(screen.getByText("10 cases from 30 passages of its knowledge base")).toBeInTheDocument();
    expect(screen.getByText("10 red-team cases")).toBeInTheDocument();
    expect(screen.getByText(/1 knowledge base of this agent left out/)).toBeInTheDocument();
  });

  it("says when the cost cannot be estimated, and mentions no exclusion that did not happen", () => {
    render(
      <GenerationEstimate
        estimate={{
          count: 1,
          sources: [{ source: "agent", cases: 1, material: 2 }],
          excluded_collections: 0,
          estimated_cost_usd: null,
        }}
      />,
    );
    expect(screen.getByText(/cannot be estimated/)).toBeInTheDocument();
    expect(screen.queryByText(/left out/)).toBeNull();
  });
});

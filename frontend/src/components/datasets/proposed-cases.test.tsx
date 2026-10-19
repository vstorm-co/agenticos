import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { CaseGeneration, CaseProposal } from "@/types/case-generation";
import { ProposedCases } from "./proposed-cases";

const { generations, proposals } = vi.hoisted(() => ({
  generations: { current: [] as CaseGeneration[] },
  proposals: {
    current: {
      proposals: [] as CaseProposal[],
      total: 0,
      error: null as Error | null,
      isDeciding: false,
      refetch: vi.fn(),
      accept: { mutate: vi.fn(), mutateAsync: vi.fn() },
      dismiss: { mutate: vi.fn() },
    },
  },
}));
const asked = vi.fn();
vi.mock("@/hooks/use-agents", () => ({ useCapabilityCatalog: () => ({ capabilities: [] }) }));
vi.mock("@/hooks/use-case-generation", () => ({
  useCaseGenerations: () => ({ generations: generations.current }),
  useCaseProposals: (_id: string, options: unknown) => {
    asked(options);
    return proposals.current;
  },
}));

function proposal(id: string, input: string): CaseProposal {
  return {
    id,
    generation_id: "g1",
    origin: "agent",
    input,
    history: [],
    reference_answer: "An answer.",
    counter_example: null,
    expected_tool_calls: [],
    order_mode: "any",
    checks: [],
    tags: [],
    note: null,
    source_document_id: null,
    source_run_id: null,
    source_conversation_id: null,
    source_message_id: null,
    created_at: "2026-10-13T00:00:00Z",
  };
}

const RUNNING: CaseGeneration = {
  id: "g1",
  agent_id: "a1",
  sources: ["agent"],
  requested_count: 5,
  status: "running",
  error: null,
  run_id: null,
  proposed_count: 0,
  accepted_count: 0,
  dismissed_count: 0,
  created_at: "2026-10-13T00:00:00Z",
  finished_at: null,
};

beforeEach(() => {
  vi.clearAllMocks();
  generations.current = [];
  proposals.current = {
    ...proposals.current,
    proposals: [],
    total: 0,
    error: null,
  };
});

describe("ProposedCases", () => {
  it("draws nothing for a reader who may not decide", () => {
    proposals.current.total = 3;
    const { container } = render(<ProposedCases datasetId="d1" canEdit={false} />);
    expect(container).toBeEmptyDOMElement();
    expect(asked).toHaveBeenCalledWith(expect.objectContaining({ enabled: false }));
  });

  it("draws nothing when no draft waits and nothing is being drafted", () => {
    generations.current = [{ ...RUNNING, status: "ready" }];
    const { container } = render(<ProposedCases datasetId="d1" canEdit />);
    expect(container).toBeEmptyDOMElement();
  });

  it("says a generation is running before any draft has arrived", () => {
    generations.current = [RUNNING];
    render(<ProposedCases datasetId="d1" canEdit />);
    expect(screen.getByText("Nothing waiting")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Drafting 5 cases…");
    expect(screen.queryByRole("button", { name: "Accept all" })).toBeNull();
  });

  it("accepts, dismisses and edits single drafts, and the whole page at once", async () => {
    proposals.current.proposals = [proposal("p1", "First?"), proposal("p2", "Second?")];
    proposals.current.total = 2;
    proposals.current.accept.mutateAsync.mockResolvedValue({});
    render(<ProposedCases datasetId="d1" canEdit />);

    expect(screen.getByText("2 cases waiting for a decision")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Accept all" }));
    expect(proposals.current.accept.mutate).toHaveBeenCalledWith([{ id: "p1" }, { id: "p2" }]);
    await userEvent.click(screen.getByRole("button", { name: "Dismiss all" }));
    expect(proposals.current.dismiss.mutate).toHaveBeenCalledWith(["p1", "p2"]);

    const [accept] = screen.getAllByRole("button", { name: "Accept this proposed case" });
    await userEvent.click(accept!);
    expect(proposals.current.accept.mutate).toHaveBeenLastCalledWith([{ id: "p1" }]);
    const [, dismiss] = screen.getAllByRole("button", { name: "Dismiss this proposed case" });
    await userEvent.click(dismiss!);
    expect(proposals.current.dismiss.mutate).toHaveBeenLastCalledWith(["p2"]);

    const [edit] = screen.getAllByRole("button", { name: "Edit proposed case" });
    await userEvent.click(edit!);
    const input = await screen.findByDisplayValue("First?");
    await userEvent.clear(input);
    await userEvent.type(input, "Reworded?");
    await userEvent.click(screen.getByRole("button", { name: "Accept" }));
    await waitFor(() =>
      expect(proposals.current.accept.mutateAsync).toHaveBeenCalledWith([
        { id: "p1", content: expect.objectContaining({ input: "Reworded?" }) },
      ]),
    );
    await waitFor(() => expect(screen.queryByDisplayValue("Reworded?")).toBeNull());
  });

  it("closes the editor without deciding when it is cancelled", async () => {
    proposals.current.proposals = [proposal("p1", "First?")];
    proposals.current.total = 1;
    render(<ProposedCases datasetId="d1" canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Edit proposed case" }));
    await userEvent.click(await screen.findByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByDisplayValue("First?")).toBeNull());
    expect(proposals.current.accept.mutateAsync).not.toHaveBeenCalled();
  });

  it("pages when the drafts outnumber a page", async () => {
    proposals.current.proposals = [proposal("p1", "First?")];
    proposals.current.total = 120;
    render(<ProposedCases datasetId="d1" canEdit />);
    await userEvent.click(screen.getByRole("button", { name: /next/i }));
    expect(asked).toHaveBeenLastCalledWith(expect.objectContaining({ skip: 50 }));
  });

  it("says a failed read out loud and retries it", async () => {
    proposals.current.total = 1;
    proposals.current.error = new Error("boom");
    render(<ProposedCases datasetId="d1" canEdit />);
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(proposals.current.refetch).toHaveBeenCalled();
  });
});

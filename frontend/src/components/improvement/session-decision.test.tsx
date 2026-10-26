import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { hunk } from "@/test-utils/authoring";
import { SESSION } from "@/test-utils/improvement";
import type { Hunk } from "@/types/authoring";
import type { Improvement } from "@/types/improvement";
import { SessionDecision } from "./session-decision";

const state = vi.hoisted(() => ({
  changes: [] as Hunk[],
  changesLoading: false,
  changesError: null as Error | null,
  refetch: vi.fn(),
  topics: [] as { id: string; label: string; status: string }[],
  evidence: [] as { run_id: string; topic_id: string | null }[],
  suites: [] as { dataset_id: string; created_at: string }[],
}));
vi.mock("@/hooks/use-improvements", () => ({
  useImprovementChanges: () => ({
    changes: state.changes,
    isLoading: state.changesLoading,
    error: state.changesError,
    refetch: state.refetch,
  }),
  useImprovementEvidence: () => ({ evidence: { items: state.evidence } }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useKnowledgeGaps: () => ({ topics: state.topics }),
}));
vi.mock("@/hooks/use-eval-suites", () => ({
  useAgentEvalSuites: () => ({ suites: state.suites }),
}));
vi.mock("@/components/authoring/result-dialog", () => ({
  ChangePreview: ({ hunk }: { hunk: Hunk }) => <p>{`Change ${hunk.id}`}</p>,
}));

function ended(status: Improvement["status"], extra: Partial<Improvement> = {}): Improvement {
  return {
    ...SESSION,
    status,
    finished_at: "2026-10-24T14:00:00Z",
    timeline: [
      {
        action: "improvement.started",
        at: "2026-10-24T12:00:00Z",
        stage: null,
        status: null,
        reason: null,
        actor_name: "Ada",
      },
    ],
    ...extra,
  };
}

const decided = () => screen.getByRole("region", { name: "What was decided" });

beforeEach(() => {
  state.changes = [];
  state.changesLoading = false;
  state.changesError = null;
  state.topics = [];
  state.evidence = [];
  state.suites = [];
});

describe("SessionDecision", () => {
  it("says who published which version, and links to it", () => {
    render(
      <SessionDecision
        session={ended("published", {
          published_version: 4,
          timeline: [
            {
              action: "improvement.published",
              at: "2026-10-24T13:00:00Z",
              stage: null,
              status: "published",
              reason: null,
              actor_name: "Grace",
            },
          ],
        })}
      />,
    );
    expect(within(decided()).getByRole("status")).toHaveTextContent("Published as version 4");
    expect(decided()).toHaveTextContent(/By Grace/);
    expect(screen.getByRole("link", { name: "Open version 4" })).toHaveAttribute(
      "href",
      "/agents/a1?tab=history&from=4&to=4",
    );
  });

  it.each([
    ["accepted", /Kept as a draft\. Publish it from the agent/],
    ["rejected", /Discarded\. Nothing it suggested was kept/],
    ["cancelled", /Stopped before anything was decided/],
    ["stale", /changed while it ran/],
    ["published", /^Published$/],
  ] as const)("words a %s session's end, with no version to open", (status, words) => {
    render(<SessionDecision session={ended(status)} />);
    expect(within(decided()).getByRole("status")).toHaveTextContent(words);
    expect(screen.queryByRole("link", { name: /Open version/ })).not.toBeInTheDocument();
    // Nobody is named for an end the session reached by itself.
    expect(decided()).toHaveTextContent(/On /);
  });

  it("lists the changes it measured as they were decided", () => {
    state.changes = [
      hunk({ id: "h1", status: "accepted" }),
      hunk({ id: "h2", status: "dismissed" }),
      hunk({ id: "h3", status: "pending" }),
    ];
    render(<SessionDecision session={ended("accepted")} />);
    expect(screen.getByText("The 3 changes it measured")).toBeInTheDocument();
    expect(screen.getByText("Change h1")).toBeInTheDocument();
    for (const word of ["Kept", "Left out", "Not decided"]) {
      expect(screen.getByText(word)).toBeInTheDocument();
    }
  });

  it("says when no change was chosen, and waits for or offers to reread the changes", () => {
    const view = render(<SessionDecision session={ended("rejected")} />);
    expect(screen.getByText("No change was chosen in this improvement.")).toBeInTheDocument();
    state.changesLoading = true;
    view.rerender(<SessionDecision session={ended("rejected")} />);
    expect(screen.queryByText(/No change was chosen/)).not.toBeInTheDocument();
    state.changesLoading = false;
    state.changesError = new Error("read failed");
    view.rerender(<SessionDecision session={ended("rejected")} />);
    screen.getByRole("button", { name: "Try reading again" }).click();
    expect(state.refetch).toHaveBeenCalled();
  });

  it("says what became of each knowledge document the session drafted", () => {
    state.evidence = [
      { run_id: "r1", topic_id: "t1" },
      { run_id: "r2", topic_id: "t2" },
      { run_id: "r3", topic_id: "t3" },
      { run_id: "r4", topic_id: null },
    ];
    state.topics = [
      { id: "t1", label: "Returns", status: "covered" },
      { id: "t2", label: "Shipping", status: "open" },
      { id: "t3", label: "Warranty", status: "open" },
      { id: "t9", label: "Someone else's", status: "covered" },
    ];
    render(<SessionDecision session={ended("accepted", { deferred_topic_ids: ["t2"] })} />);
    const item = (label: string) => screen.getByText(label).closest("li")!;
    expect(item("Returns")).toHaveTextContent("Added to the knowledge base");
    expect(item("Shipping")).toHaveTextContent("Set aside");
    expect(item("Warranty")).toHaveTextContent("Not added");
    expect(screen.queryByText("Someone else's")).not.toBeInTheDocument();
  });

  it.each([
    [[{ dataset_id: "d1", created_at: "2026-10-24T13:30:00Z" }], /set up with this improvement/],
    [[{ dataset_id: "d1", created_at: "2026-09-01T00:00:00Z" }], /The agent's automatic check/],
    [[{ dataset_id: "other", created_at: "2026-10-24T13:30:00Z" }], /The agent's automatic check/],
    [[], /No automatic check runs/],
  ])("says whether an automatic check guards the agent", (suites, words) => {
    state.suites = suites;
    render(<SessionDecision session={ended("published")} />);
    expect(screen.getByText(words)).toBeInTheDocument();
  });
});

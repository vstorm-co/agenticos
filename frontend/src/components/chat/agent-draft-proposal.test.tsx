import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AgentDraftProposal, draftArgs } from "./agent-draft-proposal";
import { useOrgStore } from "@/stores";

const organizations = { data: [{ id: "o1", name: "Acme" }] };

vi.mock("@/hooks/use-organizations", () => ({
  useOrganizationList: () => organizations,
}));

beforeEach(() => {
  useOrgStore.setState({ activeOrgId: "o1" });
});

describe("the arguments of an agent draft (#1799)", () => {
  it("reads a draft and drops what is not one", () => {
    expect(draftArgs({ name: "Helpdesk", instructions: "Answer", capabilities: ["a", 3] })).toEqual(
      { name: "Helpdesk", description: null, instructions: "Answer", capabilities: ["a"] },
    );
    expect(draftArgs({ name: "Helpdesk" })).toBeNull();
    expect(draftArgs(undefined)).toBeNull();
    expect(
      draftArgs({ name: "H", instructions: "I", description: "D", capabilities: "x" }),
    ).toEqual({ name: "H", description: "D", instructions: "I", capabilities: [] });
  });
});

describe("an agent draft to approve (#1799)", () => {
  it("names where it is created, what it may do and what it starts from", () => {
    render(
      <AgentDraftProposal
        draft={{
          name: "Helpdesk",
          description: "Answers staff questions",
          instructions: "Answer from the handbook.",
          capabilities: ["web_research", "not_a_capability"],
        }}
      />,
    );

    expect(screen.getByText("Created in Acme")).toBeInTheDocument();
    expect(screen.getByText("Answers staff questions")).toBeInTheDocument();
    expect(screen.getByText("Web search")).toBeInTheDocument();
    expect(screen.getByText("not_a_capability")).toBeInTheDocument();
    expect(screen.getByText("Answer from the handbook.")).toBeInTheDocument();
    expect(screen.getByText(/Nothing is published/)).toBeInTheDocument();
  });

  it("says this organization before the list is known, and lists nothing it lacks", () => {
    useOrgStore.setState({ activeOrgId: "unknown" });

    render(
      <AgentDraftProposal
        draft={{ name: "Helpdesk", description: null, instructions: "Hi", capabilities: [] }}
      />,
    );

    expect(screen.getByText("Created in this organization")).toBeInTheDocument();
    expect(screen.queryByText("What it may do")).not.toBeInTheDocument();
  });
});

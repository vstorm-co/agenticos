import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import { CheckAnswersAiOff, CheckAnswersButton } from "./knowledge-gaps-check";

const state = vi.hoisted(() => ({
  granted: [] as string[],
  mutate: vi.fn(),
  checkedFor: [] as string[],
  org: null as { id: string; ai_assistance_enabled: boolean } | null,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => state.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-organizations", () => ({
  useOrganizations: () => ({ activeOrg: state.org }),
}));
vi.mock("@/hooks/use-knowledge-gaps", () => ({
  useClassifyKnowledgeGaps: (id: string) => {
    state.checkedFor.push(id);
    return { mutate: state.mutate, isPending: false };
  },
}));

beforeEach(() => {
  vi.clearAllMocks();
  state.granted = [Perm.agentsRun];
  state.checkedFor = [];
  state.org = { id: "org-1", ai_assistance_enabled: true };
});

describe("CheckAnswersButton", () => {
  it("offers to check the answers waiting and starts the check", async () => {
    render(<CheckAnswersButton knowledgeBaseId="kb1" unchecked={12} />);
    await userEvent.click(screen.getByRole("button", { name: "Check 12 answers" }));
    expect(state.checkedFor).toContain("kb1");
    expect(state.mutate).toHaveBeenCalled();
  });

  it.each([
    ["AI assistance is off", () => (state.org = { id: "org-1", ai_assistance_enabled: false })],
    ["the caller may not run the classifier", () => (state.granted = [])],
  ])("is not offered when %s", (_, arrange) => {
    arrange();
    render(<CheckAnswersButton knowledgeBaseId="kb1" unchecked={12} />);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("is not offered when no answer waits", () => {
    render(<CheckAnswersButton knowledgeBaseId="kb1" unchecked={0} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

describe("CheckAnswersAiOff", () => {
  beforeEach(() => {
    state.org = { id: "org-1", ai_assistance_enabled: false };
  });

  it("points somebody who may turn AI assistance on at the switch", () => {
    state.granted = [Perm.orgSettings];
    render(<CheckAnswersAiOff unchecked={3} />);
    expect(screen.getByText(/3 recent answers could also be read/)).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Enable AI assistance" })).toHaveAttribute(
      "href",
      "/orgs/org-1/members#org-ai-assistance",
    );
  });

  it("tells everybody else to ask an admin", () => {
    render(<CheckAnswersAiOff unchecked={1} />);
    expect(screen.getByText(/Ask an admin/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("says nothing while AI assistance is on, or when no answer waits", () => {
    const { container, unmount } = render(<CheckAnswersAiOff unchecked={0} />);
    expect(container).toBeEmptyDOMElement();
    unmount();
    state.org = { id: "org-1", ai_assistance_enabled: true };
    const second = render(<CheckAnswersAiOff unchecked={3} />);
    expect(second.container).toBeEmptyDOMElement();
    second.unmount();
    state.org = null;
    expect(render(<CheckAnswersAiOff unchecked={3} />).container).toBeEmptyDOMElement();
  });
});

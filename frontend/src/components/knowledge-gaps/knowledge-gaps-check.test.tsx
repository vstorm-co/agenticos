import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { Perm } from "@/types/permissions";
import { CheckAnswersButton } from "./knowledge-gaps-check";

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

  it.each([["the caller may not run the classifier", () => (state.granted = [])]])(
    "is not offered when %s",
    (_, arrange) => {
      arrange();
      render(<CheckAnswersButton knowledgeBaseId="kb1" unchecked={12} />);
      expect(screen.queryByRole("button")).toBeNull();
    },
  );

  it("is not offered when no answer waits", () => {
    render(<CheckAnswersButton knowledgeBaseId="kb1" unchecked={0} />);
    expect(screen.queryByRole("button")).toBeNull();
  });
});

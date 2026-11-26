import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ApiError } from "@/lib/api-error";
import { SkillDetails } from "./skill-details";

const state = vi.hoisted(() => ({
  metadataError: null as Error | null,
  forksError: null as Error | null,
  versionsError: null as Error | null,
  metadataRetry: vi.fn(),
  forksRetry: vi.fn(),
  versionsRetry: vi.fn(),
}));
vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks", () => ({
  useSkill: () => ({ skill: undefined, error: state.metadataError, refetch: state.metadataRetry }),
}));
vi.mock("@/hooks/use-organizations", () => ({ useOrganizationList: () => ({ data: [] }) }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => false }) }));
vi.mock("@/hooks/use-url-state", () => ({ useUrlState: () => [null, vi.fn()] }));
vi.mock("@/hooks/use-skill-versions", () => ({
  useSkillForks: () => ({
    forks: [],
    isLoading: false,
    error: state.forksError,
    refetch: state.forksRetry,
  }),
  useSkillVersions: () => ({
    versions: [],
    isLoading: false,
    error: state.versionsError,
    refetch: state.versionsRetry,
  }),
  useSkillAgents: () => ({ agents: undefined, error: null }),
}));

beforeEach(() => {
  state.metadataError = null;
  state.forksError = null;
  state.versionsError = null;
  vi.clearAllMocks();
});

it.each(["metadataError", "forksError", "versionsError"] as const)(
  "recovers a failed %s read without reloading the page",
  async (field) => {
    state[field] = new Error("Skill service unavailable");
    render(<SkillDetails id="s1" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Skill service unavailable");
    await userEvent.click(screen.getByRole("button", { name: "Retry" }));
    expect(state.metadataRetry).toHaveBeenCalledOnce();
    expect(state.forksRetry).toHaveBeenCalledOnce();
    expect(state.versionsRetry).toHaveBeenCalledOnce();
  },
);

it("keeps access refusal separate from retryable service failures", () => {
  state.metadataError = new ApiError(403, "Not allowed");
  render(<SkillDetails id="s1" />);
  expect(screen.queryByRole("button", { name: "Retry" })).toBeNull();
  expect(screen.getByRole("link", { name: "Back" })).toHaveAttribute("href", "/skills");
});

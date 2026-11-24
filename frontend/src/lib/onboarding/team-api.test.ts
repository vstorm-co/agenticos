import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type {
  CreateOnboardingTeamRequest,
  OnboardingProfileRequest,
  OnboardingTeamProposal,
  OnboardingTeamResult,
} from "@/types/onboarding";
import { createOnboardingTeam, fetchTeamProposal } from "./team-api";

vi.mock("@/lib/api-client", () => ({ apiClient: { post: vi.fn() } }));
const profile: OnboardingProfileRequest = {
  role: "Engineering lead",
  industry: "Software",
  team_size: "2-10",
  goals: ["Review releases"],
  details: "Keep approvals with the project owner",
  tools: ["github"],
};
const proposal: OnboardingTeamProposal = {
  industry: profile.industry,
  role: profile.role,
  rationale: "Review the release before publishing",
  lead: {
    name: "Release lead",
    role: "Lead",
    description: "Coordinate the review",
    starters: ["Review this release"],
  },
  specialists: [
    {
      key: "reviewer",
      name: "Reviewer",
      role: "Reviewer",
      description: "Check proposed changes",
      capabilities: ["code_review"],
      recommended: true,
    },
  ],
};
const request: CreateOnboardingTeamRequest = {
  lead: proposal.lead,
  specialists: proposal.specialists,
  project_name: "Release review",
};
const created: OnboardingTeamResult = {
  lead_agent_id: "lead-1",
  lead_agent_slug: "release-lead",
  lead_conversation_id: "room-1",
  created_agents: [
    {
      id: "lead-1",
      name: "Release lead",
      slug: "release-lead",
      role: "Lead",
      is_lead: true,
      status: "draft",
    },
  ],
  message: "Team created",
};
beforeEach(() => vi.resetAllMocks());

describe("onboarding team API", () => {
  it("submits the complete profile and returns the server's proposed team unchanged", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(proposal);
    await expect(fetchTeamProposal(profile)).resolves.toBe(proposal);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/onboarding/team-proposal", profile);
  });

  it("propagates a proposal refusal without returning a fabricated team", async () => {
    const failure = new ApiError(403, "Cannot propose a team in this organization");
    vi.mocked(apiClient.post).mockRejectedValueOnce(failure);
    await expect(fetchTeamProposal(profile)).rejects.toBe(failure);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/onboarding/team-proposal", profile);
  });

  it("creates the chosen team and returns its actual agent and conversation identities", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce(created);
    await expect(createOnboardingTeam(request)).resolves.toBe(created);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/onboarding/team", request);
  });

  it("preserves an uncertain creation failure without issuing another create", async () => {
    const failure = new TypeError("The acknowledgement was lost");
    vi.mocked(apiClient.post).mockRejectedValueOnce(failure);
    await expect(createOnboardingTeam(request)).rejects.toBe(failure);
    expect(apiClient.post).toHaveBeenCalledExactlyOnceWith("/onboarding/team", request);
  });
});

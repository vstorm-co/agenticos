import { apiClient } from "@/lib/api-client";
import type {
  CreateOnboardingTeamRequest,
  OnboardingProfileRequest,
  OnboardingTeamProposal,
  OnboardingTeamResult,
} from "@/types/onboarding";

export async function fetchTeamProposal(
  profile: OnboardingProfileRequest,
): Promise<OnboardingTeamProposal> {
  return apiClient.post<OnboardingTeamProposal>("/onboarding/team-proposal", profile);
}

export async function createOnboardingTeam(
  request: CreateOnboardingTeamRequest,
): Promise<OnboardingTeamResult> {
  return apiClient.post<OnboardingTeamResult>("/onboarding/team", request);
}

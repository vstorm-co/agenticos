export interface OnboardingProfileRequest {
  role: string;
  industry: string;
  team_size: string;
  goals: string[];
  details?: string | null;
  tools?: string[];
}

export interface ProposedSpecialist {
  key?: string | null;
  name: string;
  role: string;
  description: string;
  capabilities: string[];
  recommended: boolean;
}

export interface ProposedLead {
  name: string;
  role: string;
  description: string;
  starters: string[];
}

export interface OnboardingTeamProposal {
  industry: string;
  role: string;
  rationale: string;
  lead: ProposedLead;
  specialists: ProposedSpecialist[];
}

export interface CreateOnboardingTeamRequest {
  lead: ProposedLead;
  specialists: ProposedSpecialist[];
  project_name?: string | null;
}

export interface CreatedAgentInfo {
  id: string;
  name: string;
  slug: string;
  role: string;
  is_lead: boolean;
  status: "published" | "draft";
}

export interface OnboardingTeamResult {
  lead_agent_id: string;
  lead_agent_slug: string;
  lead_conversation_id?: string | null;
  created_agents: CreatedAgentInfo[];
  message: string;
}

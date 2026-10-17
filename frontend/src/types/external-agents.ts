/** A remote agent registered by the URL of its A2A agent card (#2092). */
export interface ExternalAgentSkill {
  id: string;
  name: string;
  description: string;
}

export interface ExternalAgent {
  id: string;
  /** The handle a delegating agent calls it by. */
  slug: string;
  name: string;
  description: string;
  card_url: string;
  endpoint_url: string;
  /** The vault API key sent as its bearer token, when it asks for one. */
  secret_id: string | null;
  skills: ExternalAgentSkill[];
  created_at: string;
  updated_at: string | null;
}

export interface ExternalAgentList {
  items: ExternalAgent[];
}

export interface ExternalAgentCreate {
  card_url: string;
  slug?: string | null;
  secret_id?: string | null;
}

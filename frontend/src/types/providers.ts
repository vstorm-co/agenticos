/**
 * Types for the provider catalog and an organization's model profiles.
 *
 * `provider` is a plain string, not a union. The platform ships two dozen
 * providers and gains one whenever Pydantic AI does; a union here would be a
 * second list to keep in step with `GET /providers/catalog`, and the two would
 * disagree. The catalog is the list - and it is also what a credential form
 * branches on, because it says which shape of credential each provider takes.
 */

import type { SecretKind } from "./secrets";

/** One selectable provider, as the credential form reads it. */
export interface ProviderInfo {
  id: string;
  name: string;
  /** Which shape of credential this provider needs - see `/secrets/kinds`. */
  secret_kind: SecretKind;
  /** False means a custom endpoint would be ignored, so storing one is refused. */
  supports_base_url: boolean;
  /**
   * Whether this provider can run with no credential at all. True only for
   * self-hosted servers, and a keyless credential still has to carry a
   * `base_url` - otherwise it is aimed at the vendor's public API with nothing
   * to authenticate it.
   */
  keyless: boolean;
}

export interface ProviderCatalog {
  items: ProviderInfo[];
  total: number;
}

/** One named model a provider key is behind. */
export interface ModelProfile {
  id: string;
  label: string;
  provider: string;
  model: string;
  /**
   * The vault secret this model is keyed by, and the only key it has.
   *
   * Null on a self-hosted profile, which authenticates against nothing, and on
   * one whose key was deleted - the foreign key is `ON DELETE SET NULL`. Those
   * two look the same here and are told apart by `base_url`, which is what the
   * resolver does.
   */
  secret_id: string | null;
  /**
   * Where requests go, when it is not the provider's public API: a gateway, a
   * LiteLLM proxy, a model server on this network. Absent for most profiles.
   *
   * On the profile rather than the key because a key says what authenticates and
   * this says where it is sent - the same key can front a staging proxy and a
   * production one as two profiles.
   */
  base_url?: string | null;
  params: Record<string, unknown>;
  allow_byo: boolean;
  fallback_profile_ids: string[];
  created_at?: string;
}

export interface ModelProfileList {
  items: ModelProfile[];
  total: number;
}

/** One file a skill carries, as a listing names it - without the body. */
export interface SkillResourceSummary {
  id: string;
  name: string;
  description: string | null;
  size_bytes: number;
}

/** One file with its body, fetched when somebody opens it. */
export interface SkillResource extends SkillResourceSummary {
  content: string;
}

export interface Skill {
  id: string;
  name: string;
  description: string;
  content: string;
  /** A grouping label for people ("marketing", "devops"); null is uncategorized. */
  category: string | null;
  enabled: boolean;
  version: number;
  visibility: string;
  owner_user_id: string | null;
  /**
   * The files beyond the body, without their contents. Optional because a
   * backend older than the resources endpoint omits it entirely, and a client
   * that assumed the field would crash rather than degrade.
   */
  resources?: SkillResourceSummary[];
}

/** One skill this deployment ships with, as the gallery shows it. */
export interface LibrarySkill {
  key: string;
  name: string;
  description: string;
  category: string | null;
  content: string;
  resources: SkillResourceSummary[];
  /** Whether this organization already has a skill by that name. */
  installed: boolean;
}

export interface LibrarySkillList {
  items: LibrarySkill[];
  total: number;
}

export interface SkillSummary {
  id: string;
  name: string;
  description: string;
  category: string | null;
  enabled: boolean;
  /** How many files the skill carries beyond its body. */
  file_count: number;
  /** Whether this skill shipped with the deployment, matched by library name. */
  built_in: boolean;
}

export interface SkillList {
  items: SkillSummary[];
  total: number;
  /**
   * Every distinct category in the organization - the filter's choices,
   * unaffected by the search and paging that shaped `items`.
   */
  categories: string[];
  /** The deployment's predefined shelf names - picker suggestions, never a constraint. */
  suggested_categories: string[];
}

/**
 * Types for the organization's vault.
 *
 * The one thing nothing here can express is a value coming back out. There is
 * no endpoint that returns a plaintext, by design, so a stored secret is a
 * name, a kind and four characters - and a `SecretPayload` only ever travels
 * outward.
 */

import type { JsonSchema } from "./agents";

/** Which shape a secret has. Mirrors `SecretKind` in `app/core/secret_kinds.py`. */
export type SecretKind =
  | "none"
  | "api_key"
  | "azure_openai"
  | "aws_credentials"
  | "gcp_service_account"
  | "github_oauth_app";

/**
 * Every kind a person can save. `none` is not one of them: it says "there is no
 * credential", which is an answer a provider credential may give and a secret
 * may not - `POST /secrets` refuses it with a 422.
 */
export type StorableSecretKind = Exclude<SecretKind, "none">;

/**
 * A secret a capability declares it cannot work without. Mirrors
 * `SecretRequirement` in `app/core/secret_kinds.py`.
 *
 * A capability names a *kind*, never an instance: the code says "I need an API
 * key", the binding says which one. `none` is not among the kinds it may name -
 * the server refuses that declaration outright - which is what lets a picker
 * compare this against a stored secret's own kind directly.
 */
export interface SecretRequirement {
  kind: StorableSecretKind;
  /** What the capability's author said it is for, shown beside the picker. */
  description: string;
  /**
   * When the key is actually needed, or null for "always".
   *
   * A capability can offer several providers where only some authenticate - web
   * search takes a key for Tavily and none for DuckDuckGo. The rule is data
   * rather than a predicate precisely so this side can evaluate the same one
   * the server does: asking for a key the server will not demand is as wrong as
   * not asking for one it will.
   */
  required_when: SecretCondition | null;
}

/** "This config field is one of these values." Mirrors `SecretCondition`. */
export interface SecretCondition {
  field: string;
  equals: string[];
}

/** Whether a binding's current configuration needs the declared secret. */
export function secretIsRequired(
  requirement: SecretRequirement,
  config: Record<string, unknown>,
): boolean {
  const condition = requirement.required_when;
  if (!condition) return true;
  return condition.equals.includes(String(config[condition.field]));
}

/**
 * A secret on its way to the server: the kind, plus whatever that kind declares.
 *
 * The fields are deliberately not enumerated. `GET /secrets/kinds` serves the
 * JSON Schema each form is generated from, and a second copy of those five
 * shapes written out here is a copy that drifts - which is the reason the
 * endpoint exists at all. What the shapes have in common is the discriminator,
 * and that is what this type states.
 */
export interface SecretPayload {
  kind: SecretKind;
  [field: string]: unknown;
}

/** One kind as the forms render it, with the schema they are generated from. */
export interface SecretKindInfo {
  kind: StorableSecretKind;
  name: string;
  description: string;
  json_schema: JsonSchema;
}

export interface SecretKindList {
  items: SecretKindInfo[];
  total: number;
}

/** A stored secret, identified by everything except what it holds. */
/** One place a secret is bound, so "can I delete this" has an answer. */
export interface SecretUsage {
  kind: "agent";
  id: string;
  name: string;
}

/** One thing a secret can be for. Mirrors `app/core/secret_purposes.py`. */
export interface SecretPurpose {
  id: string;
  label: string;
  category: "model_provider" | "search" | "observability" | "other";
  /** The shape of credential this service takes - the form follows from it. */
  kind: StorableSecretKind;
  help_url: string | null;
  description: string;
}

export interface SecretPurposeList {
  items: SecretPurpose[];
  total: number;
}

/** How far a secret reaches. The same scale every shared resource here uses. */
export type SecretVisibility = "private" | "team" | "org";

export interface Secret {
  id: string;
  name: string;
  description: string | null;
  kind: StorableSecretKind;
  /**
   * Four characters of the field that *identifies* the credential rather than
   * the one that authenticates it, where the two differ - an AWS access key id
   * is not confidential and its secret access key is.
   */
  hint: string;
  /** What the key is for - a provider id, a service id, or `custom`. */
  purpose?: string;
  visibility?: SecretVisibility;
  owner_user_id?: string | null;
  /** Whose key it is, when it belongs to one person rather than the team. */
  owner_email?: string | null;
  /**
   * Who stored it, by id - the seed the fallback avatar's colour comes from, so
   * the author wears the same hue here as in member and run lists. Still set once
   * they have left the organization, when `created_by_email` is null.
   */
  created_by_user_id?: string | null;
  /** Who stored it; null once that account has left the organization. */
  created_by_email?: string | null;
  created_by_avatar_url?: string | null;
  /**
   * How many people hold an explicit grant on this key.
   *
   * Read next to `visibility`, never instead of it: an org-wide key reaches
   * everybody whatever this says, and a private one shared with four people is
   * a different thing from a private one shared with nobody.
   */
  shared_with?: number;
  /**
   * What breaks if this is deleted. Empty is the interesting case: a key
   * nothing binds is one nobody can account for.
   */
  used_by?: SecretUsage[];
  created_at?: string;
  updated_at?: string;
}

export interface SecretList {
  items: Secret[];
  total: number;
}

/** What `POST /secrets` takes. */
export interface NewSecret {
  name: string;
  description?: string | null;
  value: SecretPayload;
  /** What it is for. Drives which providers the model picker can offer. */
  purpose?: string;
  visibility?: SecretVisibility;
}

/**
 * What `PATCH /secrets/{id}` takes.
 *
 * Rotation keeps the id, which is the point: every agent binding names a secret
 * by id, so replacing the value leaves all of them working. The kind cannot
 * change - the server answers 400 - so it is not offered.
 */
export interface SecretEdit {
  id: string;
  name?: string;
  description?: string | null;
  value?: SecretPayload;
}

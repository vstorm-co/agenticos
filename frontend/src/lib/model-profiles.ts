import { subscriptionModelId } from "@/lib/subscription-model-id";
import { ApiError } from "@/lib/api-error";
import type { ModelProfile } from "@/types/providers";

/** A technical description, unless the profile's label already includes both parts. */
export function modelDetail(
  profile: Pick<ModelProfile, "label" | "provider" | "model">,
): string | null {
  const name = profile.label.toLowerCase();
  const saysIt =
    name.includes(profile.provider.toLowerCase()) && name.includes(profile.model.toLowerCase());
  return saysIt ? null : `${profile.provider} · ${profile.model}`;
}

/** The catalog sometimes prefixes model names with the model maker. */
export function catalogModelName(id: string, name?: string): string {
  const model = subscriptionModelId(id);
  const display = name ? subscriptionModelId(name.trim()) : undefined;
  if (!display) return model;
  const separator = model.includes("/") ? display.indexOf(": ") : -1;
  return separator < 0 ? display : display.slice(separator + 2).trim() || model;
}

/** Match the picker’s catalog spelling while respecting a saved custom label. */
export function modelName(
  profile: Pick<ModelProfile, "label" | "provider" | "model">,
  catalogName?: string,
): string {
  if (
    profile.provider === "subscription_accounts" &&
    (profile.label.endsWith(` · ${profile.model}`) ||
      / · account-[a-f0-9]{24}\//.test(profile.label))
  ) {
    const model = subscriptionModelId(profile.model);
    return catalogModelName(model, catalogName ?? model.split("/").at(-1));
  }
  if (profile.label && profile.label !== profile.model && modelDetail(profile) !== null)
    return profile.label;
  return catalogModelName(profile.model, catalogName ?? profile.model.split("/").at(-1));
}

/**
 * Whether an agent - or a conversation - can run on this profile (#2487).
 *
 * A profile can name a text-to-speech, transcription, image or embedding model;
 * the server says so in `chat_capable`. Absent is true, the server's own rule: a
 * model nothing classifies is never hidden.
 */
export function runsAgents(profile: Pick<ModelProfile, "chat_capable">): boolean {
  return profile.chat_capable !== false;
}

/**
 * Whether the profile has something to authenticate with (#2478).
 *
 * False when its key was deleted from the vault or never set, on a provider that
 * needs one - the server says so in `missing_key`, by the rule the run resolver
 * applies. A self-hosted profile with an endpoint and no key is true. Absent is
 * true, like `chat_capable`: an older server says nothing either way.
 */
export function hasKey(profile: Pick<ModelProfile, "missing_key">): boolean {
  return profile.missing_key !== true;
}

/**
 * Whether an agent - or a conversation - can be pointed at this profile now.
 *
 * A chat model with a key: the two refusals publish makes about a profile
 * itself. Pickers offer only these; a profile failing either stays visible where
 * it is already chosen, or where models are managed, marked and not selectable.
 */
export function usableForAgents(
  profile: Pick<ModelProfile, "chat_capable" | "missing_key">,
): boolean {
  return runsAgents(profile) && hasKey(profile);
}

/** The agents a refused delete named, how many are archived, and how many more the caller cannot see. */
export interface ModelInUse {
  names: string[];
  /** Of `names`: an archived agent cannot publish, so it is deleted or restored first. */
  archived: number;
  hidden: number;
}

/**
 * Whether a delete was refused because agents still run on the model (#2478).
 *
 * The server answers `409 IN_USE` with `details.agents` - the ones the caller
 * may see, by name - and `details.hidden_agents` for the rest. `null` for any
 * other failure, which the caller words the ordinary way.
 */
export function modelInUse(error: unknown): ModelInUse | null {
  if (!(error instanceof ApiError) || error.code !== "IN_USE") return null;
  const agents = (Array.isArray(error.details?.agents) ? error.details.agents : []).filter(
    (agent: unknown): agent is { name: string; archived?: unknown } =>
      typeof agent === "object" &&
      agent !== null &&
      "name" in agent &&
      typeof agent.name === "string",
  );
  const hidden = error.details?.hidden_agents;
  return {
    names: agents.map((agent) => agent.name),
    archived: agents.filter((agent) => agent.archived === true).length,
    hidden: typeof hidden === "number" ? hidden : 0,
  };
}

/**
 * A run's model as a list column reads it: the model alone, without the vendor
 * or the routing prefix a derived label carries.
 *
 * `OpenRouter · openai/gpt-5.5` printed in a narrow column ends as
 * `OpenRouter · openai/gpt…`, cutting off the one part that differs between
 * rows - the vendor's mark beside it already says whose model it is. A label
 * somebody typed (`fast gpt-5`) has neither separator and is kept whole.
 */
export function modelShortName(label: string): string {
  const model = label.split(" · ").at(-1) ?? label;
  return model.split("/").at(-1) || model;
}

/**
 * The providers whose model list is read at an endpoint the caller names.
 *
 * A hosted provider's list is read at its own API. These have it read at the
 * endpoint the profile carries instead - a regional gateway, an OpenRouter
 * region, a server the organization runs - so the request carries that
 * endpoint, and the key when the endpoint wants one.
 *
 * Whether a provider *takes* an endpoint is the API's to say, and the console
 * reads it from there rather than keeping a list of its own. Whether its
 * *listing* can be read at one is a fact about the provider's shape, and this
 * is where that fact lives.
 */
export const LISTED_AT_ENDPOINT: readonly string[] = [
  "openrouter",
  "stav",
  "otari",
  "openai_compatible",
  "anthropic_compatible",
];

/**
 * The providers whose listing at a named endpoint is authenticated with the
 * profile's own key.
 *
 * OpenRouter's list is public. The others are servers somebody answers for,
 * and the key stored for them is what authenticates the listing - the same key
 * the runs send to that same endpoint.
 */
export const LISTED_WITH_KEY: readonly string[] = [
  "stav",
  "otari",
  "openai_compatible",
  "anthropic_compatible",
];

/**
 * The providers that have no model list of their own, so there is nothing to
 * ask until an endpoint is named.
 *
 * Otari and the two custom endpoints exist only at an address somebody types.
 * Asking one without it returns an empty list, which the form would then read
 * as "this provider publishes no list" - a sentence about a provider the
 * organization has not pointed anywhere yet.
 */
export const LISTED_ONLY_AT_ENDPOINT: readonly string[] = [
  "otari",
  "openai_compatible",
  "anthropic_compatible",
];

import { ApiError } from "@/lib/api-error";
import type { ModelProfile } from "@/types/providers";

/**
 * The technical line under a profile's name, or nothing when the name is it.
 *
 * A label is *derived* from the provider and the model unless somebody typed
 * their own - both forms that create one submit `${provider.label} · ${model}` -
 * so printing `provider · model` after it read `OpenRouter · openai/gpt-5.5
 * openrouter · openai/gpt-5.5`. Three places did it: the Builder's current-model
 * strip, every row of its saved-model list, and the chat's active-model line.
 *
 * Both halves are checked rather than only the model, because a label carrying
 * one of them (`fast gpt-5`, on Azure) still leaves the other worth saying.
 *
 * `null` rather than an empty string, so a caller renders no element at all
 * instead of an empty line under the name.
 */
export function modelDetail(
  profile: Pick<ModelProfile, "label" | "provider" | "model">,
): string | null {
  const name = profile.label.toLowerCase();
  const saysIt =
    name.includes(profile.provider.toLowerCase()) && name.includes(profile.model.toLowerCase());
  return saysIt ? null : `${profile.provider} · ${profile.model}`;
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

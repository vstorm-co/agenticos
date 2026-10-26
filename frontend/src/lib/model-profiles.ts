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

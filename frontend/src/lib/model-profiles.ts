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

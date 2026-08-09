import { describe, expect, it } from "vitest";

import { modelHint, modelIdIsWellFormed, modelPlaceholder, placeholderWords } from "./add-model";
import en from "../../../messages/en.json";

/**
 * Resolve an absolute catalog key, or `undefined` when it is not there.
 *
 * Deliberately *not* falling back to the key. It used to, and that is why nothing
 * caught `pickProviderFirst` being unresolvable: a missing key came back as the
 * key, and an assertion about a sentence containing "openai/gpt-5" passed anyway.
 * A resolver that cannot fail cannot be asked whether the copy exists.
 */
function resolve(key: string): string | undefined {
  return key
    .split(".")
    .reduce<unknown>(
      (node, part) =>
        typeof node === "object" && node !== null
          ? (node as Record<string, unknown>)[part]
          : undefined,
      en,
    ) as string | undefined;
}

/** The English catalog: these helpers answer with a key, and this is its sentence. */
const words = (key: string): string => resolve(key) ?? key;

/**
 * The one model id this form can know is wrong before sending it.
 *
 * OpenRouter routes to other people's models, so its ids carry the origin -
 * `openai/gpt-5`, never `gpt-5` - and the backend refuses a bare one. That
 * refusal used to arrive as an unhandled rejection, which Next.js renders as a
 * full-screen error overlay: a filled-in form replaced by a stack trace,
 * because of a missing slash.
 */
describe("modelIdIsWellFormed", () => {
  it("refuses a bare id for OpenRouter", () => {
    expect(modelIdIsWellFormed("openrouter", "gpt-5")).toBe(false);
  });

  it("accepts a namespaced one", () => {
    expect(modelIdIsWellFormed("openrouter", "openai/gpt-5")).toBe(true);
  });

  it("does not impose the rule on providers that do not have it", () => {
    // Everybody else names their own models, and a slash would be the mistake.
    expect(modelIdIsWellFormed("openai", "gpt-5")).toBe(true);
    expect(modelIdIsWellFormed("anthropic", "claude-opus-5")).toBe(true);
  });
});

describe("modelHint", () => {
  it("shows OpenRouter's shape before anybody guesses wrong", () => {
    expect(words(modelHint("openrouter"))).toContain("openai/gpt-5");
  });

  it("says nothing specific for a provider with no such rule", () => {
    expect(modelHint("openai")).not.toContain("/");
    expect(modelHint(undefined)).not.toContain("/");
  });
});

/**
 * The keys these helpers answer with have to exist, and be absolute.
 *
 * `AddModel` and the chat's model picker share them and read *different*
 * namespaces - `agents` and `chat.modelPicker` - so a relative key resolved for
 * one caller and threw `MISSING_MESSAGE` for the other. What reached the user was
 * a console error over the picker, on a component whose own suite was green: the
 * key was only ever resolved through a helper that fell back to it.
 */
describe("the catalog keys these helpers hand back", () => {
  const providers = [undefined, "openrouter", "openai", "anthropic"];

  it.each(providers)("resolves the placeholder for %s", (providerId) => {
    const placeholder = modelPlaceholder(providerId);
    if (typeof placeholder === "string") {
      // An example id rather than English - `openai/gpt-5` is what the provider
      // calls the model, and asking the catalog for it is the bug this shape
      // avoids.
      expect(placeholder).not.toBe("");
      return;
    }
    expect(placeholder.key).toContain(".");
    expect(resolve(placeholder.key)).toBeTypeOf("string");
  });

  it.each(providers)("resolves the hint for %s", (providerId) => {
    const key = modelHint(providerId);

    expect(key).toContain(".");
    expect(resolve(key)).toBeTypeOf("string");
  });

  it("reads a key through whichever namespace the caller is in, because it names one", () => {
    // The regression, stated as the thing that broke: a root translator resolves
    // it, and that is the only translator either caller can share.
    const placeholder = modelPlaceholder(undefined);

    expect(placeholderWords(placeholder, words)).toBe("Pick a provider first");
  });
});

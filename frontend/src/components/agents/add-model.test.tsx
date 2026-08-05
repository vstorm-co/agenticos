import { describe, expect, it } from "vitest";

import { modelHint, modelIdIsWellFormed } from "./add-model";
import en from "../../../messages/en.json";

/** The English catalog: these helpers answer with a key, and this is its sentence. */
const words = (key: string): string => (en.agents as Record<string, string>)[key] ?? key;

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

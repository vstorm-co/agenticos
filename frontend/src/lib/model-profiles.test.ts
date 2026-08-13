import { describe, expect, it } from "vitest";

import { modelDetail } from "./model-profiles";

function profile(overrides: Partial<Parameters<typeof modelDetail>[0]> = {}) {
  return { label: "the cheap one", provider: "openai", model: "gpt-4.1", ...overrides };
}

describe("modelDetail", () => {
  it("says nothing where the name already is the provider and the model", () => {
    // The defect: both forms that create a profile derive its label this way, so
    // the strip read `OpenRouter · openai/gpt-5.5 openrouter · openai/gpt-5.5`.
    expect(
      modelDetail(
        profile({
          label: "OpenRouter · openai/gpt-5.5",
          provider: "openrouter",
          model: "openai/gpt-5.5",
        }),
      ),
    ).toBeNull();
  });

  it("names both where somebody chose the name themselves", () => {
    expect(modelDetail(profile())).toBe("openai · gpt-4.1");
  });

  it("still names the provider where only the model is in the name", () => {
    // Why both halves are checked. `fast gpt-5` on Azure says which model and
    // nothing about whose endpoint answers it.
    expect(modelDetail(profile({ label: "fast gpt-5", provider: "azure", model: "gpt-5" }))).toBe(
      "azure · gpt-5",
    );
  });

  it("still names the model where only the provider is in the name", () => {
    expect(modelDetail(profile({ label: "openai default" }))).toBe("openai · gpt-4.1");
  });
});

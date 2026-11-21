import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { ProviderIcon } from "@/components/vault/provider-icon";
import { ModelIcon } from "./model-icon";

describe("model maker icons", () => {
  it.each([
    ["claude-opus-4-6-thinking", "anthropic"],
    ["claude-sonnet-4-6", "anthropic"],
    ["gemini-3.8-flash-high", "google"],
    ["gpt-oss-120b-medium", "openai"],
    ["gpt-6-sol", "openai"],
    ["qwen3", "alibaba"],
    ["kimi-k2", "moonshotai"],
    ["grok-4", "xai"],
    ["anthropic/claude-sonnet-5", "anthropic"],
    ["openai/gpt-6", "openai"],
    ["z-ai/glm-5", "zai"],
    ["moonshotai/kimi-k2", "moonshotai"],
    ["deepseek/deepseek-chat", "deepseek"],
    ["qwen/qwen3", "alibaba"],
    ["meta-llama/llama-4", "meta"],
    ["microsoft/phi-4", "microsoft"],
    ["amazon/nova-lite", "bedrock"],
    ["anthropic:claude-sonnet-5", "anthropic"],
  ])("shows the maker of %s instead of the routing provider", (model, maker) => {
    const actual = render(<ModelIcon model={model} provider="openrouter" />);
    const reference = render(<ProviderIcon provider={maker} brand={maker} />);
    expect(actual.container.querySelector("svg")?.innerHTML).toBe(
      reference.container.querySelector("svg")?.innerHTML,
    );
    expect(actual.container.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
  });

  it("uses a direct provider for unprefixed model ids", () => {
    const actual = render(<ModelIcon model="claude-sonnet-5" provider="anthropic" />);
    expect(actual.container.querySelector("svg")).toHaveAttribute("fill", "#D97757");
  });

  it.each([
    ["unknown/mystery", "anthropic"],
    ["custom-model", "openrouter"],
    ["", undefined],
  ])("does not attribute an unknown model %s to its host", (model, provider) => {
    const { container } = render(<ModelIcon model={model} provider={provider} />);
    expect(container.querySelector("svg")).toHaveClass("lucide-cpu");
  });
});

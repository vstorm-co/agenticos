import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

import { MARKED_PROVIDERS, ProviderIcon } from "./provider-icon";

// One custom mark shipped, under a name lobehub does not know. Only the hook
// is replaced; `CustomMark` stays real.
vi.mock("@/components/icons/custom-icons", async () => {
  const actual = await vi.importActual<typeof import("@/components/icons/custom-icons")>(
    "@/components/icons/custom-icons",
  );
  return { ...actual, useCustomIcons: () => new Set(["acme"]) };
});

describe("ProviderIcon", () => {
  it("draws a deployment-supplied mark for a provider the compiled set does not know", () => {
    const { container } = render(<ProviderIcon provider="acme" />);
    const mark = container.firstElementChild as HTMLElement;

    expect(mark.style.maskImage).toBe('url("/api/catalog/icons/acme")');
    expect(mark.style.backgroundColor).toBe("currentcolor");
  });

  it("draws every mark monochrome, never in brand colours", () => {
    // The console's brand marks are `currentColor` everywhere - MCP catalog,
    // connectors, sign-in. One provider re-imported as `Color` would put a
    // four-colour Gemini in a column of ink and read as a different UI.
    for (const provider of MARKED_PROVIDERS) {
      const { container } = render(<ProviderIcon provider={provider} />);
      expect(container.querySelector('svg [fill^="#"]'), provider).toBeNull();
      expect(
        container.querySelector("svg linearGradient, svg radialGradient"),
        provider,
      ).toBeNull();
    }
  });

  it("renders the brand mark for a provider the set carries", () => {
    const { container } = render(<ProviderIcon provider="openai" />);
    expect(container.querySelector("svg")).not.toBeNull();
  });

  it("renders a monogram for one it does not, rather than nothing", () => {
    // Heroku, OVHcloud and a LiteLLM proxy have no mark anywhere, and a
    // deployment gains a provider whenever Pydantic AI does - so this is the
    // normal case. A blank gap would read as a logo that failed to load.
    const { container } = render(<ProviderIcon provider="litellm" />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toBe("l");
  });

  it("stays out of the accessibility tree either way", () => {
    // Every row prints the provider beside the icon. A mark that named itself
    // would make a screen reader say it twice - and lobehub's SVGs carry a
    // <title>, so this has to be switched off rather than merely omitted.
    const { container: known } = render(<ProviderIcon provider="anthropic" />);
    const { container: unknown } = render(<ProviderIcon provider="ovhcloud" />);

    expect(known.firstElementChild).toHaveAttribute("aria-hidden");
    expect(unknown.firstElementChild).toHaveAttribute("aria-hidden");
  });
});

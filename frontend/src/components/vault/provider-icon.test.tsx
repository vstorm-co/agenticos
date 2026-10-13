import { describe, expect, it, vi } from "vitest";
import { render } from "@testing-library/react";

import { MARKED_PROVIDERS, ProviderIcon } from "./provider-icon";

// One custom mark shipped, under a name the glyph set does not carry. Only the
// hook is replaced; `CustomMark` stays real.
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

  it("draws every mark in one colour - its brand's, or the text colour", () => {
    // A mark is one shape in one fill: the brand's own colour where it reads on
    // both themes, the text colour for a black or white brand. Never a
    // multi-colour import - a four-colour Gemini beside one-colour marks reads
    // as a different UI.
    for (const provider of MARKED_PROVIDERS) {
      const { container } = render(<ProviderIcon provider={provider} />);
      const fill = container.querySelector("svg")?.getAttribute("fill") ?? "";
      expect(fill === "currentColor" || /^#[0-9A-F]{6}$/.test(fill), provider).toBe(true);
      expect(container.querySelector('svg [fill^="#"]'), provider).toBeNull();
      expect(
        container.querySelector("svg linearGradient, svg radialGradient"),
        provider,
      ).toBeNull();
    }
  });

  it("colours a brand that reads on both themes, and leaves a black one to the text", () => {
    const anthropic = render(<ProviderIcon provider="anthropic" />);
    expect(anthropic.container.querySelector("svg")).toHaveAttribute("fill", "#D97757");
    const openai = render(<ProviderIcon provider="openai" />);
    expect(openai.container.querySelector("svg")).toHaveAttribute("fill", "currentColor");
  });

  it("renders a brand mark for every provider the set carries", () => {
    // A provider whose mark went missing still gets a row, a name and a
    // monogram - which reads as "this one has no logo" rather than as a defect.
    for (const provider of MARKED_PROVIDERS) {
      const { container } = render(<ProviderIcon provider={provider} />);
      expect(container.querySelector("svg path"), provider).not.toBeNull();
    }
  });

  it("renders a monogram for one it does not, rather than nothing", () => {
    // A deployment gains a provider whenever Pydantic AI does, so one with no
    // mark is the normal case. A blank gap would read as a logo that failed to
    // load.
    const { container } = render(<ProviderIcon provider="newcomer" />);
    expect(container.querySelector("svg")).toBeNull();
    expect(container.textContent).toBe("n");
  });

  it("draws every provider the vault offers with a mark, not an initial", () => {
    for (const provider of ["xai", "cohere", "huggingface", "heroku", "ovhcloud", "litellm"]) {
      const { container, unmount } = render(<ProviderIcon provider={provider} />);
      expect(container.querySelector("svg")).not.toBeNull();
      unmount();
    }
  });

  it("stays out of the accessibility tree either way", () => {
    // Every row prints the provider beside the icon. A mark that named itself
    // would make a screen reader say it twice - which is why the generator
    // drops each source SVG's <title> rather than carrying it through.
    const { container: known } = render(<ProviderIcon provider="anthropic" />);
    const { container: unknown } = render(<ProviderIcon provider="ovhcloud" />);

    expect(known.firstElementChild).toHaveAttribute("aria-hidden");
    expect(unknown.firstElementChild).toHaveAttribute("aria-hidden");
  });
});

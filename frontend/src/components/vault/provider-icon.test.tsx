import { describe, expect, it } from "vitest";
import { render } from "@testing-library/react";

import { ProviderIcon } from "./provider-icon";

describe("ProviderIcon", () => {
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

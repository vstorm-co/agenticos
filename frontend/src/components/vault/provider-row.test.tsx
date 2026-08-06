import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Check } from "lucide-react";
import { describe, expect, it } from "vitest";

import { ProviderRow } from "./provider-row";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui";

/** The brand mark actually drawn, by the name lobehub titles its SVG with. */
function markIn(element: HTMLElement): string | null {
  return element.querySelector("svg > title")?.textContent ?? null;
}

describe("ProviderRow", () => {
  it("draws the brand mark for the id it is given", () => {
    const { container } = render(<ProviderRow provider="openrouter" name="Embeddings key" />);

    expect(markIn(container)).toBe("OpenRouter");
    expect(screen.getByText("Embeddings key")).toBeInTheDocument();
  });

  it("falls back to a monogram rather than a gap for an id with no mark", () => {
    // A deployment gains a provider whenever Pydantic AI does, and a key can be
    // for a service nobody has a logo for - so this is the normal case.
    const { container } = render(<ProviderRow provider="custom" name="Acme webhook" />);

    expect(container.querySelector("svg")).toBeNull();
    expect(screen.getByText("c")).toBeInTheDocument();
  });

  it("masks a key's hint the way the vault listing does", () => {
    render(<ProviderRow provider="openai" name="OpenAI prod" hint="3123" />);

    expect(screen.getByText("····3123")).toBeInTheDocument();
  });

  it("draws no hint at all where there is no key to identify", () => {
    // A provider row is a provider, not a credential; four dots with nothing
    // after them would read as a key whose tail failed to load.
    render(<ProviderRow provider="openai" name="OpenAI" />);

    expect(screen.queryByText(/····/)).toBeNull();
  });
});

/**
 * Why the tick is `SelectItem`'s to draw and not this row's.
 *
 * Radix mirrors an item's `ItemText` children into `SelectValue`: the closed
 * trigger renders whatever the selected item rendered. That is the whole reason
 * a mark in the row reaches the trigger for nothing - and the reason anything
 * meaningful only *against the other options* must stay out of it.
 */
describe("what a select trigger inherits from the row", () => {
  function pickerWith(trailing: React.ReactNode) {
    return render(
      <Select defaultValue="openrouter">
        <SelectTrigger aria-label="Provider">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          <SelectItem value="openrouter" trailing={trailing}>
            <ProviderRow provider="openrouter" name="OpenRouter" />
          </SelectItem>
        </SelectContent>
      </Select>,
    );
  }

  it("draws the selected row's mark in the closed trigger", () => {
    pickerWith(null);

    expect(markIn(screen.getByLabelText("Provider"))).toBe("OpenRouter");
  });

  it("needs `textValue`, because the mark's own title is part of the item's text", async () => {
    // Radix takes an item's type-to-search key from its `textContent` unless
    // `textValue` says otherwise, and lobehub titles its SVGs - so a row for
    // `text-embedding-3-large` answered to `openroutertext-embedding-3-large`
    // and typing `t` found nothing. Every picker that draws a mark passes it.
    render(
      <Select>
        <SelectTrigger aria-label="Model">
          <SelectValue placeholder="Pick one" />
        </SelectTrigger>
        <SelectContent>
          {/* First, so that "the search did nothing" and "the search found the
              second one" are two different outcomes rather than one. */}
          <SelectItem value="ada" textValue="ada-002">
            <ProviderRow provider="openrouter" name="ada-002" />
          </SelectItem>
          <SelectItem value="large" textValue="text-embedding-3-large">
            <ProviderRow provider="openrouter" name="text-embedding-3-large" />
          </SelectItem>
        </SelectContent>
      </Select>,
    );

    await userEvent.click(screen.getByLabelText("Model"));
    await userEvent.keyboard("t");

    expect(screen.getByRole("option", { name: /text-embedding-3-large/ })).toHaveAttribute(
      "data-highlighted",
    );
  });

  it("leaves a trailing badge in the list instead of repeating it in the trigger", async () => {
    pickerWith(<Check data-testid="keyed" className="ml-auto h-3.5 w-3.5" />);

    expect(screen.queryByTestId("keyed")).toBeNull();

    await userEvent.click(screen.getByLabelText("Provider"));
    expect(screen.getByRole("option", { name: "OpenRouter" })).toContainElement(
      screen.getByTestId("keyed"),
    );
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { InlineSecret } from "./inline-secret";

/**
 * What the button that opens the inline vault form is called.
 *
 * One page can render two of these - Create knowledge base offers an embedding
 * key and a model-provider key four inches apart - so "Add a key" for every
 * caller was two writes a screen reader could not tell apart. The label carries
 * the caller's name for the key, and this pins the two properties that has to
 * have: it names the key, and it does not inflect a name the caller already
 * finished.
 */

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ create: { mutate: vi.fn(), isPending: false } }),
}));

function mount(suggestedName: string) {
  render(
    <InlineSecret
      kind="api_key"
      purpose="openai"
      suggestedName={suggestedName}
      onCreated={vi.fn()}
    />,
  );
}

describe("the inline vault form's button", () => {
  it("names the key it would store", () => {
    mount("OpenAI");

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
  });

  it("does not repeat a word the caller's name already carries", () => {
    // `connection-dialog.tsx` suggests "Daytona API key" and the observability
    // card suggests "Logfire write token" - names that finish the noun
    // themselves. A label built by inflection reads "Add Daytona API key key",
    // which is why this one appends.
    mount("Daytona API key");

    expect(screen.getByRole("button", { name: "Add a key: Daytona API key" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /key key/ })).toBeNull();
  });
});

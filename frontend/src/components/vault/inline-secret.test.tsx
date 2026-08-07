import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { InlineSecret } from "./inline-secret";
import { Perm } from "@/types/permissions";
import type { Permission } from "@/types/permissions";

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

const held: { permissions: Permission[] } = { permissions: [] };
/** The write itself. Hoisted so a test can assert it was never sent. */
const storeKey = vi.hoisted(() => vi.fn());

vi.mock("@/hooks", () => ({
  useSecrets: () => ({ create: { mutate: storeKey, isPending: false } }),
  usePermissions: () => ({
    can: (permission: Permission) => held.permissions.includes(permission),
  }),
}));

beforeEach(() => {
  vi.clearAllMocks();
  held.permissions = [Perm.secretsEdit];
});

function mount(suggestedName: string, disabled = false) {
  return render(
    <InlineSecret
      kind="api_key"
      purpose="openai"
      suggestedName={suggestedName}
      onCreated={vi.fn()}
      disabled={disabled}
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

describe("who is offered the form at all", () => {
  /**
   * The write is `POST /secrets`, which is `Perm.SECRETS_EDIT` and nothing else -
   * the same permission whichever page rendered this. So the check lives here
   * rather than at seven call sites, six of which had forgotten it (#361), and a
   * caller who cannot make the write is told so instead of finding out from a
   * 403 after pasting a key in.
   */

  it("offers it to a caller holding secrets:edit", () => {
    mount("OpenAI");

    expect(screen.getByRole("button", { name: "Add a key: OpenAI" })).toBeInTheDocument();
    expect(screen.queryByText(/permission you do not hold/)).toBeNull();
  });

  it("offers no form, and says why, without it", () => {
    held.permissions = [];
    mount("OpenAI");

    expect(screen.queryByRole("button", { name: "Add a key: OpenAI" })).toBeNull();
    // Paired with the sentence deliberately: rendering nothing at all would
    // satisfy the `toBeNull` above and leave the picker beside it a blank gap
    // with no account of itself, which is the state this component exists to
    // remove.
    expect(screen.getByText(/permission you do not hold/)).toBeInTheDocument();
  });

  it("offers no way to the Vault page either, which refuses the same write", () => {
    // The link is unconditional for a caller who may write: it is where the
    // shapes this form cannot store are stored. For one who may not, it is a
    // second door onto the same refusal.
    held.permissions = [];
    mount("OpenAI");

    expect(screen.queryByRole("link", { name: /Open the Vault/ })).toBeNull();
  });
});

describe("a surface that has gone read-only under an open form", () => {
  /**
   * `disabled` is what a caller passes when its own form may no longer be
   * written to - a dialog mid-save (`ingestion-dialog.tsx` passes `isSaving`,
   * `create-kb-dialog.tsx` passes `isSubmitting`), a panel somebody may only
   * read. It gated the button that *opens* this form and nothing else, so a
   * form already open kept an enabled Save and stored an organization-wide
   * secret out from under the surface that had just said no. Same shape as the
   * permission gate above: the check belongs on the write, not on the way in.
   */

  it("does not store a key once the caller has disabled the form", async () => {
    const { rerender } = mount("OpenAI");
    await userEvent.click(screen.getByRole("button", { name: "Add a key: OpenAI" }));
    await userEvent.type(screen.getByLabelText("Key"), "sk-live-1234");

    rerender(
      <InlineSecret
        kind="api_key"
        purpose="openai"
        suggestedName="OpenAI"
        onCreated={vi.fn()}
        disabled
      />,
    );

    const save = screen.getByRole("button", { name: "Save key" });
    expect(save).toBeDisabled();
    await userEvent.click(save);
    expect(storeKey).not.toHaveBeenCalled();
  });

  it("still stores it when nothing has said otherwise", async () => {
    mount("OpenAI");
    await userEvent.click(screen.getByRole("button", { name: "Add a key: OpenAI" }));
    await userEvent.type(screen.getByLabelText("Key"), "sk-live-1234");
    await userEvent.click(screen.getByRole("button", { name: "Save key" }));

    expect(storeKey).toHaveBeenCalledWith(
      { name: "OpenAI", value: { kind: "api_key", api_key: "sk-live-1234" }, purpose: "openai" },
      expect.anything(),
    );
  });
});

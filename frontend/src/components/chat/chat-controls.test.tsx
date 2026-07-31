import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { ChatControls } from "./chat-controls";

vi.mock("@/hooks", () => ({
  useModelProviders: () => ({
    profiles: [],
    createProfile: { mutateAsync: vi.fn(), isPending: false },
  }),
  useProviderModels: () => ({ models: [], source: "curated", isLoading: false }),
  useSecretPurposes: () => ({ purposes: [], isLoading: false }),
  useSecrets: () => ({ secrets: [] }),
}));
vi.mock("@/stores", () => ({
  useConversationStore: (pick: (state: unknown) => unknown) =>
    pick({ currentConversationId: null }),
}));

describe("the chat controls trigger", () => {
  it("is reachable by the /settings slash command", () => {
    // The command's only handle on this popover is a DOM query for the data
    // attribute (see ChatContainer's slashContext.openSettings). If the
    // attribute drops off the trigger, /settings silently does nothing.
    render(<ChatControls />);

    const trigger = screen.getByRole("button", { name: "Chat controls" });
    expect(document.querySelector("[data-chat-settings-trigger]")).toBe(trigger);
  });
});

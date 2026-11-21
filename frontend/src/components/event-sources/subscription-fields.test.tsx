import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { SubscriptionFields } from "./subscription-fields";
vi.mock("@/hooks/use-portals", () => ({
  usePortalCatalog: () => ({
    error: null,
    portals: [
      {
        event_source: "github",
        presets: [
          {
            key: "comments",
            label: "Issue comments",
            description: "Comments that mention the agent",
            event_config: { event: "issue_comment", actions: ["created"], authors: "members" },
          },
        ],
      },
    ],
  }),
}));
describe("source subscription presets", () => {
  it("reuses existing provider event filters without connecting or registering a provider hook", async () => {
    const onChange = vi.fn();
    render(<SubscriptionFields provider="github" config={{}} onChange={onChange} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Events for this routine" }));
    await userEvent.click(screen.getByRole("option", { name: "Issue comments" }));
    expect(onChange).toHaveBeenCalledWith({
      event: "issue_comment",
      actions: ["created"],
      authors: "members",
    });
  });
});

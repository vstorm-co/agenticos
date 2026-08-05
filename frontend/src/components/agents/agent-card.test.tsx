import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useTranslations } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import { AgentCard, accessSummary, type AgentCardActions } from "./agent-card";
import type { Agent } from "@/types/agents";

/**
 * `accessSummary` answers with words, so it takes the translator the component holds.
 * The suite's `next-intl` stands on the real catalog, which is what makes asserting
 * on words here the same thing as asserting on what a reader sees.
 */
function useWords(subject: Agent): string {
  return accessSummary(subject, useTranslations("agents")).label;
}

function agent(overrides: Partial<Agent>): Agent {
  return {
    id: "a1",
    slug: "support",
    name: "Support",
    description: null,
    status: "published",
    visibility: "private",
    owner_user_id: null,
    current_version_id: null,
    ...overrides,
  };
}

describe("accessSummary", () => {
  it("an org-visible agent reads as the organization's, whatever the grant count", () => {
    expect(useWords(agent({ visibility: "org", shared_user_count: 5 }))).toBe("Organization");
  });

  it("a team-visible agent reads as the team's", () => {
    expect(useWords(agent({ visibility: "team" }))).toBe("Team");
  });

  it("a private agent with grants says how many people were handed it", () => {
    expect(useWords(agent({ visibility: "private", shared_user_count: 3 }))).toBe("Shared with 3");
  });

  it("a private agent nobody was handed reads as private, including when the listing omits the count", () => {
    expect(useWords(agent({ visibility: "private", shared_user_count: 0 }))).toBe("Private");
    expect(useWords(agent({ visibility: "private" }))).toBe("Private");
  });
});

function mount(overrides: Partial<Agent> = {}, { canEdit = true, busy = false } = {}) {
  const actions: AgentCardActions = {
    onDuplicate: vi.fn(),
    onArchive: vi.fn(),
    onRestore: vi.fn(),
    onDelete: vi.fn(),
  };
  render(<AgentCard agent={agent(overrides)} canEdit={canEdit} actions={actions} busy={busy} />);
  return actions;
}

/**
 * One agent in the gallery.
 *
 * The whole card is the link to the builder and the menu sits outside it: a
 * button nested inside an anchor navigates when somebody meant to open a menu,
 * and it is invalid to a screen reader besides. Everything below asserts through
 * the accessible names, which is the only way that stays true.
 */
describe("AgentCard", () => {
  it("opens the builder from anywhere on the card", () => {
    mount();

    expect(screen.getByRole("link", { name: "Open Support" })).toHaveAttribute(
      "href",
      "/agents/a1",
    );
  });

  it("says an agent has no description rather than leaving the line blank", () => {
    mount({ description: null });

    expect(screen.getByText("No description.")).toBeInTheDocument();
  });

  it("names the surfaces an agent answers on, and passes an unknown one through", () => {
    // A new platform must not vanish from the card between a backend release and
    // a frontend one.
    mount({ channels: ["slack", "discord"] });

    expect(screen.getByText("Slack")).toBeInTheDocument();
    expect(screen.getByText("discord")).toBeInTheDocument();
  });

  it("says when an agent was last edited, and says so when it never was", () => {
    mount({ updated_at: null });

    expect(screen.getByText("never edited")).toBeInTheDocument();
  });

  it("dates the last edit when there is one", () => {
    mount({ updated_at: "2026-07-01T10:00:00Z" });

    expect(screen.getByText(/^edited /)).toBeInTheDocument();
  });

  it("offers a reader the card and nothing to act on", () => {
    // Duplicating, archiving and deleting are all `agents:edit` on the server.
    mount({}, { canEdit: false });

    expect(screen.getByRole("link", { name: "Open Support" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Edit Support" })).toBeNull();
    expect(screen.queryByRole("button", { name: /More actions/ })).toBeNull();
  });

  it("duplicates from the menu", async () => {
    const actions = mount();

    await userEvent.click(screen.getByRole("button", { name: "More actions for Support" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Duplicate" }));

    expect(actions.onDuplicate).toHaveBeenCalled();
  });

  it("offers archive for a live agent and restore for an archived one", async () => {
    const actions = mount({ status: "archived" });

    await userEvent.click(screen.getByRole("button", { name: "More actions for Support" }));
    expect(screen.queryByRole("menuitem", { name: "Archive" })).toBeNull();
    await userEvent.click(screen.getByRole("menuitem", { name: "Restore" }));

    expect(actions.onRestore).toHaveBeenCalled();
  });

  it("archives a live agent", async () => {
    const actions = mount();

    await userEvent.click(screen.getByRole("button", { name: "More actions for Support" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Archive" }));

    expect(actions.onArchive).toHaveBeenCalled();
  });

  it("deletes permanently, and says that is what it is", async () => {
    const actions = mount();

    await userEvent.click(screen.getByRole("button", { name: "More actions for Support" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Delete permanently" }));

    expect(actions.onDelete).toHaveBeenCalled();
  });

  it("shows who the agent is reachable by, as one chip", () => {
    mount({ visibility: "org" });

    expect(screen.getByText("Organization")).toBeInTheDocument();
  });

  it("stops a second action while one is in flight", () => {
    // The card keeps its controls but nothing reaches them, so a double archive
    // cannot be sent while the first is still open.
    const { container } = render(
      <AgentCard
        agent={agent({})}
        canEdit
        busy
        actions={{
          onDuplicate: vi.fn(),
          onArchive: vi.fn(),
          onRestore: vi.fn(),
          onDelete: vi.fn(),
        }}
      />,
    );

    expect(container.firstElementChild).toHaveClass("pointer-events-none");
  });
});

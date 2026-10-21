import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../../messages/en.json";
import { TooltipProvider } from "@/components/ui";
import { GettingStartedWidget } from "./getting-started";
import type { Period } from "@/lib/dashboard/period";
import { useAuthStore } from "@/stores";
import { useArchitectAskStore } from "@/stores/architect-ask-store";
import type { User } from "@/types";

/**
 * The first steps, each ticked off by what the person has actually done (#2301).
 *
 * Every step reads state another page already holds, so what is asserted here is
 * which state ticks which step - a checklist ticked by the wrong read lies.
 */

const agentsMock = vi.fn();
const conversationsMock = vi.fn();
const triggersMock = vi.fn();
const connectionsMock = vi.fn();

vi.mock("@/hooks", () => ({ useAgents: () => agentsMock() }));
vi.mock("@/hooks/use-dashboard-data", () => ({
  useRecentConversations: () => conversationsMock(),
}));
vi.mock("@/hooks/use-org-triggers", () => ({ useOrgTriggers: () => triggersMock() }));
vi.mock("@/hooks/use-mcp-connections", () => ({ useMcpConnections: () => connectionsMock() }));

const PERIOD: Period = { preset: "30d", from: "2026-07-19", to: "2026-08-18" };
const ME = { id: "u-1", job_title: null } as User;

interface State {
  jobTitle?: string | null;
  conversations?: number;
  routineBy?: string | null;
  connections?: number;
  agents?: { slug: string; owner_user_id: string }[];
  loading?: boolean;
}

function renderWidget(state: State = {}) {
  const loading = state.loading ?? false;
  useAuthStore.setState({ user: { ...ME, job_title: state.jobTitle ?? null } });
  conversationsMock.mockReturnValue({
    conversations: Array.from({ length: state.conversations ?? 0 }, (_, i) => ({ id: `c-${i}` })),
    isLoading: loading,
  });
  triggersMock.mockReturnValue({
    triggers:
      state.routineBy === undefined ? [] : [{ id: "t-1", created_by_user_id: state.routineBy }],
    isLoading: false,
  });
  connectionsMock.mockReturnValue({
    connections: Array.from({ length: state.connections ?? 0 }, (_, i) => ({ id: `m-${i}` })),
    isLoading: false,
  });
  agentsMock.mockReturnValue({ agents: state.agents ?? [], isLoading: false });
  render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <TooltipProvider>
        <GettingStartedWidget title="Getting started" hint="" period={PERIOD} />
      </TooltipProvider>
    </NextIntlClientProvider>,
  );
}

/** An open step: a link to its page, or the button that asks the Architect. */
const open = (name: string) =>
  screen.queryByRole("link", { name: new RegExp(name) }) ??
  screen.queryByRole("button", { name: new RegExp(name) });

beforeEach(() => {
  useArchitectAskStore.setState({ request: null });
});

describe("the getting-started widget", () => {
  it("waits for every read before ticking anything", () => {
    renderWidget({ loading: true });

    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  });

  it("opens with nothing done and every step a way to do it", () => {
    renderWidget();

    expect(screen.getByText("0 of 5 done")).toBeVisible();
    expect(screen.getAllByRole("link")).toHaveLength(4);
    expect(screen.getAllByRole("button", { name: /Build an agent/ })).toHaveLength(1);
  });

  it("ticks each step from the state that proves it", () => {
    renderWidget({
      jobTitle: "Sales",
      conversations: 1,
      routineBy: "u-1",
      connections: 0,
      agents: [],
    });

    expect(screen.getByText("3 of 5 done")).toBeVisible();
    // A done step is a line to read, not one more thing to click.
    expect(open("Tell agents about you")).toBeNull();
    expect(open("Start a conversation")).toBeNull();
    expect(open("Set up a routine")).toBeNull();
    expect(screen.getByText("Set up a routine")).toBeVisible();
    expect(open("Connect a service")).not.toBeNull();
  });

  it("does not count somebody else's routine, or an agent every organization opens with", () => {
    renderWidget({
      routineBy: "u-2",
      agents: [
        { slug: "agenticos", owner_user_id: "u-1" },
        { slug: "architect", owner_user_id: "u-1" },
        { slug: "sales-helper", owner_user_id: "u-2" },
      ],
    });

    expect(open("Set up a routine")).not.toBeNull();
    expect(open("Build an agent")).not.toBeNull();
  });

  it("links each open step to the page it is done on", () => {
    renderWidget();

    expect(screen.getAllByRole("link").map((link) => link.getAttribute("href"))).toEqual([
      "/settings/profile",
      "/chat",
      "/routines",
      "/mcp-servers",
    ]);
  });

  it("hands building an agent to the Architect rather than to a page", async () => {
    renderWidget();

    await userEvent.click(screen.getByRole("button", { name: /Build an agent/ }));

    expect(useArchitectAskStore.getState().request?.text).toBe(
      messages.dashboard.widgets["getting-started"].agentAsk,
    );
  });

  it("says so once every step is done", () => {
    renderWidget({
      jobTitle: "Sales",
      conversations: 1,
      routineBy: "u-1",
      connections: 1,
      agents: [{ slug: "sales-helper", owner_user_id: "u-1" }],
    });

    expect(screen.getByText("You are set up")).toBeVisible();
  });
});

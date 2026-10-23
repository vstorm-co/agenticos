import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { StartChecklist } from "./start-checklist";

/**
 * The dashboard's one Get started card (#2072, #2301): the person's own steps for
 * everybody, the organization's after them for whoever builds agents, each ticked
 * from what exists.
 */

const data = vi.hoisted(() => ({
  perms: new Set<string>(["agents:edit", "channels:manage"]),
  user: { id: "u1", job_title: null as string | null },
  conversations: [] as unknown[],
  triggers: [] as { created_by_user_id: string }[],
  connections: [] as unknown[],
  agents: [] as { status: string; owner_user_id?: string; slug?: string }[],
  loading: false,
  kbs: [] as unknown[],
  groups: [] as unknown[],
  members: [{}] as unknown[],
  bots: [] as unknown[],
  ask: vi.fn(),
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (perm: string) => data.perms.has(perm) }),
  useAgents: () => ({ agents: data.agents, isLoading: data.loading }),
  useKnowledgeBases: () => ({ kbs: data.kbs }),
  useGroups: () => ({ groups: data.groups }),
  useMembers: () => ({ members: data.members }),
  useChannelBots: () => ({ bots: data.bots }),
}));
vi.mock("@/hooks/use-dashboard-data", () => ({
  useRecentConversations: () => ({ conversations: data.conversations, isLoading: false }),
}));
vi.mock("@/hooks/use-org-triggers", () => ({
  useOrgTriggers: () => ({ triggers: data.triggers, isLoading: false }),
}));
vi.mock("@/hooks/use-mcp-connections", () => ({
  useMcpConnections: () => ({ connections: data.connections, isLoading: false }),
}));
vi.mock("@/stores", () => ({
  useAuthStore: (pick: (state: { user: typeof data.user }) => unknown) => pick({ user: data.user }),
}));
vi.mock("@/stores/architect-ask-store", () => ({
  useArchitectAskStore: (pick: (state: { ask: typeof data.ask }) => unknown) =>
    pick({ ask: data.ask }),
}));

/** Everything the person themselves can do, done. */
function personalDone() {
  data.user = { id: "u1", job_title: "Engineer" };
  data.conversations = [{}];
  data.triggers = [{ created_by_user_id: "u1" }];
  data.connections = [{}];
  data.agents = [{ status: "draft", owner_user_id: "u1", slug: "mine" }];
}

beforeEach(() => {
  window.localStorage.clear();
  data.perms = new Set(["agents:edit", "channels:manage"]);
  data.user = { id: "u1", job_title: null };
  data.conversations = [];
  data.triggers = [];
  data.connections = [];
  data.agents = [];
  data.loading = false;
  data.kbs = [];
  data.groups = [];
  data.members = [{}];
  data.bots = [];
  data.ask.mockReset();
});

describe("the dashboard's start checklist", () => {
  it("leads with the person's own steps and says what the next one is for", () => {
    render(<StartChecklist orgId="o1" />);

    expect(screen.getByRole("progressbar")).toHaveAttribute("aria-valuetext", "0 of 10 done");
    expect(screen.getByText("0/10")).toBeInTheDocument();
    expect(screen.getByText("10 steps left")).toBeInTheDocument();
    expect(screen.getByText("Your role and work, so answers fit you.")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute(
      "href",
      "/settings/profile",
    );
    expect(screen.queryByText("Already done")).toBeNull();
  });

  it("raises the next step, lists the rest, and keeps what is done as links", () => {
    personalDone();
    data.agents = [{ status: "draft", owner_user_id: "u1", slug: "mine" }];
    data.groups = [{}];
    render(<StartChecklist orgId="o1" />);

    expect(screen.getByText("6/10")).toBeInTheDocument();
    expect(screen.getByText("4 steps left")).toBeInTheDocument();
    // The organization's first step left is the next, for a builder whose own are done.
    expect(screen.getByRole("link", { name: "Start" })).toHaveAttribute("href", "/agents");
    expect(screen.getByRole("link", { name: "Invite a teammate" })).toHaveAttribute(
      "href",
      "/orgs/o1/members",
    );
    expect(screen.getByText("Already done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Add your departments" })).toHaveAttribute(
      "href",
      "/groups",
    );
  });

  it("asks the Architect for the agent a person did not build, not the ones every org has", async () => {
    personalDone();
    data.agents = [{ status: "published", owner_user_id: "u1", slug: "architect" }];
    data.perms = new Set();
    render(<StartChecklist orgId="o1" />);

    expect(screen.getByText("4/5")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(data.ask).toHaveBeenCalledWith(
      "Help me build my first agent. Ask me what I want it to do.",
    );
  });

  it("asks the Architect from a row too, when building an agent is not the next step", async () => {
    data.agents = [{ status: "published", owner_user_id: "u1", slug: "architect" }];
    data.perms = new Set();
    render(<StartChecklist orgId="o1" />);

    await userEvent.click(screen.getByRole("button", { name: "Build an agent" }));
    expect(data.ask).toHaveBeenCalled();
  });

  it("leaves the chat-app step to whoever may add one", () => {
    data.perms = new Set(["agents:edit"]);
    render(<StartChecklist orgId="o1" />);

    expect(screen.getByText("9 steps left")).toBeInTheDocument();
  });

  it("goes once everything is done, for a builder and for a reader alike", () => {
    personalDone();
    data.agents = [{ status: "published", owner_user_id: "u1", slug: "mine" }];
    data.kbs = [{}];
    data.groups = [{}];
    data.members = [{}, {}];
    data.bots = [{}];
    const { container, unmount } = render(<StartChecklist orgId="o1" />);
    expect(container).toBeEmptyDOMElement();
    unmount();

    data.perms = new Set();
    const reader = render(<StartChecklist orgId="o1" />);
    expect(reader.container).toBeEmptyDOMElement();
  });

  it("waits for what it reads before saying anything", () => {
    data.loading = true;
    const { container } = render(<StartChecklist orgId="o1" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("is hidden for good once closed", async () => {
    const { unmount } = render(<StartChecklist orgId="o1" />);
    await userEvent.click(screen.getByRole("button", { name: "Hide the checklist" }));
    expect(screen.queryByText("Get started")).toBeNull();
    unmount();

    render(<StartChecklist orgId="o1" />);
    expect(screen.queryByText("Get started")).toBeNull();
  });

  it("works without browser storage", async () => {
    const getItem = vi.spyOn(window.localStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    const setItem = vi.spyOn(window.localStorage, "setItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    render(<StartChecklist orgId="o2" />);

    await userEvent.click(screen.getByRole("button", { name: "Hide the checklist" }));

    expect(screen.queryByText("Get started")).toBeNull();
    getItem.mockRestore();
    setItem.mockRestore();
  });
});

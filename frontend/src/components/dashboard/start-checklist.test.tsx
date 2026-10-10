import { beforeEach, describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { StartChecklist } from "./start-checklist";

const data = vi.hoisted(() => ({
  perms: new Set<string>(["agents:edit", "channels:manage"]),
  agents: [] as { status: string }[],
  agentsLoading: false,
  kbs: [] as unknown[],
  groups: [] as unknown[],
  members: [{}] as unknown[],
  bots: [] as unknown[],
}));

vi.mock("@/hooks", () => ({
  usePermissions: () => ({ can: (perm: string) => data.perms.has(perm) }),
  useAgents: () => ({ agents: data.agents, isLoading: data.agentsLoading }),
  useKnowledgeBases: () => ({ kbs: data.kbs }),
  useGroups: () => ({ groups: data.groups }),
  useMembers: () => ({ members: data.members }),
  useChannelBots: () => ({ bots: data.bots }),
}));

beforeEach(() => {
  window.localStorage.clear();
  data.perms = new Set(["agents:edit", "channels:manage"]);
  data.agents = [];
  data.agentsLoading = false;
  data.kbs = [];
  data.groups = [];
  data.members = [{}];
  data.bots = [];
});

describe("the dashboard's start checklist (#2072)", () => {
  it("ticks what exists and links to what does not", () => {
    data.agents = [{ status: "draft" }];
    data.groups = [{}];
    render(<StartChecklist orgId="o1" />);

    expect(screen.getByText("2 of 6 done")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Publish it" })).toHaveAttribute("href", "/agents");
    expect(screen.getByRole("link", { name: "Invite a teammate" })).toHaveAttribute(
      "href",
      "/orgs/o1/members",
    );
  });

  it("leaves the chat-app step to whoever may add one", () => {
    data.perms = new Set(["agents:edit"]);
    render(<StartChecklist orgId="o1" />);

    expect(screen.getByText("0 of 5 done")).toBeInTheDocument();
  });

  it("goes once everything is done, and is not there for a reader", () => {
    data.agents = [{ status: "published" }];
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

  it("waits for the agents before saying anything", () => {
    data.agentsLoading = true;
    const { container } = render(<StartChecklist orgId="o1" />);

    expect(container).toBeEmptyDOMElement();
  });

  it("is hidden for good once closed, and still closes where storage refuses", async () => {
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

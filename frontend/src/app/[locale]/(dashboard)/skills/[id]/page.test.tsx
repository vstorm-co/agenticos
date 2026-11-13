import { Suspense, type ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type { SkillAgentUsage, SkillFork, SkillVersionSummary } from "@/types/skill-versions";
import SkillPage from "./page";
import type { CheckedDraft } from "@/components/skills/skill-check-dialog";
import { SkillDetailDialog } from "@/components/skills/skill-detail-dialog";

const state = vi.hoisted(() => ({
  tab: null as string | null,
  show: null as string | null,
  push: vi.fn(),
  runsView: true,
  checkedDraft: null as CheckedDraft | null,
}));
vi.mock("@/components/skills/check-running", () => ({
  CheckRunning: ({ onEdit }: { onEdit: (draft: CheckedDraft) => void }) =>
    state.checkedDraft === null ? null : (
      <button
        onClick={() => {
          if (state.checkedDraft) onEdit(state.checkedDraft);
        }}
      >
        Edit checked text
      </button>
    ),
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (permission: string) => permission === "runs:view" && state.runsView,
    isLoading: false,
  }),
}));
vi.mock("next/navigation", async (original) => ({
  ...(await original<typeof import("next/navigation")>()),
  useRouter: () => ({ push: state.push, replace: vi.fn() }),
  useSearchParams: () =>
    new URLSearchParams({
      ...(state.tab === null ? {} : { tab: state.tab }),
      ...(state.show === null ? {} : { show: state.show }),
    }),
  usePathname: () => "/skills/s1",
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/use-organizations", async (original) => ({
  ...(await original<typeof import("@/hooks/use-organizations")>()),
  useOrganizationList: () => ({ data: [] }),
}));

const RETURNS: SkillFork = {
  id: "f1",
  skill_id: "s1",
  name: "Returns",
  base: { id: "m7", number: 7 },
  started_from: { id: "m7", number: 7 },
  latest: { id: "r2", number: 2 },
  changes: 2,
  behind_main: 5,
  agents: 1,
  archive_candidate: false,
  archived_at: null,
  created_at: "2026-10-30T10:00:00Z",
};

function usage(
  name: string,
  binding: Partial<SkillAgentUsage["binding"]> & Pick<SkillAgentUsage["binding"], "state">,
  extra: Partial<SkillAgentUsage> = {},
): SkillAgentUsage {
  return {
    agent: { id: name, name, slug: name.toLowerCase() },
    via_specialist: null,
    draft_only: false,
    binding: {
      version: { id: `v-${name}`, number: 12, fork_id: null },
      fork: null,
      behind_main: 0,
      ...binding,
    },
    agent_version: 3,
    environments: [],
    draft_differs: false,
    can_change: true,
    can_publish: true,
    ...extra,
  };
}

const AGENTS = {
  main_latest: { id: "m12", number: 12 },
  items: [
    usage("Support", { state: "main" }),
    usage("HR", {
      state: "pinned",
      version: { id: "m9", number: 9, fork_id: null },
      behind_main: 3,
    }),
    usage(
      "Refunds",
      {
        state: "fork",
        version: { id: "r2", number: 2, fork_id: "f1" },
        fork: { id: "f1", name: "Returns", base_number: 7, changes: 2 },
        behind_main: 5,
      },
      { can_change: false },
    ),
    usage(
      "Drafty",
      { state: "pinned", version: { id: "m10", number: 10, fork_id: null }, behind_main: 2 },
      { draft_only: true, agent_version: null },
    ),
  ],
  hidden: 2,
};

function version(number: number, extra: Partial<SkillVersionSummary> = {}): SkillVersionSummary {
  return {
    id: `m${number}`,
    skill_id: "s1",
    fork_id: null,
    number,
    source: "edit",
    previous: number > 1 ? { id: `m${number - 1}`, number: number - 1, fork_id: null } : null,
    restored_from: null,
    proposal_id: null,
    created_by: { id: "u1", name: "Bartek" },
    created_at: "2026-11-01T10:00:00Z",
    agents: 0,
    ...extra,
  };
}

const skill = vi.hoisted(() => ({ canEdit: true, error: null as unknown }));

/** What the API answers for each read the page makes. */
async function serveOnce(path: string): Promise<unknown> {
  if (path === "/skills/s1/versions/m12")
    return {
      ...version(12),
      description: "How returns are handled.",
      content: "# Returns",
      resources: [],
    };
  if (path === "/skills/s1") {
    if (skill.error) throw skill.error;
    return {
      id: "s1",
      name: "returns-policy",
      description: "How returns are handled.",
      content: "# Returns",
      category: null,
      version: 12,
      latest_version_id: "m12",
      forks: 1,
      can_edit: skill.canEdit,
      visibility: "org",
      owner_user_id: null,
      resources: [],
    };
  }
  if (path.startsWith("/skills/s1/forks")) return { items: [RETURNS], total: 1 };
  if (path === "/skills/s1/agents") return AGENTS;
  if (path === "/skills/s1/improvements") return [];
  if (path.startsWith("/skills/s1/usage")) {
    return { days: 30, since: "", loads: 0, agents: [], hidden_agents: 0, hidden_loads: 0 };
  }
  if (path.startsWith("/skills/s1/versions?")) {
    return {
      items: [
        version(12),
        version(11, { source: "restore", restored_from: { id: "m4", number: 4, fork_id: null } }),
      ],
      total: 12,
    };
  }
  return { items: [], total: 0, categories: [], suggested_categories: [] };
}

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

async function mount() {
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <SkillPage params={Promise.resolve({ id: "s1" })} />
      </Suspense>,
      { wrapper },
    );
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  state.runsView = true;
  state.checkedDraft = null;
  state.tab = null;
  state.show = null;
  skill.canEdit = true;
  skill.error = null;
  vi.mocked(apiClient.get).mockImplementation(serveOnce);
});

describe("SkillPage", () => {
  it.each([
    ["main", "f1"],
    ["fork:f1", null],
    ["fork:f1", "f1"],
  ] as const)("opens a checked draft on its own line from %s to %s", async (shown, target) => {
    state.show = shown;
    state.checkedDraft = {
      description: "Checked description.",
      content: "Checked instructions.",
      baseVersionId: target === null ? "m12" : "r2",
      forkId: target,
    };
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/versions/r2"
        ? { id: "r2", description: "Fork", content: "Fork body", resources: [] }
        : serveOnce(path),
    );
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Edit checked text" }));
    expect(await screen.findByLabelText("Description", { exact: true })).toHaveValue(
      "Checked description.",
    );
    expect(screen.getByLabelText(/Instructions source/)).toHaveValue("Checked instructions.");
    expect(
      screen.getByRole("button", {
        name: target === null ? "Edit" : "Edit fork “Returns”",
        hidden: true,
      }),
    ).toBeInTheDocument();
  });

  it("reads a skill in a modal without rewriting catalog filters and links to its full view", async () => {
    const before = window.location.href;
    const onClose = vi.fn();
    render(<SkillDetailDialog id="s1" onClose={onClose} />, { wrapper });
    expect(await screen.findByRole("dialog", { name: "returns-policy" })).toBeVisible();
    expect(await screen.findByRole("button", { name: "Open full view" })).toBeVisible();
    expect(screen.queryByRole("tab", { name: "Version tree" })).toBeNull();
    expect(state.push).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Open full view" }));
    expect(state.push).toHaveBeenCalledWith("/skills/s1?tab=content");
    expect(window.location.href).toBe(before);
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("lists each agent with the version it is served", async () => {
    await mount();

    expect(await screen.findByText("v12 · main")).toBeInTheDocument();
    expect(screen.getByText("v9 · pinned · 3 behind main")).toBeInTheDocument();
    expect(
      screen.getByText("Fork “Returns” · from v7 · 2 changes · 5 behind main"),
    ).toBeInTheDocument();
    expect(screen.getByText("Only in the draft")).toBeInTheDocument();
    expect(screen.getByText("2 more agents you can't see use this skill.")).toBeInTheDocument();
  });

  it("lists an agent's specialist as its own row and counts the agent once", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/agents"
        ? {
            ...AGENTS,
            items: [
              ...AGENTS.items,
              usage("Support", { state: "main" }, { via_specialist: "billing", can_change: false }),
            ],
          }
        : serveOnce(path),
    );
    await mount();

    expect(await screen.findByText("Through its specialist billing")).toBeInTheDocument();
    expect(screen.getAllByRole("link", { name: "Support" })).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Main (1)" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "All (4)" })).toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: "Change the version of the skill for Support" }),
    ).toHaveLength(1);
  });

  it("offers Change version only where the caller may publish the agent", async () => {
    await mount();
    await screen.findByText("v12 · main");

    expect(
      screen.getByRole("button", { name: "Change the version of the skill for Support" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Change the version of the skill for Refunds" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Change the version of the skill for Drafty" }),
    ).toBeNull();
  });

  it("narrows the table to one fork, leaving draft-only agents out of every line", async () => {
    await mount();
    await screen.findByText("v12 · main");

    expect(screen.getByRole("button", { name: "Main (1)" })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Fork “Returns” (1)" }));

    expect(screen.queryByText("Support")).toBeNull();
    expect(screen.getByText("Refunds")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit fork “Returns”" })).toBeInTheDocument();
  });

  it("lists a line's history and offers Restore on all but its newest version", async () => {
    state.tab = "history";
    await mount();

    expect(await screen.findByText("Restored from v4")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Restore v12" })).toBeNull();
    expect(screen.getByRole("button", { name: "Restore v11" })).toBeInTheDocument();
  });

  it("restores over the line's newest version once the person confirms", async () => {
    state.tab = "history";
    vi.mocked(apiClient.post).mockResolvedValue(version(13));
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Restore v11" }));
    expect(screen.getByText(/comes back as the newest version on main/)).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Restore" }));

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/versions/m11/restore", {
      base_version_id: "m12",
    });
  });

  it("keeps a reader's page read-only", async () => {
    skill.canEdit = false;
    state.tab = "history";
    await mount();

    await screen.findByText("Restored from v4");
    expect(screen.queryByRole("button", { name: /^Restore/ })).toBeNull();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Improve" })).toBeNull();
    expect(await screen.findByText("No change to this line has been checked yet.")).toBeVisible();
  });

  it("lists no checks to a reader who may not read runs", async () => {
    state.runsView = false;
    state.tab = "history";
    await mount();

    await screen.findByText("Restored from v4");
    expect(screen.queryByText("Checks")).toBeNull();
  });

  it("opens the agents tab for an obsolete version-tree bookmark", async () => {
    state.tab = "tree";
    await mount();

    expect(screen.queryByRole("tab", { name: "Version tree" })).toBeNull();
    expect(await screen.findByRole("tab", { name: "Agents" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    expect(await screen.findByText("v12 · main")).toBeInTheDocument();
  });

  it("reads what the line shown serves on Content, for main and for a fork", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/versions/")
        ? {
            id: path.split("/").at(-1),
            number: 2,
            description: "d",
            content: `served ${path.split("/").at(-1)}`,
            resources: [],
          }
        : serveOnce(path),
    );
    state.tab = "content";
    await mount();
    expect(await screen.findByText("served m12")).toBeInTheDocument();
    expect(screen.getByText("v12")).toBeInTheDocument();
  });

  it("reads a fork's own newest version on Content", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/versions/")
        ? { id: "r2", number: 2, description: "d", content: "served r2", resources: [] }
        : serveOnce(path),
    );
    state.tab = "content";
    state.show = "fork:f1";
    await mount();
    expect(await screen.findByText("served r2")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/versions/r2");
  });

  it("says the skill is out of reach rather than empty when it cannot be read", async () => {
    skill.error = new ApiError(404, "Not found");
    await mount();

    expect(await screen.findByRole("link", { name: "Back" })).toHaveAttribute("href", "/skills");
    expect(screen.queryByText("returns-policy")).toBeNull();
  });
});

describe("SkillPage's lines and writes", () => {
  it("says the forks cannot be read rather than guessing the line", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/skills/s1/forks")) throw new Error("forks offline");
      return serveOnce(path);
    });
    await mount();

    expect(await screen.findByText("forks offline")).toBeInTheDocument();
    expect(screen.queryByText("returns-policy")).toBeNull();
  });

  it("opens a fork's history and editor from a link to the fork", async () => {
    state.tab = "history";
    state.show = "fork:f1";
    await mount();

    expect(await screen.findByText("History of fork “Returns”")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Edit fork “Returns”" })).toBeInTheDocument();
  });

  it("offers catching the fork shown up with main and moving it to main", async () => {
    state.show = "fork:f1";
    await mount();

    expect(
      await screen.findByRole("link", { name: "Catch “Returns” up with main" }),
    ).toHaveAttribute("href", "/skills/s1/improve/new?fork=f1&merge=catch_up");
    await userEvent.click(screen.getByRole("button", { name: "More actions" }));
    expect(screen.getByRole("menuitem", { name: "Move “Returns” to main" })).toHaveAttribute(
      "href",
      "/skills/s1/improve/new?fork=f1&merge=to_main",
    );
  });

  it("returns a fork with nothing of its own to main from its page", async () => {
    state.show = "fork:f1";
    state.runsView = false;
    const empty = { ...RETURNS, latest: null, changes: 0 };
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/skills/s1/forks")) return { items: [empty], total: 1 };
      if (path === "/skills/s1/agents") {
        return {
          ...AGENTS,
          items: AGENTS.items.map((one) => ({ ...one, can_change: true })),
        };
      }
      return serveOnce(path);
    });
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "More actions" }));
    await userEvent.click(screen.getByRole("menuitem", { name: "Return “Returns” to main" }));

    expect(await screen.findByRole("dialog")).toHaveTextContent(
      "Return the agents of “Returns” to main",
    );
    expect(screen.queryByRole("link", { name: /up with main/ })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers no return of a fork whose agents the reader may not change", async () => {
    state.show = "fork:f1";
    const empty = { ...RETURNS, latest: null, changes: 0 };
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/forks") ? { items: [empty], total: 1 } : serveOnce(path),
    );
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "More actions" }));
    expect(screen.queryByRole("menuitem", { name: "Return “Returns” to main" })).toBeNull();
  });

  it("says main's versions cannot be read rather than guessing who an edit reaches", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/skills/s1/versions?")) throw new Error("versions offline");
      return serveOnce(path);
    });
    await mount();

    expect(await screen.findByText("versions offline")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
  });

  it("offers no editor until main's followers are counted", async () => {
    let count: () => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/skills/s1/versions?")) {
        await new Promise<void>((resolve) => (count = resolve));
      }
      return serveOnce(path);
    });
    await mount();
    await act(() => new Promise((resolve) => setTimeout(resolve, 50)));

    expect(screen.queryByRole("button", { name: "Edit" })).toBeNull();
    await act(async () => count());
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("reads a link to a fork that is gone as everyone, on main", async () => {
    state.show = "fork:gone";
    await mount();

    expect(await screen.findByRole("button", { name: "All (4)" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("button", { name: "Edit" })).toBeInTheDocument();
  });

  it("points History at the line picked there", async () => {
    state.tab = "history";
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "fork “Returns”" }));
    expect(await screen.findByText("History of fork “Returns”")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "main" }));
    expect(await screen.findByText("History of main")).toBeInTheDocument();
  });

  it("pages a line's checks, and starts the next line's on its first page", async () => {
    state.tab = "history";
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path.startsWith("/skills/s1/checks?") ? { items: [], total: 45 } : serveOnce(path),
    );
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Next page" }));
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/checks?limit=20&skip=20");
    expect(await screen.findByText("45 checks · page 2 of 3")).toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "fork “Returns”" }));
    expect(await screen.findByText("45 checks · page 1 of 3")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/skills/s1/checks?limit=20&fork_id=f1");
  });

  it("opens the editor and closes it", async () => {
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("closes the catalog modal after deleting its skill without navigating away", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/agents" ? { ...AGENTS, items: [], hidden: 0 } : serveOnce(path),
    );
    const onClose = vi.fn();
    render(<SkillDetailDialog id="s1" onClose={onClose} />, { wrapper });
    await userEvent.click(
      await screen.findByRole("button", { name: "More actions for returns-policy" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(apiClient.delete).not.toHaveBeenCalled();
    expect(onClose).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "More actions for returns-policy" }));
    await userEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));
    expect(apiClient.delete).toHaveBeenCalledWith("/skills/s1");
    expect(onClose).toHaveBeenCalledOnce();
    expect(state.push).not.toHaveBeenCalled();
  });

  it("deletes a skill nobody uses from the editor and returns to the list", async () => {
    vi.mocked(apiClient.delete).mockResolvedValue(undefined);
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/agents" ? { ...AGENTS, items: [], hidden: 0 } : serveOnce(path),
    );
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "More actions for returns-policy" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));
    await userEvent.click(screen.getByRole("button", { name: "Delete" }));

    expect(apiClient.delete).toHaveBeenCalledWith("/skills/s1");
    expect(state.push).toHaveBeenCalledWith("/skills");
  });

  it("warns an edit reaches the agents the server counts on the line", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path.startsWith("/skills/s1/versions?")) {
        return { items: [version(12, { agents: 4 })], total: 12 };
      }
      if (path === "/skills/s1/versions/r2") {
        return { id: "r2", description: "Fork.", content: "Fork body.", resources: [] };
      }
      return serveOnce(path);
    });
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.type(await screen.findByLabelText("Description"), "!");
    expect(screen.getByRole("alert")).toHaveTextContent("4 agents following main get it at once");

    cleanup();
    state.show = "fork:f1";
    await mount();
    await userEvent.click(await screen.findByRole("button", { name: "Edit fork “Returns”" }));
    await userEvent.type(await screen.findByLabelText("Description"), "!");
    expect(screen.getByRole("alert")).toHaveTextContent("Its 1 agent gets it at once");
  });

  it("offers no delete while agents use the skill, and names them", async () => {
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Edit" }));
    await userEvent.click(
      await screen.findByRole("button", { name: "More actions for returns-policy" }),
    );
    await userEvent.click(screen.getByRole("menuitem", { name: /Delete/ }));

    expect(
      await screen.findByText(
        /Used by 6 agents: Support, HR, Refunds,? and Drafty, and 2 you can.t see/,
      ),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(apiClient.delete).not.toHaveBeenCalled();
  });

  it("starts a fork from main's newest version and shows it", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "f2", name: "Marketplace" });
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "New fork" }));
    await userEvent.type(screen.getByLabelText("Name"), "Marketplace");
    await userEvent.click(screen.getByRole("button", { name: "Create fork" }));

    expect(apiClient.post).toHaveBeenCalledWith("/skills/s1/forks", {
      name: "Marketplace",
      from_version_id: "m12",
    });
  });

  it("offers a new fork only once the agents to move onto it are read", async () => {
    let listAgents: () => void = () => {};
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/skills/s1/agents")
        await new Promise<void>((resolve) => (listAgents = resolve));
      return serveOnce(path);
    });
    await mount();
    expect(await screen.findByRole("button", { name: "Edit" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New fork" })).toBeNull();

    await act(async () => listAgents());
    await userEvent.click(await screen.findByRole("button", { name: "New fork" }));
    expect(screen.getByRole("checkbox", { name: /^Support/ })).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).toBeNull();
  });

  it("offers no new fork when the agents cannot be read, and says why", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
      if (path === "/skills/s1/agents") throw new Error("agents offline");
      return serveOnce(path);
    });
    await mount();

    expect(await screen.findByText("agents offline")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "New fork" })).toBeNull();
  });

  it("offers no fork to a reader", async () => {
    skill.canEdit = false;
    await mount();
    await screen.findByText("v12 · main");
    expect(screen.queryByRole("button", { name: "New fork" })).toBeNull();
  });

  it("shows how much the skill is used to a reader of runs", async () => {
    state.runsView = true;
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1/usage?days=30"
        ? { days: 30, since: "", loads: 0, agents: [], hidden_agents: 0, hidden_loads: 0 }
        : serveOnce(path),
    );
    await mount();

    expect(await screen.findByText("Use in the last 30 days")).toBeInTheDocument();
  });

  it("names the agents bound only in a draft, and an empty fork", async () => {
    await mount();

    await userEvent.click(await screen.findByRole("button", { name: "Only in the draft (1)" }));
    expect(screen.getByText("Drafty")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Pinned (1)" }));
    expect(screen.getByText("HR")).toBeInTheDocument();
  });
});

describe("SkillPage's Improve", () => {
  it("opens the wizard for main, or for the fork on screen", async () => {
    await mount();
    expect(await screen.findByRole("link", { name: "Improve" })).toHaveAttribute(
      "href",
      "/skills/s1/improve/new",
    );

    cleanup();
    state.show = "fork:f1";
    await mount();
    expect(await screen.findByRole("link", { name: "Improve fork “Returns”" })).toHaveAttribute(
      "href",
      "/skills/s1/improve/new?fork=f1",
    );
  });

  it("leaves Improve out for an editor who may not read runs", async () => {
    state.runsView = false;
    await mount();

    expect(await screen.findByText("v12 · main")).toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Improve" })).toBeNull();
  });
});

it("switches tabs and deletes a skill from its full-page header", async () => {
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
  vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
    path === "/skills/s1/agents" ? { ...AGENTS, items: [], hidden: 0 } : serveOnce(path),
  );
  await mount();
  await userEvent.click(await screen.findByRole("tab", { name: "Content" }));
  expect(screen.getByRole("tab", { name: "Content" })).toHaveAttribute("aria-selected", "true");
  await userEvent.click(screen.getByRole("tab", { name: "Agents" }));
  await userEvent.click(screen.getByRole("button", { name: "Delete" }));
  await userEvent.click(within(screen.getByRole("dialog")).getByRole("button", { name: "Delete" }));
  expect(apiClient.delete).toHaveBeenCalledWith("/skills/s1");
  expect(state.push).toHaveBeenCalledWith("/skills");
});

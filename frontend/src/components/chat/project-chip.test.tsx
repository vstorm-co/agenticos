import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { getProject } from "@/lib/projects-api";
import { useAgentSelectionStore, useConversationStore } from "@/stores";
import { act } from "@testing-library/react";
import { useWorkOnStore, type LocalTarget } from "@/stores/work-on-store";
import { ProjectChip } from "./project-chip";

const desktop = vi.hoisted(() => ({ enabled: false, folder: null as LocalTarget | null }));
vi.mock("@/hooks/use-shell", () => ({
  useShell: () => (desktop.enabled ? { platform: "macos" } : null),
}));
vi.mock("@/hooks/use-project-folder", () => ({
  useProjectFolder: (id: string | null) => ({
    target: desktop.folder,
    available: true,
    scopeKey: id ? `alice:org:${id}` : null,
  }),
}));
const params = vi.fn(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useSearchParams: () => params(),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
vi.mock("@/lib/projects-api", async (original) => ({
  ...(await original<typeof import("@/lib/projects-api")>()),
  getProject: vi.fn(),
}));
const setUrlParam = vi.fn();
vi.mock("@/lib/utils", async (original) => ({
  ...(await original<typeof import("@/lib/utils")>()),
  setUrlParam: (...args: unknown[]) => setUrlParam(...args),
}));
vi.mock("@/components/projects/project-picker-dialog", () => ({
  ProjectPickerDialog: ({
    open,
    onPick,
  }: {
    open: boolean;
    onPick: (project: { id: string; default_agent_id: string | null } | null) => void;
  }) =>
    open ? (
      <div>
        <button onClick={() => onPick({ id: "p-2", default_agent_id: "a-9" })}>pick</button>
        <button onClick={() => onPick({ id: "p-3", default_agent_id: null })}>pick bare</button>
        <button onClick={() => onPick(null)}>none</button>
      </div>
    ) : null,
}));

function chip(conversationId: string | null, pickerOpen = false) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ProjectChip
        conversationId={conversationId}
        pickerOpen={pickerOpen}
        onPickerOpenChange={vi.fn()}
      />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  desktop.enabled = false;
  desktop.folder = null;
  useWorkOnStore.setState({ byConversation: {}, draft: null, draftProjectKey: null });
  params.mockReturnValue(new URLSearchParams());
  useConversationStore.getState().setPendingProjectId(null);
  useAgentSelectionStore.getState().select(null);
  vi.mocked(getProject).mockImplementation(
    async (id) =>
      ({
        id,
        can_use: true,
        name: id === "p-1" ? "Launch" : "Treasury",
        default_agent_id: id === "p-1" ? "a-1" : null,
      }) as never,
  );
});

describe("ProjectChip", () => {
  it("starts a chat from a project's New chat in it, with its default agent", async () => {
    params.mockReturnValue(new URLSearchParams("project=p-1"));
    chip(null);

    expect(await screen.findByRole("link", { name: "Launch" })).toHaveAttribute(
      "href",
      "/projects/p-1",
    );
    expect(useConversationStore.getState().pendingProjectId).toBe("p-1");
    expect(setUrlParam).toHaveBeenCalledWith("project", null);
    await waitFor(() => expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-1"));
  });

  it("starts a new chat rather than reopen the one that was open before", async () => {
    useConversationStore.getState().setCurrentConversationId("c-old");
    useConversationStore.getState().setCurrentMessages([
      {
        id: "m-1",
        role: "user",
        content: "earlier",
        created_at: "2026-10-18T10:00:00Z",
      } as never,
    ]);
    params.mockReturnValue(new URLSearchParams("project=p-1"));
    chip(null);

    await waitFor(() => expect(useConversationStore.getState().currentConversationId).toBeNull());
    expect(useConversationStore.getState().pendingProjectId).toBe("p-1");
  });

  it("drops a project from a link that cannot be read, rather than keep it unseen", async () => {
    vi.mocked(getProject).mockRejectedValue(new Error("Project not found"));
    params.mockReturnValue(new URLSearchParams("project=p-gone"));
    chip(null);

    await waitFor(() => expect(useConversationStore.getState().pendingProjectId).toBeNull());
    expect(screen.queryByRole("link")).toBeNull();
  });

  it("lets a new chat leave the project before it starts", async () => {
    useConversationStore.getState().setPendingProjectId("p-1");
    chip(null);
    await userEvent.click(await screen.findByRole("button", { name: "Start outside Launch" }));
    expect(useConversationStore.getState().pendingProjectId).toBeNull();
  });

  it("shows the project an existing chat is in, without a way out", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "c-1", project_id: "p-2" });
    chip("c-1");
    expect(await screen.findByRole("link", { name: "Treasury" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /Start outside/ })).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/c-1/metadata");
    expect(apiClient.get).not.toHaveBeenCalledWith("/conversations/c-1");
  });

  it("shows nothing for a chat outside any project", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({ id: "c-1" });
    const { container } = chip("c-1");
    await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
    expect(container.querySelector("a")).toBeNull();
  });

  it("puts a picked project's default agent in charge, and a cleared pick ends it", async () => {
    chip(null, true);
    await userEvent.click(screen.getByRole("button", { name: "pick" }));
    expect(useConversationStore.getState().pendingProjectId).toBe("p-2");
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-9");

    await userEvent.click(screen.getByRole("button", { name: "pick bare" }));
    expect(useAgentSelectionStore.getState().selectedAgentId).toBe("a-9");
    await userEvent.click(screen.getByRole("button", { name: "none" }));
    expect(useConversationStore.getState().pendingProjectId).toBeNull();
  });
});

it("inherits the approved folder for a new desktop project chat and keeps a manual Cloud override", async () => {
  desktop.enabled = true;
  desktop.folder = { folder: "/approved/project", mode: "read_only" };
  useConversationStore.getState().setPendingProjectId("p-1");
  const view = chip(null, true);
  await waitFor(() => expect(useWorkOnStore.getState().targetFor(null)).toEqual(desktop.folder));
  act(() => useWorkOnStore.getState().set(null, null));
  await userEvent.click(screen.getByRole("button", { name: "pick bare" }));
  await waitFor(() => expect(useWorkOnStore.getState().draftProjectKey).toBe("alice:org:p-3"));
  expect(useWorkOnStore.getState().targetFor(null)).toEqual(desktop.folder);
  act(() => useWorkOnStore.getState().set(null, null));
  view.rerender(
    <QueryClientProvider client={new QueryClient()}>
      <ProjectChip conversationId={null} pickerOpen={false} onPickerOpenChange={vi.fn()} />
    </QueryClientProvider>,
  );
  await screen.findByRole("link");
  expect(useWorkOnStore.getState().targetFor(null)).toBeNull();
});
it("does not apply a computer's project folder in a browser or to an existing conversation", async () => {
  desktop.folder = { folder: "/approved", mode: "read_only" };
  useConversationStore.getState().setPendingProjectId("p-1");
  const view = chip(null);
  await screen.findByRole("link");
  expect(useWorkOnStore.getState().targetFor(null)).toBeNull();
  view.unmount();
  desktop.enabled = true;
  vi.mocked(apiClient.get).mockResolvedValue({ id: "c-existing", project_id: "p-1" });
  chip("c-existing");
  await screen.findByRole("link");
  expect(useWorkOnStore.getState().targetFor("c-existing")).toBeNull();
});

it("clears the inherited folder when a desktop draft has no project", async () => {
  desktop.enabled = true;
  useWorkOnStore.getState().applyProject("alice:org:p-old", { folder: "/old", mode: "read_only" });
  chip(null);
  await waitFor(() => expect(useWorkOnStore.getState().draftProjectKey).toBeNull());
  expect(useWorkOnStore.getState().targetFor(null)).toBeNull();
});

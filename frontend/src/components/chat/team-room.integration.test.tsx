import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { announceRoomChange } from "@/lib/room-events";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { Agent } from "@/types/agents";
import type { Project } from "@/types/projects";
import type { RoomAgentRequest, RoomMessageResult } from "@/types/room";
import { StartTeamRoom } from "@/components/projects/start-team-room";
import { TeamRoomComposer } from "./team-room-composer";
import { TeamRoomHeader } from "./team-room-header";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => true }) }));
const push = vi.fn();
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push }),
}));
vi.mock("@/components/sharing/share-resource-button", () => ({
  ShareResourceButton: ({ canManage }: { canManage: boolean }) => (
    <button data-can-manage={canManage}>Share project</button>
  ),
}));
let agents: Agent[];
let project: Project;
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents }) }));
vi.mock("@/hooks/use-projects", () => ({
  useProject: () => ({ project, isLoading: false }),
}));
let client: QueryClient;
let canPost: boolean;
let requestItems: RoomAgentRequest[];
function wrapper({ children }: { children: ReactNode }) {
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}
function agent(id: string, changes: Partial<Agent> = {}): Agent {
  return {
    id,
    slug: id,
    name: id,
    status: "published",
    can_run: true,
    visibility: "private",
    owner_user_id: "me",
    current_version_id: "version",
    description: null,
    ...changes,
  };
}
function request(
  id: string,
  requester: string,
  status: RoomAgentRequest["status"],
): RoomAgentRequest {
  return {
    id,
    requester_id: requester,
    agent_id: "Writer",
    message_id: `message-${id}`,
    conversation_id: "room-a",
    status,
    run_id: status === "queued" ? null : "run-a",
    error: null,
    created_at: "2026-11-13T00:00:00Z",
  };
}
const saved: RoomMessageResult = {
  message: {
    id: "saved",
    conversation_id: "room-a",
    role: "user",
    content: "Hello",
    created_at: "2026-11-13T00:00:00Z",
  },
  request: null,
};
function room(id = "room-a") {
  return (
    <TeamRoomComposer
      key={id}
      projectId="project-a"
      conversationId={id}
      readOnly={false}
      onTyping={vi.fn()}
    />
  );
}
function changed() {
  announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" });
}

beforeEach(() => {
  vi.clearAllMocks();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useAuthStore.setState({
    user: { id: "me", email: "me@example.com", is_active: true, created_at: "" },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a" });
  useChatStore.setState({ messages: [], replyTo: null });
  agents = [agent("Writer")];
  project = {
    id: "project-a",
    name: "Launch",
    description: null,
    instructions: "",
    default_agent_id: null,
    default_agent_name: null,
    owner_user_id: "me",
    visibility: "private",
    backend: "state",
    runtime: null,
    chat_count: 1,
    last_active_at: null,
    shared_groups: [],
    can_use: true,
    can_edit: true,
    created_at: null,
    updated_at: null,
  };
  canPost = true;
  requestItems = [];
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path === "/orgs"
      ? { items: [] }
      : { items: requestItems, total: requestItems.length, can_post: canPost },
  );
  vi.mocked(apiClient.post).mockResolvedValue(saved);
});
afterEach(() => client.clear());

describe("the room composer", () => {
  it("defaults to people and does not treat typed @names as responder selection", async () => {
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.type(
      await screen.findByRole("textbox", { name: "Message to the team" }),
      "Hello @Writer",
    );
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    expect(apiClient.post).toHaveBeenCalledWith("/conversations/room-a/room-messages", {
      client_message_id: expect.any(String),
      content: "Hello @Writer",
    });
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
  });

  it("requires explicit selection of a published runnable cloud responder", async () => {
    agents.push(
      agent("Draft", { status: "draft" }),
      agent("Forbidden", { can_run: false }),
      agent("Computer", { local_workspace: true }),
      agent("Local coder", { local_coding_agent: { harness: "codex", access: "edit" } }),
      agent("Subscription", { personal_coding_harness: "codex" }),
    );
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.click(await screen.findByRole("combobox", { name: "Who should answer" }));
    expect(screen.queryByRole("option", { name: "Ask @Draft" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Ask @Forbidden" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Ask @Computer" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Ask @Local coder" })).not.toBeInTheDocument();
    expect(screen.queryByRole("option", { name: "Ask @Subscription" })).not.toBeInTheDocument();
    await user.click(screen.getByRole("option", { name: "Ask @Writer" }));
    expect(apiClient.post).not.toHaveBeenCalled();
    await user.type(screen.getByRole("textbox"), "Check this");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({ content: "Check this", agent_id: "Writer" }),
      ),
    );
  });

  it("hides posting and cancellation for a reader without project use", async () => {
    canPost = false;
    requestItems = [request("mine", "me", "queued")];
    render(room(), { wrapper });
    await screen.findByText(
      "You can read this room. Posting requires permission to use its project.",
    );
    expect(screen.queryByRole("textbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Post message" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Cancel request" })).not.toBeInTheDocument();
    expect(screen.getByText("Queued")).toBeInTheDocument();
  });

  it("preserves an uncertain attempt across a failed queue read and access recovery", async () => {
    const user = userEvent.setup();
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Connection lost"));
    render(room(), { wrapper });
    await user.type(await screen.findByRole("textbox"), "Do this once");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await screen.findByRole("button", { name: "Retry same message" });
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/orgs") return { items: [] };
      throw new ApiError(503, "Queue unavailable");
    });
    act(changed);
    await screen.findByText("Queue unavailable");
    expect(screen.queryByRole("button", { name: "Post message" })).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockResolvedValue({ items: [], total: 0, can_post: true });
    await user.click(screen.getByRole("button", { name: "Try again" }));
    await user.click(await screen.findByRole("button", { name: "Retry same message" }));
    await waitFor(() => expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first));
  });

  it("does not reset room B's draft when a slow post from room A succeeds", async () => {
    let resolve!: (result: RoomMessageResult) => void;
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise<RoomMessageResult>((yes) => {
        resolve = yes;
      }),
    );
    const user = userEvent.setup();
    const { rerender } = render(room(), { wrapper });
    await user.type(await screen.findByRole("textbox"), "From A");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    act(() => useConversationStore.setState({ currentConversationId: "room-b" }));
    rerender(room("room-b"));
    await user.type(await screen.findByRole("textbox"), "Draft B");
    await act(async () => resolve(saved));
    expect(screen.getByRole("textbox")).toHaveValue("Draft B");
    expect(screen.getByRole("button", { name: "Post message" })).toBeEnabled();
  });

  it("shows the shared queue and lets only the requester cancel a queued request", async () => {
    requestItems = [
      request("mine", "me", "queued"),
      request("theirs", "other", "queued"),
      request("working", "me", "running"),
    ];
    const user = userEvent.setup();
    render(room(), { wrapper });
    await screen.findByText("Working");
    expect(screen.getAllByRole("button", { name: "Cancel request" })).toHaveLength(1);
    expect(screen.getByRole("link", { name: "View run" })).toHaveAttribute(
      "href",
      "/runs?run=run-a",
    );
    await user.click(screen.getByRole("button", { name: "Cancel request" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-requests/mine/cancel",
        {},
      ),
    );
  });

  it("does not submit Enter while an IME is composing", async () => {
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    fireEvent.change(input, { target: { value: "你好" } });
    fireEvent.keyDown(input, { key: "Enter", isComposing: true });
    expect(apiClient.post).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter", shiftKey: true });
    expect(apiClient.post).not.toHaveBeenCalled();
    fireEvent.keyDown(input, { key: "Enter" });
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
  });
});

it("keeps the shared audience and project sharing visible when the reader is alone", () => {
  project.can_edit = false;
  render(<TeamRoomHeader projectId="project-a" present={[]} />, { wrapper });
  expect(screen.getByRole("link", { name: "Team room · Launch" })).toHaveAttribute(
    "href",
    "/projects/project-a",
  );
  expect(
    screen.getByText("Everyone with access to this project can read this room."),
  ).toBeInTheDocument();
  expect(screen.getByText("You're the only person here right now.")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Share project" })).toHaveAttribute(
    "data-can-manage",
    "false",
  );
});

it("opens a new shared room before anyone asks an agent", async () => {
  vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "new-room", project_id: "project-a" });
  const user = userEvent.setup();
  render(<StartTeamRoom projectId="project-a" />, { wrapper });
  await user.click(screen.getByRole("button", { name: "New team room" }));
  await waitFor(() => expect(push).toHaveBeenCalledWith("/chat?id=new-room"));
  expect(apiClient.post).toHaveBeenCalledWith("/conversations", {
    project_id: "project-a",
    title: "Team room",
  });
});

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { announceRoomChange } from "@/lib/room-events";
import { useRoomDraft } from "@/hooks/use-room-draft";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { Agent } from "@/types/agents";
import type { Project } from "@/types/projects";
import type { FileUploadResponse } from "@/lib/file-api";
import type { RoomAgentRequest, RoomMessageResult, RoomParticipantRead } from "@/types/room";
import { toast } from "sonner";
import { StartTeamRoom } from "@/components/projects/start-team-room";
import { RoomComposer, TeamRoomComposer } from "./team-room-composer";
import { TeamRoomHeader } from "./team-room-header";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), upload: vi.fn() },
}));
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
let project: Project | undefined;
let projectLoading = false;
vi.mock("@/hooks/use-agents", () => ({ useAgents: () => ({ agents }) }));
vi.mock("@/hooks/use-projects", () => ({
  useProject: () => ({ project, isLoading: projectLoading }),
}));
let client: QueryClient;
let canPost: boolean;
let requestItems: RoomAgentRequest[];
let mentionables: RoomParticipantRead[];
let leadPolicy: {
  enabled: boolean;
  revision: number;
  lead: { agent_id: string; version_id: string; name: string; current: boolean } | null;
  specialists: never[];
  max_items: number;
  can_edit: boolean;
  can_ask: boolean;
};
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
function participant(
  kind: "user" | "agent",
  id: string,
  name: string,
  changes: Partial<RoomParticipantRead> = {},
): RoomParticipantRead {
  return {
    kind,
    id,
    name,
    avatar_url: null,
    is_member: true,
    can_add: false,
    can_mention: true,
    auto_reply: false,
    ...changes,
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
function threadRoom(rootId: string) {
  return <ThreadRoom rootId={rootId} />;
}
function ThreadRoom({ rootId }: { rootId: string }) {
  const draft = useRoomDraft("room-a", rootId);
  return (
    <RoomComposer
      conversationId="room-a"
      draft={draft}
      threadRootMessageId={rootId}
      readOnly={false}
      onTyping={vi.fn()}
    />
  );
}
function changed() {
  announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" });
}

async function getFilePicker(container: HTMLElement): Promise<HTMLInputElement> {
  await screen.findByRole("button", { name: /attach/i });
  const picker = container.querySelector<HTMLInputElement>('input[type="file"]');
  expect(picker).not.toBeNull();
  return picker!;
}

beforeEach(() => {
  vi.clearAllMocks();
  projectLoading = false;
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  useAuthStore.setState({
    user: { id: "me", email: "me@example.com", is_active: true, created_at: "" },
  });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a" });
  useChatStore.setState({ messages: [], replyTo: null, roomDrafts: {} });
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
  leadPolicy = {
    enabled: false,
    revision: 0,
    lead: null,
    specialists: [],
    max_items: 3,
    can_edit: true,
    can_ask: false,
  };
  mentionables = [];
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path === "/orgs"
      ? { items: [] }
      : path.endsWith("/room-mentionables")
        ? { items: mentionables }
        : path.endsWith("/lead-policy")
          ? leadPolicy
          : { items: requestItems, total: requestItems.length, can_post: canPost },
  );
  vi.mocked(apiClient.post).mockResolvedValue(saved);
  vi.mocked(apiClient.upload).mockResolvedValue({
    id: "file-a",
    filename: "notes.txt",
    mime_type: "text/plain",
    size: 5,
    file_type: "text",
    preview: null,
  } satisfies FileUploadResponse);
});
afterEach(() => client.clear());

describe("the room composer", () => {
  it("defaults to people and does not treat typed @names as responder selection", async () => {
    leadPolicy = {
      ...leadPolicy,
      enabled: true,
      revision: 7,
      lead: { agent_id: "Writer", version_id: "pinned-version", name: "Writer", current: true },
      can_ask: true,
    };
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
      mentions: [],
    });
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue(""));
  });

  it("asks the configured lead with its policy revision and no client-selected agent", async () => {
    leadPolicy = {
      ...leadPolicy,
      enabled: true,
      revision: 7,
      lead: { agent_id: "Writer", version_id: "pinned-version", name: "Writer", current: false },
      can_ask: true,
    };
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.click(await screen.findByRole("button", { name: "Ask lead" }));
    const input = screen.getByRole("textbox");
    await user.type(input, "Propose the next steps");
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/conversations/room-a/room-messages", {
        client_message_id: expect.any(String),
        content: "Propose the next steps",
        intent: "ask_lead",
        expected_policy_revision: 7,
        mentions: [],
      }),
    );
  });

  it.each([
    ["a lost acknowledgement", new TypeError("Connection lost")],
    ["an unspecified conflict", new ApiError(409, "Admission outcome unknown")],
  ])("retries the frozen lead intent after %s and a policy change", async (_name, failure) => {
    leadPolicy = {
      ...leadPolicy,
      enabled: true,
      revision: 7,
      lead: { agent_id: "Writer", version_id: "pinned-version", name: "Writer", current: true },
      can_ask: true,
    };
    vi.mocked(apiClient.post).mockRejectedValueOnce(failure);
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.click(await screen.findByRole("button", { name: "Ask lead" }));
    await user.type(screen.getByRole("textbox"), "Plan this once");
    await user.keyboard("{Enter}");
    await screen.findByRole("button", { name: "Retry same message" });
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    expect(first).toMatchObject({ intent: "ask_lead", expected_policy_revision: 7 });
    leadPolicy = { ...leadPolicy, revision: 8, enabled: false, can_ask: false };
    act(changed);
    await user.click(screen.getByRole("button", { name: "Retry same message" }));
    await waitFor(() => expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first));
  });

  it("unlocks a first policy refusal and reloads the lead before explicit resubmission", async () => {
    leadPolicy = {
      ...leadPolicy,
      enabled: true,
      revision: 7,
      lead: { agent_id: "Writer", version_id: "pinned-version", name: "Writer", current: true },
      can_ask: true,
    };
    vi.mocked(apiClient.post).mockImplementationOnce(async () => {
      leadPolicy = {
        ...leadPolicy,
        revision: 8,
        lead: { agent_id: "Analyst", version_id: "new-version", name: "Analyst", current: true },
      };
      throw new ApiError(409, "Room lead policy changed", {
        error: { code: "ROOM_LEAD_POLICY_CHANGED", message: "Room lead policy changed" },
      });
    });
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.click(await screen.findByRole("button", { name: "Ask lead" }));
    await user.type(screen.getByRole("textbox"), "Plan this once");
    await user.keyboard("{Enter}");
    const first = vi.mocked(apiClient.post).mock.calls[0]![1] as {
      client_message_id: string;
    };
    await waitFor(() => expect(screen.getByRole("textbox")).toHaveValue("Plan this once"));
    expect(screen.getAllByRole("button", { name: "Ask lead" })[0]).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "The room lead changed. Review the current lead and send again.",
    );
    expect(screen.getByRole("textbox")).toHaveValue("Plan this once");
    await user.type(screen.getByRole("textbox"), " reviewed");
    await user.keyboard("{Enter}");
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toMatchObject({
      content: "Plan this once reviewed",
      intent: "ask_lead",
      expected_policy_revision: 8,
    });
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).not.toMatchObject({
      client_message_id: first.client_message_id,
    });
  });

  it("retains an uncertain lead token when a later retry receives a policy refusal", async () => {
    leadPolicy = {
      ...leadPolicy,
      enabled: true,
      revision: 7,
      lead: { agent_id: "Writer", version_id: "pinned-version", name: "Writer", current: true },
      can_ask: true,
    };
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new TypeError("Connection lost"))
      .mockRejectedValueOnce(
        new ApiError(409, "Room lead policy changed", {
          error: { code: "ROOM_LEAD_POLICY_CHANGED", message: "Room lead policy changed" },
        }),
      );
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.click(await screen.findByRole("button", { name: "Ask lead" }));
    await user.type(screen.getByRole("textbox"), "Plan this once");
    await user.keyboard("{Enter}");
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    await user.click(await screen.findByRole("button", { name: "Retry same message" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Room lead policy changed"),
    );
    await user.click(screen.getByRole("button", { name: "Retry same message" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(3));
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
    expect(vi.mocked(apiClient.post).mock.calls[2]![1]).toEqual(first);
  });

  it("does not silently add an eligible outsider when it is selected for mention", async () => {
    const outsider = participant("agent", "writer", "Writer", {
      is_member: false,
      can_add: true,
      can_mention: false,
    });
    mentionables = [outsider];
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.type(input, "Please ask @Writer");
    await user.click(
      await screen.findByRole("option", { name: "Writer, Agents, Add before mentioning" }),
    );
    expect(await screen.findByRole("alertdialog")).toHaveTextContent("Add Writer to this room?");
    expect(apiClient.post).not.toHaveBeenCalledWith(
      "/conversations/room-a/participants",
      expect.anything(),
    );
    vi.mocked(apiClient.post).mockImplementation(async (path) =>
      String(path).endsWith("/participants")
        ? participant("agent", "writer", "Writer", { can_mention: true })
        : saved,
    );
    await user.click(screen.getByRole("button", { name: "Add and mention" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/conversations/room-a/participants", {
        kind: "agent",
        id: "writer",
      }),
    );
    await waitFor(() => expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument());
    expect(input).toHaveValue("Please ask @Writer ");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({
          content: "Please ask @Writer",
          mentions: [{ kind: "agent", id: "writer" }],
        }),
      ),
    );
  });

  it("keeps the converted room draft and hides the project-only Ask Lead control", async () => {
    const consumeInitialContent = vi.fn(() => "A draft from the existing chat");
    render(
      <TeamRoomComposer
        conversationId="room-a"
        projectId={null}
        readOnly={false}
        onTyping={vi.fn()}
        consumeInitialContent={consumeInitialContent}
      />,
      { wrapper },
    );
    expect(await screen.findByRole("textbox")).toHaveValue("A draft from the existing chat");
    expect(consumeInitialContent).toHaveBeenCalledOnce();
    expect(screen.queryByRole("button", { name: "Ask lead" })).not.toBeInTheDocument();
    expect(apiClient.get).not.toHaveBeenCalledWith("/conversations/room-a/lead-policy");
  });

  it("submits duplicate visible names as distinct structured people and agent mentions", async () => {
    mentionables = [participant("agent", "writer", "Alex"), participant("user", "person", "Alex")];
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.type(input, "Hi @");
    expect(await screen.findByRole("option", { name: "Alex, Agents" })).toBeVisible();
    expect(screen.getAllByRole("option")).toHaveLength(2);
    await user.click(screen.getByRole("option", { name: "Alex, People" }));
    await user.type(input, "@");
    expect(await screen.findByRole("option", { name: "Alex, Agents" })).toBeVisible();
    await user.keyboard("{ArrowDown}{Enter}");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({
          content: "Hi @Alex @Alex",
          mentions: [
            { kind: "user", id: "person" },
            { kind: "agent", id: "writer" },
          ],
        }),
      ),
    );
  });

  it.each([
    ["first", "agent", "writer"],
    ["second", "user", "person"],
  ] as const)(
    "deleting the %s identical mention preserves only the other identity",
    async (position, expectedKind, expectedId) => {
      mentionables = [
        participant("agent", "writer", "Alex"),
        participant("user", "person", "Alex"),
      ];
      const user = userEvent.setup();
      render(room(), { wrapper });
      const input = await screen.findByRole<HTMLTextAreaElement>("textbox", {
        name: "Message to the team",
      });

      await user.type(input, "Hi @");
      await user.click(await screen.findByRole("option", { name: "Alex, People" }));
      await user.type(input, "@");
      await screen.findByRole("option", { name: "Alex, Agents" });
      await user.keyboard("{ArrowDown}{Enter}");
      await waitFor(() => expect(input).toHaveValue("Hi @Alex @Alex "));

      const start =
        position === "first" ? input.value.indexOf("@Alex") : input.value.lastIndexOf("@Alex");
      act(() => input.setSelectionRange(start, start + "@Alex".length + 1));
      await user.keyboard("{Backspace}");
      await waitFor(() => expect(input).toHaveValue("Hi @Alex "));
      await user.click(screen.getByRole("button", { name: "Post message" }));

      await waitFor(() =>
        expect(apiClient.post).toHaveBeenCalledWith(
          "/conversations/room-a/room-messages",
          expect.objectContaining({
            content: "Hi @Alex",
            mentions: [{ kind: expectedKind, id: expectedId }],
          }),
        ),
      );
    },
  );

  it("blocks posting after an upload failure and allows a captionless attachment retry", async () => {
    vi.mocked(apiClient.upload).mockRejectedValueOnce(new Error("Upload unavailable"));
    const user = userEvent.setup();
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });

    fireEvent.change(picker, { target: { files: [file] } });
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Post message" })).toBeDisabled();
    expect(apiClient.post).not.toHaveBeenCalled();

    fireEvent.change(picker, { target: { files: [file] } });
    await screen.findByText("notes.txt");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({ content: "", file_ids: ["file-a"] }),
      ),
    );
    expect(apiClient.upload).toHaveBeenCalledTimes(2);
  });

  it("lets the person discard a failed upload and send the remaining draft", async () => {
    vi.mocked(apiClient.upload).mockRejectedValueOnce(new Error("Upload unavailable"));
    const user = userEvent.setup();
    const { container } = render(room(), { wrapper });
    await user.type(await screen.findByRole("textbox"), "Keep this text");
    const picker = await getFilePicker(container);
    fireEvent.change(picker, {
      target: { files: [new File(["notes"], "notes.txt", { type: "text/plain" })] },
    });
    await screen.findByRole("alert");
    expect(screen.getByRole("button", { name: "Post message" })).toBeDisabled();

    await user.click(screen.getByRole("button", { name: "Discard failed upload" }));
    expect(screen.getByRole("button", { name: "Post message" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({ content: "Keep this text" }),
      ),
    );
    expect(apiClient.post).not.toHaveBeenCalledWith(
      "/conversations/room-a/room-messages",
      expect.objectContaining({ file_ids: expect.anything() }),
    );
  });

  it("keeps an upload pending across a room remount and attaches it after returning", async () => {
    let resolveUpload!: (file: FileUploadResponse) => void;
    vi.mocked(apiClient.upload).mockReturnValueOnce(
      new Promise<FileUploadResponse>((resolve) => {
        resolveUpload = resolve;
      }),
    );
    const user = userEvent.setup();
    const { container, rerender } = render(room("room-a"), { wrapper });
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    const picker = await getFilePicker(container);
    fireEvent.change(picker, { target: { files: [file] } });
    expect(await screen.findByText("notes.txt")).toBeVisible();
    expect(screen.getByRole("button", { name: "Post message" })).toBeDisabled();

    act(() => useConversationStore.setState({ currentConversationId: "room-b" }));
    rerender(room("room-b"));
    await user.type(await screen.findByRole("textbox"), "Room B remains independent");
    expect(screen.getByRole("button", { name: "Post message" })).toBeEnabled();

    act(() => useConversationStore.setState({ currentConversationId: "room-a" }));
    rerender(room("room-a"));
    expect(screen.getByText("notes.txt")).toBeVisible();
    expect(screen.getByRole("button", { name: "Post message" })).toBeDisabled();

    await act(async () =>
      resolveUpload({
        id: "file-a",
        filename: "notes.txt",
        mime_type: "text/plain",
        size: 5,
        file_type: "text",
        preview: null,
      }),
    );
    expect(screen.getByRole("button", { name: "Post message" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({ content: "", file_ids: ["file-a"] }),
      ),
    );
  });

  it("keeps a failed upload blocked across a room remount until the user retries it", async () => {
    vi.mocked(apiClient.upload).mockRejectedValueOnce(new Error("Upload unavailable"));
    const user = userEvent.setup();
    const { container, rerender } = render(room("room-a"), { wrapper });
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    const picker = await getFilePicker(container);
    fireEvent.change(picker, { target: { files: [file] } });
    await screen.findByRole("alert");

    act(() => useConversationStore.setState({ currentConversationId: "room-b" }));
    rerender(room("room-b"));
    act(() => useConversationStore.setState({ currentConversationId: "room-a" }));
    rerender(room("room-a"));
    expect(screen.getByRole("alert")).toHaveTextContent("notes.txt: Upload unavailable");
    expect(screen.getByRole("button", { name: "Post message" })).toBeDisabled();

    const retryPicker = await getFilePicker(container);
    fireEvent.change(retryPicker, { target: { files: [file] } });
    await waitFor(() => expect(screen.getByRole("button", { name: "Post message" })).toBeEnabled());
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({ content: "", file_ids: ["file-a"] }),
      ),
    );
  });

  it("does not start another file upload after the account organization scope changes", async () => {
    let resolveFirst!: (file: FileUploadResponse) => void;
    vi.mocked(apiClient.upload).mockReturnValueOnce(
      new Promise<FileUploadResponse>((resolve) => {
        resolveFirst = resolve;
      }),
    );
    const user = userEvent.setup();
    const { container } = render(room("room-a"), { wrapper });
    const picker = await getFilePicker(container);
    const first = new File(["one"], "one.txt", { type: "text/plain" });
    const second = new File(["two"], "two.txt", { type: "text/plain" });
    fireEvent.change(picker, { target: { files: [first, second] } });
    expect(apiClient.upload).toHaveBeenCalledTimes(1);

    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    await act(async () =>
      resolveFirst({
        id: "file-a",
        filename: "one.txt",
        mime_type: "text/plain",
        size: 3,
        file_type: "text",
        preview: null,
      }),
    );
    expect(apiClient.upload).toHaveBeenCalledTimes(1);

    act(() => useOrgStore.setState({ activeOrgId: "org-a" }));
    await screen.findByText(/An upload stopped after your account or organization changed\./);
    expect(screen.getByRole("button", { name: "Post message" })).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Discard failed upload" }));
    expect(screen.getByRole("button", { name: "Post message" })).toBeEnabled();
  });

  it("keeps an upload attached to its original thread draft when switching roots", async () => {
    let resolveUpload!: (file: FileUploadResponse) => void;
    vi.mocked(apiClient.upload).mockReturnValueOnce(
      new Promise<FileUploadResponse>((resolve) => {
        resolveUpload = resolve;
      }),
    );
    const user = userEvent.setup();
    const { container, rerender } = render(threadRoom("root-a"), { wrapper });
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    const picker = await getFilePicker(container);
    fireEvent.change(picker, { target: { files: [file] } });
    expect(await screen.findByText("notes.txt")).toBeVisible();

    rerender(threadRoom("root-b"));
    expect(screen.getByRole("button", { name: "Post reply" })).toBeDisabled();
    rerender(threadRoom("root-a"));
    expect(screen.getByText("notes.txt")).toBeVisible();
    expect(screen.getByRole("button", { name: "Post reply" })).toBeDisabled();

    await act(async () =>
      resolveUpload({
        id: "file-a",
        filename: "notes.txt",
        mime_type: "text/plain",
        size: 5,
        file_type: "text",
        preview: null,
      }),
    );
    expect(screen.getByRole("button", { name: "Post reply" })).toBeEnabled();
    await user.click(screen.getByRole("button", { name: "Post reply" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({
          content: "",
          file_ids: ["file-a"],
          thread_root_message_id: "root-a",
        }),
      ),
    );
  });

  it("retries an uncertain attachment post with the same uploaded file id", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Acknowledgement lost"));
    const user = userEvent.setup();
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    fireEvent.change(picker, { target: { files: [file] } });
    await screen.findByText("notes.txt");

    await user.click(screen.getByRole("button", { name: "Post message" }));
    await screen.findByRole("button", { name: "Retry same message" });
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    expect(first).toMatchObject({ content: "", file_ids: ["file-a"] });

    await user.click(screen.getByRole("button", { name: "Retry same message" }));
    await waitFor(() => expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first));
    expect(apiClient.upload).toHaveBeenCalledTimes(1);
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

function ActionsRoom({ actionsSlot }: { actionsSlot: ReactNode }) {
  const draft = useRoomDraft("room-a");
  return (
    <RoomComposer
      conversationId="room-a"
      draft={draft}
      readOnly={false}
      onTyping={vi.fn()}
      actionsSlot={actionsSlot}
    />
  );
}

describe("the room composer edges", () => {
  function bigFile(name: string) {
    const file = new File(["x"], name, { type: "text/plain" });
    Object.defineProperty(file, "size", { value: 11 * 1024 * 1024 });
    return file;
  }
  function pickable(changes: Partial<RoomParticipantRead> = {}) {
    return participant("agent", "writer", "Writer", {
      is_member: false,
      can_add: true,
      can_mention: false,
      ...changes,
    });
  }

  it("tells a reader without a project that the room is read-only", () => {
    render(
      <TeamRoomComposer
        conversationId={null}
        projectId={null}
        readOnly={false}
        onTyping={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText(/You can read this room/)).toBeVisible();
  });

  it.each([
    ["is still loading", false, true, "Checking room access"],
    ["is not usable by the viewer", false, false, "You can read this room"],
    ["is read-only for the viewer", true, false, "You can read this room"],
  ])("explains a project room that %s", (_name, readOnly, loading, text) => {
    projectLoading = loading;
    project = loading ? undefined : { ...project!, can_use: false };
    render(
      <TeamRoomComposer
        conversationId={null}
        projectId="project-a"
        readOnly={readOnly}
        onTyping={vi.fn()}
      />,
      { wrapper },
    );
    expect(screen.getByText(new RegExp(text))).toBeVisible();
  });

  it("starts a room from the empty state and reports the new room and project", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "new-room", project_id: "project-a" });
    const onRoomCreated = vi.fn(() => true);
    const user = userEvent.setup();
    render(
      <TeamRoomComposer
        conversationId={null}
        projectId="project-a"
        readOnly={false}
        onTyping={vi.fn()}
        onRoomCreated={onRoomCreated}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: "New team room" }));
    await waitFor(() => expect(onRoomCreated).toHaveBeenCalledWith("new-room", "project-a"));
  });

  it("shows the actions slot beside a reader's notice", async () => {
    canPost = false;
    render(<ActionsRoom actionsSlot={<button type="button">Extra action</button>} />, { wrapper });
    expect(await screen.findByText(/You can read this room/)).toBeVisible();
    expect(screen.getByRole("button", { name: "Extra action" })).toBeInTheDocument();
  });

  it("limits a room message to ten files and rejects an oversized one", async () => {
    const toastError = vi.spyOn(toast, "error").mockImplementation(() => "");
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    const files = Array.from(
      { length: 11 },
      (_unused, index) => new File(["x"], `f${index}.txt`, { type: "text/plain" }),
    );
    fireEvent.change(picker, { target: { files } });
    await waitFor(() => expect(apiClient.upload).toHaveBeenCalledTimes(10));
    expect(toastError).toHaveBeenCalledWith("A room message can include up to 10 files.");
    await waitFor(() => expect(screen.getByRole("button", { name: /attach/i })).toBeEnabled());
    toastError.mockClear();

    fireEvent.change(picker, { target: { files: [bigFile("huge.bin")] } });
    expect(toastError).toHaveBeenCalledWith("huge.bin: File too large. Maximum 10MB.");
    expect(apiClient.upload).toHaveBeenCalledTimes(10);
    toastError.mockRestore();
  });

  it("ignores an empty file selection and a missing file list", async () => {
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    fireEvent.change(picker, { target: { files: [] } });
    Object.defineProperty(picker, "files", { value: null, configurable: true });
    fireEvent.change(picker);
    expect(apiClient.upload).not.toHaveBeenCalled();
  });

  it("accepts pasted files and leaves plain text pastes alone", async () => {
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    fireEvent.paste(input, { clipboardData: { files: [] } });
    expect(apiClient.upload).not.toHaveBeenCalled();
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    fireEvent.paste(input, { clipboardData: { files: [file] } });
    await screen.findByText("notes.txt");
    expect(apiClient.upload).toHaveBeenCalledTimes(1);
  });

  it("removes an attached file, then freezes the files and reply once a post is uncertain", async () => {
    useChatStore.setState({ replyTo: { messageId: "m1", role: "user", excerpt: "Earlier note" } });
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Connection lost"));
    const user = userEvent.setup();
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    expect(await screen.findByRole("button", { name: "Don't reply" })).toBeVisible();
    const notes = () => new File(["notes"], "notes.txt", { type: "text/plain" });
    fireEvent.change(picker, { target: { files: [notes()] } });
    await user.click(await screen.findByRole("button", { name: "Remove notes.txt" }));
    expect(screen.queryByText("notes.txt")).not.toBeInTheDocument();

    fireEvent.change(picker, { target: { files: [notes()] } });
    await screen.findByText("notes.txt");
    await user.type(screen.getByRole("textbox"), "Hi");
    await user.click(screen.getByRole("button", { name: "Post message" }));
    await screen.findByRole("button", { name: "Retry same message" });
    expect(screen.queryByRole("button", { name: "Remove notes.txt" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Don't reply" })).not.toBeInTheDocument();
    expect(screen.getByText("Earlier note")).toBeVisible();
  });

  it("opens the file chooser from the attach button", async () => {
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    const click = vi.spyOn(picker, "click").mockImplementation(() => undefined);
    await userEvent.setup().click(screen.getByRole("button", { name: /attach/i }));
    expect(click).toHaveBeenCalledOnce();
  });

  it("cycles, dismisses and picks mentions by keyboard", async () => {
    mentionables = [participant("user", "ann", "Ann"), participant("user", "bob", "Bob")];
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole<HTMLTextAreaElement>("textbox");
    fireEvent.keyPress(input, { key: "@", charCode: 64, which: 64 });
    fireEvent.change(input, { target: { value: "@" } });
    await user.clear(input);
    await user.type(input, "@");
    await screen.findByRole("option", { name: "Ann, People" });
    await user.keyboard("{ArrowUp}");
    expect(screen.getByRole("option", { name: "Bob, People" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{ArrowDown}");
    expect(screen.getByRole("option", { name: "Ann, People" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    await user.type(input, "b");
    await screen.findByRole("option", { name: "Bob, People" });
    await user.keyboard("{Enter}");
    expect(input).toHaveValue("@Bob ");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("uploads files dropped on the page", async () => {
    render(room(), { wrapper });
    await screen.findByRole("textbox");
    const file = new File(["notes"], "notes.txt", { type: "text/plain" });
    fireEvent.drop(window, { dataTransfer: { types: ["Files"], files: [file] } });
    await screen.findByText("notes.txt");
    expect(apiClient.upload).toHaveBeenCalledTimes(1);
  });

  it("starts a room from the empty state without a creation callback", async () => {
    vi.mocked(apiClient.post).mockResolvedValueOnce({ id: "new-room", project_id: "project-a" });
    const user = userEvent.setup();
    render(
      <TeamRoomComposer
        conversationId={null}
        projectId="project-a"
        readOnly={false}
        onTyping={vi.fn()}
      />,
      { wrapper },
    );
    await user.click(screen.getByRole("button", { name: "New team room" }));
    await waitFor(() => expect(push).toHaveBeenCalledWith("/chat?id=new-room"));
  });

  it("starts only one upload when two selections arrive in the same tick", async () => {
    vi.mocked(apiClient.upload).mockReturnValueOnce(new Promise<FileUploadResponse>(() => {}));
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    const first = new File(["one"], "one.txt", { type: "text/plain" });
    const second = new File(["two"], "two.txt", { type: "text/plain" });
    act(() => {
      fireEvent.change(picker, { target: { files: [first] } });
      fireEvent.change(picker, { target: { files: [second] } });
    });
    expect(apiClient.upload).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("two.txt")).not.toBeInTheDocument();
  });

  it("stays quiet when an upload fails after its draft was discarded", async () => {
    const toastError = vi.spyOn(toast, "error").mockImplementation(() => "");
    let reject!: (error: Error) => void;
    vi.mocked(apiClient.upload).mockReturnValueOnce(
      new Promise<FileUploadResponse>((_resolve, fail) => {
        reject = fail;
      }),
    );
    const { container } = render(room(), { wrapper });
    const picker = await getFilePicker(container);
    fireEvent.change(picker, {
      target: { files: [new File(["one"], "one.txt", { type: "text/plain" })] },
    });
    await screen.findByText("one.txt");
    act(() => useChatStore.setState({ roomDrafts: {} }));
    await act(async () => reject(new Error("Gone")));
    expect(toastError).not.toHaveBeenCalled();
    toastError.mockRestore();
  });

  it("falls through to posting when Enter finds no mention match", async () => {
    mentionables = [participant("user", "ann", "Ann")];
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.type(input, "@zzz");
    await screen.findByText("No matching people or agents.");
    await user.keyboard("{ArrowDown}{ArrowUp}{Enter}");
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/room-messages",
        expect.objectContaining({ content: "@zzz" }),
      ),
    );
  });

  it("does nothing when a mention is neither addable nor mentionable", async () => {
    mentionables = [pickable({ is_member: true })];
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.type(input, "@Wri");
    await user.click(await screen.findByRole("option", { name: "Writer, Agents" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();
    expect(input).toHaveValue("@Wri");
  });

  it("can cancel adding an outsider, and shows why adding failed", async () => {
    mentionables = [pickable()];
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.type(input, "@Wri");
    await user.click(
      await screen.findByRole("option", { name: "Writer, Agents, Add before mentioning" }),
    );
    await user.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("alertdialog")).not.toBeInTheDocument();

    await user.type(input, "t");
    await user.click(
      await screen.findByRole("option", { name: "Writer, Agents, Add before mentioning" }),
    );
    vi.mocked(apiClient.post).mockRejectedValueOnce(new Error("Nope"));
    await user.click(screen.getByRole("button", { name: "Add and mention" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Nope");
    expect(input).toBeDisabled();
  });

  it("drops an add that finishes after the organization changed", async () => {
    mentionables = [pickable()];
    let finish!: (value: RoomParticipantRead) => void;
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.type(input, "@Wri");
    await user.click(
      await screen.findByRole("option", { name: "Writer, Agents, Add before mentioning" }),
    );
    vi.mocked(apiClient.post).mockReturnValueOnce(
      new Promise<RoomParticipantRead>((resolve) => {
        finish = resolve;
      }) as never,
    );
    await user.click(screen.getByRole("button", { name: "Add and mention" }));
    expect(await screen.findByRole("button", { name: "Adding…" })).toBeDisabled();
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    await act(async () => finish(participant("agent", "writer", "Writer")));
    expect(input).not.toHaveValue("@Writer ");
  });

  it("filters mentions to people while asking the lead, and toggles the lead off", async () => {
    leadPolicy = {
      ...leadPolicy,
      enabled: true,
      revision: 7,
      lead: { agent_id: "Writer", version_id: "v", name: "Writer", current: true },
      can_ask: true,
    };
    mentionables = [participant("user", "ann", "Ann"), participant("agent", "writer", "Writer")];
    const user = userEvent.setup();
    render(room(), { wrapper });
    await user.click(await screen.findByRole("button", { name: "Ask lead" }));
    await user.type(screen.getByRole("textbox"), "@");
    await screen.findByRole("option", { name: "Ann, People" });
    expect(screen.queryByRole("option", { name: "Writer, Agents" })).not.toBeInTheDocument();
    await user.click(screen.getAllByRole("button", { name: "Ask lead" })[0]!);
    expect(screen.getAllByRole("button", { name: "Ask lead" })[0]).toHaveAttribute(
      "aria-pressed",
      "false",
    );
  });

  it("refuses an empty send and retries a failed mention list", async () => {
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/orgs") return { items: [] };
      if (path.endsWith("/room-mentionables")) throw new ApiError(500, "Down");
      return { items: [], total: 0, can_post: true };
    });
    const user = userEvent.setup();
    render(room(), { wrapper });
    const input = await screen.findByRole("textbox");
    await user.click(input);
    await user.keyboard("{Enter}");
    expect(apiClient.post).not.toHaveBeenCalled();
    await user.type(input, "@");
    const calls = () =>
      vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.endsWith("/room-mentionables"))
        .length;
    const retry = await screen.findByRole("button", { name: "Try again" });
    const before = calls();
    await user.click(retry);
    await waitFor(() => expect(calls()).toBeGreaterThan(before));
  });
});

it("keeps the shared audience and project sharing visible when the reader is alone", () => {
  project!.can_edit = false;
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

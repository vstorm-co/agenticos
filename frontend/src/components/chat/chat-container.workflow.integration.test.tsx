import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { ChatContainer } from "./chat-container";
import {
  useAgentSelectionStore,
  useAuthStore,
  useChatStore,
  useConversationStore,
  useOrgStore,
} from "@/stores";

/**
 * A message addressed to a workflow, through the whole chat: the picker's
 * choice decides where the composer's words go, so a workflow picked there has
 * to be the thing that answers - not the agent socket the chat keeps open.
 */

const { get, post } = vi.hoisted(() => ({ get: vi.fn(), post: vi.fn() }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { get, post, patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
  ApiError: class extends Error {},
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const { agentSend } = vi.hoisted(() => ({ agentSend: vi.fn() }));
vi.mock("@/hooks/use-websocket", () => ({
  useWebSocket: () => ({
    isConnected: true,
    connect: vi.fn(),
    disconnect: vi.fn(),
    sendMessage: agentSend,
  }),
}));

class FakeSocket {
  static opened: FakeSocket[] = [];
  onopen: (() => void) | null = null;
  onmessage: ((event: MessageEvent<string>) => void) | null = null;
  onclose: (() => void) | null = null;
  constructor(public url: string) {
    FakeSocket.opened.push(this);
  }
  send() {}
  close() {}
}

const SIGNED_IN = { id: "u-1", email: "kacper@example.test", full_name: "Kacper" };
const WORKFLOW = {
  id: "wf-1",
  name: "Lead triage",
  description: null,
  status: "published",
  current_version_id: "v1",
};

beforeEach(() => {
  vi.clearAllMocks();
  FakeSocket.opened = [];
  vi.stubGlobal("WebSocket", FakeSocket);
  get.mockImplementation((url: string) =>
    url.startsWith("/auth/me")
      ? Promise.resolve({ ...SIGNED_IN, access_token: "t-1" })
      : url === "/me/permissions"
        ? Promise.resolve({
            organization_id: "org-1",
            role: "member",
            is_app_admin: false,
            permissions: [{ permission: "workflows:run", scope: "all" }],
          })
        : url === "/workflows"
          ? Promise.resolve({ items: [WORKFLOW], total: 1 })
          : Promise.resolve({ items: [], total: 0 }),
  );
  post.mockResolvedValue({
    id: "c-new",
    title: "t",
    created_at: "2026-09-29T10:00:00Z",
    updated_at: "2026-09-29T10:00:00Z",
    is_archived: false,
  });
  useAuthStore.setState({
    accessToken: "t-1",
    user: SIGNED_IN as never,
    sessionOwnerId: SIGNED_IN.id,
  });
  useOrgStore.setState({ activeOrgId: "org-1" });
  useConversationStore.getState().reset();
  useChatStore.getState().clearMessages();
});

afterEach(() => vi.unstubAllGlobals());

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <ChatContainer />
    </QueryClientProvider>,
  );
}

/** Send one of the empty state's suggested prompts, the shortest way to send. */
async function pickASuggestion() {
  await userEvent.click(await screen.findByRole("button", { name: /Brainstorm/ }));
}

describe("the chat with a workflow picked to answer", () => {
  it("sends the message to the workflow's socket, in a conversation it opens", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: null, selectedWorkflowId: "wf-1" });
    mount();
    await screen.findByRole("button", { name: "Agent: Lead triage" });

    await pickASuggestion();

    await waitFor(() => expect(FakeSocket.opened).toHaveLength(1));
    expect(FakeSocket.opened[0]?.url).toContain("/api/v1/ws/workflow-runs");
    expect(post).toHaveBeenCalledWith("/conversations", expect.anything());
    expect(agentSend).not.toHaveBeenCalled();
    expect(await screen.findByText("Lead triage", { selector: "p" })).toBeTruthy();
  });

  it("leaves the message with the agent when no workflow is picked", async () => {
    useAgentSelectionStore.setState({ selectedAgentId: null, selectedWorkflowId: null });
    mount();
    await screen.findByRole("button", { name: /^Agent:/ });

    await pickASuggestion();

    expect(FakeSocket.opened).toHaveLength(0);
  });
});

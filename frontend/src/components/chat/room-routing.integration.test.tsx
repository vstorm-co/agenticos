import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  act,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import * as intl from "next-intl";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { announceRoomChange, onRoomChange } from "@/lib/room-events";
import { useRoomDraft } from "@/hooks/use-room-draft";
import { useRoomDecisionAttempt, useRoomRoutingActions } from "@/hooks/use-room-routing";
import { useAuthStore, useChatStore, useConversationStore, useOrgStore } from "@/stores";
import type { Agent } from "@/types/agents";
import type { RoomLeadPolicy, RoomRoutingProposal, RoomTaskCard } from "@/types/room-routing";
import { RoomRoutingPanel } from "./room-routing-panel";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn() } }));
let agents: Agent[];
let agentsError: Error | null;
vi.mock("@/hooks/use-agents", () => ({
  useAgents: () => ({ agents, isLoading: false, error: agentsError }),
}));
let client: QueryClient;
let policy: RoomLeadPolicy;
let proposals: RoomRoutingProposal[];
let tasks: RoomTaskCard[];
const pin = { agent_id: "writer", version_id: "published-7", name: "Writer", current: false };
const user = (id = "me") => ({ id, email: `${id}@example.com`, is_active: true, created_at: "" });
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
function proposal(changes: Partial<RoomRoutingProposal> = {}): RoomRoutingProposal {
  return {
    id: "proposal-a",
    conversation_id: "room-a",
    thread_root_message_id: null,
    submission_id: "submission-a",
    message_id: "message-a",
    requester_id: "me",
    lead_run_id: "run-a",
    policy_revision: 7,
    revision: 1,
    decision: "pending",
    accepted_item_ids: [],
    can_accept: true,
    can_discard: true,
    created_at: "2026-11-16T00:00:00Z",
    items: [
      {
        proposal_item_id: "item-a",
        title: "Review the invoice batch",
        expected_result: "A checked reconciliation",
        accountable_user_id: "me",
        due_at: "2026-11-17T09:00:00Z",
        agent: pin,
        existing_task_id: null,
        expected_task_revision: null,
      },
    ],
    ...changes,
  };
}
function task(changes: Partial<RoomTaskCard> = {}): RoomTaskCard {
  return {
    id: "link-a",
    proposal_id: "proposal-a",
    proposal_item_id: "item-a",
    message_id: "message-a",
    thread_root_message_id: null,
    task_id: "task-a",
    table_id: "board-a",
    accepted_revision: 1,
    revision: 2,
    title: "Reconcile invoices",
    description: "Review the prepared reconciliation",
    status: "waiting_for_user",
    next_actor: "user",
    accountable_user_id: "me",
    agent: pin,
    due_at: "2026-11-17T09:00:00Z",
    ...changes,
  };
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (reason: unknown) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
function changed() {
  announceRoomChange({ conversationId: "room-a", accountId: "me", organizationId: "org-a" });
}
async function openPanel(props: Partial<React.ComponentProps<typeof RoomRoutingPanel>> = {}) {
  const interaction = userEvent.setup();
  const rendered = render(
    <RoomRoutingPanel conversationId="room-a" readOnly={false} {...props} />,
    { wrapper },
  );
  await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
  await screen.findByText("Lead: Writer");
  return { interaction, ...rendered };
}

beforeEach(() => {
  vi.clearAllMocks();
  vi.spyOn(intl, "useFormatter").mockReturnValue(
    intl.createFormatter({ locale: "en", timeZone: "UTC" }),
  );
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  useAuthStore.setState({ user: user() });
  useOrgStore.setState({ activeOrgId: "org-a" });
  useConversationStore.setState({ currentConversationId: "room-a" });
  useChatStore.getState().clearRoomDrafts();
  agents = [agent("writer", { name: "Writer" }), agent("analyst", { name: "Analyst" })];
  agentsError = null;
  policy = {
    enabled: true,
    revision: 7,
    lead: pin,
    specialists: [],
    max_items: 3,
    can_edit: true,
    can_ask: true,
  };
  proposals = [proposal()];
  tasks = [];
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/orgs") return { items: [] };
    if (path.endsWith("/lead-policy")) return policy;
    if (path.endsWith("/routing-proposals")) return { items: proposals, has_more: false };
    if (path.endsWith("/task-links")) return { items: tasks, has_more: false };
    if (path.endsWith("/routing-proposals/proposal-a")) return proposals[0];
    throw new Error(`Unexpected GET ${path}`);
  });
  vi.mocked(apiClient.put).mockImplementation(async () => policy);
  vi.mocked(apiClient.post).mockImplementation(async (path, input) => {
    const value = input as { selected_item_ids?: string[] };
    proposals = [
      proposal({
        decision: path.endsWith("/accept") ? "accepted" : "discarded",
        revision: 2,
        accepted_item_ids: value.selected_item_ids ?? [],
        can_accept: false,
        can_discard: false,
      }),
    ];
    return proposals[0];
  });
});
afterEach(() => {
  client.clear();
  vi.restoreAllMocks();
});

describe("room lead policy", () => {
  it("reads on opening without invoking the lead, and saves an explicit versioned policy", async () => {
    const { interaction } = await openPanel();
    expect(apiClient.post).not.toHaveBeenCalled();
    expect(apiClient.put).not.toHaveBeenCalled();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    const dialog = screen.getByRole("dialog", { name: "Configure lead" });
    await interaction.click(within(dialog).getByRole("checkbox", { name: "Writer" }));
    await interaction.click(within(dialog).getByRole("checkbox", { name: "Analyst" }));
    await interaction.click(within(dialog).getByRole("button", { name: "Save lead" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/conversations/room-a/lead-policy", {
        expected_revision: 7,
        enabled: true,
        lead_agent_id: "writer",
        specialist_agent_ids: ["writer", "analyst"],
        max_items: 3,
      }),
    );
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("edits the pinned specialists and task limit without adding unreviewed agents", async () => {
    policy = {
      ...policy,
      specialists: [pin, { ...pin, agent_id: "analyst", name: "Analyst" }],
    };
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByRole("checkbox", { name: "Writer" })).toBeChecked();
    expect(within(dialog).getByRole("checkbox", { name: "Analyst" })).toBeChecked();
    await interaction.click(within(dialog).getByRole("checkbox", { name: "Analyst" }));
    await interaction.click(
      within(dialog).getByRole("combobox", { name: "Maximum proposed tasks" }),
    );
    await interaction.click(screen.getByRole("option", { name: "1 task" }));
    await interaction.click(within(dialog).getByRole("button", { name: "Save lead" }));
    await waitFor(() =>
      expect(apiClient.put).toHaveBeenCalledWith("/conversations/room-a/lead-policy", {
        expected_revision: 7,
        enabled: true,
        lead_agent_id: "writer",
        specialist_agent_ids: ["writer"],
        max_items: 1,
      }),
    );
  });

  it("dismisses a policy draft without saving it", async () => {
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    await interaction.click(screen.getByRole("switch", { name: "Enable room lead" }));
    await interaction.keyboard("{Escape}");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiClient.put).not.toHaveBeenCalled();
    expect(screen.getByText("Lead: Writer")).toBeVisible();
  });

  it("admits one policy write and keeps its editor open until the response arrives", async () => {
    const pending = deferred<RoomLeadPolicy>();
    vi.mocked(apiClient.put).mockReturnValueOnce(pending.promise);
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    const dialog = screen.getByRole("dialog");
    const form = within(dialog).getByRole("button", { name: "Save lead" }).closest("form")!;
    act(() => {
      fireEvent.submit(form);
      fireEvent.submit(form);
    });
    expect(apiClient.put).toHaveBeenCalledTimes(1);
    expect(within(dialog).getByRole("button", { name: "Saving…" })).toBeDisabled();
    await interaction.keyboard("{Escape}");
    expect(dialog).toBeVisible();
    await act(async () => pending.resolve(policy));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
  });

  it("retains the edited policy after a non-conflict refusal", async () => {
    vi.mocked(apiClient.put).mockRejectedValueOnce(new ApiError(503, "Policy service unavailable"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    await interaction.click(screen.getByRole("checkbox", { name: "Analyst" }));
    await interaction.click(screen.getByRole("button", { name: "Save lead" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Policy service unavailable");
    expect(screen.getByRole("checkbox", { name: "Analyst" })).toBeChecked();
    expect(screen.getByRole("button", { name: "Save lead" })).toBeEnabled();
    await interaction.click(screen.getByRole("button", { name: "Cancel" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });

  it("allows disabling an unconfigured lead while agent permissions are unavailable", async () => {
    policy = { ...policy, enabled: false, lead: null, can_ask: false };
    agents = [];
    agentsError = new ApiError(503, "Agent read unavailable");
    const interaction = userEvent.setup();
    render(<RoomRoutingPanel conversationId="room-a" readOnly={false} />, { wrapper });
    await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
    await screen.findByText("No enabled room lead");
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    expect(screen.getByText("No runnable cloud agents are available.")).toBeVisible();
    expect(screen.getByRole("alert")).toHaveTextContent("Agent permissions could not be checked");
    await interaction.click(screen.getByRole("switch", { name: "Enable room lead" }));
    expect(screen.getByRole("button", { name: "Save lead" })).toBeDisabled();
    await interaction.click(screen.getByRole("switch", { name: "Enable room lead" }));
    await interaction.click(screen.getByRole("button", { name: "Save lead" }));
    expect(apiClient.put).toHaveBeenCalledWith("/conversations/room-a/lead-policy", {
      expected_revision: 7,
      enabled: false,
      lead_agent_id: null,
      specialist_agent_ids: [],
      max_items: 3,
    });
  });

  it("requires a runnable replacement before enabling an unavailable pinned lead", async () => {
    agents = [agent("analyst", { name: "Analyst" })];
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    expect(screen.getByRole("button", { name: "Save lead" })).toBeDisabled();
    await interaction.click(screen.getByRole("combobox", { name: "Lead agent" }));
    expect(
      screen.getByRole("option", { name: "The configured agent is unavailable to you." }),
    ).toHaveAttribute("aria-disabled", "true");
    await interaction.click(screen.getByRole("option", { name: "Analyst" }));
    await interaction.click(screen.getByRole("button", { name: "Save lead" }));
    expect(apiClient.put).toHaveBeenCalledWith(
      "/conversations/room-a/lead-policy",
      expect.objectContaining({ lead_agent_id: "analyst", expected_revision: 7 }),
    );
  });

  it("does not publish a late policy response into the next account", async () => {
    const pending = deferred<RoomLeadPolicy>();
    vi.mocked(apiClient.put).mockReturnValueOnce(pending.promise);
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    await interaction.click(screen.getByRole("button", { name: "Save lead" }));
    policy = { ...policy, enabled: false, lead: null, can_edit: false, can_ask: false };
    proposals = [];
    act(() => useAuthStore.setState({ user: user("other") }));
    await act(async () => pending.resolve({ ...policy, enabled: true, lead: pin }));
    await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
    expect(await screen.findByText("No enabled room lead")).toBeVisible();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(screen.queryByText("Lead: Writer")).not.toBeInTheDocument();
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });

  it("honors a read-only room even when a prior response allowed edits", async () => {
    await openPanel({ readOnly: true });
    expect(screen.queryByRole("button", { name: "Configure lead" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept selected" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard proposal" })).not.toBeInTheDocument();
  });

  it("offers only published, runnable cloud agents", async () => {
    agents.push(
      agent("private", { can_run: false }),
      agent("draft", { status: "draft" }),
      agent("desktop", { local_workspace: true }),
      agent("coding", { local_coding_agent: { harness: "codex", access: "read_only" } }),
      agent("subscription", { personal_coding_harness: "codex" }),
    );
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    const dialog = screen.getByRole("dialog");
    await interaction.click(within(dialog).getByRole("combobox", { name: "Lead agent" }));
    expect(screen.getByRole("option", { name: "Writer" })).toBeVisible();
    expect(screen.getByRole("option", { name: "Analyst" })).toBeVisible();
    for (const name of ["private", "draft", "desktop", "coding", "subscription"])
      expect(screen.queryByRole("option", { name })).not.toBeInTheDocument();
  });

  it("requires a reload after a policy conflict instead of overwriting it", async () => {
    vi.mocked(apiClient.put).mockRejectedValueOnce(new ApiError(409, "stale policy"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Configure lead" }));
    await interaction.click(screen.getByRole("button", { name: "Save lead" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("The room policy changed");
    expect(screen.queryByRole("button", { name: "Save lead" })).not.toBeInTheDocument();
    policy = { ...policy, revision: 8 };
    await interaction.click(screen.getByRole("button", { name: "Reload policy" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).not.toBeInTheDocument());
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });

  it("shows read-only state without exposing policy or decision controls", async () => {
    policy = { ...policy, can_edit: false, can_ask: false };
    proposals = [proposal({ can_accept: false, can_discard: false })];
    await openPanel();
    expect(screen.queryByRole("button", { name: "Configure lead" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept selected" })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Discard proposal" })).not.toBeInTheDocument();
    expect(screen.getByText("The requester must review this proposal.")).toBeVisible();
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

describe("human proposal decisions", () => {
  it("renders model text as text and accepts only the reviewed selection", async () => {
    proposals = [
      proposal({
        items: [
          { ...proposal().items[0]!, title: "<script>untrusted()</script>" },
          {
            ...proposal().items[0]!,
            proposal_item_id: "item-b",
            title: "A separate task",
            existing_task_id: "task-b",
            expected_task_revision: 4,
          },
        ],
      }),
    ];
    vi.mocked(apiClient.post).mockImplementationOnce(async (_path, input) => {
      proposals = [
        {
          ...proposals[0]!,
          decision: "accepted",
          revision: 2,
          accepted_item_ids: (input as { selected_item_ids: string[] }).selected_item_ids,
          can_accept: false,
          can_discard: false,
        },
      ];
      return proposals[0];
    });
    const { interaction } = await openPanel();
    expect(screen.getByText("<script>untrusted()</script>")).toBeVisible();
    expect(document.querySelector("script")).toBeNull();
    expect(screen.getByRole("button", { name: "Accept selected" })).toBeDisabled();
    await interaction.click(screen.getByRole("checkbox", { name: "<script>untrusted()</script>" }));
    await interaction.click(screen.getByRole("checkbox", { name: "A separate task" }));
    await interaction.click(screen.getByRole("checkbox", { name: "A separate task" }));
    expect(apiClient.post).not.toHaveBeenCalled();
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/conversations/room-a/routing-proposals/proposal-a/accept",
        {
          expected_revision: 1,
          idempotency_key: expect.any(String),
          selected_item_ids: ["item-a"],
        },
      ),
    );
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(await screen.findByText("Accepted as a task")).toBeVisible();
    expect(screen.getByText("Not accepted")).toBeVisible();
    expect(
      screen.getByText("Updates an existing task only if it has not changed since this proposal."),
    ).toBeVisible();
  });

  it("reconciles a lost acknowledgement before retrying the identical decision token", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    const retry = await screen.findByRole("button", { name: "Check and retry" });
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    expect(screen.getByRole("checkbox")).toBeDisabled();
    await interaction.click(retry);
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
    const readIndex = vi
      .mocked(apiClient.get)
      .mock.calls.findIndex(([path]) => path.endsWith("/routing-proposals/proposal-a"));
    expect(readIndex).toBeGreaterThanOrEqual(0);
    expect(vi.mocked(apiClient.get).mock.invocationCallOrder[readIndex]).toBeLessThan(
      vi.mocked(apiClient.post).mock.invocationCallOrder[1]!,
    );
  });

  it("uses the committed decision after a lost acknowledgement without another POST", async () => {
    vi.mocked(apiClient.post).mockImplementationOnce(async () => {
      proposals = [
        proposal({
          decision: "accepted",
          revision: 2,
          accepted_item_ids: ["item-a"],
          can_accept: false,
          can_discard: false,
        }),
      ];
      throw new TypeError("Lost acknowledgement");
    });
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
    expect(await screen.findByText("Accepted as a task")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Check and retry" })).not.toBeInTheDocument();
  });

  it("refuses an uncertain replay when current decision authority was revoked", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    const retry = await screen.findByRole("button", { name: "Check and retry" });
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    proposals = [proposal({ can_accept: false, can_discard: false })];
    await interaction.click(retry);
    expect(await screen.findByText("The requester must review this proposal.")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Accept selected" })).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Check and retry" })).toBeEnabled();
    expect(Object.values(useChatStore.getState().roomDecisionAttempts)).toContainEqual({
      decision: "accept",
      input: first,
    });
    proposals = [proposal()];
    act(changed);
    await interaction.click(screen.getByRole("button", { name: "Check and retry" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
  });

  it("uses fresh permission and redaction metadata even when the proposal revision is unchanged", async () => {
    proposals = [
      proposal({
        items: [
          {
            ...proposal().items[0]!,
            accountable_user_id: "other",
            accountable_user_name: "Private teammate",
          },
        ],
      }),
    ];
    vi.mocked(apiClient.post)
      .mockRejectedValueOnce(new TypeError("Lost acknowledgement"))
      .mockRejectedValueOnce(new TypeError("Still uncertain"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    await waitFor(() => expect(screen.getByRole("alert")).toHaveTextContent("Still uncertain"));
    expect(screen.getByText("Private teammate")).toBeVisible();

    proposals = [
      proposal({
        can_accept: false,
        can_discard: false,
        items: [
          {
            ...proposal().items[0]!,
            accountable_user_id: null,
            accountable_user_name: null,
            agent: null,
          },
        ],
      }),
    ];
    act(changed);
    await waitFor(() => expect(screen.queryByText("Private teammate")).not.toBeInTheDocument());
    expect(screen.queryByText("Writer", { exact: true })).not.toBeInTheDocument();
    expect(screen.queryByRole("checkbox")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept selected" })).not.toBeInTheDocument();
    expect(screen.getByText("The requester must review this proposal.")).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(2);
  });

  it.each([403, 404, 409])(
    "retains the original decision after a reconciliation GET %s and remount",
    async (status) => {
      vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
      const { interaction, unmount } = await openPanel();
      await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
      await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
      await screen.findByRole("button", { name: "Check and retry" });
      const first = vi.mocked(apiClient.post).mock.calls[0]![1];
      const read = vi.mocked(apiClient.get).getMockImplementation()!;
      vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
        if (path.endsWith("/routing-proposals/proposal-a"))
          throw new ApiError(status, "Reconciliation read refused");
        return read(path, options);
      });
      await interaction.click(screen.getByRole("button", { name: "Check and retry" }));
      await waitFor(() =>
        expect(screen.getByRole("alert")).toHaveTextContent("Reconciliation read refused"),
      );
      expect(apiClient.post).toHaveBeenCalledTimes(1);
      expect(Object.values(useChatStore.getState().roomDecisionAttempts)).toContainEqual({
        decision: "accept",
        input: first,
      });

      unmount();
      vi.mocked(apiClient.get).mockImplementation(read);
      const recovered = await openPanel();
      await recovered.interaction.click(
        await screen.findByRole("button", { name: "Check and retry" }),
      );
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
      expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
    },
  );

  it.each([400, 403, 404, 422])(
    "keeps the earlier uncertain decision when a retry POST %s is refused before replay",
    async (status) => {
      vi.mocked(apiClient.post)
        .mockRejectedValueOnce(new TypeError("Lost acknowledgement"))
        .mockImplementationOnce(async () => {
          proposals = [proposal({ can_accept: false, can_discard: false })];
          throw new ApiError(status, "Write access changed");
        });
      const { interaction } = await openPanel();
      await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
      await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
      const first = vi.mocked(apiClient.post).mock.calls[0]![1];
      await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
      await waitFor(() =>
        expect(screen.getByRole("alert")).toHaveTextContent("Write access changed"),
      );
      expect(apiClient.get).toHaveBeenCalledWith(
        "/conversations/room-a/routing-proposals/proposal-a",
      );
      expect(apiClient.post).toHaveBeenCalledTimes(2);
      expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
      expect(Object.values(useChatStore.getState().roomDecisionAttempts)).toContainEqual({
        decision: "accept",
        input: first,
      });

      // The original write finishes after the earlier GET; the retry refusal did not settle it.
      proposals = [
        proposal({
          decision: "accepted",
          revision: 2,
          accepted_item_ids: ["item-a"],
          can_accept: false,
          can_discard: false,
        }),
      ];
      await interaction.click(screen.getByRole("button", { name: "Check and retry" }));
      expect(await screen.findByText("Accepted as a task")).toBeVisible();
      expect(apiClient.post).toHaveBeenCalledTimes(2);
      expect(Object.values(useChatStore.getState().roomDecisionAttempts)).not.toContainEqual({
        decision: "accept",
        input: first,
      });
    },
  );

  it("keeps the uncertain decision token through a refused read and recovery", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    await screen.findByRole("button", { name: "Check and retry" });
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    const prior = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path.endsWith("/routing-proposals"))
        throw new ApiError(503, "Read temporarily unavailable");
      return prior(path, options);
    });
    act(changed);
    expect(
      await screen.findByText("Proposals could not be read with your current access."),
    ).toBeVisible();
    expect(screen.queryByText("Review the invoice batch")).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockImplementation(prior);
    await interaction.click(screen.getByRole("button", { name: "Check again" }));
    await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(2));
    expect(vi.mocked(apiClient.post).mock.calls[1]![1]).toEqual(first);
  });

  it.each(["first decision", "uncertain retry"] as const)(
    "requires a fresh selection after a post-lock revision conflict on the %s",
    async (phase) => {
      if (phase === "uncertain retry")
        vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
      vi.mocked(apiClient.post).mockImplementationOnce(async () => {
        proposals = [proposal({ revision: 2 })];
        throw new ApiError(409, "Stale proposal revision");
      });
      const { interaction } = await openPanel();
      await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
      await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
      if (phase === "uncertain retry")
        await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Review the current proposal before deciding again",
      );
      await waitFor(() =>
        expect(screen.getByRole("button", { name: "Accept selected" })).toBeDisabled(),
      );
      expect(screen.getByRole("checkbox")).not.toBeChecked();
      const refusedAttempts = phase === "uncertain retry" ? 2 : 1;
      expect(apiClient.post).toHaveBeenCalledTimes(refusedAttempts);
      const refused = vi.mocked(apiClient.post).mock.calls.at(-1)![1] as {
        idempotency_key: string;
      };
      await interaction.click(screen.getByRole("checkbox"));
      await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
      await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(refusedAttempts + 1));
      expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).toMatchObject({
        expected_revision: 2,
        selected_item_ids: ["item-a"],
      });
      expect(vi.mocked(apiClient.post).mock.calls.at(-1)![1]).not.toMatchObject({
        idempotency_key: refused.idempotency_key,
      });
    },
  );

  it("discards explicitly without creating selected task items", async () => {
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Discard proposal" }));
    expect(await screen.findByText("Discarded", { exact: true })).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledWith(
      "/conversations/room-a/routing-proposals/proposal-a/discard",
      { expected_revision: 1, idempotency_key: expect.any(String) },
    );
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });

  it("retries an uncertain discard with its original token and current discard authority", async () => {
    proposals = [proposal({ can_accept: false, can_discard: true })];
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost discard acknowledgement"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("button", { name: "Discard proposal" }));
    const first = vi.mocked(apiClient.post).mock.calls[0]![1];
    await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
    expect(await screen.findByText("Discarded", { exact: true })).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(2);
    expect(vi.mocked(apiClient.post).mock.calls[1]).toEqual([
      "/conversations/room-a/routing-proposals/proposal-a/discard",
      first,
    ]);
    expect(first).not.toHaveProperty("selected_item_ids");
  });

  it("does not replay a decision after its reconciliation read outlives the account", async () => {
    vi.mocked(apiClient.post).mockRejectedValueOnce(new TypeError("Lost acknowledgement"));
    const { interaction } = await openPanel();
    await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
    await interaction.click(screen.getByRole("button", { name: "Accept selected" }));
    const pending = deferred<RoomRoutingProposal>();
    const read = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation((path, options) =>
      path.endsWith("/routing-proposals/proposal-a") ? pending.promise : read(path, options),
    );
    await interaction.click(await screen.findByRole("button", { name: "Check and retry" }));
    expect(screen.getByRole("button", { name: "Checking decision…" })).toBeDisabled();
    proposals = [];
    act(() => useAuthStore.setState({ user: user("other") }));
    await act(async () => pending.resolve(proposal()));
    await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
    expect(
      await screen.findByText("No proposals yet. Ask the lead to suggest work when you need it."),
    ).toBeVisible();
    expect(apiClient.post).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("button", { name: "Check and retry" })).not.toBeInTheDocument();
  });

  it.each(["accepted", "refused"] as const)(
    "keeps one in-flight decision and ignores its late %s result after switching accounts",
    async (outcome) => {
      const pending = deferred<RoomRoutingProposal>();
      vi.mocked(apiClient.post).mockReturnValueOnce(pending.promise);
      const { interaction } = await openPanel();
      await interaction.click(screen.getByRole("checkbox", { name: "Review the invoice batch" }));
      const accept = screen.getByRole("button", { name: "Accept selected" });
      act(() => {
        accept.click();
        accept.click();
      });
      expect(apiClient.post).toHaveBeenCalledTimes(1);
      proposals = [];
      policy = { ...policy, can_edit: false };
      act(() => useAuthStore.setState({ user: user("other") }));
      await act(async () => {
        if (outcome === "accepted")
          pending.resolve(
            proposal({ decision: "accepted", revision: 2, accepted_item_ids: ["item-a"] }),
          );
        else pending.reject(new ApiError(403, "Earlier account decision refused"));
      });
      await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
      expect(
        await screen.findByText("No proposals yet. Ask the lead to suggest work when you need it."),
      ).toBeVisible();
      expect(screen.queryByText("Accepted as a task")).not.toBeInTheDocument();
      expect(screen.queryByText("Review the invoice batch")).not.toBeInTheDocument();
      expect(screen.queryByText("Earlier account decision refused")).not.toBeInTheDocument();
    },
  );
});

describe("canonical task reads and audience boundaries", () => {
  it("distinguishes loading and redacted lead metadata from an empty room", async () => {
    const policyRead = deferred<RoomLeadPolicy>();
    const proposalRead = deferred<{ items: RoomRoutingProposal[]; has_more: boolean }>();
    const taskRead = deferred<{ items: RoomTaskCard[]; has_more: boolean }>();
    const read = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation((path, options) => {
      if (path.endsWith("/lead-policy")) return policyRead.promise;
      if (path.endsWith("/routing-proposals")) return proposalRead.promise;
      if (path.endsWith("/task-links")) return taskRead.promise;
      return read(path, options);
    });
    const interaction = userEvent.setup();
    render(<RoomRoutingPanel conversationId="room-a" readOnly={false} />, { wrapper });
    await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
    expect(screen.getByRole("status")).toHaveTextContent("Checking room access…");
    expect(screen.queryByText(/No proposals yet/)).not.toBeInTheDocument();
    await act(async () => policyRead.resolve({ ...policy, lead: null, can_edit: false }));
    expect(await screen.findByText("The configured agent is unavailable to you.")).toBeVisible();
    expect(screen.getAllByRole("status")).toHaveLength(2);
    expect(screen.queryByText(/Accepted tasks will appear/)).not.toBeInTheDocument();
    await act(async () => {
      proposalRead.resolve({ items: [], has_more: false });
      taskRead.resolve({ items: [], has_more: false });
    });
    expect(
      await screen.findByText("No proposals yet. Ask the lead to suggest work when you need it."),
    ).toBeVisible();
    expect(
      screen.getByText("Accepted tasks will appear here with their current status."),
    ).toBeVisible();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("does not claim a due date or personal ownership when safe task metadata omits it", async () => {
    proposals = [];
    tasks = [
      task({
        status: "in_progress",
        next_actor: "agent",
        accountable_user_id: "another-member",
        accountable_user_name: null,
        due_at: null,
        agent: { ...pin, current: true },
      }),
    ];
    await openPanel();
    const card = screen.getByRole("article", { name: "Linked task" });
    expect(within(card).getByText("In progress")).toBeVisible();
    expect(within(card).getByText("Next: the assigned agent")).toBeVisible();
    expect(within(card).getByText("Another teammate")).toBeVisible();
    expect(card.querySelector("time")).toBeNull();
    expect(within(card).queryByText("Earlier published version")).not.toBeInTheDocument();
    expect(within(card).getByRole("link", { name: "Open task board" })).toHaveAttribute(
      "href",
      "/en/tables/board-a",
    );
  });

  it("shows waiting for review and the existing board route without private work links or writes", async () => {
    tasks = [
      task(),
      task({
        id: "link-b",
        task_id: "task-b",
        title: "Teammate's task",
        status: "planned",
        accountable_user_id: "another-member",
        accountable_user_name: "Jordan",
      }),
    ];
    const { interaction } = await openPanel();
    expect(await screen.findByText("Waiting for review", { exact: true })).toBeVisible();
    expect(screen.queryByText("Done", { exact: true })).not.toBeInTheDocument();
    expect(screen.getByText("Jordan", { exact: true })).toBeVisible();
    expect(
      screen.getByText(
        "This teammate starts their task through Tasks. Acceptance does not start it on their behalf.",
      ),
    ).toBeVisible();
    for (const link of screen.getAllByRole("link", { name: "Open task board" }))
      expect(link).toHaveAttribute("href", "/en/tables/board-a");
    expect(screen.queryByRole("link", { name: /chat|Inbox|working/i })).not.toBeInTheDocument();
    act(changed);
    await waitFor(() =>
      expect(
        vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.endsWith("/task-links")).length,
      ).toBeGreaterThan(1),
    );
    await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("hides previously loaded cards when the current read is refused", async () => {
    tasks = [task()];
    const read = vi.mocked(apiClient.get).getMockImplementation()!;
    const { interaction } = await openPanel();
    expect(await screen.findByText("Reconcile invoices")).toBeVisible();
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/orgs") return { items: [] };
      throw new ApiError(403, "Room access revoked");
    });
    act(changed);
    expect(
      await screen.findByText(
        "The room lead policy is unavailable. Check again to confirm your access.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("Reconcile invoices")).not.toBeInTheDocument();
    expect(screen.queryByText("Review the invoice batch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Configure lead" })).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockImplementation(read);
    await interaction.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Lead: Writer")).toBeVisible();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("recovers a failed canonical task read through a read-only check", async () => {
    tasks = [task()];
    const read = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (path.endsWith("/task-links")) throw new ApiError(503, "Task read unavailable");
      return read(path, options);
    });
    const { interaction } = await openPanel();
    expect(
      await screen.findByText("Linked tasks could not be read with your current access."),
    ).toBeVisible();
    expect(screen.queryByText("Reconcile invoices")).not.toBeInTheDocument();
    vi.mocked(apiClient.get).mockImplementation(read);
    await interaction.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByText("Reconcile invoices")).toBeVisible();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("hides all cached cards as soon as room access is refused while other reads are pending", async () => {
    tasks = [task()];
    await openPanel();
    expect(await screen.findByText("Reconcile invoices")).toBeVisible();
    const pending = deferred<{ items: never[]; has_more: boolean }>();
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/orgs") return { items: [] };
      if (path.endsWith("/lead-policy")) throw new ApiError(403, "Room access revoked");
      return pending.promise;
    });
    act(changed);
    expect(
      await screen.findByText(
        "The room lead policy is unavailable. Check again to confirm your access.",
      ),
    ).toBeVisible();
    expect(screen.queryByText("Reconcile invoices")).not.toBeInTheDocument();
    expect(screen.queryByText("Review the invoice batch")).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Accept selected" })).not.toBeInTheDocument();
    await act(async () => pending.resolve({ items: [], has_more: false }));
  });

  it("separates organization reads and hides old cards while the next tenant is loading", async () => {
    tasks = [task()];
    const { interaction } = await openPanel();
    expect(await screen.findByText("Reconcile invoices")).toBeVisible();
    const pending = deferred<{ items: RoomTaskCard[]; has_more: boolean }>();
    const prior = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation((path, options) =>
      path.endsWith("/task-links") ? pending.promise : prior(path, options),
    );
    act(() => useOrgStore.setState({ activeOrgId: "org-b" }));
    await interaction.click(screen.getByRole("button", { name: /Lead & tasks/ }));
    expect(screen.queryByText("Reconcile invoices")).not.toBeInTheDocument();
    await act(async () =>
      pending.resolve({ items: [task({ title: "Second organization task" })], has_more: false }),
    );
    expect(await screen.findByText("Second organization task")).toBeVisible();
    expect(screen.queryByText("Reconcile invoices")).not.toBeInTheDocument();
  });

  it("uses explicit subthread reads and excludes foreign room or thread cards", async () => {
    proposals = [
      proposal({ thread_root_message_id: "thread-a" }),
      proposal({
        id: "foreign-room",
        conversation_id: "room-b",
        thread_root_message_id: "thread-a",
        items: [{ ...proposal().items[0]!, title: "Foreign room secret" }],
      }),
      proposal({
        id: "foreign-thread",
        thread_root_message_id: "thread-b",
        items: [{ ...proposal().items[0]!, title: "Other thread content" }],
      }),
    ];
    tasks = [
      task({ thread_root_message_id: "thread-a" }),
      task({ id: "other-thread", title: "Wrong thread task", thread_root_message_id: "thread-b" }),
    ];
    await openPanel({ threadRootMessageId: "thread-a" });
    expect(await screen.findByText("Reconcile invoices")).toBeVisible();
    expect(screen.queryByText("Foreign room secret")).not.toBeInTheDocument();
    expect(screen.queryByText("Other thread content")).not.toBeInTheDocument();
    expect(screen.queryByText("Wrong thread task")).not.toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/room-a/routing-proposals", {
      params: { limit: "50", skip: "0", thread_root_message_id: "thread-a" },
      signal: expect.any(AbortSignal),
    });
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/room-a/task-links", {
      params: { limit: "50", skip: "0", thread_root_message_id: "thread-a" },
      signal: expect.any(AbortSignal),
    });
  });

  it("loads another bounded page with the same thread scope only on request", async () => {
    const prior = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (!path.endsWith("/routing-proposals")) return prior(path, options);
      const skip = (options?.params as Record<string, string>)?.skip;
      return skip === "0"
        ? { items: [proposal({ thread_root_message_id: "thread-a" })], has_more: true }
        : {
            items: [
              proposal({
                id: "next-proposal",
                thread_root_message_id: "thread-a",
                items: [{ ...proposal().items[0]!, title: "Next page task" }],
              }),
            ],
            has_more: false,
          };
    });
    const { interaction } = await openPanel({ threadRootMessageId: "thread-a" });
    expect(screen.queryByText("Next page task")).not.toBeInTheDocument();
    await interaction.click(screen.getByRole("button", { name: "Load more proposals" }));
    expect(await screen.findByText("Next page task")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/room-a/routing-proposals", {
      params: { limit: "50", skip: "50", thread_root_message_id: "thread-a" },
      signal: expect.any(AbortSignal),
    });
    expect(screen.queryByRole("button", { name: "Load more proposals" })).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("loads the next canonical task page in its original thread scope", async () => {
    const read = vi.mocked(apiClient.get).getMockImplementation()!;
    vi.mocked(apiClient.get).mockImplementation(async (path, options) => {
      if (!path.endsWith("/task-links")) return read(path, options);
      const skip = (options?.params as Record<string, string>)?.skip;
      return skip === "0"
        ? { items: [task({ thread_root_message_id: "thread-a" })], has_more: true }
        : {
            items: [
              task({
                id: "link-next",
                task_id: "task-next",
                title: "Next canonical task",
                thread_root_message_id: "thread-a",
              }),
            ],
            has_more: false,
          };
    });
    const { interaction } = await openPanel({ threadRootMessageId: "thread-a" });
    expect(screen.queryByText("Next canonical task")).not.toBeInTheDocument();
    await interaction.click(screen.getByRole("button", { name: "Load more tasks" }));
    expect(await screen.findByText("Next canonical task")).toBeVisible();
    expect(apiClient.get).toHaveBeenCalledWith("/conversations/room-a/task-links", {
      params: { limit: "50", skip: "50", thread_root_message_id: "thread-a" },
      signal: expect.any(AbortSignal),
    });
    expect(screen.queryByRole("button", { name: "Load more tasks" })).not.toBeInTheDocument();
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("ignores room-change events for a different account, organization or room", async () => {
    await openPanel();
    vi.mocked(apiClient.get).mockClear();
    await act(async () => {
      announceRoomChange({ accountId: "other", organizationId: "org-a", conversationId: "room-a" });
      announceRoomChange({ accountId: "me", organizationId: "org-b", conversationId: "room-a" });
      announceRoomChange({ accountId: "me", organizationId: "org-a", conversationId: "room-b" });
    });
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(screen.getByText("Review the invoice batch")).toBeVisible();
  });

  it("refuses retained action callbacks and draft tokens after the account changes", async () => {
    const rendered = renderHook(
      () => ({
        actions: useRoomRoutingActions("room-a"),
        attempt: useRoomDecisionAttempt("room-a", "proposal-a"),
      }),
      { wrapper },
    );
    const held = rendered.result.current;
    const attempt = {
      decision: "accept" as const,
      input: { expected_revision: 1, idempotency_key: "original", selected_item_ids: ["item-a"] },
    };
    act(() => held.attempt.set(attempt));
    expect(held.attempt.read()).toEqual(attempt);
    act(() => {
      useAuthStore.setState({ user: user("other") });
      useChatStore.getState().clearRoomDrafts();
    });
    const listener = vi.fn();
    const stop = onRoomChange(listener);
    try {
      await act(async () => {
        held.attempt.set(attempt);
        held.actions.changed();
        expect(await held.actions.readProposal("proposal-a")).toBeNull();
        expect(await held.actions.decide("proposal-a", "accept", attempt.input)).toBeNull();
        expect(
          await held.actions.savePolicy({
            expected_revision: 7,
            enabled: false,
            lead_agent_id: null,
            specialist_agent_ids: [],
            max_items: 3,
          }),
        ).toBeNull();
      });
      expect(Object.values(useChatStore.getState().roomDecisionAttempts)).toEqual([]);
      expect(listener).not.toHaveBeenCalled();
      expect(apiClient.post).not.toHaveBeenCalled();
      expect(apiClient.put).not.toHaveBeenCalled();
      expect(
        vi.mocked(apiClient.get).mock.calls.filter(([path]) => path.startsWith("/conversations/")),
      ).toEqual([]);
    } finally {
      stop();
    }
  });

  it("keeps an Ask lead draft local until the current policy revision is known", async () => {
    const { result } = renderHook(() => useRoomDraft("room-a"), { wrapper });
    act(() => {
      result.current.setContent("Plan the review");
      result.current.setAskLead();
    });
    await act(async () => result.current.submit());
    expect(result.current.content).toBe("Plan the review");
    expect(result.current.intent).toBe("ask_lead");
    expect(result.current.locked).toBe(false);
    expect(result.current.sending).toBe(false);
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("opens the existing reply thread from a room-wide card without starting work", async () => {
    proposals = [proposal({ thread_root_message_id: "thread-a" })];
    const open = vi.fn();
    const { interaction } = await openPanel({ onOpenThread: open });
    await interaction.click(screen.getByRole("button", { name: "Open reply thread" }));
    expect(open).toHaveBeenCalledWith("thread-a");
    expect(apiClient.post).not.toHaveBeenCalled();
  });
});

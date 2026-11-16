import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import { qk } from "@/lib/query-keys";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import { TEACHING_IDS as ids, teachingSummaryFixture } from "@/test-utils/browser-teaching";
import { Perm } from "@/types/permissions";
import type {
  TeachingList,
  TeachingPolicy,
  TeachingPreference,
  TeachingToggle,
} from "@/types/browser-teaching";
import { BrowserTeachingList } from "./browser-teaching-list";
import { BrowserTeachingPolicy } from "./browser-teaching-policy";
import { BrowserTeachingPreference } from "./browser-teaching-preference";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), put: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
const permission = vi.hoisted(() => ({ denied: new Set<string>() }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (name: string) => !permission.denied.has(name), isLoading: false }),
}));
vi.mock("@/components/dashboard/page-header", () => ({
  PageHeader: ({
    title,
    description,
    secondaryActions,
  }: {
    title: string;
    description: string;
    secondaryActions: ReactNode;
  }) => (
    <header>
      <h1>{title}</h1>
      <p>{description}</p>
      {secondaryActions}
    </header>
  ),
}));

const policyName = "Allow browser teaching";
const preferenceName = "Suggest procedures from my completed work";
const opaque = "eyJvcGFxdWUiOiJjdXJzb3IifQ-_/+=";
const scopedWrite = expect.objectContaining({
  cache: "no-store",
  retryAfterRefresh: false,
  headers: { "X-Organization-Id": ids.org },
  signal: expect.any(AbortSignal),
});
const refused = (status: number, reason_code = "teaching_unavailable") =>
  new ApiError(status, "PRIVATE REFUSAL TEXT", {
    error: { code: "BAD_REQUEST", message: "PRIVATE REFUSAL TEXT", details: { reason_code } },
  });
let client: QueryClient;
let policy: TeachingPolicy;
let preference: TeachingPreference;
let list: TeachingList;
function setup(node: ReactNode) {
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{node}</QueryClientProvider>);
}
function noWrites() {
  expect(apiClient.put).not.toHaveBeenCalled();
  expect(apiClient.post).not.toHaveBeenCalled();
  expect(apiClient.patch).not.toHaveBeenCalled();
  expect(apiClient.delete).not.toHaveBeenCalled();
}
beforeEach(() => {
  vi.resetAllMocks();
  permission.denied.clear();
  useAuthStore.setState({
    user: { id: ids.owner } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>,
    accessToken: "synthetic-test-token",
  });
  useOrgStore.setState({ activeOrgId: ids.org });
  policy = { enabled: false, generation: ids.other, deployment_enabled: true };
  preference = { agent_id: ids.agent, enabled: false, generation: ids.other, allowed: true };
  list = { items: [teachingSummaryFixture()], next_cursor: null };
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/browser-teaching-policy") return policy as never;
    if (path.endsWith("/browser-teaching-preference")) return preference as never;
    return list as never;
  });
  vi.mocked(apiClient.put).mockImplementation(async (path, body) => {
    const toggle = body as TeachingToggle;
    if (path === "/browser-teaching-policy") {
      policy = { ...policy, enabled: toggle.enabled, generation: ids.proposal };
      return policy as never;
    }
    preference = { ...preference, enabled: toggle.enabled, generation: ids.proposal };
    return preference as never;
  });
});
afterEach(() => {
  cleanup();
  client?.clear();
  vi.restoreAllMocks();
});

describe("durable teaching discovery refusal and pagination", () => {
  it("keeps an empty owner collection as an empty state without creating a capture", async () => {
    list = { items: [], next_cursor: null };
    setup(<BrowserTeachingList />);
    await screen.findByText("You have no browser captures to review yet.");
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(screen.queryByRole("link", { name: "Open capture" })).toBeNull();
    noWrites();
  });

  it("passes the opaque next cursor unchanged and stops at the last page", async () => {
    const second = teachingSummaryFixture({ id: ids.other, title: "Second owner capture" });
    vi.mocked(apiClient.get).mockImplementation(
      async (_path, options) =>
        (new URLSearchParams(options?.params).get("cursor") === opaque
          ? { items: [second], next_cursor: null }
          : { items: [teachingSummaryFixture()], next_cursor: opaque }) as never,
    );
    setup(<BrowserTeachingList />);
    await screen.findByRole("heading", { name: "Monthly report demonstration" });
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByRole("heading", { name: second.title });
    expect(screen.getAllByRole("link", { name: "Open capture" })).toHaveLength(2);
    expect(apiClient.get).toHaveBeenLastCalledWith(
      "/browser-teachings",
      expect.objectContaining({
        params: { limit: "20", cursor: opaque },
        headers: { "X-Organization-Id": ids.org },
        cache: "no-store",
      }),
    );
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    noWrites();
  });

  it("holds a failed cursor as a refusal until explicit refresh restarts the first page", async () => {
    let restarted = false;
    vi.mocked(apiClient.get).mockImplementation(async (_path, options) => {
      if (new URLSearchParams(options?.params).get("cursor") === opaque)
        throw refused(400, "invalid_cursor");
      return {
        items: [
          teachingSummaryFixture({
            title: restarted ? "Fresh owner capture" : "Previously cached capture",
          }),
        ],
        next_cursor: restarted ? null : opaque,
      } as never;
    });
    setup(<BrowserTeachingList />);
    await screen.findByRole("heading", { name: "Previously cached capture" });
    await userEvent.click(screen.getByRole("button", { name: "Load more" }));
    await screen.findByRole("alert");
    expect(screen.queryByText("Previously cached capture")).toBeNull();
    expect(screen.queryByRole("button", { name: "Load more" })).toBeNull();
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    restarted = true;
    await userEvent.click(screen.getByRole("button", { name: "Refresh list" }));
    await screen.findByRole("heading", { name: "Fresh owner capture" });
    expect(vi.mocked(apiClient.get).mock.calls.map(([, options]) => options?.params)).toEqual([
      { limit: "20" },
      { limit: "20", cursor: opaque },
      { limit: "20" },
    ]);
    noWrites();
  });

  it.each([400, 403, 404])(
    "hides retained rows on a fresh authority refusal %s without replaying writes",
    async (status) => {
      setup(<BrowserTeachingList />);
      await screen.findByRole("heading", { name: "Monthly report demonstration" });
      vi.mocked(apiClient.get).mockRejectedValue(refused(status));
      await act(async () => {
        await client.invalidateQueries({ queryKey: qk.browserTeaching.list(ids.owner, ids.org) });
      });
      await screen.findByRole("alert");
      expect(screen.queryByText("Monthly report demonstration")).toBeNull();
      expect(screen.queryByRole("link", { name: "Open capture" })).toBeNull();
      expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
      expect(apiClient.get).toHaveBeenCalledTimes(2);
      noWrites();
    },
  );

  it("keeps a pending next-page read from being submitted again by a second Load more click", async () => {
    let resolve!: (value: TeachingList) => void;
    const pending = new Promise<TeachingList>((done) => {
      resolve = done;
    });
    vi.mocked(apiClient.get).mockImplementation(async (_path, options) => {
      if (new URLSearchParams(options?.params).get("cursor")) return pending as never;
      return { items: [teachingSummaryFixture()], next_cursor: opaque } as never;
    });
    setup(<BrowserTeachingList />);
    await screen.findByRole("heading", { name: "Monthly report demonstration" });
    const more = screen.getByRole("button", { name: "Load more" });
    await userEvent.click(more);
    await waitFor(() => expect(more).toBeDisabled());
    await userEvent.click(more);
    expect(apiClient.get).toHaveBeenCalledTimes(2);
    await act(async () => {
      resolve({ items: [], next_cursor: null });
    });
    await waitFor(() => expect(screen.queryByRole("button", { name: "Load more" })).toBeNull());
    noWrites();
  });
});

describe("organization teaching policy uses explicit current-generation decisions", () => {
  it("unmounts policy controls immediately when org:settings is no longer available", async () => {
    const view = setup(<BrowserTeachingPolicy />);
    await screen.findByRole("switch", { name: policyName });
    permission.denied.add(Perm.orgSettings);
    view.rerender(
      <QueryClientProvider client={client}>
        <BrowserTeachingPolicy />
      </QueryClientProvider>,
    );
    expect(screen.queryByRole("switch", { name: policyName })).toBeNull();
    expect(apiClient.get).toHaveBeenCalledTimes(1);
    noWrites();
  });

  it("does not offer enabling while deployment admission is disabled", async () => {
    policy = { ...policy, deployment_enabled: false };
    setup(<BrowserTeachingPolicy />);
    const toggle = await screen.findByRole("switch", { name: policyName });
    expect(toggle).toBeDisabled();
    expect(screen.getByText("Browser teaching is unavailable on this deployment.")).toBeVisible();
    await userEvent.click(toggle);
    expect(screen.queryByRole("button", { name: "Save" })).toBeNull();
    noWrites();
  });

  it.each([false, true])(
    "requires a separate confirmed CAS write when current enabled is %s",
    async (enabled) => {
      policy = { enabled, generation: enabled ? ids.other : null, deployment_enabled: !enabled };
      const expectedGeneration = policy.generation;
      setup(<BrowserTeachingPolicy />);
      const toggle = await screen.findByRole("switch", { name: policyName });
      expect(toggle).toBeEnabled();
      await userEvent.click(toggle);
      await screen.findByText(enabled ? "Turn off browser teaching?" : "Enable browser teaching?");
      noWrites();
      await userEvent.click(screen.getByRole("button", { name: "Save" }));
      await waitFor(() => {
        if (enabled) expect(toggle).not.toBeChecked();
        else expect(toggle).toBeChecked();
      });
      expect(apiClient.put).toHaveBeenCalledExactlyOnceWith(
        "/browser-teaching-policy",
        { generation: expectedGeneration, enabled: !enabled },
        scopedWrite,
      );
      expect(apiClient.post).not.toHaveBeenCalled();
    },
  );

  it("cancels a confirmation without modifying policy or generation", async () => {
    setup(<BrowserTeachingPolicy />);
    await userEvent.click(await screen.findByRole("switch", { name: policyName }));
    await screen.findByText("Enable browser teaching?");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("button", { name: "Save" })).toBeNull());
    expect(screen.getByRole("switch", { name: policyName })).not.toBeChecked();
    expect(policy.generation).toBe(ids.other);
    noWrites();
  });

  it("recovers a refused policy GET only through Check again, without guessing its switch state", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(refused(403));
    setup(<BrowserTeachingPolicy />);
    await screen.findByRole("alert");
    expect(screen.queryByRole("switch", { name: policyName })).toBeNull();
    vi.mocked(apiClient.get).mockResolvedValue(policy);
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByRole("switch", { name: policyName })).not.toBeChecked();
    noWrites();
  });

  it("does not use an open confirmation after a fresh read removes policy authority", async () => {
    setup(<BrowserTeachingPolicy />);
    await userEvent.click(await screen.findByRole("switch", { name: policyName }));
    await screen.findByRole("button", { name: "Save" });
    vi.mocked(apiClient.get).mockRejectedValue(refused(400));
    await act(async () => {
      await client.invalidateQueries({ queryKey: qk.browserTeaching.policy(ids.owner, ids.org) });
    });
    await waitFor(() =>
      expect(screen.queryByRole("switch", { name: policyName, hidden: true })).toBeNull(),
    );
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    noWrites();
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByRole("button", { name: "Check again" });
    expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
  });

  it("keeps a stale-generation rejection visible without optimistic enabling or automatic retry", async () => {
    vi.mocked(apiClient.put).mockImplementation(async () => {
      policy = { ...policy, generation: ids.proposal };
      throw refused(409, "stale_revision");
    });
    setup(<BrowserTeachingPolicy />);
    await userEvent.click(await screen.findByRole("switch", { name: policyName }));
    await userEvent.click(screen.getByRole("button", { name: "Save" }));
    await waitFor(() => expect(apiClient.put).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.getByRole("button", { name: "Save" })).toBeEnabled());
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await screen.findByRole("alert");
    expect(screen.getByRole("switch", { name: policyName })).not.toBeChecked();
    expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith(
      "/browser-teaching-policy",
      { generation: ids.other, enabled: true },
      scopedWrite,
    );
  });
});

describe("member learning preference refuses unavailable authority and permits revocation", () => {
  it("does not offer a new opt-in when the agent is unavailable", async () => {
    preference = { ...preference, allowed: false };
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    const toggle = await screen.findByRole("switch", { name: preferenceName });
    expect(toggle).not.toBeChecked();
    expect(toggle).toBeDisabled();
    expect(screen.getByText(/New suggestions are unavailable/)).toBeVisible();
    await userEvent.click(toggle);
    noWrites();
  });

  it("revokes a known existing opt-in with its current generation after allowed becomes false", async () => {
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    await screen.findByRole("switch", { name: preferenceName });
    preference = { ...preference, enabled: true, allowed: false, generation: ids.takeover };
    await act(async () => {
      await client.invalidateQueries({
        queryKey: qk.browserTeaching.preference(ids.owner, ids.org, ids.agent),
      });
    });
    const toggle = screen.getByRole("switch", { name: preferenceName });
    await waitFor(() => expect(toggle).toBeChecked());
    expect(toggle).toBeEnabled();
    await userEvent.click(toggle);
    await waitFor(() => expect(toggle).not.toBeChecked());
    expect(toggle).toBeDisabled();
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith(
      "/agents/" + ids.agent + "/browser-teaching-preference",
      { generation: ids.takeover, enabled: false },
      scopedWrite,
    );
  });

  it("hides a previously known preference when a fresh personal-context GET is refused", async () => {
    preference.enabled = true;
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    await screen.findByRole("switch", { name: preferenceName });
    vi.mocked(apiClient.get).mockRejectedValue(refused(400));
    await act(async () => {
      await client.invalidateQueries({
        queryKey: qk.browserTeaching.preference(ids.owner, ids.org, ids.agent),
      });
    });
    await screen.findByRole("alert");
    expect(screen.queryByRole("switch", { name: preferenceName })).toBeNull();
    expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    noWrites();
  });

  it("recovers a failed preference read through GET only", async () => {
    vi.mocked(apiClient.get).mockRejectedValue(refused(404));
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    await screen.findByRole("button", { name: "Check again" });
    expect(screen.queryByRole("switch", { name: preferenceName })).toBeNull();
    vi.mocked(apiClient.get).mockResolvedValue(preference);
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(await screen.findByRole("switch", { name: preferenceName })).not.toBeChecked();
    noWrites();
  });

  it("does not borrow another agent's returned preference", async () => {
    preference = { ...preference, agent_id: ids.other, enabled: true };
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    await waitFor(() => expect(apiClient.get).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    expect(screen.queryByRole("switch", { name: preferenceName })).toBeNull();
    noWrites();
  });

  it("does not guess a successful opt-in after a refused write and read", async () => {
    vi.mocked(apiClient.put).mockImplementation(async () => {
      vi.mocked(apiClient.get).mockRejectedValue(refused(403));
      throw refused(403);
    });
    setup(<BrowserTeachingPreference agentId={ids.agent} />);
    await userEvent.click(await screen.findByRole("switch", { name: preferenceName }));
    await screen.findByRole("button", { name: "Check again" });
    expect(screen.queryByRole("switch", { name: preferenceName })).toBeNull();
    expect(screen.queryByText("PRIVATE REFUSAL TEXT")).toBeNull();
    expect(apiClient.put).toHaveBeenCalledExactlyOnceWith(
      "/agents/" + ids.agent + "/browser-teaching-preference",
      { generation: ids.other, enabled: true },
      scopedWrite,
    );
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    expect(apiClient.put).toHaveBeenCalledTimes(1);
  });
});

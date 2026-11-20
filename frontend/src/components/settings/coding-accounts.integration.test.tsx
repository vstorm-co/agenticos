import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { CodingAccounts, PersonalCodingAccount } from "./coding-accounts";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";
import type {
  CodingAccount,
  CodingAccountChange,
  CodingAccountUsage,
} from "@/lib/coding-accounts-api";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/hooks/use-organizations", () => ({
  useTenantId: () => "org-1",
  useTenantGuard: () => () => true,
}));
vi.mock("@/stores", () => {
  const state = { user: { id: "user-1" } };
  return {
    useAuthStore: Object.assign((selector: (value: typeof state) => unknown) => selector(state), {
      getState: () => state,
    }),
  };
});
vi.mock("@/hooks/use-shell", () => ({ useShell: () => null }));
vi.mock("@/lib/desktop/shell", () => ({ isDesktopShell: () => false }));
vi.mock("@/components/desktop/local-agent-settings", () => ({ LocalAgentSettings: () => null }));
const account: CodingAccount = {
  id: "c-1",
  harness: "claude_code",
  label: "My Claude",
  secret_kind: "api_key",
  enabled: false,
  generation: "g-1",
  is_default: true,
  pool_member: false,
  model_catalog: {
    status: "unknown",
    source: "unavailable",
    observed_at: null,
    valid_until: null,
    model_ids: [],
    reason_code: "model_catalog_unverified",
  },
  usage_refresh_pending: false,
  usage: {
    status: "unknown",
    observed_at: null,
    observation_age_seconds: null,
    valid_until: null,
    source: "unavailable",
    windows: [],
    reason_code: "provider_contract_unverified",
  },
};
function mount(ui: ReactElement = <CodingAccounts />) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
function report(row: CodingAccount): CodingAccountUsage {
  return {
    account_id: row.id,
    generation: row.generation,
    usage: row.usage,
    model_catalog: row.model_catalog,
    refresh_pending: row.usage_refresh_pending,
  };
}
function serve(row: CodingAccount) {
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/coding-accounts") return { items: [row] };
    if (path === `/coding-accounts/${row.id}/usage`) return report(row);
    throw new Error(`Unexpected GET ${path}`);
  });
}
function codex(overrides: Partial<CodingAccount> = {}): CodingAccount {
  return {
    ...account,
    harness: "codex",
    label: "My Codex",
    secret_kind: "openai_codex",
    enabled: true,
    ...overrides,
  };
}
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
beforeEach(() => {
  vi.clearAllMocks();
  vi.mocked(apiClient.get).mockResolvedValue({ items: [] });
  vi.mocked(apiClient.post).mockResolvedValue(account);
  vi.mocked(apiClient.patch).mockResolvedValue({ ...account, enabled: true });
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});
it("connects a private key with consent off and clears the form", async () => {
  mount();
  const buttons = await screen.findAllByRole("button", { name: "Connect" });
  const connect = buttons[0];
  if (!connect) throw new Error("Missing Claude connect");
  await waitFor(() => expect(connect).toBeEnabled());
  await userEvent.click(connect);
  const dialog = screen.getByRole("dialog");
  expect(screen.getByRole("checkbox")).not.toBeChecked();
  await userEvent.type(screen.getByLabelText("Account label"), "My Claude");
  await userEvent.type(screen.getByLabelText("API key or Claude setup token"), "private-key-value");
  const submit = dialog.querySelector<HTMLButtonElement>('button[type="submit"]');
  expect(submit).not.toBeNull();
  if (!submit) throw new Error("Missing submit");
  await userEvent.click(submit);
  await waitFor(() => expect(dialog).not.toBeInTheDocument());
  expect(apiClient.post).toHaveBeenCalledWith("/coding-accounts", {
    harness: "claude_code",
    label: "My Claude",
    api_key: "private-key-value",
    enabled: false,
  });
  expect(screen.queryByDisplayValue("private-key-value")).not.toBeInTheDocument();
});
it("shows a loading state before deciding whether any coding accounts are connected", () => {
  vi.mocked(apiClient.get).mockReturnValue(new Promise(() => {}));
  mount();
  expect(screen.getByText("Loading your coding accounts…")).toBeVisible();
  expect(screen.queryByText("Not connected")).toBeNull();
});
it("refreshes Codex usage before any coding task is started", async () => {
  const codex: CodingAccount = {
    ...account,
    harness: "codex",
    label: "My Codex",
    secret_kind: "openai_codex",
    enabled: true,
  };
  const report = {
    account_id: codex.id,
    generation: codex.generation,
    usage: codex.usage,
    model_catalog: {
      status: "unknown",
      source: "unavailable",
      observed_at: null,
      valid_until: null,
      model_ids: [],
      reason_code: "model_catalog_unverified",
    },
    refresh_pending: false,
  };
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path.endsWith("/usage") ? report : { items: [codex] },
  );
  vi.mocked(apiClient.post).mockResolvedValue({ ...report, refresh_pending: true });
  mount();
  await screen.findByText("My Codex");
  expect(apiClient.post).not.toHaveBeenCalled();
  const refresh = screen.getByRole("button", { name: "Refresh usage" });
  await userEvent.click(refresh);
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith("/coding-accounts/c-1/usage/refresh", {
      generation: "g-1",
    }),
  );
  expect(await screen.findByText("Usage refresh is pending.")).toBeVisible();
  expect(refresh).toBeDisabled();
  expect(apiClient.post).toHaveBeenCalledTimes(1);
});
it("changes consent with a generation check and disconnects only the selected account", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ items: [account] });
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Enable use" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith("/coding-accounts/c-1", {
      generation: "g-1",
      enabled: true,
    }),
  );
  await userEvent.click(screen.getByRole("button", { name: "Disconnect" }));
  await waitFor(() => expect(apiClient.delete).toHaveBeenCalledWith("/coding-accounts/c-1"));
});
it("shows unknown provider usage and lets the owner choose a default and pool account", async () => {
  let codex: CodingAccount = {
    ...account,
    id: "c-2",
    harness: "codex",
    label: "Second Codex",
    secret_kind: "openai_codex",
    enabled: true,
    generation: "g-2",
    is_default: false,
  };
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path.endsWith("/usage") ? report(codex) : { items: [account, codex] },
  );
  vi.mocked(apiClient.patch).mockImplementation(async (_path, data) => {
    codex = { ...codex, ...(data as CodingAccountChange) };
    return codex;
  });
  mount();
  const row = (await screen.findByText("Second Codex")).closest("li");
  if (!row) throw new Error("Missing Codex account row");
  expect(within(row).getByText("Reported status: Unknown")).toBeInTheDocument();
  expect(within(row).getByText("Source: Not reported")).toBeInTheDocument();
  expect(screen.getByText("Reported status: Disabled")).toBeInTheDocument();
  expect(within(row).queryByRole("button", { name: "Enable use" })).not.toBeInTheDocument();
  await userEvent.click(await screen.findByRole("button", { name: "Make default" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith("/coding-accounts/c-2", {
      generation: "g-2",
      enabled: true,
      is_default: true,
    }),
  );
  await waitFor(() => expect(within(row).getByText("Default")).toBeInTheDocument());
  expect(within(row).queryByRole("button", { name: "Make default" })).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Add to pool" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith("/coding-accounts/c-2", {
      generation: "g-2",
      enabled: true,
      pool_member: true,
    }),
  );
  expect(await within(row).findByText("In pool")).toBeInTheDocument();
  await userEvent.click(within(row).getByRole("button", { name: "Remove from pool" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith("/coding-accounts/c-2", {
      generation: "g-2",
      enabled: true,
      pool_member: false,
    }),
  );
  await waitFor(() => expect(within(row).queryByText("In pool")).not.toBeInTheDocument());
});
it("shows reported usage windows with their source, freshness and exact reset time", async () => {
  const observed = new Date(Date.now() - 12_000).toISOString();
  const validUntil = new Date(Date.now() + 300_000).toISOString();
  serve(
    codex({
      usage: {
        ...account.usage,
        status: "rate_limited",
        source: "native_runtime",
        observed_at: observed,
        valid_until: validUntil,
        observation_age_seconds: 12,
        reason_code: "provider_reported_rate_limit",
        windows: [
          {
            name: "primary",
            used: 100,
            limit: 100,
            unit: "%",
            resets_at: "2026-11-16T12:00:00Z",
            window_duration_minutes: 300,
          },
          {
            name: "secondary",
            used: null,
            limit: null,
            unit: null,
            resets_at: null,
            window_duration_minutes: 10080,
          },
        ],
      },
    }),
  );
  mount();
  expect(await screen.findByText("Reported status: Rate limited")).toBeInTheDocument();
  expect(screen.getByText("Source: Native account report")).toBeInTheDocument();
  expect(screen.getByText("Window: 5 hours")).toBeInTheDocument();
  expect(screen.getByText("100 / 100 %")).toBeInTheDocument();
  expect(document.querySelector(`time[datetime="${observed}"]`)).toBeInTheDocument();
  expect(document.querySelector(`time[datetime="${validUntil}"]`)).toBeInTheDocument();
  expect(document.querySelector('time[datetime="2026-11-16T12:00:00Z"]')).toBeInTheDocument();
  expect(screen.getByText("Window: 7 days")).toBeInTheDocument();
  expect(screen.getByText("Usage windows were not reported.")).toBeInTheDocument();
  expect(screen.getByText("Reset time not reported.")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Make default" })).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Add to pool" })).toBeEnabled();
});
it.each([
  { harness: "claude_code", secret_kind: "api_key", enabled: true },
  { harness: "codex", secret_kind: "api_key", enabled: true },
  { harness: "codex", secret_kind: "openai_codex", enabled: false },
] as const)(
  "does not offer a probe for $harness / $secret_kind / enabled=$enabled",
  async (state) => {
    serve(codex({ ...state, label: "Connection" }));
    mount();
    await screen.findByText("Connection");
    expect(screen.queryByRole("button", { name: "Refresh usage" })).toBeNull();
    expect(
      screen.getByText(
        state.enabled
          ? "Usage reporting is not supported for this connection."
          : "Enable this account to refresh its usage.",
      ),
    ).toBeVisible();
    expect(vi.mocked(apiClient.get).mock.calls.map(([path]) => path)).toEqual(["/coding-accounts"]);
    expect(apiClient.post).not.toHaveBeenCalled();
  },
);

function observedAccount(validFor = 300_000): CodingAccount {
  const observed = new Date(Date.now() - 12_000).toISOString();
  const validUntil = new Date(Date.now() + validFor).toISOString();
  return codex({
    usage: {
      ...account.usage,
      status: "available",
      source: "native_runtime",
      observed_at: observed,
      valid_until: validUntil,
      observation_age_seconds: 12,
      reason_code: null,
      windows: [{ name: "Reported window", used: 100, limit: 100, unit: "%", resets_at: null }],
    },
    model_catalog: {
      status: "advertised",
      source: "native_runtime",
      observed_at: observed,
      valid_until: validUntil,
      model_ids: ["reported-model-a"],
      reason_code: null,
    },
  });
}

it("keeps reported percentages and advertised models separate from availability", async () => {
  const row = observedAccount();
  row.usage.status = "unknown";
  row.usage.reason_code = "provider_readiness_unavailable";
  serve(row);
  mount();
  expect(await screen.findByText("Reported status: Unknown")).toBeVisible();
  expect(screen.getByText("100 / 100 %")).toBeVisible();
  expect(
    screen.getByText("The provider did not report this account’s availability."),
  ).toBeVisible();
  expect(screen.getByText("Provider-advertised models")).toBeVisible();
  expect(screen.getByText("reported-model-a")).toBeVisible();
  expect(screen.getByText("This report does not confirm access to each model.")).toBeVisible();
  expect(screen.queryByText("Reported status: Available")).toBeNull();
  expect(screen.queryByText("Reported status: Quota exhausted")).toBeNull();
});

it("hides expired cached windows and model IDs instead of presenting them as current", async () => {
  serve(observedAccount(-1));
  mount();
  expect(
    await screen.findByText("This usage report has expired. Refresh for a current report."),
  ).toBeVisible();
  expect(screen.getByText("Reported status: Unknown")).toBeVisible();
  expect(screen.getByText("Source: Not reported")).toBeVisible();
  expect(screen.queryByText("100 / 100 %")).toBeNull();
  expect(screen.queryByText("reported-model-a")).toBeNull();
});

it("keeps partially reported usage amounts unknown and preserves minute windows", async () => {
  const row = observedAccount();
  row.usage.windows = [
    {
      name: "quarter-hour",
      window_duration_minutes: 15,
      used: null,
      limit: 7,
      unit: null,
      resets_at: null,
    },
    { name: "Reported percent", used: 12, limit: null, unit: "percent", resets_at: null },
  ];
  serve(row);
  mount();
  expect(await screen.findByText("Window: 15 minutes")).toBeVisible();
  expect(screen.getByText("Unknown / 7")).toBeVisible();
  expect(screen.getByText("12 / Unknown %")).toBeVisible();
  expect(screen.getByText("Reported status: Available")).toBeVisible();
});

it.each([null, "usage_windows_unavailable"])(
  "shows missing windows once without inferring readiness from reason %s",
  async (reason) => {
    const row = observedAccount();
    row.usage.windows = [];
    row.usage.reason_code = reason;
    serve(row);
    mount();
    expect(await screen.findByText("Reported status: Available")).toBeVisible();
    expect(screen.getAllByText("Usage windows were not reported.")).toHaveLength(1);
    expect(screen.getByText("reported-model-a")).toBeVisible();
    expect(screen.queryByText("100 / 100 %")).toBeNull();
  },
);

it("expires a displayed report without another read or a provider refresh", async () => {
  vi.useFakeTimers();
  serve(observedAccount(1_000));
  mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(screen.getByText("Reported status: Available")).toBeVisible();
  expect(screen.getByText("reported-model-a")).toBeVisible();
  const reads = vi.mocked(apiClient.get).mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(1_001);
  });
  expect(screen.getByText("Reported status: Unknown")).toBeVisible();
  expect(
    screen.getByText("This usage report has expired. Refresh for a current report."),
  ).toBeVisible();
  expect(screen.queryByText("reported-model-a")).toBeNull();
  expect(screen.queryByText("100 / 100 %")).toBeNull();
  expect(apiClient.get).toHaveBeenCalledTimes(reads);
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("keeps a valid report after a failed cached read and checks again without requesting a probe", async () => {
  const row = observedAccount();
  vi.mocked(apiClient.get).mockImplementation(async (path) => {
    if (path === "/coding-accounts") return { items: [row] };
    throw new Error("offline");
  });
  mount();
  expect(await screen.findByRole("alert")).toHaveTextContent(
    "Could not read the latest usage status",
  );
  expect(screen.getByText("Reported status: Available")).toBeVisible();
  expect(screen.getByText("reported-model-a")).toBeVisible();
  row.usage = { ...row.usage, status: "rate_limited", reason_code: "provider_reported_rate_limit" };
  serve(row);
  await userEvent.click(screen.getByRole("button", { name: "Check again" }));
  expect(await screen.findByText("Reported status: Rate limited")).toBeVisible();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it.each([
  ["read", 403],
  ["read", 404],
  ["refresh", 403],
  ["refresh", 404],
] as const)(
  "clears a private report after a denied %s %i and requires a fresh read before refreshing",
  async (operation, status) => {
    const row = observedAccount();
    let denyRead!: (reason: Error) => void;
    const heldRead = new Promise<never>((_resolve, reject) => {
      denyRead = reject;
    });
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/coding-accounts") return { items: [row] };
      if (path.endsWith("/usage")) return operation === "read" ? heldRead : report(row);
      throw new Error(`Unexpected GET ${path}`);
    });
    mount();
    expect(await screen.findByText("100 / 100 %")).toBeVisible();
    expect(screen.getByText("reported-model-a")).toBeVisible();
    const denied = new ApiError(status, "Synthetic authority refusal");
    const refresh = screen.getByRole("button", { name: "Refresh usage" });
    if (operation === "read") {
      await act(async () => {
        denyRead(denied);
      });
    } else {
      vi.mocked(apiClient.post).mockRejectedValueOnce(denied);
      await userEvent.click(refresh);
    }
    expect(
      await screen.findByText("This connection changed. Checking its current status."),
    ).toBeVisible();
    expect(screen.getByText("Reported status: Unknown")).toBeVisible();
    expect(screen.queryByText("100 / 100 %")).toBeNull();
    expect(screen.queryByText("reported-model-a")).toBeNull();
    expect(refresh).toBeDisabled();
    const writes = operation === "refresh" ? 1 : 0;
    expect(apiClient.post).toHaveBeenCalledTimes(writes);

    let finish!: (value: CodingAccountUsage) => void;
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path === "/coding-accounts") return { items: [row] };
      return new Promise<CodingAccountUsage>((resolve) => {
        finish = resolve;
      });
    });
    await userEvent.click(screen.getByRole("button", { name: "Check again" }));
    await waitFor(() => expect(finish).toBeDefined());
    expect(screen.queryByText("100 / 100 %")).toBeNull();
    expect(screen.queryByText("reported-model-a")).toBeNull();
    expect(refresh).toBeDisabled();
    await act(async () => {
      finish(report(row));
    });
    expect(await screen.findByText("reported-model-a")).toBeVisible();
    expect(screen.getByText("100 / 100 %")).toBeVisible();
    expect(refresh).toBeEnabled();
    expect(apiClient.post).toHaveBeenCalledTimes(writes);
  },
);

it("bounds pending polling and offers a cached check without starting another refresh", async () => {
  vi.useFakeTimers();
  serve(codex({ usage_refresh_pending: true }));
  mount();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(screen.getByText("Usage refresh is pending.")).toBeVisible();
  expect(screen.getByRole("button", { name: "Refresh usage" })).toBeDisabled();
  await act(async () => {
    await vi.advanceTimersByTimeAsync(180_001);
  });
  expect(
    screen.getByText("Usage refresh is still pending. Check again to read its status."),
  ).toBeVisible();
  const reads = vi.mocked(apiClient.get).mock.calls.length;
  await act(async () => {
    await vi.advanceTimersByTimeAsync(60_000);
  });
  expect(apiClient.get).toHaveBeenCalledTimes(reads);
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Check again" }));
    await vi.advanceTimersByTimeAsync(10);
  });
  expect(apiClient.get).toHaveBeenCalledTimes(reads + 1);
  expect(screen.getByText("Usage refresh is pending.")).toBeVisible();
  expect(apiClient.post).not.toHaveBeenCalled();
});

it("starts a fresh ChatGPT flow and submits its callback", async () => {
  vi.mocked(apiClient.post).mockImplementation(async (path) =>
    path.endsWith("sign-in")
      ? { authorization_url: "https://auth.openai.com/authorize" }
      : { ...account, harness: "codex" },
  );
  mount();
  const buttons = await screen.findAllByRole("button", { name: "Connect" });
  const connect = buttons[1];
  if (!connect) throw new Error("Missing Codex connect");
  await waitFor(() => expect(connect).toBeEnabled());
  await userEvent.click(connect);
  await userEvent.type(screen.getByLabelText("Account label"), "My ChatGPT");
  await userEvent.click(screen.getByRole("button", { name: "ChatGPT sign-in" }));
  await userEvent.click(screen.getByRole("button", { name: "Start sign-in" }));
  expect(await screen.findByRole("link", { name: "Continue at OpenAI" })).toHaveAttribute(
    "href",
    "https://auth.openai.com/authorize",
  );
  const callback = "http://localhost:1455/auth/callback?code=test&state=state";
  await userEvent.type(screen.getByLabelText("Callback address"), callback);
  await userEvent.click(screen.getByRole("checkbox"));
  const submit = screen
    .getByRole("dialog")
    .querySelector<HTMLButtonElement>('button[type="submit"]');
  if (!submit) throw new Error("Missing submit");
  await userEvent.click(submit);
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith("/coding-accounts/codex/complete", {
      label: "My ChatGPT",
      callback_url: callback,
      enabled: true,
    }),
  );
});

it("offers a chat only the account its agent codes on, and connects it there", async () => {
  mount(<PersonalCodingAccount harness="codex" />);
  const section = screen.getByRole("region", { name: "Your Codex account" });
  const connect = await screen.findByRole("button", { name: "Connect" });
  expect(section.querySelectorAll("svg")).toHaveLength(1);
  expect(screen.queryByText("Claude Code")).toBeNull();
  await waitFor(() => expect(connect).toBeEnabled());
  await userEvent.click(connect);
  expect(screen.getByRole("dialog", { name: "Connect Codex" })).toBeVisible();
});

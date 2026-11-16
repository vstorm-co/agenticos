import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { CodingAccounts, PersonalCodingAccount } from "./coding-accounts";
import { apiClient } from "@/lib/api-client";
import type { CodingAccount, CodingAccountChange } from "@/lib/coding-accounts-api";

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
  vi.mocked(apiClient.get).mockImplementation(async () => ({ items: [account, codex] }));
  vi.mocked(apiClient.patch).mockImplementation(async (_path, data) => {
    codex = { ...codex, ...(data as CodingAccountChange) };
    return codex;
  });
  mount();
  expect(await screen.findAllByText("Provider usage: Unknown · source: unavailable")).toHaveLength(
    2,
  );
  const row = screen.getByText("Second Codex").closest("li");
  if (!row) throw new Error("Missing Codex account row");
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
it("shows reported usage windows with their source, age and reset time", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({
    items: [
      {
        ...account,
        usage: {
          ...account.usage,
          status: "rate_limited",
          source: "native_runtime",
          observation_age_seconds: 12,
          windows: [
            {
              name: "Five-hour",
              used: 100,
              limit: 100,
              unit: "%",
              resets_at: "2026-11-16T12:00:00Z",
            },
            { name: "Weekly", used: null, limit: null, unit: null, resets_at: null },
          ],
        },
      },
    ],
  });
  mount();
  expect(
    await screen.findByText(
      "Provider status: rate_limited \u00b7 source: native_runtime \u00b7 checked 12 seconds ago",
    ),
  ).toBeInTheDocument();
  expect(
    screen.getByText("Five-hour: 100 / 100 % \u00b7 resets at 2026-11-16T12:00:00Z"),
  ).toBeInTheDocument();
  expect(screen.getByText("Weekly: Unknown / Unknown")).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Make default" })).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Add to pool" })).not.toBeInTheDocument();
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
  expect(section.querySelectorAll("svg")).toHaveLength(1);
  expect(screen.queryByText("Claude Code")).toBeNull();
  const connect = await screen.findByRole("button", { name: "Connect" });
  await waitFor(() => expect(connect).toBeEnabled());
  await userEvent.click(connect);
  expect(screen.getByRole("dialog", { name: "Connect Codex" })).toBeVisible();
});

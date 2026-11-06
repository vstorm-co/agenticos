import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import type { ReactElement } from "react";
import { CodingAccounts, PersonalCodingAccount } from "./coding-accounts";
import { apiClient } from "@/lib/api-client";

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
const account = {
  id: "c-1",
  harness: "claude_code",
  label: "My Claude",
  secret_kind: "api_key",
  enabled: false,
  generation: "g-1",
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

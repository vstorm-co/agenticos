import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { OrgChatHomeSettings } from "./org-chat-home-settings";
import { useOrgStore } from "@/stores";
import { DEFAULT_CHAT_HOME } from "@/lib/console-experience-api";
import { apiClient } from "@/lib/api-client";
import { qk } from "@/lib/query-keys";
import type { ConsoleRoleDefaults } from "@/lib/console-experience-api";
import type { OrgRole } from "@/types/organization";
const env = vi.hoisted(() => ({
  can: false,
  presentation: false,
  failedRead: false,
  costsAvailable: true,
  refetch: vi.fn(),
  saved: vi.fn(),
  read: vi.fn(),
  error: vi.fn(),
}));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.can }) }));
vi.mock("@/hooks/use-console-experience", () => ({
  useConsoleExperience: () => {
    env.read();
    return {
      data: {
        availability: DEFAULT_CHAT_HOME,
        reminders: { availability: true },
        presentation: env.presentation ? {} : undefined,
        costs: { availability: env.costsAvailable },
      },
      error: env.failedRead ? new Error("unavailable") : undefined,
      refetch: env.refetch,
    };
  },
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { patch: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { error: env.error } }));
vi.mock("./org-console-navigation", () => ({
  OrganizationConsoleNavigation: ({
    disabled,
    onSave,
  }: {
    disabled: boolean;
    onSave: (role: OrgRole, changes: ConsoleRoleDefaults, onSaved: () => void) => void;
  }) => (
    <button
      type="button"
      disabled={disabled}
      onClick={() => onSave("member", { navigation: [] }, env.saved)}
    >
      save-navigation
    </button>
  ),
}));
function mount(client = new QueryClient()) {
  return render(
    <QueryClientProvider client={client}>
      <OrgChatHomeSettings
        org={{ id: "org-one", chat_home_defaults: {}, onboarding_reminders: {} }}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  env.can = false;
  env.presentation = false;
  env.failedRead = false;
  env.costsAvailable = true;
  useOrgStore.setState({ activeOrgId: "org-one" });
  vi.mocked(apiClient.patch).mockResolvedValue({});
});
it("does not expose or read admin defaults without this workspace's permission", () => {
  const result = mount();
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(env.read).not.toHaveBeenCalled();
  env.can = true;
  useOrgStore.setState({ activeOrgId: "org-two" });
  result.rerender(
    <QueryClientProvider client={new QueryClient()}>
      <OrgChatHomeSettings org={{ id: "org-one" }} />
    </QueryClientProvider>,
  );
  expect(screen.queryByRole("combobox")).toBeNull();
  expect(env.read).not.toHaveBeenCalled();
});
it("sends only a named default field to the explicit organization", async () => {
  env.can = true;
  mount();
  await userEvent.click(screen.getByRole("combobox", { name: "Prompt suggestions" }));
  await userEvent.click(screen.getByRole("option", { name: "Hide" }));
  await waitFor(() =>
    expect(apiClient.patch).toHaveBeenCalledWith(
      "/orgs/org-one",
      { chat_home_defaults: { starters: false } },
      { headers: { "X-Organization-Id": "org-one" } },
    ),
  );
});
it("surfaces an org settings refusal instead of claiming a local save", async () => {
  env.can = true;
  vi.mocked(apiClient.patch).mockRejectedValue(new Error("refused"));
  mount();
  await userEvent.click(screen.getByRole("combobox", { name: "Setup reminders" }));
  await userEvent.click(screen.getByRole("option", { name: "Hide" }));
  await waitFor(() => expect(env.error).toHaveBeenCalled());
});

it("offers a real retry on failed experience reads and keeps deployment-restricted costs disabled", async () => {
  env.can = true;
  env.failedRead = true;
  env.costsAvailable = false;
  mount();
  expect(screen.getByRole("combobox", { name: "Who sees costs in chat" })).toBeDisabled();
  expect(screen.getByText("Unavailable for this deployment.")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Retry" }));
  expect(env.refetch).toHaveBeenCalledOnce();
  expect(apiClient.patch).not.toHaveBeenCalled();
});

it("keeps unrelated controls mounted and enabled while a cost write waits, then serializes the next field", async () => {
  env.can = true;
  const response = Promise.withResolvers<{ id: string; chat_cost_visibility: "nobody" }>();
  vi.mocked(apiClient.patch).mockReturnValueOnce(response.promise);
  const client = new QueryClient();
  const otherOrg = { id: "org-two", chat_cost_visibility: "everyone" };
  client.setQueryData(qk.organizations.list(), [
    { id: "org-one", name: "Keep this name", chat_cost_visibility: "everyone" },
    otherOrg,
  ]);
  const invalidate = vi.spyOn(client, "invalidateQueries");
  mount(client);
  const invitation = screen.getByRole("switch", { name: "Desktop app invitation" });
  const cost = screen.getByRole("combobox", { name: "Who sees costs in chat" });
  await userEvent.click(cost);
  await userEvent.click(screen.getByRole("option", { name: "Nobody in chat" }));
  await waitFor(() => expect(cost).toBeDisabled());
  expect(screen.getByRole("switch", { name: "Desktop app invitation" })).toBe(invitation);
  expect(invitation).toBeEnabled();
  expect(screen.getByRole("combobox", { name: "Prompt suggestions" })).toBeEnabled();

  await userEvent.click(invitation);
  await waitFor(() => expect(invitation).toBeDisabled());
  expect(cost).toBeDisabled();
  expect(apiClient.patch).toHaveBeenCalledTimes(1);
  await act(async () => response.resolve({ id: "org-one", chat_cost_visibility: "nobody" }));
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
  expect(apiClient.patch).toHaveBeenNthCalledWith(
    2,
    "/orgs/org-one",
    { console_notices: { desktop_install_prompt: false } },
    { headers: { "X-Organization-Id": "org-one" } },
  );
  await waitFor(() => expect(cost).toBeEnabled());
  expect(screen.getByRole("switch", { name: "Desktop app invitation" })).toBe(invitation);
  expect(client.getQueryData(qk.organizations.list())).toEqual([
    { id: "org-one", name: "Keep this name", chat_cost_visibility: "nobody" },
    otherOrg,
  ]);
  expect(
    invalidate.mock.calls.every(
      ([options]) =>
        options?.queryKey?.[0] === qk.organizations.list()[0] ||
        options?.queryKey?.[0] === qk.consoleExperience.all()[0],
    ),
  ).toBe(true);
});

it("refuses a queued write after switching organizations", async () => {
  env.can = true;
  const response = Promise.withResolvers<{ id: string }>();
  vi.mocked(apiClient.patch).mockReturnValueOnce(response.promise);
  mount();
  await userEvent.click(screen.getByRole("combobox", { name: "Who sees costs in chat" }));
  await userEvent.click(screen.getByRole("option", { name: "Nobody in chat" }));
  await userEvent.click(screen.getByRole("switch", { name: "Desktop app invitation" }));
  expect(apiClient.patch).toHaveBeenCalledTimes(1);
  act(() => useOrgStore.setState({ activeOrgId: "org-two" }));
  await act(async () => response.resolve({ id: "org-one" }));
  await waitFor(() => expect(env.error).toHaveBeenCalled());
  expect(apiClient.patch).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("switch", { name: "Desktop app invitation" })).toBeNull();
});

it("refreshes discovery catalogs only for role defaults and retains its save callback across a queued cost change", async () => {
  env.can = true;
  env.presentation = true;
  const response = Promise.withResolvers<{ id: string }>();
  vi.mocked(apiClient.patch).mockReturnValueOnce(response.promise);
  const client = new QueryClient();
  const invalidate = vi.spyOn(client, "invalidateQueries");
  mount(client);
  await userEvent.click(screen.getByRole("button", { name: "Console for each role" }));
  await userEvent.click(screen.getByRole("button", { name: "save-navigation" }));
  const cost = screen.getByRole("combobox", { name: "Who sees costs in chat" });
  expect(cost).toBeEnabled();
  await userEvent.click(cost);
  await userEvent.click(screen.getByRole("option", { name: "Nobody in chat" }));
  expect(apiClient.patch).toHaveBeenCalledTimes(1);
  await act(async () => response.resolve({ id: "org-one" }));
  await waitFor(() => expect(apiClient.patch).toHaveBeenCalledTimes(2));
  await waitFor(() => expect(env.saved).toHaveBeenCalledTimes(1));
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpServers.catalog() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpServers.lists() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.mcpServers.entries() });
  expect(invalidate).toHaveBeenCalledWith({ queryKey: qk.skills.gallery() });
});

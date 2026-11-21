import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { beforeEach, expect, it, vi } from "vitest";
import { OrgChatHomeSettings } from "./org-chat-home-settings";
import { useOrgStore } from "@/stores";
import { DEFAULT_CHAT_HOME } from "@/lib/console-experience-api";
import { apiClient } from "@/lib/api-client";
const env = vi.hoisted(() => ({ can: false, read: vi.fn(), error: vi.fn() }));
vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ can: () => env.can }) }));
vi.mock("@/hooks/use-console-experience", () => ({
  useConsoleExperience: () => {
    env.read();
    return { data: { availability: DEFAULT_CHAT_HOME, reminders: { availability: true } } };
  },
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { patch: vi.fn() } }));
vi.mock("sonner", () => ({ toast: { error: env.error } }));
function mount() {
  return render(
    <QueryClientProvider client={new QueryClient()}>
      <OrgChatHomeSettings
        org={{ id: "org-one", chat_home_defaults: {}, onboarding_reminders: {} }}
      />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.clearAllMocks();
  env.can = false;
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

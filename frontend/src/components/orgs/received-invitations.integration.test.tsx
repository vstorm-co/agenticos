import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor, act } from "@testing-library/react";
import { beforeEach, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import { ReceivedInvitations } from "./received-invitations";
import type { ReceivedInvitation } from "@/hooks/use-received-invitations";

const env = vi.hoisted(() => ({
  auth: { isAuthenticated: true, user: { id: "person" } as { id: string } | null },
  path: "/chat",
  push: vi.fn(),
  setOrg: vi.fn(),
  items: [] as ReceivedInvitation[],
}));
vi.mock("next/navigation", () => ({
  usePathname: () => env.path,
  useRouter: () => ({ push: env.push }),
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: Object.assign((select: (state: typeof env.auth) => unknown) => select(env.auth), {
    getState: () => env.auth,
  }),
}));
vi.mock("@/stores/org-store", () => ({
  useOrgStore: (select: (state: { setActiveOrgId: typeof env.setOrg }) => unknown) =>
    select({ setActiveOrgId: env.setOrg }),
}));
vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn(), post: vi.fn() } }));

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <ReceivedInvitations />
    </QueryClientProvider>,
  );
}
beforeEach(() => {
  vi.resetAllMocks();
  env.path = "/chat";
  env.auth = { isAuthenticated: true, user: { id: "person" } };
  env.items = [
    {
      id: "invite",
      organization_id: "company",
      organization_name: "Northwind",
      role: "member",
      expires_at: "2026-12-01T00:00:00Z",
    },
  ];
  vi.mocked(apiClient.get).mockImplementation(async () => env.items);
  vi.mocked(apiClient.post).mockImplementation(async () => {
    env.items = [];
    return { organization_id: "company" };
  });
});
it("shows addressed invitations after sign-in without any token or selected organization", async () => {
  mount();
  expect(await screen.findByRole("dialog", { name: "Your team is waiting" })).toBeVisible();
  expect(screen.getByText("Northwind")).toBeVisible();
  expect(screen.getByText("Your role: Member")).toBeVisible();
  expect(apiClient.get).toHaveBeenCalledWith("/invitations/received");
  expect(apiClient.post).not.toHaveBeenCalled();
});
it("accepts the chosen invitation and enters its organization's onboarding", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Join workspace" }));
  await waitFor(() => expect(env.push).toHaveBeenCalledWith("/onboarding?welcome=1&entry=joined"));
  expect(apiClient.post).toHaveBeenCalledWith("/invitations/received/invite/accept");
  expect(env.setOrg).toHaveBeenCalledWith("company");
});
it("lets the person postpone and reopen without accepting", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Later" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Invitations (1)" }));
  expect(screen.getByRole("dialog")).toBeVisible();
  expect(apiClient.post).not.toHaveBeenCalled();
});
it("keeps a failed acceptance explicit and does not switch workspace", async () => {
  vi.mocked(apiClient.post).mockRejectedValue(new Error("Expired"));
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Join workspace" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Could not accept");
  expect(env.setOrg).not.toHaveBeenCalled();
  expect(env.push).not.toHaveBeenCalled();
});
it("offers all invitations and joins only the selected one", async () => {
  env.items.push({
    ...env.items[0]!,
    id: "second",
    organization_id: "other",
    organization_name: "Acme",
  });
  mount();
  const buttons = await screen.findAllByRole("button", { name: "Join workspace" });
  fireEvent.click(buttons[1]!);
  await waitFor(() =>
    expect(apiClient.post).toHaveBeenCalledWith("/invitations/received/second/accept"),
  );
});
it.each(["/login", "/pl/invitations/pending", "/shared/chat"])(
  "leaves explicit authentication/invitation/public paths alone: %s",
  (path) => {
    env.path = path;
    mount();
    expect(apiClient.get).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  },
);
it("does not query when signed out", () => {
  env.auth = { isAuthenticated: false, user: null };
  mount();
  expect(apiClient.get).not.toHaveBeenCalled();
});
it("ignores a late acceptance after the account changes", async () => {
  let resolve: (value: { organization_id: string }) => void = () => {
    throw new Error("Not started");
  };
  vi.mocked(apiClient.post).mockImplementation(
    () =>
      new Promise((done) => {
        resolve = done;
      }),
  );
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Join workspace" }));
  await waitFor(() => expect(apiClient.post).toHaveBeenCalled());
  expect(screen.getByRole("button", { name: "Joining…" })).toBeDisabled();
  env.auth = { isAuthenticated: true, user: { id: "different" } };
  await act(async () => resolve({ organization_id: "company" }));
  expect(env.setOrg).not.toHaveBeenCalled();
  expect(env.push).not.toHaveBeenCalled();
});

it("closes with the dialog control while keeping the invitation available", async () => {
  mount();
  fireEvent.click(await screen.findByRole("button", { name: "Close" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Invitations (1)" })).toBeVisible();
  expect(apiClient.post).not.toHaveBeenCalled();
});

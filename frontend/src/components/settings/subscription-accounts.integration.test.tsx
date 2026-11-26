import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { SubscriptionAccounts } from "./subscription-accounts";
import { apiClient } from "@/lib/api-client";
import { toast } from "sonner";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
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

const ACCOUNT = {
  name: "antigravity-me.json",
  provider: "antigravity",
  label: null,
  email: "me@example.com",
  status: "active",
  disabled: false,
  unavailable: false,
};

let signInStatus = "wait";

function mount() {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return render(
    <QueryClientProvider client={client}>
      <SubscriptionAccounts />
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  signInStatus = "wait";
  vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
    path.endsWith("/usage")
      ? { status: "unavailable", observed_at: null, windows: [] }
      : path.startsWith("/subscription-accounts/sign-ins/")
        ? { status: signInStatus, error: null }
        : { enabled: true, items: [ACCOUNT] },
  );
  vi.mocked(apiClient.delete).mockResolvedValue(undefined);
});

async function rowOf(name: string) {
  const search = screen.getByRole("textbox", { name: "Search subscriptions..." });
  await userEvent.clear(search);
  await userEvent.type(search, name);
  const title = await screen.findByText(name);
  const row = title.closest("tr");
  if (!row) throw new Error(`No row for ${name}`);
  return within(row);
}

it("lists each sign-in with the accounts filed under it, and the risk", async () => {
  mount();
  const antigravity = await rowOf("Google Antigravity");
  expect(await antigravity.findByText("me@example.com")).toBeInTheDocument();
  expect(antigravity.getByRole("button", { name: "Add account" })).toBeInTheDocument();
  const claude = await rowOf("Claude Code (Pro, Max)");
  expect(claude.getByText("Not connected")).toBeInTheDocument();
  expect(screen.getByRole("note")).toHaveTextContent("at your own risk");
});

it("renders nothing where the deployment runs no gateway", async () => {
  vi.mocked(apiClient.get).mockResolvedValue({ enabled: false, items: [] });
  const { container } = mount();
  await waitFor(() => expect(apiClient.get).toHaveBeenCalled());
  await waitFor(() => expect(container).toBeEmptyDOMElement());
});

it("finishes a device sign-in on its own once the provider approves", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://auth.example/device",
    state: "st-1",
    flow: "device",
    user_code: "ABCD-1234",
    expires_in: 600,
  });
  mount();
  const kimi = await rowOf("Kimi Code (kimi.com)");
  await userEvent.click(kimi.getByRole("button", { name: "Connect" }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByText("ABCD-1234")).toBeInTheDocument();
  expect(
    within(dialog).getByRole("link", { name: /Open Kimi Code \(kimi.com\) sign-in/ }),
  ).toHaveAttribute("href", "https://auth.example/device");
  expect(within(dialog).queryByLabelText("Address your browser ended on")).toBeNull();
  expect(apiClient.post).toHaveBeenCalledWith("/subscription-accounts/sign-ins", {
    provider: "kimi",
  });
  signInStatus = "ok";
  await waitFor(
    () => expect(toast.success).toHaveBeenCalledWith("Kimi Code (kimi.com) is connected"),
    {
      timeout: 5000,
    },
  );
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
}, 10_000);

it("finishes a browser sign-in with the pasted address, and cancels an abandoned one", async () => {
  vi.mocked(apiClient.post).mockImplementation(async (path: string) =>
    path === "/subscription-accounts/sign-ins"
      ? { url: "https://claude.example/oauth", state: "st-2", flow: null, user_code: null }
      : undefined,
  );
  mount();
  const claude = await rowOf("Claude Code (Pro, Max)");
  await userEvent.click(claude.getByRole("button", { name: "Connect" }));
  const dialog = await screen.findByRole("dialog");
  const field = await within(dialog).findByLabelText("Address your browser ended on");
  expect(within(dialog).getByText(/localhost on your computer/)).toBeInTheDocument();
  await userEvent.type(field, "http://localhost:54545/callback?code=c&state=st-2");
  await userEvent.click(within(dialog).getByRole("button", { name: "Finish" }));
  expect(apiClient.post).toHaveBeenCalledWith("/subscription-accounts/sign-ins/st-2/callback", {
    redirect_url: "http://localhost:54545/callback?code=c&state=st-2",
  });
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  expect(apiClient.delete).toHaveBeenCalledWith("/subscription-accounts/sign-ins/st-2");
});

it("disconnects one account by its name", async () => {
  mount();
  const antigravity = await rowOf("Google Antigravity");
  await userEvent.click(await antigravity.findByRole("button", { name: "Actions" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
  expect(apiClient.delete).toHaveBeenCalledWith("/subscription-accounts/antigravity-me.json");
});

it("closes the dialog with the reason when a sign-in cannot start", async () => {
  vi.mocked(apiClient.post).mockRejectedValue(new Error("gateway down"));
  mount();
  const xai = await rowOf("Grok (xAI)");
  await userEvent.click(xai.getByRole("button", { name: "Connect" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
});

it("offers a retry when the accounts cannot be loaded", async () => {
  vi.mocked(apiClient.get).mockRejectedValue(new Error("offline"));
  mount();
  await userEvent.click(await screen.findByRole("button", { name: "Retry" }));
  expect(apiClient.get).toHaveBeenCalledTimes(2);
});

it("says why a pasted address was refused, and copies a device code", async () => {
  const writeText = vi.fn().mockResolvedValue(undefined);
  Object.defineProperty(navigator, "clipboard", { value: { writeText }, configurable: true });
  vi.mocked(apiClient.post).mockImplementation(async (path: string) => {
    if (path.endsWith("/callback")) throw new Error("refused");
    return { url: "https://x.example", state: "st-3", flow: null, user_code: null };
  });
  mount();
  const meta = await rowOf("Meta AI");
  await userEvent.click(meta.getByRole("button", { name: "Connect" }));
  const dialog = await screen.findByRole("dialog");
  await userEvent.type(
    await within(dialog).findByLabelText("Address your browser ended on"),
    "http://localhost/cb",
  );
  await userEvent.click(within(dialog).getByRole("button", { name: "Finish" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());

  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://x.example",
    state: "st-4",
    flow: "device",
    user_code: "WXYZ",
  });
  await userEvent.click(within(dialog).getByRole("button", { name: "Cancel" }));
  const devin = await rowOf("Devin");
  await userEvent.click(devin.getByRole("button", { name: "Connect" }));
  const second = await screen.findByRole("dialog");
  await userEvent.click(await within(second).findByRole("button", { name: "Copy the code" }));
  expect(writeText).toHaveBeenCalledWith("WXYZ");
});

it("cancels the sign-in when the dialog is dismissed with Escape", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://x.example",
    state: "st-5",
    flow: null,
    user_code: null,
  });
  // An expired sign-in refuses the cancel; closing must not surface that.
  vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("gone"));
  mount();
  const codex = await rowOf("ChatGPT (Codex)");
  await userEvent.click(codex.getByRole("button", { name: "Connect" }));
  await screen.findByLabelText("Address your browser ended on");
  await userEvent.keyboard("{Escape}");
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(apiClient.delete).toHaveBeenCalledWith("/subscription-accounts/sign-ins/st-5");
  expect(toast.error).not.toHaveBeenCalled();
});

it("says why an account could not be disconnected", async () => {
  vi.mocked(apiClient.delete).mockRejectedValueOnce(new Error("gateway down"));
  mount();
  const antigravity = await rowOf("Google Antigravity");
  await userEvent.click(await antigravity.findByRole("button", { name: "Actions" }));
  await userEvent.click(screen.getByRole("menuitem", { name: "Disconnect" }));
  await waitFor(() => expect(toast.error).toHaveBeenCalled());
});

it("keeps several accounts of the same provider and their quota windows separate", async () => {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) => {
    if (path.endsWith("/usage"))
      return {
        status: "available",
        observed_at: null,
        windows: [
          {
            kind: "provider",
            label: "Gemini · Weekly",
            remaining_percent: path.includes("first.json") ? 39 : 75,
            duration_minutes: 10080,
            resets_at: null,
          },
        ],
      };
    return {
      enabled: true,
      items: [
        { ...ACCOUNT, name: "first.json", email: "first@example.com" },
        { ...ACCOUNT, name: "second.json", email: "second@example.com" },
      ],
    };
  });
  mount();
  const first = within(await screen.findByRole("row", { name: /first@example.com/ }));
  const second = within(await screen.findByRole("row", { name: /second@example.com/ }));
  expect(await first.findByRole("progressbar", { name: "Gemini · Weekly" })).toHaveAttribute(
    "aria-valuetext",
    "39% left",
  );
  expect(await second.findByRole("progressbar", { name: "Gemini · Weekly" })).toHaveAttribute(
    "aria-valuetext",
    "75% left",
  );
  expect(screen.getAllByRole("progressbar", { name: "Gemini · Weekly" })).toHaveLength(2);
  expect(screen.getByText("first@example.com")).toBeInTheDocument();
  expect(screen.getByText("second@example.com")).toBeInTheDocument();
  expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/first.json/usage");
  expect(apiClient.get).toHaveBeenCalledWith("/subscription-accounts/second.json/usage");
});

it("pages individual accounts and resets to the first page when searching", async () => {
  vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
    path.endsWith("/usage")
      ? { status: "unavailable", observed_at: null, windows: [] }
      : {
          enabled: true,
          items: Array.from({ length: 12 }, (_, index) => ({
            ...ACCOUNT,
            name: `account-${index}.json`,
            email: `person${index}@example.com`,
          })),
        },
  );
  mount();
  expect(await screen.findByText("person0@example.com")).toBeVisible();
  expect(screen.queryByText("person10@example.com")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Next page" }));
  expect(screen.getByText("person10@example.com")).toBeVisible();
  expect(screen.queryByText("person0@example.com")).not.toBeInTheDocument();
  await userEvent.type(screen.getByRole("textbox", { name: "Search subscriptions..." }), "person0");
  expect(screen.getByText("person0@example.com")).toBeVisible();
  expect(screen.queryByText("person10@example.com")).not.toBeInTheDocument();
});

it("does not request a callback URL for a device flow without a separate code", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://auth.example/device?code=complete",
    state: "device",
    flow: "device",
    user_code: null,
    expires_in: 600,
  });
  mount();
  const row = await rowOf("Grok (xAI)");
  await userEvent.click(row.getByRole("button", { name: "Connect" }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByRole("link", { name: /Open Grok/ })).toBeVisible();
  expect(within(dialog).queryByLabelText("Address your browser ended on")).not.toBeInTheDocument();
  expect(within(dialog).queryByRole("button", { name: "Finish" })).not.toBeInTheDocument();
});

it("shows a failed device status read and resumes sign-in after an explicit retry", async () => {
  vi.mocked(apiClient.post).mockResolvedValue({
    url: "https://auth.example/device",
    state: "st-1",
    flow: "device",
    user_code: "ABCD-1234",
    expires_in: 600,
  });
  const original = vi.mocked(apiClient.get).getMockImplementation()!;
  let failed = true;
  vi.mocked(apiClient.get).mockImplementation(async (...args) => {
    if (args[0].startsWith("/subscription-accounts/sign-ins/") && failed)
      throw new Error("Status temporarily unavailable");
    return original(...args);
  });
  mount();
  const kimi = await rowOf("Kimi Code (kimi.com)");
  await userEvent.click(kimi.getByRole("button", { name: "Connect" }));
  const dialog = await screen.findByRole("dialog");
  expect(await within(dialog).findByRole("alert")).toHaveTextContent(
    "Status temporarily unavailable",
  );
  expect(within(dialog).queryByText("Waiting for sign-in…")).toBeNull();
  failed = false;
  signInStatus = "ok";
  await userEvent.click(within(dialog).getByRole("button", { name: "Retry" }));
  await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  expect(toast.success).toHaveBeenCalledWith("Kimi Code (kimi.com) is connected");
});

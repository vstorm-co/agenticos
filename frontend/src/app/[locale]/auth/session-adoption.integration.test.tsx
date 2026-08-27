import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import type { ReactElement } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import CallbackPage from "./callback/page";
import MagicLinkPage from "./magic-link/page";
import { AuthGuard } from "@/components/layout/auth-guard";
import { apiClient } from "@/lib/api-client";
import { useAuthStore, useConversationStore } from "@/stores";

/**
 * The three pages that sign somebody in without going through `login`.
 *
 * Their hooks are unit-tested; what is untested without this file is the
 * wiring, and the wiring is the whole fix. Reverting any of these pages to the
 * `useAuthStore.getState().setUser(...)` it used to call leaves every other
 * test in the suite green while the account signing in is handed the previous
 * one's cache.
 *
 * An integration test rather than a Playwright spec, which is what
 * `.claude/rules/frontend.md` asks for: the assertion is about what the page
 * does to the client's own state, and none of these journeys are reachable in
 * the E2E environment - OAuth needs a provider and a magic link needs an email.
 */
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));

const replace = vi.hoisted(() => vi.fn());
const searchParams = vi.hoisted(() => new URLSearchParams());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ replace, push: vi.fn() }),
  useSearchParams: () => searchParams,
}));

let client: QueryClient;

/**
 * Leave the previous account's state lying around, then render.
 *
 * In that order, and not the other way round: these pages adopt from an effect
 * that resolves a promise, so seeding afterwards races the thing under test and
 * the assertion passes whether or not the page cleans up.
 */
function mountOver(ui: ReactElement) {
  useAuthStore.setState({ sessionOwnerId: "u-previous", user: null, isAuthenticated: false });
  client.setQueryData(["sessions", "list", 0], { items: [{ ip_address: "10.0.0.1" }] });
  useConversationStore.getState().setCurrentConversationId("c-previous");
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

const arriving = { id: "u-new", email: "new@example.com" };

beforeEach(() => {
  vi.clearAllMocks();
  searchParams.forEach((_, key) => searchParams.delete(key));
  useAuthStore.getState().logout();
  useConversationStore.getState().reset();
  client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
});

describe("the OAuth callback", () => {
  it("empties the previous account before adopting the one it exchanged", async () => {
    searchParams.set("code", "one-time");
    vi.mocked(apiClient.post).mockResolvedValue({ user: arriving, access_token: "t-new" });
    mountOver(<CallbackPage />);

    await waitFor(() => expect(useAuthStore.getState().user?.id).toBe("u-new"));

    expect(apiClient.post).toHaveBeenCalledWith("/auth/oauth-callback", { code: "one-time" });
    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
    expect(useConversationStore.getState().currentConversationId).toBeNull();
    expect(useAuthStore.getState().accessToken).toBe("t-new");
  });

  it("spends a single-use code once across a remount", async () => {
    // Strict Mode mounts this effect, cleans it up and mounts it again in dev;
    // both must share the one request, or the second POSTs a code the first
    // already redeemed and the sign-in 401s (#14, codex).
    searchParams.set("code", "dupe");
    let resolve!: (value: { user: typeof arriving; access_token: string }) => void;
    vi.mocked(apiClient.post).mockReturnValue(
      new Promise<{ user: typeof arriving; access_token: string }>((r) => {
        resolve = r;
      }),
    );

    render(
      <QueryClientProvider client={client}>
        <CallbackPage />
      </QueryClientProvider>,
    );
    render(
      <QueryClientProvider client={client}>
        <CallbackPage />
      </QueryClientProvider>,
    );

    await waitFor(() => expect(apiClient.post).toHaveBeenCalledTimes(1));
    resolve({ user: arriving, access_token: "t-new" });
    await waitFor(() => expect(useAuthStore.getState().user?.id).toBe("u-new"));
    expect(apiClient.post).toHaveBeenCalledTimes(1);
  });
});

describe("the magic link", () => {
  it("re-reads who is signed in before sending them on", async () => {
    // Verification answers with tokens and no user, so the page has nothing to
    // adopt - it has to ask. A tab that had already run its auth check keeps
    // the account it asked about otherwise.
    searchParams.set("token", "m-1");
    vi.mocked(apiClient.post).mockResolvedValue({ access_token: "t-new" });
    vi.mocked(apiClient.get).mockResolvedValue(arriving);
    mountOver(<MagicLinkPage />);

    await waitFor(() => expect(useAuthStore.getState().user?.id).toBe("u-new"));

    expect(apiClient.get).toHaveBeenCalledWith("/auth/me");
    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
    expect(useConversationStore.getState().currentConversationId).toBeNull();
  });
});

describe("the dashboard guard", () => {
  it("empties the previous account when it finds a different one signed in", async () => {
    // After the first auth check this guard is the only thing in the tab that
    // re-reads the identity, so it is the last place that can notice the
    // cookie now belongs to somebody else.
    vi.mocked(apiClient.get).mockResolvedValue({ ...arriving, access_token: "t-new" });
    mountOver(
      <AuthGuard>
        <p>the dashboard</p>
      </AuthGuard>,
    );

    await waitFor(() => expect(useAuthStore.getState().user?.id).toBe("u-new"));

    expect(client.getQueryData(["sessions", "list", 0])).toBeUndefined();
    expect(useConversationStore.getState().currentConversationId).toBeNull();
  });
});

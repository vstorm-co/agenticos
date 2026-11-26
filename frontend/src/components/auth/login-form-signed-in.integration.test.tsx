import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "./login-form";
import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { apiClient } from "@/lib/api-client";
import { ROUTES } from "@/lib/constants";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";

// A file of its own: the session check runs once per page load, and the other
// login-form tests have already spent it on a signed-out answer.
vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const router = vi.hoisted(() => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }));
vi.mock("next/navigation", () => ({
  useRouter: () => router,
  useSearchParams: () => new URLSearchParams(window.location.search),
  usePathname: () => "/login",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PublicConfigProvider config={DEFAULT_PUBLIC_CONFIG}>
        <LoginForm />
      </PublicConfigProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  // Signed in already: the session check answers with an account.
  vi.mocked(apiClient.get).mockResolvedValue({
    id: "u-1",
    email: "jdoe@acme.test",
    is_active: true,
    created_at: "",
    access_token: "t",
  });
});

describe("opening the sign-in page while signed in", () => {
  it("goes on to where the sign-in was headed", async () => {
    window.history.replaceState(null, "", `/login?returnTo=${encodeURIComponent("/agents")}`);
    mount();

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith("/agents"));
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("goes to the app when nothing named a destination", async () => {
    window.history.replaceState(null, "", "/login");
    mount();

    await waitFor(() => expect(router.replace).toHaveBeenCalledWith(ROUTES.CHAT));
  });
});

afterEach(() => vi.restoreAllMocks());

it("replaces the document for an already signed-in fragment destination", async () => {
  const replace = vi.fn();
  const assign = vi.fn();
  const location = window.location;
  window.history.replaceState(
    null,
    "",
    `/login?returnTo=${encodeURIComponent("/agents/a-1#tools")}`,
  );
  vi.spyOn(window, "location", "get").mockReturnValue({
    ...location,
    search: window.location.search,
    replace,
    assign,
  } as Location);
  mount();
  await waitFor(() => expect(replace).toHaveBeenCalledWith("/agents/a-1#tools"));
  expect(assign).not.toHaveBeenCalled();
  expect(router.push).not.toHaveBeenCalled();
});

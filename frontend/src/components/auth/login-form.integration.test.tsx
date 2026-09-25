import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { LoginForm } from "./login-form";
import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { apiClient, ApiError } from "@/lib/api-client";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";

vi.mock("@/lib/api-client", async () => {
  const actual = await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client");
  return { ...actual, apiClient: { get: vi.fn(), post: vi.fn() } };
});
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
// The query the page was opened with, which a test sets before mounting.
const query = vi.hoisted(() => ({ current: new URLSearchParams() }));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => query.current,
  usePathname: () => "/login",
  useParams: () => ({}),
  redirect: vi.fn(),
  permanentRedirect: vi.fn(),
}));

const FLOW = "0123456789abcdef0123456789abcdef";

function mount() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <PublicConfigProvider
        config={{
          ...DEFAULT_PUBLIC_CONFIG,
          oauthProviders: ["ldap", "google"],
          ldapDisplayName: "Active Directory",
        }}
      >
        <LoginForm />
      </PublicConfigProvider>
    </QueryClientProvider>,
  );
}

async function openDirectoryForm() {
  await userEvent.click(screen.getByRole("button", { name: "Continue with Active Directory" }));
}

async function signIn(username: string, password: string) {
  await userEvent.type(screen.getByLabelText("Active Directory username"), username);
  await userEvent.type(screen.getByLabelText("Password"), password);
  await userEvent.click(screen.getByRole("button", { name: "Login" }));
}

beforeEach(() => {
  vi.clearAllMocks();
  window.history.replaceState(null, "", "/login");
  query.current = new URLSearchParams();
  // Signed out on load: the session check answers 401.
  vi.mocked(apiClient.get).mockRejectedValue(new ApiError(401, "Not authenticated"));
});

describe("signing in with a directory account", () => {
  it("swaps the email form for a username form named after the directory", async () => {
    mount();
    await openDirectoryForm();

    expect(screen.getByText("Sign in with Active Directory")).toBeInTheDocument();
    // A username, not an address: `jdoe` is what the directory binds with.
    expect(screen.getByLabelText("Active Directory username")).toHaveAttribute("type", "text");
    expect(screen.getByLabelText("Active Directory username")).toHaveAttribute(
      "autocomplete",
      "username",
    );
    expect(screen.queryByLabelText("Email")).not.toBeInTheDocument();
    expect(screen.queryByRole("link", { name: "Continue with Google" })).not.toBeInTheDocument();
  });

  it("posts the username and password to the directory sign-in", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      user: { id: "u-1", email: "jdoe@acme.test", is_active: true, created_at: "" },
      access_token: "t",
    });
    mount();
    await openDirectoryForm();

    await signIn("jdoe", "s3cret");

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith("/auth/ldap/login", {
        username: "jdoe",
        password: "s3cret",
      }),
    );
  });

  it("names a staged invitation's flow, so the account it creates is admitted", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({
      user: { id: "u-1", email: "jdoe@acme.test", is_active: true, created_at: "" },
      access_token: "t",
    });
    window.history.replaceState(
      null,
      "",
      `/login?returnTo=${encodeURIComponent(`/invitations/pending?flow=${FLOW}`)}`,
    );
    mount();
    await openDirectoryForm();

    await signIn("jdoe", "s3cret");

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(`/auth/ldap/login?flow=${FLOW}`, {
        username: "jdoe",
        password: "s3cret",
      }),
    );
  });

  it("shows the directory's refusal in the form, and lets the person try again", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(401, "Invalid username or password", {
        error: { code: "DIRECTORY_CREDENTIALS_REJECTED", message: "Invalid username or password" },
      }),
    );
    mount();
    await openDirectoryForm();

    await signIn("jdoe", "wrong");

    expect(await screen.findByText("Invalid username or password")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeEnabled();
  });

  it("says sign-in failed for a failure that is not a refusal", async () => {
    vi.mocked(apiClient.post).mockRejectedValue("offline");
    mount();
    await openDirectoryForm();

    await signIn("jdoe", "pw");

    expect(await screen.findByText("Login failed. Please try again.")).toBeInTheDocument();
  });

  it("says why a sign-in that left the page sent the person back", () => {
    // A Kerberos challenge the browser could not answer ends at /login?error=...
    query.current = new URLSearchParams({ error: "No Kerberos ticket was offered." });
    mount();

    expect(screen.getByText("No Kerberos ticket was offered.")).toBeInTheDocument();
  });

  it("goes back to email and password", async () => {
    mount();
    await openDirectoryForm();

    await userEvent.click(screen.getByRole("button", { name: "Use email and password instead" }));

    expect(screen.getByLabelText("Email")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Continue with Active Directory" })).toBeVisible();
  });
});

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
      expect(apiClient.post).toHaveBeenCalledWith(
        "/auth/ldap/login",
        { username: "jdoe", password: "s3cret" },
        { signal: expect.any(AbortSignal) },
      ),
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
      expect(apiClient.post).toHaveBeenCalledWith(
        `/auth/ldap/login?flow=${FLOW}`,
        { username: "jdoe", password: "s3cret" },
        { signal: expect.any(AbortSignal) },
      ),
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

  it("says the server did not answer when a sign-in times out", async () => {
    // A request a dead connection swallowed spun the button until a reload.
    vi.mocked(apiClient.post).mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    mount();
    await openDirectoryForm();

    await signIn("jdoe", "pw");

    expect(
      await screen.findByText(
        "The server did not answer in time. Check your connection and try again.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Login" })).toBeEnabled();
  });

  it("says the same for the password form", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(new DOMException("timed out", "TimeoutError"));
    mount();

    await userEvent.type(screen.getByLabelText("Email"), "a@example.com");
    await userEvent.type(screen.getByLabelText("Password"), "pw");
    await userEvent.click(screen.getByRole("button", { name: /Sign in|Login/ }));

    expect(
      await screen.findByText(
        "The server did not answer in time. Check your connection and try again.",
      ),
    ).toBeInTheDocument();
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

describe("credential refusal feedback", () => {
  it.each([false, true])(
    "marks only rejected credentials, including directory=%s",
    async (directory) => {
      vi.mocked(apiClient.post).mockRejectedValue(
        new ApiError(401, "Invalid credentials", {
          error: {
            code: directory ? "DIRECTORY_CREDENTIALS_REJECTED" : "AUTHENTICATION_ERROR",
            message: "Invalid credentials",
            details: directory ? null : { reason: "invalid_credentials" },
          },
        }),
      );
      mount();
      if (directory) await openDirectoryForm();
      await userEvent.type(
        screen.getByLabelText(directory ? "Active Directory username" : "Email"),
        directory ? "jdoe" : "ada@example.com",
      );
      const password = screen.getByLabelText("Password");
      await userEvent.type(password, "retained-password");
      await userEvent.click(screen.getByRole("button", { name: "Login" }));
      await waitFor(() => expect(password).toHaveAttribute("aria-invalid", "true"));
      expect(password).toHaveValue("retained-password");
      expect(password).toHaveAccessibleDescription();
      await userEvent.type(password, "1");
      expect(password).toHaveAttribute("aria-invalid", "false");
      vi.mocked(apiClient.post).mockRejectedValue(new ApiError(503, "Unavailable"));
      await userEvent.click(screen.getByRole("button", { name: "Login" }));
      await screen.findByRole("alert");
      expect(password).toHaveAttribute("aria-invalid", "false");
    },
  );
  it.each([false, true])(
    "keeps a disabled-account 401 separate from the password, directory=%s",
    async (directory) => {
      vi.mocked(apiClient.post).mockRejectedValue(
        new ApiError(401, "User account is disabled", {
          error: {
            code: "AUTHENTICATION_ERROR",
            message: "User account is disabled",
            details: null,
          },
        }),
      );
      mount();
      if (directory) await openDirectoryForm();
      await userEvent.type(
        screen.getByLabelText(directory ? "Active Directory username" : "Email"),
        directory ? "jdoe" : "ada@example.com",
      );
      const password = screen.getByLabelText("Password");
      await userEvent.type(password, "correct-password");
      await userEvent.click(screen.getByRole("button", { name: "Login" }));
      await expect(screen.findByRole("alert")).resolves.toHaveTextContent(
        "User account is disabled",
      );
      expect(password).toHaveAttribute("aria-invalid", "false");
      expect(password).toHaveValue("correct-password");
    },
  );
});

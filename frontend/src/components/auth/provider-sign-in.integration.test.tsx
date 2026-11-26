import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { ReactNode } from "react";

import { BrandingProvider } from "@/components/branding/branding-provider";
import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { BUILT_IN_BRANDING } from "@/lib/branding";
import { DEFAULT_PUBLIC_CONFIG, type SignInProvider } from "@/lib/public-config";
import { apiClient, ApiError } from "@/lib/api-client";
import { LoginForm } from "./login-form";
import { RegisterForm } from "./register-form";
import { ForgotPasswordForm } from "./forgot-password-form";
import { ResetPasswordForm } from "./reset-password-form";
import { ProviderSignIn } from "./provider-sign-in";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn() },
}));
const query = new URLSearchParams({ returnTo: "/projects/project-one" });
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn(), prefetch: vi.fn() }),
  useSearchParams: () => query,
  usePathname: () => "/login",
  useParams: () => ({}),
}));

function mount(children: ReactNode, providers: SignInProvider[] = ["oidc"]) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      <PublicConfigProvider
        config={{
          ...DEFAULT_PUBLIC_CONFIG,
          oidcDisplayName: "Company SSO",
          ldapDisplayName: "Directory",
        }}
      >
        <BrandingProvider
          branding={{
            ...BUILT_IN_BRANDING,
            passwordSignInEnabled: false,
            signInProviders: providers,
          }}
        >
          {children}
        </BrandingProvider>
      </PublicConfigProvider>
    </QueryClientProvider>,
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  query.set("returnTo", "/projects/project-one");
  vi.mocked(apiClient.get).mockRejectedValue(new ApiError(401, "Not authenticated"));
  window.sessionStorage.clear();
});

describe("provider-only sign-in", () => {
  it.each([
    ["login", () => <LoginForm />],
    ["registration", () => <RegisterForm />],
    ["recovery", () => <ForgotPasswordForm />],
    ["old reset link", () => <ResetPasswordForm token="old-reset-token" />],
  ])("offers the provider instead of local credentials on %s", async (_name, form) => {
    mount(form());
    const link = screen.getByRole("link", { name: "Continue with Company SSO" });
    expect(link).toHaveAttribute("href", "/api/oauth/oidc/login");
    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByLabelText("Password")).toBeNull();
    link.addEventListener("click", (event) => event.preventDefault());
    await userEvent.click(link);
    expect(sessionStorage.getItem("oauthReturnTo")).toBe("/projects/project-one");
    expect(apiClient.post).not.toHaveBeenCalled();
  });

  it("explains a provider failure without revealing the local form", () => {
    mount(<ProviderSignIn error="Provider refused this account" />);
    expect(screen.getByRole("alert")).toHaveTextContent("Provider refused this account");
  });

  it("still permits directory authentication and returning to provider selection", async () => {
    mount(<ProviderSignIn />, ["ldap"]);
    await userEvent.click(screen.getByRole("button", { name: "Continue with Directory" }));
    expect(screen.getByLabelText("Directory username")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Choose another sign-in method" }));
    expect(screen.getByRole("button", { name: "Continue with Directory" })).toBeInTheDocument();
  });

  it("explains an unavailable provider instead of showing unusable controls", () => {
    mount(<ProviderSignIn />, []);
    expect(screen.getByText(/No identity provider is available/)).toBeInTheDocument();
    expect(screen.queryByRole("link")).toBeNull();
  });
});

it("keeps a staged invitation on a provider-only registration", () => {
  query.set("returnTo", "/invitations/pending?flow=0123456789abcdef0123456789abcdef");
  mount(<RegisterForm />);
  expect(screen.getByRole("link", { name: "Continue with Company SSO" })).toHaveAttribute(
    "href",
    "/api/oauth/oidc/login?flow=0123456789abcdef0123456789abcdef",
  );
});

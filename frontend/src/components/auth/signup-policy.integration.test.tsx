import { render, screen } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { RegisterForm } from "./register-form";
import { BrandingProvider } from "@/components/branding/branding-provider";
import { BUILT_IN_BRANDING, type Branding } from "@/lib/branding";

/**
 * What the sign-up form says about a deployment's own rules.
 *
 * The backend refuses the registration either way, and that is why these matter:
 * a form which accepts an address and *then* reports "that email domain cannot
 * register" is a form that lies. The visitor has no way to know the rule exists and
 * reads the refusal as the product being broken.
 */

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/hooks", () => ({ useAuth: () => ({ register: vi.fn() }) }));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
vi.mock("@/components/auth/oauth-buttons", () => ({ OAuthBlock: () => null }));

function branded(overrides: Partial<Branding> = {}) {
  return function Wrapper({ children }: { children: ReactNode }) {
    return (
      <BrandingProvider branding={{ ...BUILT_IN_BRANDING, ...overrides }}>
        {children}
      </BrandingProvider>
    );
  };
}

describe("an open deployment", () => {
  it("shows the form and says nothing about a rule it does not have", () => {
    render(<RegisterForm />, { wrapper: branded() });

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.queryByText(/invite-only/i)).not.toBeInTheDocument();
    expect(screen.queryByText(/can register here/i)).not.toBeInTheDocument();
  });
});

describe("a closed deployment", () => {
  it("shows no form at all", () => {
    // An input somebody can fill in for a request that will always be refused is
    // worse than no input.
    render(<RegisterForm />, { wrapper: branded({ signupMode: "closed" }) });

    expect(screen.queryByLabelText(/email/i)).not.toBeInTheDocument();
    expect(screen.getByRole("heading")).toHaveTextContent(/sign-up is closed/i);
  });

  it("keeps the way back to signing in", () => {
    // The most likely visitor is somebody who already has an account.
    render(<RegisterForm />, { wrapper: branded({ signupMode: "closed" }) });

    expect(screen.getByRole("link", { name: /login/i })).toBeInTheDocument();
  });

  it("names the deployment as its administrator named it", () => {
    render(<RegisterForm />, {
      wrapper: branded({ signupMode: "closed", appName: "Acme AI" }),
    });

    expect(screen.getByText(/Acme AI/)).toBeInTheDocument();
  });
});

describe("an invite-only deployment", () => {
  it("keeps the form, because an invited person still has to register", () => {
    // `InvitationService.accept` requires an existing signed-in user, so an invited
    // person creates an account first. Hiding the form would break invitations.
    render(<RegisterForm />, { wrapper: branded({ signupMode: "invite_only" }) });

    expect(screen.getByLabelText(/email/i)).toBeInTheDocument();
    expect(screen.getByText(/invite-only/i)).toBeInTheDocument();
  });
});

describe("a narrowed domain list", () => {
  it("says which addresses may register, before anybody types one", () => {
    render(<RegisterForm />, {
      wrapper: branded({ allowedEmailDomains: ["acme.com", "partner.io"] }),
    });

    expect(screen.getByText(/acme\.com, partner\.io/)).toBeInTheDocument();
  });
});

describe("whose terms the form links to", () => {
  it("points at the built-in pages by default", () => {
    render(<RegisterForm />, { wrapper: branded() });

    expect(screen.getByRole("link", { name: /terms/i })).toHaveAttribute("href", "/legal/terms");
  });

  it("points outward, in a new tab, once the deployment names its own", () => {
    // Same tab would lose a half-filled form.
    render(<RegisterForm />, {
      wrapper: branded({
        termsUrl: "https://acme.com/terms",
        privacyUrl: "https://acme.com/privacy",
      }),
    });

    const terms = screen.getByRole("link", { name: /terms/i });
    expect(terms).toHaveAttribute("href", "https://acme.com/terms");
    expect(terms).toHaveAttribute("target", "_blank");
    expect(terms).toHaveAttribute("rel", expect.stringContaining("noopener"));
    expect(screen.getByRole("link", { name: /privacy/i })).toHaveAttribute(
      "href",
      "https://acme.com/privacy",
    );
  });
});

import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OAuthBlock } from "./oauth-buttons";
import { PublicConfigProvider } from "@/components/public-config/public-config-provider";
import { AUTH_GLYPHS, type AuthProvider } from "@/lib/auth-glyphs.generated";
import { DEFAULT_PUBLIC_CONFIG } from "@/lib/public-config";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

afterEach(() => {
  window.sessionStorage.clear();
});

/** Mount the block under a deployment offering exactly these providers. */
function renderWith(
  providers: readonly AuthProvider[],
  props: Partial<Parameters<typeof OAuthBlock>[0]> = {},
) {
  return render(
    <PublicConfigProvider
      config={{
        ...DEFAULT_PUBLIC_CONFIG,
        apiUrl: "https://api.acme.example",
        oauthProviders: providers,
      }}
    >
      <OAuthBlock label="or" {...props} />
    </PublicConfigProvider>,
  );
}

/** Click the provider button without letting jsdom follow the link out. */
async function press(name: RegExp) {
  const link = screen.getByRole("link", { name });
  link.addEventListener("click", (event) => event.preventDefault());
  await userEvent.click(link);
}

describe("the OAuth buttons", () => {
  it("renders a link and a mark per configured provider", () => {
    renderWith(["google", "github", "microsoft"]);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute("href", "/api/oauth/google/login");
    expect(document.querySelectorAll("svg")).toHaveLength(3);
  });

  it("starts the sign-in same-origin and carries no token in the URL (#1414)", () => {
    // A staged invitation rides an httpOnly cookie the same-origin proxy reads and
    // attaches to the cross-origin hop; the provider link itself is credential-free.
    renderWith(["google"], { variant: "signup" });

    expect(screen.getByRole("link")).toHaveAttribute("href", "/api/oauth/google/login");
  });

  it("names the staged invitation's flow on the start, and nothing else about it", () => {
    // The flow is which staging's cookie the proxy attaches - two staged side by side
    // hold two - and is no credential on its own; the token and handle stay off the URL.
    renderWith(["google"], {
      variant: "signup",
      returnTo: "/invitations/pending?flow=0123456789abcdef0123456789abcdef",
    });

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "/api/oauth/google/login?flow=0123456789abcdef0123456789abcdef",
    );
  });

  it("remembers the deep link the visitor was headed to", async () => {
    // Not sent to the provider and not in the OAuth `state`: the trip starts
    // and ends in this tab, and `/auth/callback` reads it back (#135).
    renderWith(["google"], { returnTo: "/agents/a-1" });

    await press(/continueWith/);

    expect(window.sessionStorage.getItem("oauthReturnTo")).toBe("/agents/a-1");
    // The provider is told nothing about it.
    expect(screen.getByRole("link")).toHaveAttribute("href", expect.not.stringContaining("a-1"));
  });

  it("forgets an abandoned one on a fresh attempt with no deep link", async () => {
    // A fresh sign-in with nothing in the URL passes `null` (what `returnToForAttempt`
    // answers there) - clear the stale one. A retry passes `undefined` and leaves it.
    window.sessionStorage.setItem("oauthReturnTo", "/agents/gone");
    renderWith(["google"], { returnTo: null });

    await press(/continueWith/);

    expect(window.sessionStorage.getItem("oauthReturnTo")).toBeNull();
  });

  it("renders nothing when no provider is configured", () => {
    const { container } = renderWith([]);

    expect(container).toBeEmptyDOMElement();
  });

  it("offers Google outside a provider, which is the default a deployment ships with", () => {
    render(<OAuthBlock label="or" />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("/oauth/google/login"),
    );
  });

  it("keeps the full brand table off the auth pages (#955)", () => {
    // Importing BrandIcon or the 89-mark table reships every mark on the sign-in
    // page's critical path, which is the regression this guards.
    const source = readFileSync(
      join(process.cwd(), "src/components/auth/oauth-buttons.tsx"),
      "utf8",
    );

    expect(source).not.toMatch(/brand-icon|brand-glyphs\.generated/);
  });

  it("ships exactly the three identity-provider marks", () => {
    expect(Object.keys(AUTH_GLYPHS).sort()).toEqual(["github", "google", "microsoft"]);
  });
});

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
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/oauth/google/login"));
    expect(document.querySelectorAll("svg")).toHaveLength(3);
  });

  it("sends the visitor to the API origin the deployment named, not a baked one (#1544)", () => {
    renderWith(["google"]);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      "https://api.acme.example/api/v1/oauth/google/login",
    );
  });

  it("carries the invitation token to the provider on a sign-up", () => {
    renderWith(["google"], { variant: "signup", invitation: "tok" });

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("invitation=tok"),
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

  it("forgets an abandoned one, rather than resuming it on the next attempt", async () => {
    window.sessionStorage.setItem("oauthReturnTo", "/agents/gone");
    renderWith(["google"]);

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

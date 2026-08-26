import { readFileSync } from "node:fs";
import { join } from "node:path";

import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { OAuthBlock } from "./oauth-buttons";
import { AUTH_GLYPHS } from "@/lib/auth-glyphs.generated";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

const SAVED = process.env.NEXT_PUBLIC_OAUTH_PROVIDERS;
afterEach(() => {
  if (SAVED === undefined) delete process.env.NEXT_PUBLIC_OAUTH_PROVIDERS;
  else process.env.NEXT_PUBLIC_OAUTH_PROVIDERS = SAVED;
});

describe("the OAuth buttons", () => {
  it("renders a link and a mark per configured provider", () => {
    process.env.NEXT_PUBLIC_OAUTH_PROVIDERS = "google,github,microsoft";

    render(<OAuthBlock label="or" />);

    const links = screen.getAllByRole("link");
    expect(links).toHaveLength(3);
    expect(links[0]).toHaveAttribute("href", expect.stringContaining("/oauth/google/login"));
    expect(document.querySelectorAll("svg")).toHaveLength(3);
  });

  it("carries the invitation token to the provider on a sign-up", () => {
    process.env.NEXT_PUBLIC_OAUTH_PROVIDERS = "google";

    render(<OAuthBlock label="or" variant="signup" invitation="tok" />);

    expect(screen.getByRole("link")).toHaveAttribute(
      "href",
      expect.stringContaining("invitation=tok"),
    );
  });

  it("renders nothing when no provider is configured", () => {
    delete process.env.NEXT_PUBLIC_OAUTH_PROVIDERS;

    const { container } = render(<OAuthBlock label="or" />);

    expect(container).toBeEmptyDOMElement();
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

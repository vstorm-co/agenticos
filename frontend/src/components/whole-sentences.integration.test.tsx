import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import NotFound from "@/app/not-found";
import { ForgotPasswordForm } from "@/components/auth/forgot-password-form";
import { LoginForm } from "@/components/auth/login-form";
import { RegisterForm } from "@/components/auth/register-form";
import { CookiesBodyEn, CookiesBodyPl } from "@/components/legal/cookies-content";
import { PrivacyBodyEn, PrivacyBodyPl } from "@/components/legal/privacy-content";
import { TermsBodyEn, TermsBodyPl } from "@/components/legal/terms-content";

/**
 * A sentence reaches the screen whole, out of one message.
 *
 * These are the surfaces #425 found split across a key and a text node - the
 * heading whose emphasised half was translated while its opening words were
 * English JSX, and the contact line whose tail was a key beginning with a full
 * stop. Each is now one ICU message with a tag in it, read with `t.rich`.
 *
 * Rendering is the only thing that checks that arrangement. `vitest.setup.ts`
 * mocks `next-intl` with a *real* translator over the real `en.json`, so a tag
 * the message names and the component does not supply - `<em>` renamed, a
 * parameter dropped - makes next-intl give up on the message and render its key.
 * Nothing else in this suite would notice: `messages/catalog.test.ts` reads the
 * catalog without a component, and `check-i18n.ts` reads the source without a
 * catalog. Both would pass on `Sign in to <em>your workspace.</em>` read with a
 * `strong` callback.
 *
 * Most of the eleven are already rendered somewhere - the create-agent dialog,
 * the sessions panel, the slash palette, the invite link dialog, the MCP list.
 * These are the ones nothing else mounts.
 *
 * **What this cannot show.** The translator here is pinned to `en`, so a sentence
 * still half-hardcoded reads correctly to it - `Sign in to <em>{t("workspace")}</em>`
 * passes seven of these ten. What fails without the fix is the arrangement: revert
 * `messages/en.json` and seven fail, because the component asks for a message the
 * catalog no longer has. That the *other* locale gets the whole sentence follows
 * from the message being whole, and only a `pl` render would show it directly.
 */

vi.mock("@/hooks", () => ({ useAuth: () => ({ login: vi.fn(), register: vi.fn() }) }));
vi.mock("@/lib/api-client", () => ({
  apiClient: { post: vi.fn(), get: vi.fn() },
  ApiError: class extends Error {},
}));

describe("a heading is one message", () => {
  it.each([
    [LoginForm, "Sign in to your workspace."],
    [RegisterForm, "Create your workspace."],
    [ForgotPasswordForm, "Happens to the best of us."],
  ])("renders it whole, emphasis included", (Form, sentence) => {
    render(<Form />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent(sentence);
  });
});

describe("a contact line is one message", () => {
  it.each([
    [
      () => <TermsBodyEn appName="agenticos" />,
      "Questions? Email legal@example.com. We respond within five business days",
    ],
    [
      () => <TermsBodyPl appName="agenticos" />,
      "Pytania? Napisz na legal@example.com. Odpowiadamy w ciągu pięciu dni",
    ],
    [() => <PrivacyBodyEn appName="agenticos" />, "Questions or requests: privacy@example.com"],
    [() => <PrivacyBodyPl appName="agenticos" />, "Pytania lub żądania: privacy@example.com"],
    [() => <CookiesBodyEn />, "Questions: privacy@example.com"],
    [() => <CookiesBodyPl />, "Pytania: privacy@example.com"],
  ])("keeps the words and the link in one sentence", (Body, sentence) => {
    const { container } = render(<Body />);

    // Normalised because the anchor and the words around it are separate nodes,
    // and `textContent` runs them together exactly as a reader sees them.
    expect(container.textContent?.replace(/\s+/g, " ")).toContain(sentence);
  });
});

describe("the 404 page", () => {
  it("says what is missing rather than naming its own message keys", () => {
    render(<NotFound />);

    expect(screen.getByRole("heading", { level: 1 })).toHaveTextContent("Page not found");
    expect(screen.getByText(/doesn't exist or has been moved/)).toBeInTheDocument();
  });
});

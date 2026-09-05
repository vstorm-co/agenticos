import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImpersonationBanner } from "./impersonation-banner";
import { useImpersonation } from "@/hooks/use-impersonation";

vi.mock("@/hooks/use-impersonation", () => ({ useImpersonation: vi.fn() }));

const end = vi.fn();

function acting(overrides: Partial<ReturnType<typeof useImpersonation>> = {}) {
  vi.mocked(useImpersonation).mockReturnValue({
    impersonation: {
      session_id: "s-1",
      impersonator: { id: "a-1", email: "admin@example.com" },
      expires_at: "2026-09-05T11:30:00Z",
    },
    actingAs: {
      id: "u-1",
      email: "customer@example.com",
      is_active: true,
      created_at: "2026-07-01T00:00:00Z",
    },
    end,
    ending: false,
    ...overrides,
  });
}

beforeEach(() => vi.clearAllMocks());

/**
 * The strip that says this browser is somebody else's account right now.
 *
 * Not dismissible, unlike the announcement beside it: the only way to make it go
 * away is to stop. What is pinned is that it names both sides - the account being
 * acted as and the administrator everything is recorded against - and that its
 * one button is the exit (#1044).
 */
describe("the impersonation banner", () => {
  it("draws nothing for an ordinary session", () => {
    vi.mocked(useImpersonation).mockReturnValue({
      impersonation: null,
      actingAs: null,
      end,
      ending: false,
    });

    const { container } = render(<ImpersonationBanner />);

    expect(container).toBeEmptyDOMElement();
  });

  it("names the account being acted as and the administrator it is recorded against", () => {
    acting();

    render(<ImpersonationBanner />);

    expect(screen.getByRole("status")).toHaveTextContent(
      "Acting as customer@example.com. Everything you do is recorded as admin@example.com.",
    );
    expect(screen.getByRole("status")).toHaveTextContent(/Ends at/);
  });

  it("offers no dismissal, only the exit", async () => {
    acting();

    render(<ImpersonationBanner />);
    await userEvent.click(screen.getByRole("button", { name: "End impersonation" }));

    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(end).toHaveBeenCalledTimes(1);
  });

  it("holds the button while the end is in flight", () => {
    acting({ ending: true });

    render(<ImpersonationBanner />);

    expect(screen.getByRole("button", { name: "End impersonation" })).toBeDisabled();
  });
});

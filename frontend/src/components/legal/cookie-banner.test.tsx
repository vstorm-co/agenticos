import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";

import { CookieBanner } from "./cookie-banner";

vi.mock("@/lib/locale-navigation", () => ({ usePathname: () => "/login" }));

beforeEach(() => {
  localStorage.clear();
  useAuthStore.setState({ isAuthenticated: false });
});

afterEach(() => {
  delete window.__AGENTICOS_SHELL__;
});

describe("CookieBanner", () => {
  it("asks a signed-out visitor", () => {
    render(<CookieBanner />);
    expect(screen.getByRole("button", { name: /accept/i })).toBeInTheDocument();
  });

  it("stays out of blobby's and quick ask's windows, where it would be the whole page", () => {
    for (const win of ["blobby", "quick-ask"]) {
      window.__AGENTICOS_SHELL__ = {
        platform: "macos",
        version: "0.2.0",
        window: win,
        vibrancy: true,
      };
      const { container, unmount } = render(<CookieBanner />);
      expect(container).toBeEmptyDOMElement();
      unmount();
    }
  });

  it.each(["macos", "ios", "android"] as const)(
    "leaves sign-in unobstructed in the %s app",
    (platform) => {
      window.__AGENTICOS_SHELL__ = { platform, window: "main", version: "0.2.0", vibrancy: false };
      const { container } = render(<CookieBanner />);
      expect(container).toBeEmptyDOMElement();
    },
  );
});

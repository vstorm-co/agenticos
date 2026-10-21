import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";

import { AccountLocale } from "./account-locale";

const replace = vi.hoisted(() => vi.fn());
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => "/agents",
  useRouter: () => ({ replace }),
}));

const ADA: User = {
  id: "u-1",
  email: "ada@example.com",
  is_active: true,
  created_at: "2026-10-21T00:00:00Z",
};

beforeEach(() => replace.mockClear());

describe("AccountLocale", () => {
  it("moves the page to the language the account chose", () => {
    useAuthStore.setState({ user: { ...ADA, locale: "de" } });

    render(<AccountLocale />);

    expect(replace).toHaveBeenCalledWith("/agents", { locale: "de" });
  });

  it("keeps the page's own state - the conversation, the open test panel", () => {
    window.history.replaceState({}, "", "/agents/a-1?test=open");
    useAuthStore.setState({ user: { ...ADA, locale: "pl" } });

    render(<AccountLocale />);

    expect(replace).toHaveBeenCalledWith("/agents?test=open", { locale: "pl" });
    window.history.replaceState({}, "", "/");
  });

  it("stays put when the page is already in it", () => {
    useAuthStore.setState({ user: { ...ADA, locale: "en" } });

    render(<AccountLocale />);

    expect(replace).not.toHaveBeenCalled();
  });

  it("leaves the cookie to decide for an account that never chose", () => {
    useAuthStore.setState({ user: ADA });

    render(<AccountLocale />);

    expect(replace).not.toHaveBeenCalled();
  });
});

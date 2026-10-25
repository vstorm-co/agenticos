import { act, render } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore } from "@/stores";
import type { User } from "@/types";
import { ACCOUNT_LOCALE_STORAGE_KEY } from "@/lib/account-locale";
import DesktopLayout from "@/app/[locale]/desktop/layout";

import { AccountLocale } from "./account-locale";

const replace = vi.hoisted(() => vi.fn());
const route = vi.hoisted(() => ({ path: "/agents", locale: "en" }));
vi.mock("next-intl", () => ({ useLocale: () => route.locale }));
vi.mock("@/lib/locale-navigation", () => ({
  usePathname: () => route.path,
  useRouter: () => ({ replace }),
}));

const ADA: User = {
  id: "u-1",
  email: "ada@example.com",
  is_active: true,
  created_at: "2026-10-21T00:00:00Z",
};

beforeEach(() => {
  replace.mockClear();
  route.path = "/agents";
  route.locale = "en";
});

function share(value: unknown, key = ACCOUNT_LOCALE_STORAGE_KEY) {
  act(() => {
    const event = new StorageEvent("storage", { key, newValue: JSON.stringify(value) });
    // The shared test setup uses a memory-backed storage rather than jsdom's Storage.
    Object.defineProperty(event, "storageArea", { value: window.localStorage });
    window.dispatchEvent(event);
  });
}

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

  it.each(["/desktop/blobby", "/desktop/quick-ask"])(
    "follows the account on first opening %s even when its URL has another language",
    (path) => {
      route.path = path;
      route.locale = "pl";
      useAuthStore.setState({ user: { ...ADA, locale: "en" } });
      render(
        <DesktopLayout>
          <span>native content</span>
        </DesktopLayout>,
      );
      expect(replace).toHaveBeenCalledWith(path, { locale: "en" });
    },
  );

  it("follows a language change from another window without adopting its identity or token", () => {
    useAuthStore.setState({ user: { ...ADA, locale: "en" }, accessToken: "this-window-token" });
    render(<AccountLocale />);
    share({
      userId: ADA.id,
      locale: "de",
      access_token: "another-token",
      email: "other@example.com",
    });
    expect(replace).toHaveBeenCalledWith("/agents", { locale: "de" });
    expect(useAuthStore.getState().user).toEqual({ ...ADA, locale: "de" });
    expect(useAuthStore.getState().accessToken).toBe("this-window-token");
  });

  it("ignores another account, an unsupported locale and unrelated storage", () => {
    useAuthStore.setState({ user: { ...ADA, locale: "en" } });
    render(<AccountLocale />);
    share({ userId: "other", locale: "de" });
    share({ userId: ADA.id, locale: "es" });
    share({ userId: ADA.id, locale: "pl" }, "auth-storage");
    expect(replace).not.toHaveBeenCalled();
    expect(useAuthStore.getState().user?.locale).toBe("en");
  });

  it("does not turn a cached identity into an authenticated session", () => {
    useAuthStore.setState({
      user: { ...ADA, locale: "en" },
      isAuthenticated: false,
      isLoading: true,
    });
    render(<AccountLocale />);
    share({ userId: ADA.id, locale: "de" });
    expect(useAuthStore.getState().isAuthenticated).toBe(false);
    expect(useAuthStore.getState().isLoading).toBe(true);
  });

  it("stops listening when the window unmounts", () => {
    useAuthStore.setState({ user: { ...ADA, locale: "en" } });
    const view = render(<AccountLocale />);
    view.unmount();
    share({ userId: ADA.id, locale: "de" });
    expect(useAuthStore.getState().user?.locale).toBe("en");
  });
});

it("ignores a language event when this window is signed out", () => {
  useAuthStore.setState({ user: null });
  render(<AccountLocale />);
  share({ userId: ADA.id, locale: "de" });
  expect(useAuthStore.getState().user).toBeNull();
  expect(replace).not.toHaveBeenCalled();
});

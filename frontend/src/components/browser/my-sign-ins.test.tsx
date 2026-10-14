import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { MySignIns } from "./my-sign-ins";

const state = vi.hoisted(() => ({
  signIns: [] as {
    id: string;
    site: string;
    created_at: string | null;
    updated_at: string | null;
    last_used_at: string | null;
  }[],
  isLoading: false,
  error: null as unknown,
  forget: vi.fn(),
}));
const signing = vi.hoisted(() => ({
  available: false,
  start: vi.fn(),
  isStarting: false,
  push: vi.fn(),
}));

vi.mock("@/hooks/use-browser-sign-ins", () => ({
  useBrowserSignIns: () => state,
  useSignInToSite: () => signing,
}));
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: signing.push }),
  usePathname: () => "/settings/sign-ins",
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn() } }));

function mount() {
  render(
    <NextIntlClientProvider locale="en" messages={messages} timeZone="UTC">
      <MySignIns />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  state.signIns = [];
  state.isLoading = false;
  state.error = null;
  state.forget.mockReset();
  signing.available = false;
  signing.start.mockReset();
  signing.push.mockReset();
});

describe("the sites your agents' browser starts signed in to", () => {
  it("lists each site with when it was kept and last used, and forgets one", () => {
    state.signIns = [
      {
        id: "s1",
        site: "portal.example.test",
        created_at: "2026-10-01T09:00:00Z",
        updated_at: null,
        last_used_at: "2026-10-12T09:00:00Z",
      },
      {
        id: "s2",
        site: "crm.example.test",
        created_at: null,
        updated_at: null,
        last_used_at: null,
      },
    ];
    mount();

    expect(screen.getByText("portal.example.test")).toBeVisible();
    expect(screen.getByText(/Saved Oct 1, 2026 · last used Oct 12, 2026/)).toBeVisible();
    expect(screen.getByText("crm.example.test")).toBeVisible();

    fireEvent.click(screen.getAllByRole("button", { name: "Forget" })[0]!);
    expect(state.forget).toHaveBeenCalledWith("s1");
  });

  it("says how a sign-in gets here when none is kept", () => {
    mount();
    expect(screen.getByText(messages.pages.signIns.empty)).toBeVisible();
  });

  it("says a failed read out loud, and waits while it loads", () => {
    state.error = new Error("boom");
    mount();
    expect(screen.queryByText(messages.pages.signIns.empty)).toBeNull();
  });

  it("draws a placeholder while loading", () => {
    state.isLoading = true;
    mount();
    expect(screen.queryByRole("button", { name: "Forget" })).toBeNull();
  });
});

describe("signing in to a site from here", () => {
  it("is not offered by a deployment with no browser for it", () => {
    mount();

    expect(screen.queryByRole("button", { name: "Sign in to a site" })).toBeNull();
  });

  it("opens the browser on the site typed, then shows its live view", async () => {
    signing.available = true;
    signing.start.mockResolvedValue({ run_id: "sign-in-1", call_id: "sign-in" });
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Sign in to a site" }));
    fireEvent.change(screen.getByPlaceholderText("linkedin.com/login"), {
      target: { value: "github.com/login" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open browser" }));

    // A bare host is given its scheme: the browser needs an address.
    await waitFor(() => expect(signing.push).toHaveBeenCalledWith("/browse/sign-in-1/sign-in"));
    expect(signing.start).toHaveBeenCalledWith("https://github.com/login");
  });

  it("puts a refused address under the field, and closes on Cancel", async () => {
    const { ApiError } = await import("@/lib/api-error");
    signing.available = true;
    signing.start.mockRejectedValue(
      new ApiError(400, "Blocked", {
        error: {
          code: "BAD_REQUEST",
          message: "That address is inside the network.",
          details: { fields: [{ field: "url", message: "That address is inside the network." }] },
        },
      }),
    );
    mount();

    fireEvent.click(screen.getByRole("button", { name: "Sign in to a site" }));
    fireEvent.change(screen.getByPlaceholderText("linkedin.com/login"), {
      target: { value: "http://10.0.0.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Open browser" }));

    expect(await screen.findByText("That address is inside the network.")).toBeVisible();
    expect(signing.start).toHaveBeenCalledWith("http://10.0.0.5");
    fireEvent.click(screen.getByRole("button", { name: "Cancel" }));
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
  });
});

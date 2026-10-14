import { fireEvent, render, screen } from "@testing-library/react";
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

vi.mock("@/hooks/use-browser-sign-ins", () => ({ useBrowserSignIns: () => state }));

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

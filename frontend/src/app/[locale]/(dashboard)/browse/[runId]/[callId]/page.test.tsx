import { act, render, screen } from "@testing-library/react";
import { Suspense } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { Browse } from "@/lib/browse";
import { useAuthStore } from "@/stores";

import LiveBrowsePage from "./page";

const live = vi.hoisted(() => ({ browse: null as Browse | null }));

vi.mock("@/hooks/use-live-browse", () => ({
  useLiveBrowse: () => ({
    browse: live.browse,
    task: "",
    canControl: false,
    canRemember: false,
    status: "live",
    send: () => undefined,
    protect: () => undefined,
  }),
}));

function browse(overrides: Partial<Browse> = {}): Browse {
  return {
    callId: "call-1",
    runId: "run-1",
    goal: "find the monthly price of the Pro plan",
    maxSteps: 25,
    url: "https://example.test/pricing",
    title: "Pricing",
    steps: [],
    image: null,
    imageStep: -1,
    outcome: null,
    detail: null,
    ...overrides,
  };
}

// The page reads its params with `use()`: the first render suspends until they resolve.
async function renderPage(value: Browse) {
  live.browse = value;
  await act(async () => {
    render(
      <Suspense fallback={null}>
        <LiveBrowsePage params={Promise.resolve({ runId: "run-1", callId: "call-1" })} />
      </Suspense>,
    );
  });
}

beforeEach(() => {
  useAuthStore.setState({ user: { id: "u1", full_name: "Ada", email: "ada@acme.test" } as never });
});

describe("the browse page title", () => {
  it("names an unprotected browse as a live browser", async () => {
    await renderPage(browse());
    expect(await screen.findByRole("heading", { level: 1, name: "Live browser" })).toBeVisible();
  });

  it("names a protected browse as a protected browser, never as a live one", async () => {
    await renderPage(browse({ outputProtected: true }));
    expect(
      await screen.findByRole("heading", { level: 1, name: "Protected browser" }),
    ).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Live browser" })).not.toBeInTheDocument();
  });
});

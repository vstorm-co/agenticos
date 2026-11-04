import { act, render, screen, fireEvent, cleanup } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { version } from "../../../package.json";
import { ReleaseNotes } from "./release-notes";
import { useReleaseNotesStore } from "@/stores/release-notes-store";
import type { CurrentReleaseResponse } from "@/lib/releases";
const state = vi.hoisted(() => ({
  userId: "alice" as string | undefined,
  data: undefined as CurrentReleaseResponse | undefined,
}));
vi.mock("@/stores/auth-store", () => ({
  useAuthStore: (select: (s: { user: { id: string } | null }) => unknown) =>
    select({ user: state.userId ? { id: state.userId } : null }),
}));
vi.mock("@/hooks/use-current-release", () => ({ useCurrentRelease: () => ({ data: state.data }) }));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <p>{content}</p>,
}));
beforeEach(() => {
  vi.useFakeTimers();
  state.userId = "alice";
  state.data = {
    release: {
      version,
      url: `https://github.com/vstorm-co/agenticos/releases/tag/v${version}`,
      body: "Release improvements",
    },
  };
  useReleaseNotesStore.setState({ acknowledged: {} });
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});
async function ready() {
  await act(async () => {
    vi.advanceTimersByTime(801);
  });
}
it("shows installed release notes after login and remembers dismissal per account", async () => {
  const view = render(<ReleaseNotes />);
  expect(screen.queryByRole("dialog")).toBeNull();
  await ready();
  expect(screen.getByRole("dialog")).toHaveTextContent("Release improvements");
  fireEvent.click(screen.getByRole("button", { name: "Got it" }));
  expect(useReleaseNotesStore.getState().acknowledged.alice).toBe(version);
  view.unmount();
  render(<ReleaseNotes />);
  await ready();
  expect(screen.queryByRole("dialog")).toBeNull();
});
it("does not mark another account's notes as read", async () => {
  useReleaseNotesStore.getState().acknowledge("bob", version);
  render(<ReleaseNotes />);
  await ready();
  expect(screen.getByRole("dialog")).toBeVisible();
});
it("waits for onboarding or another dialog to close", async () => {
  const onboarding = document.createElement("div");
  onboarding.setAttribute("role", "dialog");
  document.body.append(onboarding);
  render(<ReleaseNotes />);
  await ready();
  expect(screen.queryByText("Release improvements")).toBeNull();
  await act(async () => {
    onboarding.remove();
  });
  expect(screen.getByText("Release improvements")).toBeVisible();
});
it.each(["logged out", "missing notes", "acknowledged", "downgrade"])(
  "does not interrupt when %s",
  async (condition) => {
    if (condition === "logged out") state.userId = undefined;
    if (condition === "missing notes") state.data = { release: null };
    if (condition === "acknowledged") useReleaseNotesStore.getState().acknowledge("alice", version);
    if (condition === "downgrade") useReleaseNotesStore.getState().acknowledge("alice", "99.0.0");
    render(<ReleaseNotes />);
    await ready();
    expect(screen.queryByRole("dialog")).toBeNull();
  },
);

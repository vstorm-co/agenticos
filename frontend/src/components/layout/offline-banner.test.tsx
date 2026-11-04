import { act, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { useAuthStore, useConversationStore, useOfflineStore } from "@/stores";
import type { User } from "@/types";
import { OfflineBanner } from "./offline-banner";

const { available, keepConsoleCode, refreshOutboxCounts } = vi.hoisted(() => ({
  available: { value: true },
  keepConsoleCode: vi.fn(() => Promise.resolve()),
  refreshOutboxCounts: vi.fn(() => Promise.resolve()),
}));
vi.mock("@/lib/offline/device-cache", () => ({
  offlineAvailable: () => available.value,
  keepConsoleCode,
  refreshOutboxCounts,
}));

function goOffline(offline: boolean) {
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(!offline);
  act(() => {
    window.dispatchEvent(new Event(offline ? "offline" : "online"));
  });
}

beforeEach(() => {
  vi.clearAllMocks();
  available.value = true;
  vi.spyOn(navigator, "onLine", "get").mockReturnValue(true);
  useOfflineStore.getState().reset();
  useConversationStore.getState().reset();
});

afterEach(() => {
  vi.restoreAllMocks();
});

describe("OfflineBanner", () => {
  it("is nothing online with nothing waiting", () => {
    const { container } = render(<OfflineBanner />);

    expect(container).toBeEmptyDOMElement();
    expect(keepConsoleCode).toHaveBeenCalled();
    expect(refreshOutboxCounts).not.toHaveBeenCalled();
  });

  it("reads what waits in the outboxes once somebody is signed in", () => {
    useAuthStore.setState({ user: { id: "u-1" } as User });
    render(<OfflineBanner />);

    expect(refreshOutboxCounts).toHaveBeenCalled();
    useAuthStore.setState({ user: null });
  });

  it("says the network is gone", () => {
    render(<OfflineBanner />);
    goOffline(true);

    expect(screen.getByRole("status")).toHaveTextContent("You're offline.");
  });

  it("says since when the screen is a copy, and stops once the network is back", () => {
    render(<OfflineBanner />);
    goOffline(true);
    act(() => useOfflineStore.getState().servedFromDevice(new Date("2026-10-22T08:30:00")));
    expect(screen.getByRole("status")).toHaveTextContent("saved on this device");

    goOffline(false);
    expect(screen.queryByRole("status")).toBeNull();
    expect(useOfflineStore.getState().savedAt).toBeNull();
  });

  it("says the server cannot be reached when the device has a network", () => {
    useOfflineStore.getState().servedFromDevice(new Date("2026-10-22T08:30:00"));
    render(<OfflineBanner />);

    expect(screen.getByRole("status")).toHaveTextContent("Can't reach the server");
  });

  it("names messages waiting in another conversation and leads there", () => {
    useConversationStore.getState().setCurrentConversationId("c-open");
    useOfflineStore.getState().setOutbox([
      { conversationId: "c-open", count: 1 },
      { conversationId: "c-other", count: 2 },
    ]);
    render(<OfflineBanner />);

    const link = screen.getByRole("link", { name: "2 messages waiting to send" });
    expect(link).toHaveAttribute("href", "/chat?id=c-other");
  });

  it("leads a new chat's waiting message to a new chat", () => {
    useOfflineStore.getState().setOutbox([{ conversationId: null, count: 1 }]);
    useConversationStore.getState().setCurrentConversationId("c-open");
    render(<OfflineBanner />);

    expect(screen.getByRole("link", { name: "1 message waiting to send" })).toHaveAttribute(
      "href",
      "/chat",
    );
  });

  it("is nothing in a browser tab, which keeps no copy", () => {
    available.value = false;
    useOfflineStore.getState().setOutbox([{ conversationId: "c-1", count: 1 }]);
    const { container } = render(<OfflineBanner />);
    goOffline(true);

    expect(container).toBeEmptyDOMElement();
    expect(keepConsoleCode).not.toHaveBeenCalled();
  });
});

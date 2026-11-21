import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";

import { EventSourcesWidget } from "./event-sources";

const useEventSources = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-event-sources", () => ({ useEventSources }));

function renderWidget(result: unknown) {
  useEventSources.mockReturnValue(result);
  render(
    <EventSourcesWidget
      title="Event sources"
      hint=""
      period={{ preset: "7d", from: "2026-10-05", to: "2026-10-11" }}
      seeAll="/event-sources"
    />,
  );
}

it("shows active and paused source counts and opens their catalog", () => {
  renderWidget({
    data: { items: [{ is_active: true }, { is_active: false }, { is_active: false }] },
  });
  expect(screen.getByText("Active")).toBeVisible();
  expect(screen.getByText("Paused")).toBeVisible();
  expect(screen.getByText("1")).toBeVisible();
  expect(screen.getByText("2")).toBeVisible();
  expect(screen.getByRole("link")).toHaveAttribute("href", "/event-sources");
});

it("waits for the catalog without showing the empty message", () => {
  renderWidget({ isLoading: true });
  expect(screen.getByRole("status")).toBeVisible();
  expect(screen.queryByText("No event sources yet")).toBeNull();
});

it("shows when there are no visible event sources", () => {
  renderWidget({ data: { items: [] } });
  expect(screen.getByText("No event sources yet")).toBeVisible();
});

it("retries when the catalog cannot be read", async () => {
  const refetch = vi.fn();
  renderWidget({ error: new Error("offline"), refetch });
  await userEvent.click(screen.getByRole("button", { name: /retry/i }));
  expect(refetch).toHaveBeenCalledOnce();
});

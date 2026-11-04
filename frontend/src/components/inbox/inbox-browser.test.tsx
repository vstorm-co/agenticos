import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { InboxBrowser } from "./inbox-browser";
import type { Suggestion } from "@/lib/suggestions-api";
const route = vi.hoisted(() => ({ selected: "b", select: vi.fn() }));
vi.mock("@/hooks/use-url-state", () => ({ useUrlState: () => [route.selected, route.select] }));
vi.mock("@/components/chat/suggestion-actions", () => ({
  SuggestionMark: () => null,
  urgentFirst: (items: Suggestion[]) => items,
  useSuggestionSource: () => () => null,
}));
vi.mock("./suggestion-rows", () => ({
  SuggestionRows: ({ items }: { items: Suggestion[] }) => (
    <div data-testid="detail">{items[0]?.id}</div>
  ),
}));
const item = (id: string): Suggestion => ({
  id,
  title: `Decision ${id}`,
  kind: "profile",
  status: "open",
  detail: null,
  payload: {},
  created_at: "2026-11-04T12:00:00Z",
});
describe("InboxBrowser", () => {
  it("opens a linked decision, selects by URL and falls back after it is resolved", () => {
    const { rerender } = render(<InboxBrowser items={[item("a"), item("b")]} />);
    expect(screen.getByTestId("detail")).toHaveTextContent("b");
    fireEvent.click(screen.getByRole("button", { name: /Decision a/ }));
    expect(route.select).toHaveBeenCalledWith("a");
    rerender(<InboxBrowser items={[item("a")]} />);
    expect(screen.getByTestId("detail")).toHaveTextContent("a");
  });
});

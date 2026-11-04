import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import type { Browse } from "@/lib/browse";
import { BrowserTabs } from "./browser-tabs";

const tab = (id: string, title: string | null): Browse => ({
  callId: id,
  goal: "",
  maxSteps: null,
  url: "https://example.test",
  title,
  steps: [],
  image: null,
  imageStep: -1,
  outcome: null,
  detail: null,
});
it("selects tabs by mouse and arrow/Home/End keys, keeping focus on the selected tab", async () => {
  const tabs = [tab("first", "Pricing"), tab("second", "Docs")];
  const select = vi.fn();
  const { rerender } = render(<BrowserTabs tabs={tabs} selected="first" onSelect={select} />);
  await userEvent.click(screen.getByRole("tab", { name: "Docs" }));
  expect(select).toHaveBeenLastCalledWith(tabs[1]);
  rerender(<BrowserTabs tabs={tabs} selected="second" onSelect={select} />);
  await userEvent.keyboard("{ArrowLeft}");
  expect(screen.getByRole("tab", { name: "Pricing" })).toHaveFocus();
  expect(select).toHaveBeenLastCalledWith(tabs[0]);
  rerender(<BrowserTabs tabs={tabs} selected="first" onSelect={select} />);
  await userEvent.keyboard("{End}");
  expect(screen.getByRole("tab", { name: "Docs" })).toHaveFocus();
  await userEvent.keyboard("{Home}");
  expect(screen.getByRole("tab", { name: "Pricing" })).toHaveFocus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Docs" })).toHaveFocus();
});
it("uses the host when a tab has no title", () => {
  render(<BrowserTabs tabs={[tab("first", null)]} selected="first" onSelect={vi.fn()} />);
  expect(screen.getByRole("tab", { name: "example.test" })).toHaveAttribute(
    "aria-selected",
    "true",
  );
});

it("keeps ordinary keys available and tolerates a tab list becoming empty", () => {
  const select = vi.fn();
  const { rerender } = render(
    <BrowserTabs
      tabs={[{ ...tab("loading", null), url: null }]}
      selected="loading"
      onSelect={select}
    />,
  );
  expect(screen.getByRole("tab", { name: "Browser" })).not.toHaveAttribute("title");
  fireEvent.keyDown(screen.getByRole("tablist"), { key: "a" });
  expect(select).not.toHaveBeenCalled();
  rerender(<BrowserTabs tabs={[]} selected="closed" onSelect={select} />);
  fireEvent.keyDown(screen.getByRole("tablist"), { key: "ArrowRight" });
  expect(select).not.toHaveBeenCalled();
});

it("reveals a newly selected overflowing tab without scrolling the chat", () => {
  const geometry = vi
    .spyOn(HTMLElement.prototype, "getBoundingClientRect")
    .mockImplementation(function (this: HTMLElement) {
      return this.getAttribute("role") === "tablist"
        ? new DOMRect(0, 0, 120, 32)
        : new DOMRect(this.textContent === "Docs" ? 150 : -30, 0, 100, 32);
    });
  try {
    const tabs = [tab("first", "Pricing"), tab("second", "Docs")];
    const { rerender } = render(<BrowserTabs tabs={tabs} selected="second" onSelect={vi.fn()} />);
    const strip = screen.getByRole("tablist");
    expect(strip.scrollLeft).toBe(130);
    rerender(<BrowserTabs tabs={tabs} selected="first" onSelect={vi.fn()} />);
    expect(strip.scrollLeft).toBe(100);
  } finally {
    geometry.mockRestore();
  }
});

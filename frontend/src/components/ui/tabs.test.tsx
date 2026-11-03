import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { Tabs, TabsList, TabsTrigger } from "./tabs";

beforeEach(() => {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockImplementation(function (
    this: HTMLElement,
  ) {
    const offset =
      this.getAttribute("role") === "tab" ? (this.closest('[role="tablist"]')?.scrollLeft ?? 0) : 0;
    const left =
      (this.getAttribute("role") === "tab" && this.textContent === "Settings" ? 260 : 0) - offset;
    const width = this.getAttribute("role") === "tablist" ? 200 : 80;
    return new DOMRect(left, 100, width, 40);
  });
});

afterEach(() => vi.restoreAllMocks());

function Strip({ value }: { value: string }) {
  return (
    <Tabs value={value}>
      <TabsList>
        <TabsTrigger value="cases">Cases</TabsTrigger>
        <TabsTrigger value="settings">Settings</TabsTrigger>
      </TabsList>
    </Tabs>
  );
}

it("reveals a tab selected by a deep link without scrolling the page vertically", async () => {
  render(<Strip value="settings" />);
  const strip = screen.getByRole("tablist");
  await waitFor(() => expect(strip.scrollLeft).toBe(140));
  expect(strip.scrollTop).toBe(0);
});

it("reveals a controlled selection changed by browser navigation", async () => {
  const view = render(<Strip value="cases" />);
  const strip = screen.getByRole("tablist");
  expect(strip.scrollLeft).toBe(0);
  view.rerender(<Strip value="settings" />);
  await waitFor(() => expect(strip.scrollLeft).toBe(140));
});

it("brings an earlier tab back into view when navigating back", async () => {
  const view = render(<Strip value="settings" />);
  const strip = screen.getByRole("tablist");
  await waitFor(() => expect(strip.scrollLeft).toBe(140));
  view.rerender(<Strip value="cases" />);
  await waitFor(() => expect(strip.scrollLeft).toBe(0));
});

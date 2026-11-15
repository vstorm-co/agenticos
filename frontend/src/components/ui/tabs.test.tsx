import { createRef } from "react";
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

it("forwards an object ref while a strip has no selected tab", () => {
  const ref = createRef<HTMLDivElement>();
  render(
    <Tabs>
      <TabsList ref={ref} />
    </Tabs>,
  );
  expect(ref.current).toBe(screen.getByRole("tablist"));
});

it("forwards a callback ref and clears it when the strip unmounts", () => {
  const ref = vi.fn();
  const view = render(
    <Tabs>
      <TabsList ref={ref} />
    </Tabs>,
  );
  expect(ref).toHaveBeenCalledWith(screen.getByRole("tablist"));
  view.unmount();
  expect(ref).toHaveBeenLastCalledWith(null);
});

it("supports an asChild list whose child has no rendered element", () => {
  function HiddenList() {
    return null;
  }
  render(
    <Tabs>
      <TabsList asChild>
        <HiddenList />
      </TabsList>
    </Tabs>,
  );
  expect(screen.queryByRole("tablist")).toBeNull();
});

it("keeps a selected tab's label out of the scroll affordance fade", async () => {
  const view = render(<Strip value="cases" />);
  const list = screen.getByRole("tablist");
  list.style.scrollPaddingLeft = "32px";
  list.style.scrollPaddingRight = "32px";
  view.rerender(<Strip value="settings" />);
  await waitFor(() => expect(list.scrollLeft).toBe(172));
});

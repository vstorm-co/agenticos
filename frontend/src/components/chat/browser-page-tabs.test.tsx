import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { BrowserPageTabs } from "./browser-page-tabs";

const tabs = {
  environment_id: "11111111-1111-4111-8111-111111111111",
  active_tab_id: "one",
  tabs: [
    { id: "one", title: "One", url: "https://one.example" },
    { id: "two", title: "Two", url: "https://two.example" },
  ],
};
it("shows real open pages and activates by click without a takeover", async () => {
  const activate = vi.fn();
  render(
    <BrowserPageTabs tabs={tabs} disabled={false} onActivate={activate} panelId="page" id="tabs" />,
  );
  expect(screen.getByRole("tab", { name: "One" })).toHaveAttribute("aria-selected", "true");
  await userEvent.click(screen.getByRole("tab", { name: "Two" }));
  expect(activate).toHaveBeenCalledExactlyOnceWith("two");
  expect(screen.getByRole("tab", { name: "One" })).toHaveAttribute("aria-selected", "true");
});
it("arrows move focus without issuing remote mutations; Enter activates", async () => {
  const activate = vi.fn();
  render(
    <BrowserPageTabs tabs={tabs} disabled={false} onActivate={activate} panelId="page" id="tabs" />,
  );
  screen.getByRole("tab", { name: "One" }).focus();
  await userEvent.keyboard("{ArrowRight}");
  expect(screen.getByRole("tab", { name: "Two" })).toHaveFocus();
  expect(activate).not.toHaveBeenCalled();
  await userEvent.keyboard("{Enter}");
  expect(activate).toHaveBeenCalledExactlyOnceWith("two");
});
it("keeps busy tabs readable but refuses clicks while another driver holds them", async () => {
  const activate = vi.fn();
  render(<BrowserPageTabs tabs={tabs} disabled onActivate={activate} panelId="page" id="tabs" />);
  await userEvent.click(screen.getByRole("tab", { name: "Two" }));
  expect(activate).not.toHaveBeenCalled();
  expect(screen.getByRole("tab", { name: "Two" })).toHaveAttribute("aria-disabled", "true");
});

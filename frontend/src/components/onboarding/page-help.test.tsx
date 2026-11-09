import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { PageHelp } from "./page-help";
import { useOnboardingStore } from "@/stores/onboarding-store";

const nav = vi.hoisted(() => ({ pathname: "/context" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

beforeEach(() => {
  nav.pathname = "/context";
  useOnboardingStore.setState({ isOpen: false, mode: "tour", index: 0 });
});

it("offers one info button, then closes the explanation before starting the page tour", async () => {
  render(<PageHelp description="Standing knowledge for agents" />);
  expect(screen.getAllByRole("button")).toHaveLength(1);
  expect(screen.queryByText("Standing knowledge for agents")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "More information" }));
  expect(screen.getByText("Standing knowledge for agents")).toBeVisible();
  await userEvent.click(screen.getByRole("button", { name: "Show tips for this page" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, mode: "page" });
});

it("keeps explanations available on pages without a walkthrough", async () => {
  nav.pathname = "/admin/users";
  render(<PageHelp description="Manage users" />);
  await userEvent.click(screen.getByRole("button", { name: "More information" }));
  expect(screen.getByText("Manage users")).toBeVisible();
  expect(screen.queryByRole("button", { name: "Show tips for this page" })).toBeNull();
});

it("offers the walkthrough without repeating a live summary", async () => {
  nav.pathname = "/pl/agents";
  render(<PageHelp />);
  await userEvent.click(screen.getByRole("button", { name: "More information" }));
  expect(screen.getByRole("button", { name: "Show tips for this page" })).toBeVisible();
});

it("renders no empty help on an undocumented page", () => {
  nav.pathname = "/admin/users";
  const { container } = render(<PageHelp />);
  expect(container).toBeEmptyDOMElement();
});

import { render, screen } from "@testing-library/react";
import { isValidElement, type ReactElement } from "react";
import { describe, expect, it, vi } from "vitest";
import DashboardLayout from "./layout";
import { StartOffer } from "@/components/onboarding/start-offer";
import { AppSidebar } from "@/components/layout/app-sidebar";
import { MainViewport } from "@/components/layout/main-viewport";

vi.mock("next/navigation", async (importOriginal) => ({
  ...(await importOriginal<typeof import("next/navigation")>()),
  usePathname: () => "/dashboard",
}));
interface FrameProps {
  children?: unknown;
  className?: string;
}
function find(
  node: unknown,
  matches: (element: ReactElement<FrameProps>) => boolean,
): ReactElement<FrameProps> | null {
  if (!isValidElement<FrameProps>(node)) return null;
  if (matches(node)) return node;
  const children = Array.isArray(node.props.children) ? node.props.children : [node.props.children];
  for (const child of children) {
    const hit = find(child, matches);
    if (hit) return hit;
  }
  return null;
}

describe("the dashboard's scroll container", () => {
  it("uses the positioned viewport for its content", () => {
    expect(
      find(DashboardLayout({ children: null }), (element) => element.type === MainViewport),
    ).not.toBeNull();
    render(<MainViewport>Content</MainViewport>);
    expect(screen.getByRole("main")).toHaveClass("relative");
  });
  it("scrolls within the screen-height shell", () => {
    const frame = find(
      DashboardLayout({ children: null }),
      (element) => element.props.className?.includes("h-[calc(var(--app-height") === true,
    );
    expect(frame).not.toBeNull();
    render(<MainViewport>Content</MainViewport>);
    expect(screen.getByRole("main")).toHaveClass("min-h-0", "flex-1", "overflow-auto");
  });
  it("leaves bottom spacing to the page rather than the scroll container", () => {
    render(<MainViewport>Content</MainViewport>);
    expect(screen.getByRole("main").className).not.toMatch(/(^|\s|:)pb-/);
  });
});

it("puts the start notice above the shared app row, outside both navigation and main", () => {
  const tree = DashboardLayout({ children: null });
  const shell = find(
    tree,
    (el) => el.props.className?.includes("h-[calc(var(--app-height") === true,
  );
  if (!shell) throw new Error("Missing app shell");
  const children = Array.isArray(shell.props.children)
    ? shell.props.children
    : [shell.props.children];
  const noticeIndex = children.findIndex(
    (child) => find(child, (el) => el.type === StartOffer) !== null,
  );
  const appIndex = children.findIndex(
    (child) => find(child, (el) => el.type === AppSidebar) !== null,
  );
  expect(noticeIndex).toBeGreaterThanOrEqual(0);
  expect(appIndex).toBeGreaterThan(noticeIndex);
  const viewport = find(tree, (el) => el.type === MainViewport);
  expect(find(viewport, (el) => el.type === StartOffer)).toBeNull();
});

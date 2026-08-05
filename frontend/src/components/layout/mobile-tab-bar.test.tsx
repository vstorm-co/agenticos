import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { MobileTabBar } from "./mobile-tab-bar";

const currentPath = vi.fn<() => string>(() => "/chat");

vi.mock("next/navigation", () => ({
  usePathname: () => currentPath(),
  useRouter: () => ({ push: vi.fn() }),
}));
vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks", () => ({ useAuth: () => ({ user: { role: "member" } }) }));

/**
 * The tab bar had the same bug the desktop sidebar had, in a worse form: it
 * stripped any two leading letters as if they were a locale, so `/chat` became
 * "at" and `/kb` became "". Those two tabs could never light up on a phone -
 * and nobody reported it, because a tab bar that highlights nothing looks
 * merely plain rather than broken.
 */
describe("MobileTabBar", () => {
  it("marks the tab for the knowledge section", () => {
    currentPath.mockReturnValue("/rag");

    render(<MobileTabBar />);

    expect(screen.getByRole("link", { name: /kb/i })).toHaveAttribute("aria-current", "page");
  });

  it("marks a four-letter section, which the old regex also mangled", () => {
    currentPath.mockReturnValue("/chat");

    render(<MobileTabBar />);

    expect(screen.getByRole("link", { name: /chat/i })).toHaveAttribute("aria-current", "page");
  });

  it("keeps the section marked on a detail page", () => {
    currentPath.mockReturnValue("/rag/5eacffcc-873e-42fe-a73a-32cd19322d00");

    render(<MobileTabBar />);

    expect(screen.getByRole("link", { name: /kb/i })).toHaveAttribute("aria-current", "page");
  });

  it("strips a real locale and nothing else", () => {
    currentPath.mockReturnValue("/pl/rag/abc");

    render(<MobileTabBar />);

    expect(screen.getByRole("link", { name: /kb/i })).toHaveAttribute("aria-current", "page");
  });
});

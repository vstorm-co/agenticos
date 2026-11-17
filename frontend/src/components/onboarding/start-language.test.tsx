import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { StartLanguage } from "./start-language";
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/onboarding",
}));
vi.mock("@/hooks/use-choose-locale", () => ({ useChooseLocale: () => vi.fn() }));
it("offers no language choice on a deployment that serves only English", () => {
  const { container } = render(<StartLanguage />);
  expect(screen.queryByRole("button", { name: "Language" })).not.toBeInTheDocument();
  expect(container).toBeEmptyDOMElement();
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { StartLanguage } from "./start-language";
const choose = vi.hoisted(() => vi.fn());
vi.mock("@/lib/locale-navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/onboarding",
}));
vi.mock("@/hooks/use-choose-locale", () => ({ useChooseLocale: () => choose }));
it("uses the shared flag menu and persists the chosen account language", async () => {
  render(<StartLanguage />);
  await userEvent.click(screen.getByRole("button", { name: "Language" }));
  expect(screen.getByText("🇵🇱")).toBeInTheDocument();
  await userEvent.click(screen.getByRole("menuitem", { name: /Polski/ }));
  expect(choose).toHaveBeenCalledWith("pl");
});

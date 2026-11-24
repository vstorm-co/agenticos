import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";

import { useAppUpdate } from "@/hooks/use-app-update";
import { AppUpdateBanner } from "./app-update-banner";

vi.mock("@/hooks/use-app-update", () => ({ useAppUpdate: vi.fn() }));
vi.mock("@/components/branding/branding-provider", () => ({
  useBranding: () => ({ appName: "T3OS" }),
}));

afterEach(() => vi.unstubAllGlobals());

it("stays absent until the deployment changes", () => {
  vi.mocked(useAppUpdate).mockReturnValue(false);
  render(<AppUpdateBanner />);
  expect(screen.queryByRole("status")).not.toBeInTheDocument();
  expect(screen.queryByRole("button", { name: "Reload" })).not.toBeInTheDocument();
});

it("announces the update and reloads only when its button is clicked", () => {
  vi.mocked(useAppUpdate).mockReturnValue(true);
  render(<AppUpdateBanner />);
  const reload = vi.fn();
  vi.stubGlobal("window", { location: { reload } });

  expect(screen.getByRole("status")).toHaveTextContent("T3OS has been updated");
  expect(screen.getByText("Reload to get the newest version.")).toBeInTheDocument();
  expect(reload).not.toHaveBeenCalled();
  fireEvent.click(screen.getByRole("button", { name: "Reload" }));
  expect(reload).toHaveBeenCalledTimes(1);
});

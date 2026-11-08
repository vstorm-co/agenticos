import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { StartOffer } from "./start-offer";
const env = vi.hoisted(() => ({
  path: "/chat",
  params: new URLSearchParams(),
  dismissed: false,
  hasResult: false,
  save: vi.fn(),
}));
vi.mock("next/navigation", () => ({
  usePathname: () => env.path,
  useSearchParams: () => env.params,
}));
vi.mock("@/hooks/use-start", () => ({
  useStart: () => ({
    data: {
      organization_name: "Demo",
      dismissed: env.dismissed,
      has_result: env.hasResult,
      has_activity: false,
      agents: [],
    },
    save: { mutate: env.save },
  }),
}));
beforeEach(() => {
  env.path = "/chat";
  env.params = new URLSearchParams();
  env.dismissed = false;
  env.hasResult = false;
  env.save.mockClear();
});
it("offers a shared start and saves only the decision to dismiss it", async () => {
  render(<StartOffer />);
  expect(screen.getByRole("link", { name: "Get started" })).toHaveAttribute("href", "/onboarding");
  await userEvent.click(screen.getByRole("button", { name: "Later" }));
  expect(env.save).toHaveBeenCalledWith({ dismissed: true });
});
it.each(["existing chat", "example", "dismissed", "completed", "dashboard"])(
  "does not interrupt %s",
  (reason) => {
    if (reason === "existing chat") env.params.set("id", "conversation");
    if (reason === "example") env.params.set("example", "meeting");
    if (reason === "dismissed") env.dismissed = true;
    if (reason === "completed") env.hasResult = true;
    if (reason === "dashboard") env.path = "/dashboard";
    render(<StartOffer />);
    expect(screen.queryByRole("link")).not.toBeInTheDocument();
  },
);

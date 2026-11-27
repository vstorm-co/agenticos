import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { it, expect, vi } from "vitest";
import { StartActions, StartNavigation, StartNavigationScope } from "./start-navigation";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));

it("keeps one footer and submits only the visible step's form", async () => {
  const submit = vi.fn((event: React.FormEvent) => event.preventDefault());
  const back = vi.fn();
  const wizard = (second: boolean) => (
    <StartNavigation onBack={back}>
      <form id="first" hidden={second} onSubmit={submit}>
        <StartNavigationScope active={!second}>
          <StartActions>
            <button type="submit" form="first">
              Continue
            </button>
          </StartActions>
        </StartNavigationScope>
      </form>
      <form id="second" hidden={!second} onSubmit={submit}>
        <StartNavigationScope active={second}>
          <StartActions>
            <button type="submit" form="second">
              Continue
            </button>
          </StartActions>
        </StartNavigationScope>
      </form>
    </StartNavigation>
  );
  const { rerender } = render(wizard(false));
  const footer = screen.getByRole("contentinfo");
  const user = userEvent.setup();
  expect(within(footer).getByRole("button", { name: "Continue" })).toHaveAttribute("form", "first");
  await user.click(within(footer).getByRole("button", { name: "Continue" }));
  expect(submit).toHaveBeenCalledTimes(1);
  rerender(wizard(true));
  expect(screen.getByRole("contentinfo")).toBe(footer);
  expect(within(footer).getByRole("button", { name: "Continue" })).toHaveAttribute(
    "form",
    "second",
  );
  await user.click(within(footer).getByRole("button", { name: "back" }));
  expect(back).toHaveBeenCalledOnce();
});

it("blocks portaled footer actions while shared progress is saving", async () => {
  const next = vi.fn();
  const back = vi.fn();
  const wizard = (pending: boolean) => (
    <StartNavigation pending={pending} onBack={back}>
      <StartActions>
        <button onClick={next}>Continue</button>
      </StartActions>
    </StartNavigation>
  );
  const { rerender } = render(wizard(false));
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(next).toHaveBeenCalledTimes(1);
  rerender(wizard(true));
  expect(screen.getByRole("button", { name: "Continue" })).toBeDisabled();
  expect(screen.getByRole("button", { name: "back" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Continue" }));
  await user.click(screen.getByRole("button", { name: "back" }));
  expect(next).toHaveBeenCalledTimes(1);
  expect(back).not.toHaveBeenCalled();
  rerender(wizard(false));
  await user.click(screen.getByRole("button", { name: "Continue" }));
  expect(next).toHaveBeenCalledTimes(2);
});

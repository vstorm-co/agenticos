import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { RestartTourButton } from "./restart-tour-button";
import messages from "@/../messages/en.json";
import { useOnboardingStore } from "@/stores/onboarding-store";

const nav = vi.hoisted(() => ({ pathname: "/dashboard" }));
vi.mock("next/navigation", () => ({ usePathname: () => nav.pathname }));

function renderButton() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RestartTourButton />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
  nav.pathname = "/dashboard";
  useOnboardingStore.setState({ isOpen: false, mode: "tour", index: 0, flowId: null });
});

describe("RestartTourButton", () => {
  it("opens the current page's tips", async () => {
    renderButton();
    await userEvent.click(screen.getByLabelText("Show tips for this page"));
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, mode: "page" });
  });

  it("keeps hinting after it has been used", async () => {
    // The "?" sits in twenty page headers and is easy to miss. It hinted only until
    // the first press, which made the affordance invisible to anyone who had ever
    // taken it once — so the hint stays, on every visit.
    const { unmount } = renderButton();
    const button = screen.getByLabelText("Show tips for this page");
    expect(button.className).toContain("onboarding-help-hint");

    await userEvent.click(button);
    expect(button.className).toContain("onboarding-help-hint");

    unmount();
    renderButton();
    expect(screen.getByLabelText("Show tips for this page").className).toContain(
      "onboarding-help-hint",
    );
  });

  it("offers nothing on a page the registry has no stop for", () => {
    // `/admin/*` and the component playground render `PageHeader`, so they got the
    // "?" — and `TOUR_STEPS` names neither, so pressing it opened a walk with no
    // steps that closed itself again. A control that does nothing is worse than no
    // control, and the localized name is what a test can see it by.
    nav.pathname = "/admin/users";
    renderButton();
    expect(screen.queryByLabelText("Show tips for this page")).toBeNull();
  });

  it("still offers itself on a locale-prefixed covered page", () => {
    // The registry is keyed on unprefixed paths, so the locale has to come off
    // before the lookup or every page under `/pl` would lose its help.
    nav.pathname = "/pl/agents";
    renderButton();
    expect(screen.getByLabelText("Show tips for this page")).toBeVisible();
  });
});

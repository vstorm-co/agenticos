import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { beforeEach, describe, expect, it } from "vitest";

import { RestartTourButton } from "./restart-tour-button";
import messages from "@/../messages/en.json";
import { useOnboardingStore } from "@/stores/onboarding-store";

function renderButton() {
  return render(
    <NextIntlClientProvider locale="en" messages={messages}>
      <RestartTourButton />
    </NextIntlClientProvider>,
  );
}

beforeEach(() => {
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
});

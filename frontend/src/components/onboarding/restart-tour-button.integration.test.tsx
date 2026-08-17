import { render, screen, waitFor } from "@testing-library/react";
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
  localStorage.clear();
  useOnboardingStore.setState({ isOpen: false, mode: "tour", index: 0, flowId: null });
});

describe("RestartTourButton", () => {
  it("opens the current page's tips", async () => {
    renderButton();
    await userEvent.click(screen.getByLabelText("Show tips for this page"));
    expect(useOnboardingStore.getState()).toMatchObject({ isOpen: true, mode: "page" });
  });

  it("breathes until it has been used, in this browser", async () => {
    // The "?" sits in twenty page headers and is easy to miss, so it hints — once.
    // A hint that never stops is chrome that moves for the rest of the product's
    // life, which is why the first press ends it for good.
    const { unmount } = renderButton();
    const button = screen.getByLabelText("Show tips for this page");
    await waitFor(() => expect(button.className).toContain("onboarding-help-hint"));

    await userEvent.click(button);
    expect(button.className).not.toContain("onboarding-help-hint");

    unmount();
    renderButton();
    const again = screen.getByLabelText("Show tips for this page");
    await waitFor(() => expect(again.className).not.toContain("onboarding-help-hint"));
  });
});

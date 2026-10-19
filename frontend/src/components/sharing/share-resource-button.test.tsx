import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { NextIntlClientProvider } from "next-intl";
import { describe, expect, it, vi } from "vitest";

import messages from "../../../messages/en.json";
import { ShareResourceButton } from "./share-resource-button";

vi.mock("./sharing-panel", () => ({
  SharingPanel: (props: { resourceType: string; resourceId: string; canManage: boolean }) => (
    <p>
      panel for {props.resourceType} {props.resourceId} {props.canManage ? "managed" : "read-only"}
    </p>
  ),
}));

/** Share, on a resource that already exists - the panel the agent page opens. */
describe("ShareResourceButton", () => {
  it("opens the sharing panel for the resource it names", async () => {
    render(
      <NextIntlClientProvider locale="en" messages={messages}>
        <ShareResourceButton resourceType="skill" resourceId="s1" name="checklist" canManage />
      </NextIntlClientProvider>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Share" }));

    expect(screen.getByRole("dialog", { name: "Share checklist" })).toBeVisible();
    expect(screen.getByText("panel for skill s1 managed")).toBeVisible();
  });
});

import { fireEvent, render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ImessageSetup } from "./imessage-setup";

const registration = vi.hoisted(() => ({ mutate: vi.fn(), isPending: false }));
vi.mock("@/hooks/use-channel-bots", () => ({ useRegisterChannelWebhook: () => registration }));

beforeEach(() => {
  vi.clearAllMocks();
  registration.isPending = false;
});

describe("iMessage callback registration", () => {
  it("registers the saved bot only", () => {
    render(<ImessageSetup botId="saved-bot" unsaved={false} />);
    fireEvent.click(screen.getByRole("button", { name: "Register iMessage webhook" }));
    expect(registration.mutate).toHaveBeenCalledWith("saved-bot");
  });

  it("requires saving credentials before registering", () => {
    render(<ImessageSetup botId="saved-bot" unsaved />);
    expect(screen.getByRole("button", { name: "Register iMessage webhook" })).toBeDisabled();
  });

  it("prevents a second registration while one is in flight", () => {
    registration.isPending = true;
    render(<ImessageSetup botId="saved-bot" unsaved={false} />);
    expect(screen.getByRole("button", { name: "Register iMessage webhook" })).toBeDisabled();
  });
});

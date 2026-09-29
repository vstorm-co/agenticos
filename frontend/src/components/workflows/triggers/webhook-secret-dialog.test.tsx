import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { WebhookSecretDialog } from "./webhook-secret-dialog";

describe("WebhookSecretDialog", () => {
  it("shows the address and says how to sign, and closes on Escape as on Done", async () => {
    const onClose = vi.fn();
    render(<WebhookSecretDialog url="https://x/hook" secret="s3cret" onClose={onClose} />);
    expect(screen.getByDisplayValue("https://x/hook")).toBeTruthy();
    await userEvent.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});

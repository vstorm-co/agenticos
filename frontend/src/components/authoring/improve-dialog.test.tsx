import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import type { AuthoringEstimate } from "@/types/authoring";
import { ImproveDialog } from "./improve-dialog";

function quote(overrides: Partial<AuthoringEstimate> = {}): AuthoringEstimate {
  return {
    runs: 22,
    rated_down: 6,
    calls: 1,
    estimate_usd: "0.04",
    affordable: true,
    reason: null,
    ...overrides,
  };
}

describe("ImproveDialog", () => {
  it("shows what it would read and cost, and starts on the second click", async () => {
    const estimate = vi.fn().mockResolvedValue(quote());
    const start = vi.fn().mockResolvedValue({});
    const onOpenChange = vi.fn();
    render(
      <ImproveDialog
        kind="improve"
        estimate={estimate}
        start={start}
        onOpenChange={onOpenChange}
      />,
    );
    expect(estimate).toHaveBeenCalledWith({ kind: "improve", window_days: 30 });
    expect(await screen.findByText(/It will read 22 runs, 6 rated down/)).toBeInTheDocument();
    expect(start).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(start).toHaveBeenCalledWith({ kind: "improve", window_days: 30 });
    await waitFor(() => expect(onOpenChange).toHaveBeenCalledWith(false));
  });

  it("explains why it cannot start", async () => {
    render(
      <ImproveDialog
        kind="verify"
        estimate={vi.fn().mockResolvedValue(quote({ reason: "no_draft_change" }))}
        start={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        "The draft is the same as the published version, so there is nothing to verify.",
      ),
    ).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Start" })).toBeDisabled();
  });

  it("refuses past the budget and shows a refusal", async () => {
    const { unmount } = render(
      <ImproveDialog
        kind="improve"
        estimate={vi.fn().mockResolvedValue(quote({ affordable: false }))}
        start={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    expect(
      await screen.findByText(
        "That is more than the assistant's monthly budget or the organization's has left.",
      ),
    ).toBeInTheDocument();
    unmount();
    render(
      <ImproveDialog
        kind="improve"
        estimate={vi.fn().mockRejectedValue(new Error("No improver"))}
        start={vi.fn()}
        onOpenChange={vi.fn()}
      />,
    );
    expect(await screen.findByRole("alert")).toHaveTextContent("No improver");
  });

  it("keeps the dialog open when starting is refused, and cancels", async () => {
    const onOpenChange = vi.fn();
    render(
      <ImproveDialog
        kind="improve"
        estimate={vi.fn().mockResolvedValue(quote())}
        start={vi.fn().mockRejectedValue(new Error("Out of budget"))}
        onOpenChange={onOpenChange}
      />,
    );
    await screen.findByText(/It will read/);
    await userEvent.click(screen.getByRole("button", { name: "Start" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("Out of budget");
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
  });

  it("drops an estimate that arrives after the dialog closed", async () => {
    let resolve: (value: AuthoringEstimate) => void = () => undefined;
    const estimate = vi.fn(
      () =>
        new Promise<AuthoringEstimate>((done) => {
          resolve = done;
        }),
    );
    const { unmount } = render(
      <ImproveDialog kind="improve" estimate={estimate} start={vi.fn()} onOpenChange={vi.fn()} />,
    );
    unmount();
    resolve(quote());
    await Promise.resolve();
    expect(screen.queryByText(/It will read/)).toBeNull();
  });
});

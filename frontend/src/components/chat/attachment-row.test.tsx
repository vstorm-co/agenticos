import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { AttachmentRow } from "./attachment-row";

/** A row whose content is wider than the box, or not. */
function sized({ scrollWidth, clientWidth }: { scrollWidth: number; clientWidth: number }) {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockReturnValue(scrollWidth);
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockReturnValue(clientWidth);
}

beforeEach(() => vi.restoreAllMocks());

describe("the composer's attachment row", () => {
  it("scrolls rather than wrapping, whatever the count", () => {
    // #927: a wrapping grid made twenty files seven rows and about 850px of
    // composer, with the message box below the fold.
    const { container } = render(
      <AttachmentRow count={20}>
        <span>report.csv</span>
      </AttachmentRow>,
    );

    const scroller = container.querySelector(".overflow-x-auto")!;

    expect(scroller.className).not.toMatch(/flex-wrap/);
  });

  it("says how many are attached, so the row need not be scrolled to count them", () => {
    render(
      <AttachmentRow count={20}>
        <span>report.csv</span>
      </AttachmentRow>,
    );

    expect(screen.getByText("20 files")).toBeVisible();
  });

  it("counts one file as one file", () => {
    render(
      <AttachmentRow count={1}>
        <span>report.csv</span>
      </AttachmentRow>,
    );

    expect(screen.getByText("1 file")).toBeVisible();
  });

  it("offers no arrows when everything already fits", () => {
    // Measured rather than guessed from the count: a card is a fixed width and
    // the composer is not, so "more than three" is right at one window size and
    // wrong at the next.
    sized({ scrollWidth: 400, clientWidth: 400 });

    render(
      <AttachmentRow count={2}>
        <span>report.csv</span>
      </AttachmentRow>,
    );

    expect(screen.queryByRole("button", { name: "Later attachments" })).toBeNull();
  });

  it("offers arrows once there is more than fits, and pages by a card", async () => {
    sized({ scrollWidth: 2000, clientWidth: 400 });
    // jsdom implements no scrolling at all, so the method has to be planted
    // rather than spied on.
    const scrollBy = vi.fn();
    Object.defineProperty(HTMLElement.prototype, "scrollBy", {
      configurable: true,
      writable: true,
      value: scrollBy,
    });

    render(
      <AttachmentRow count={12}>
        <span>report.csv</span>
      </AttachmentRow>,
    );

    await userEvent.click(screen.getByRole("button", { name: "Later attachments" }));

    expect(scrollBy).toHaveBeenCalledWith({ left: 184, behavior: "smooth" });
  });
});

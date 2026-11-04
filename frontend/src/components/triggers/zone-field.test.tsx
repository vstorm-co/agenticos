import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { ZoneField, isTimeZone } from "./zone-field";

describe("schedule time zone picker", () => {
  it("filters by city and commits a known IANA identifier from the keyboard", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ZoneField value="UTC" onChange={onChange} />);
    await user.click(screen.getByRole("combobox", { name: "Time zone" }));
    await user.type(
      screen.getByRole("combobox", { name: "Search city or time zone…" }),
      "New York",
    );
    expect(screen.getByRole("option", { name: "America/New York" })).toBeInTheDocument();
    await user.keyboard("{Enter}");
    expect(onChange).toHaveBeenCalledWith("America/New_York");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
  });

  it("offers UTC and cancels an unmatched search without changing the schedule", async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(<ZoneField value="Europe/Warsaw" onChange={onChange} />);
    const trigger = screen.getByRole("combobox", { name: "Time zone" });
    await user.click(trigger);
    expect(screen.getByRole("option", { name: "UTC" })).toBeInTheDocument();
    await user.type(screen.getByRole("combobox", { name: "Search city or time zone…" }), "Mars");
    expect(screen.getByText("No time zones found. Try another city.")).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(trigger).toHaveTextContent("Europe/Warsaw");
    expect(onChange).not.toHaveBeenCalled();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("allows wheel scrolling in the portalled list while a parent dialog locks the page", async () => {
    const user = userEvent.setup();
    render(
      <Dialog open>
        <DialogContent aria-describedby={undefined}>
          <DialogTitle>Schedule</DialogTitle>
          <ZoneField value="UTC" onChange={vi.fn()} />
        </DialogContent>
      </Dialog>,
    );
    await user.click(screen.getByRole("combobox", { name: "Time zone" }));
    const list = screen.getByRole("listbox");
    // JSDOM does not lay out the list or load its Tailwind overflow rule.
    list.style.overflowY = "auto";
    Object.defineProperties(list, {
      scrollHeight: { value: 1200 },
      clientHeight: { value: 240 },
      scrollTop: { value: 100, writable: true },
    });
    expect(fireEvent.wheel(list, { deltaX: 0, deltaY: 100, bubbles: true, cancelable: true })).toBe(
      true,
    );
  });

  it("marks invalid stored values instead of pretending they are valid", () => {
    render(<ZoneField value="Mars/Olympus" onChange={vi.fn()} />);
    expect(screen.getByRole("combobox", { name: "Time zone" })).toHaveAttribute(
      "aria-invalid",
      "true",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("Choose a time zone");
    expect(isTimeZone("UTC")).toBe(true);
    expect(isTimeZone("Europe/Warsaw")).toBe(true);
    expect(isTimeZone("Mars/Olympus")).toBe(false);
  });
});

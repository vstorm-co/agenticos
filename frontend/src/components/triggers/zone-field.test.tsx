import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
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

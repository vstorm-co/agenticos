import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { DataView } from "./data-view";

describe("DataView", () => {
  it("shows the data as a table, as JSON and as its fields", async () => {
    render(<DataView value={{ values: { name: "Ada" } }} />);

    expect(screen.getByRole("columnheader", { name: "values.name" })).toBeTruthy();
    expect(screen.getByRole("cell", { name: "Ada" })).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "JSON" }));
    expect(screen.getByRole("button", { name: "JSON" })).toHaveAttribute("aria-pressed", "true");
    expect(screen.getByText("name:")).toBeTruthy();

    await userEvent.click(screen.getByRole("button", { name: "Fields" }));
    expect(screen.getByText("values.name")).toBeTruthy();
    expect(screen.getByText("string")).toBeTruthy();
  });

  it("says how many rows it leaves to the JSON", () => {
    const records = Array.from({ length: 53 }, (_, id) => ({ id }));
    render(<DataView value={{ records }} />);
    expect(screen.getAllByRole("row")).toHaveLength(51);
    expect(screen.getByText("3 more rows in JSON")).toBeTruthy();
  });

  it("says when there is nothing in it", async () => {
    render(<DataView value={{}} />);
    expect(screen.getByText("Nothing in it")).toBeTruthy();
    await userEvent.click(screen.getByRole("button", { name: "Fields" }));
    expect(screen.getByText("Nothing in it")).toBeTruthy();
  });
});

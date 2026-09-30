import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

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

describe("dragging a field out of the data", () => {
  function dragFrom(element: HTMLElement) {
    const setData = vi.fn();
    fireEvent.dragStart(element, { dataTransfer: { setData, effectAllowed: "none" } });
    return setData.mock.calls.map(([, value]) => JSON.parse(value as string));
  }

  it("carries a column or a field of the step it came from, with its type", async () => {
    render(
      <DataView
        value={{ values: { name: "Ada" }, list: [{ a: 1 }], more: [{ b: 2 }] }}
        source="s"
      />,
    );
    const header = screen.getByRole("columnheader", { name: "values.name" });
    expect(header).toHaveAttribute("draggable", "true");
    expect(dragFrom(header)).toEqual([{ nodeId: "s", path: ["values", "name"], type: "string" }]);

    await userEvent.click(screen.getByRole("button", { name: "Fields" }));
    expect(dragFrom(screen.getByText("values").closest("li") as HTMLElement)).toEqual([
      { nodeId: "s", path: ["values"], type: "object" },
    ]);
    expect(screen.getByText("list[].a").closest("li")).toHaveAttribute("draggable", "false");
  });

  it("carries nothing when it is not a step's input", () => {
    render(<DataView value={{ name: "Ada" }} />);
    expect(screen.getByRole("columnheader", { name: "name" })).toHaveAttribute(
      "draggable",
      "false",
    );
  });
});

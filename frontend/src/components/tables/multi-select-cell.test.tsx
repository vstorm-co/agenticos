import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { MultiSelectCell } from "./multi-select-cell";
import type { OptionDef } from "@/types/tables";

const options: OptionDef[] = [
  { id: "o1", label: "Rush", archived: false },
  { id: "o2", label: "Gift", archived: false },
  { id: "o3", label: "Retired", archived: true },
];

describe("MultiSelectCell", () => {
  it("shows a placeholder when nothing is selected", () => {
    render(<MultiSelectCell options={options} value={[]} onChange={vi.fn()} />);
    expect(screen.getByText(/none selected/i)).toBeInTheDocument();
  });

  it("shows a chip per selected option", () => {
    render(<MultiSelectCell options={options} value={["o1"]} onChange={vi.fn()} />);
    expect(screen.getByText("Rush")).toBeInTheDocument();
    expect(screen.queryByText("Gift")).not.toBeInTheDocument();
  });

  it("only offers live options in the popover, never an archived one", async () => {
    const user = userEvent.setup();
    render(<MultiSelectCell id="tags" options={options} value={[]} onChange={vi.fn()} />);

    await user.click(screen.getByRole("button"));

    expect(screen.getByText("Gift")).toBeInTheDocument();
    expect(screen.queryByText("Retired")).not.toBeInTheDocument();
  });

  it("adds an option when its checkbox is checked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(<MultiSelectCell id="tags" options={options} value={["o1"]} onChange={onChange} />);

    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("checkbox", { name: "Gift" }));

    expect(onChange).toHaveBeenCalledWith(["o1", "o2"]);
  });

  it("removes an option when its checkbox is unchecked", async () => {
    const onChange = vi.fn();
    const user = userEvent.setup();
    render(
      <MultiSelectCell id="tags" options={options} value={["o1", "o2"]} onChange={onChange} />,
    );

    await user.click(screen.getByRole("button"));
    await user.click(screen.getByRole("checkbox", { name: "Rush" }));

    expect(onChange).toHaveBeenCalledWith(["o2"]);
  });

  it("shows a message when there are no live options at all", async () => {
    const user = userEvent.setup();
    render(
      <MultiSelectCell
        id="tags"
        options={[{ id: "o3", label: "Retired", archived: true }]}
        value={[]}
        onChange={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button"));

    expect(screen.getByText(/no options/i)).toBeInTheDocument();
  });

  it("is disabled when asked", () => {
    render(<MultiSelectCell options={options} value={[]} onChange={vi.fn()} disabled />);
    expect(screen.getByRole("button")).toBeDisabled();
  });
});

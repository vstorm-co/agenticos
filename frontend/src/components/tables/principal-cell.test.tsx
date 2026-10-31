import { useState } from "react";
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { PrincipalCell } from "./principal-cell";
import type { CellValue } from "@/types/tables";

vi.mock("@/hooks/use-table-principals", () => ({
  useTablePrincipals: (kind: string) => ({
    items:
      kind === "user"
        ? [
            { kind: "user", id: "a", name: "Anna Nowak" },
            { kind: "user", id: "b", name: "Jan Kowalski" },
          ]
        : [{ kind: "agent", id: "writer", name: "Research writer", slug: "writer" }],
    isLoading: false,
    error: null,
  }),
}));

function Cell({
  kind = "user",
  multiple = false,
  change = vi.fn(),
}: {
  kind?: "user" | "agent";
  multiple?: boolean;
  change?: (value: CellValue) => void;
}) {
  const [value, setValue] = useState<CellValue>(null);
  return (
    <PrincipalCell
      id="owner"
      label="Owner"
      value={value}
      kind={kind}
      multiple={multiple}
      onChange={(next) => {
        setValue(next);
        change(next);
      }}
    />
  );
}

describe("organization identity fields", () => {
  it("suggests a person by name and stores one stable id", async () => {
    const change = vi.fn();
    render(<Cell change={change} />);
    await userEvent.click(screen.getByRole("combobox", { name: "Owner" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Search by name…" }), "anna");
    expect(screen.queryByRole("option", { name: "Jan Kowalski" })).not.toBeInTheDocument();
    await userEvent.keyboard("{ArrowDown}{Enter}");
    expect(change).toHaveBeenCalledWith("a");
    expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
    expect(screen.getByRole("combobox")).toHaveTextContent("Anna Nowak");
  });

  it("keeps multiple people selected and allows removing a choice", async () => {
    const change = vi.fn();
    render(<Cell multiple change={change} />);
    await userEvent.click(screen.getByRole("combobox"));
    const choices = within(screen.getByRole("listbox"));
    await userEvent.click(choices.getByRole("option", { name: "Anna Nowak" }));
    await userEvent.click(choices.getByRole("option", { name: "Jan Kowalski" }));
    expect(change).toHaveBeenLastCalledWith(["a", "b"]);
    await userEvent.click(choices.getByRole("option", { name: "Anna Nowak" }));
    expect(change).toHaveBeenLastCalledWith(["b"]);
    await userEvent.click(screen.getByRole("button", { name: "Clear selection" }));
    expect(change).toHaveBeenLastCalledWith(null);
  });

  it("chooses AI agents through the same field", async () => {
    const change = vi.fn();
    render(<Cell kind="agent" multiple change={change} />);
    await userEvent.click(screen.getByRole("combobox"));
    await userEvent.click(screen.getByRole("option", { name: "Research writer" }));
    expect(change).toHaveBeenCalledWith(["writer"]);
  });
});

it("caps multi-principal fields at 100 without preventing removal", async () => {
  const onChange = vi.fn();
  const value = ["a", ...Array.from({ length: 99 }, (_, i) => `member-${i}`)];
  render(
    <PrincipalCell
      id="owners"
      label="Owners"
      value={value}
      kind="user"
      multiple
      onChange={onChange}
    />,
  );
  await userEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("option", { name: "Jan Kowalski" })).toBeDisabled();
  await userEvent.click(screen.getByRole("option", { name: "Jan Kowalski" }));
  expect(onChange).not.toHaveBeenCalled();
  await userEvent.click(screen.getByRole("option", { name: "Anna Nowak" }));
  expect(onChange).toHaveBeenCalledWith(value.slice(1));
});

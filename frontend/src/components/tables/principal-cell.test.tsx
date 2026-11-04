import { useState } from "react";
import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { PrincipalCell, PrincipalBadges } from "./principal-cell";
import type { CellValue } from "@/types/tables";

const directoryState = vi.hoisted(() => ({
  loading: false,
  error: null as Error | null,
  invalid: false,
}));
beforeEach(() => {
  directoryState.loading = false;
  directoryState.error = null;
  directoryState.invalid = false;
});
vi.mock("@/hooks/use-table-principals", () => ({
  useTablePrincipals: (kind: string) => ({
    items:
      kind === "user"
        ? [
            { kind: "user", id: "a", name: "Anna Nowak" },
            { kind: "user", id: "b", name: "Jan Kowalski" },
            ...(directoryState.invalid ? [{ kind: "user", id: "", name: "Missing identity" }] : []),
          ]
        : [
            { kind: "agent", id: "writer", name: "Research writer", slug: "writer" },
            { kind: "agent", id: "archived", name: "Former writer", archived: true },
          ],
    isLoading: directoryState.loading,
    error: directoryState.error,
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

it("renders stored identities without an editor, including an unavailable reference", () => {
  render(<PrincipalBadges value={["a", "unknown"]} kind="user" />);
  expect(screen.getByText("Anna Nowak")).toBeVisible();
  expect(screen.getByText("Unavailable")).toBeVisible();
});
it("moves between directory choices with the keyboard and closes a selection", async () => {
  render(<Cell />);
  await userEvent.click(screen.getByRole("combobox"));
  const search = screen.getByRole("textbox", { name: "Search by name…" });
  await userEvent.click(search);
  await userEvent.keyboard("{ArrowDown}{ArrowDown}");
  expect(screen.getByRole("option", { name: "Jan Kowalski" })).toHaveFocus();
  await userEvent.keyboard("{ArrowUp}");
  expect(screen.getByRole("option", { name: "Anna Nowak" })).toHaveFocus();
  fireEvent.keyDown(screen.getByRole("listbox"), { key: "ArrowDown" });
  await userEvent.keyboard("{Enter}");
  expect(screen.queryByRole("listbox")).not.toBeInTheDocument();
});

it("clears directory search on close and distinguishes loading and failure", async () => {
  const { rerender } = render(<Cell />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.type(screen.getByRole("textbox", { name: "Search by name…" }), "missing");
  expect(screen.getByText("No matches")).toBeVisible();
  await userEvent.keyboard("{Escape}");
  await userEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("option", { name: "Jan Kowalski" })).toBeVisible();
  directoryState.loading = true;
  rerender(<Cell />);
  expect(screen.getByRole("status")).toHaveTextContent("Loading");
  directoryState.loading = false;
  directoryState.error = new Error("Directory down");
  rerender(<Cell />);
  expect(screen.getByRole("alert")).toHaveTextContent("Could not load the organization directory");
});

it("resolves an existing archived selection without offering it for new values", async () => {
  const props = {
    id: "agent",
    label: "Agent",
    kind: "agent" as const,
    multiple: false,
    onChange: vi.fn(),
  };
  const { rerender } = render(<PrincipalCell {...props} value="archived" />);
  expect(screen.getByRole("combobox")).toHaveTextContent("Former writer");
  await userEvent.click(screen.getByRole("combobox"));
  expect(screen.getByRole("option", { name: "Former writer" })).toBeVisible();
  rerender(<PrincipalCell {...props} value={null} />);
  expect(screen.queryByRole("option", { name: "Former writer" })).not.toBeInTheDocument();
});

it("refuses a directory entry without a stable identity", async () => {
  directoryState.invalid = true;
  const change = vi.fn();
  render(<Cell change={change} />);
  await userEvent.click(screen.getByRole("combobox"));
  await userEvent.click(screen.getByRole("option", { name: "Missing identity" }));
  expect(change).not.toHaveBeenCalled();
  expect(screen.getByRole("listbox")).toBeVisible();
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import type { ColumnDef } from "@/types/tables";

import { NewRecordRow } from "./new-record-row";

const mutateAsync = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn() } }));
vi.mock("@/hooks/use-record-mutation", () => ({
  useRecordMutation: () => ({ create: { mutateAsync, isPending: false } }),
}));

function column(id: string, over: Partial<ColumnDef> = {}): ColumnDef {
  return {
    id,
    label: id,
    type: "text",
    nullable: true,
    default: null,
    options: [],
    archived: false,
    ...over,
  };
}

beforeEach(() => {
  vi.clearAllMocks();
  mutateAsync.mockResolvedValue({ id: "r1" });
});

describe("NewRecordRow", () => {
  it("creates a record from what is typed in the first text column, and clears for the next", async () => {
    const onNeedsMore = vi.fn();
    render(
      <NewRecordRow
        tableId="t"
        columns={[column("score", { type: "number" }), column("name")]}
        onNeedsMore={onNeedsMore}
      />,
    );
    const line = screen.getByRole("textbox", { name: "New record: name" });

    await userEvent.type(line, "  Ada  {Enter}");

    expect(mutateAsync).toHaveBeenCalledWith({ values: { name: "Ada" } });
    expect(line).toHaveValue("");
    expect(toast.success).toHaveBeenCalledWith("Added Ada");
    expect(onNeedsMore).not.toHaveBeenCalled();
  });

  it("opens the full form with the value when another column is required", async () => {
    const onNeedsMore = vi.fn();
    render(
      <NewRecordRow
        tableId="t"
        columns={[
          column("name"),
          column("email", { nullable: false }),
          column("old", { nullable: false, archived: true }),
        ]}
        onNeedsMore={onNeedsMore}
      />,
    );
    await userEvent.type(screen.getByRole("textbox", { name: "New record: name" }), "Ada{Enter}");
    expect(onNeedsMore).toHaveBeenCalledWith({ name: "Ada" });
    expect(mutateAsync).not.toHaveBeenCalled();
  });

  it("ignores a blank line, clears on Escape, and keeps the text when the write fails", async () => {
    mutateAsync.mockRejectedValue(new Error("no"));
    render(<NewRecordRow tableId="t" columns={[column("name")]} onNeedsMore={vi.fn()} />);
    const line = screen.getByRole("textbox", { name: "New record: name" });

    await userEvent.type(line, "   {Enter}");
    expect(mutateAsync).not.toHaveBeenCalled();
    await userEvent.type(line, "draft{Escape}");
    expect(line).toHaveValue("");
    await userEvent.type(line, "Grace{Enter}");
    expect(line).toHaveValue("Grace");
  });

  it("offers the form itself when the table has no text column to type into", async () => {
    const onNeedsMore = vi.fn();
    render(
      <NewRecordRow
        tableId="t"
        columns={[column("n", { type: "number" })]}
        onNeedsMore={onNeedsMore}
      />,
    );
    await userEvent.click(screen.getByRole("button", { name: "New record" }));
    expect(onNeedsMore).toHaveBeenCalledWith({});
  });
});

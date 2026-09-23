import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { CreateTableDialog } from "./create-table-dialog";
import { ApiError } from "@/lib/api-client";

describe("CreateTableDialog", () => {
  it("submit is disabled until a name is typed", () => {
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );
    expect(screen.getByRole("button", { name: /create table/i })).toBeDisabled();
  });

  it("submits the trimmed name, description and visibility with no columns", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );

    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "  Orders  " } });
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "  " } });
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith({
      name: "Orders",
      description: null,
      visibility: "private",
      columns: [],
    });
  });

  it("changing visibility is reflected in the submission", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Orders" } });

    await user.click(screen.getByRole("combobox", { name: "Visibility" }));
    await user.click(screen.getByRole("option", { name: "Organization" }));
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ visibility: "org" }));
  });

  it("adds a column, edits its label and type, and includes it in the submission", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Orders" } });

    await user.click(screen.getByRole("button", { name: /add column/i }));
    fireEvent.change(screen.getByLabelText("Column label"), { target: { value: "Total" } });
    await user.click(screen.getByRole("combobox", { name: "Column type" }));
    await user.click(screen.getByRole("option", { name: "Number" }));
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({ columns: [{ label: "Total", type: "number" }] }),
    );
  });

  it("drops a column whose label was left blank", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Orders" } });

    await user.click(screen.getByRole("button", { name: /add column/i }));
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ columns: [] }));
  });

  it("edits one of several columns without touching the others", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Orders" } });

    await user.click(screen.getByRole("button", { name: /add column/i }));
    await user.click(screen.getByRole("button", { name: /add column/i }));
    const labels = screen.getAllByLabelText("Column label");
    fireEvent.change(labels[0] as HTMLElement, { target: { value: "First" } });
    fireEvent.change(labels[1] as HTMLElement, { target: { value: "Second" } });

    const typeSelects = screen.getAllByRole("combobox", { name: "Column type" });
    await user.click(typeSelects[1] as HTMLElement);
    await user.click(screen.getByRole("option", { name: "Number" }));

    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        columns: [
          { label: "First", type: "text" },
          { label: "Second", type: "number" },
        ],
      }),
    );
  });

  it("removes a column row", async () => {
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add column/i }));
    expect(screen.getAllByLabelText("Column label")).toHaveLength(1);

    await user.click(screen.getByRole("button", { name: /remove column/i }));
    expect(screen.queryByLabelText("Column label")).not.toBeInTheDocument();
  });

  it("shows a field-level error beside the name input", () => {
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        error={
          new ApiError(409, "taken", {
            error: {
              code: "ALREADY_EXISTS",
              message: "taken",
              details: {
                fields: [{ field: "name", message: "A table named 'Orders' already exists." }],
              },
            },
          })
        }
      />,
    );
    expect(screen.getByText("A table named 'Orders' already exists.")).toBeInTheDocument();
  });

  it("disables submit while creating", () => {
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={true}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Orders" } });
    expect(screen.getByRole("button", { name: /create table/i })).toBeDisabled();
  });

  it("cancel closes without creating", async () => {
    const onOpenChange = vi.fn();
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <CreateTableDialog
        open
        onOpenChange={onOpenChange}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onCreate).not.toHaveBeenCalled();
  });

  it("resets its fields once the dialog itself closes (not on the Cancel button alone)", async () => {
    const user = userEvent.setup();
    let open = true;
    const onOpenChange = vi.fn((next: boolean) => {
      open = next;
    });
    const { rerender } = render(
      <CreateTableDialog
        open={open}
        onOpenChange={onOpenChange}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Orders" } });

    // The dialog's own close control (not the footer's Cancel button, which
    // only forwards to the `onOpenChange` prop directly) drives Radix's
    // `onOpenChange`, which is where `reset()` is wired.
    await user.click(screen.getByRole("button", { name: /close/i }));
    rerender(
      <CreateTableDialog
        open={open}
        onOpenChange={onOpenChange}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );
    rerender(
      <CreateTableDialog
        open
        onOpenChange={onOpenChange}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );

    expect(screen.getByLabelText("Name")).toHaveValue("");
  });
});

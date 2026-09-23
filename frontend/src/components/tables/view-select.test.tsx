import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ViewSelect } from "./view-select";
import { ApiError } from "@/lib/api-client";
import type { TableViewRead } from "@/types/tables";

const config = {
  filters: [],
  sort: { by: "c1", direction: "asc" as const },
  visible_columns: null,
  group_by: null,
};

function view(overrides: Partial<TableViewRead> = {}): TableViewRead {
  return {
    id: "v1",
    table_id: "t1",
    owner_user_id: "u1",
    name: "Mine",
    kind: "table",
    visibility: "private",
    config,
    can_manage: true,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: null,
    ...overrides,
  };
}

describe("ViewSelect", () => {
  it("shows the unsaved-view placeholder when no view is active", () => {
    render(
      <ViewSelect
        kind="table"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    expect(screen.getByRole("combobox", { name: /select a table view/i })).toHaveTextContent(
      "Unsaved view",
    );
  });

  it("selecting a saved view calls onSelect with its id", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId={null}
        onSelect={onSelect}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("combobox", { name: /select a table view/i }));
    await user.click(screen.getByRole("option", { name: "Mine" }));

    expect(onSelect).toHaveBeenCalledWith("v1");
  });

  it("selecting the unsaved-view option calls onSelect with null", async () => {
    const onSelect = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId="v1"
        onSelect={onSelect}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("combobox", { name: /select a table view/i }));
    const listbox = screen.getByRole("listbox");
    await user.click(within(listbox).getByRole("option", { name: "Unsaved view" }));

    expect(onSelect).toHaveBeenCalledWith(null);
  });

  it("hides the new-view control when the caller may not create one", () => {
    render(
      <ViewSelect
        kind="kanban"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate={false}
      />,
    );
    expect(screen.queryByRole("button", { name: /new view/i })).not.toBeInTheDocument();
  });

  it("creates a view with the typed name and chosen visibility, and keeps the dialog open while the write is in flight", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    const { rerender } = render(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /new view/i }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "  My list  " } });
    await user.click(screen.getByRole("combobox", { name: "Visibility" }));
    await user.click(screen.getByRole("option", { name: "Shared" }));
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onCreate).toHaveBeenCalledWith("My list", "shared");
    // `onCreate` itself carries no result - the caller's mutation state is
    // what actually says whether the write is still running.
    rerender(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={onCreate}
        isCreating
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();
  });

  it("closes the create dialog once a create that was in flight finishes without error", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    await user.click(screen.getByRole("button", { name: /new view/i }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "My list" } });

    rerender(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    expect(screen.getByRole("dialog")).toBeInTheDocument();

    rerender(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("keeps the create dialog open and shows the conflict when a create fails", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    await user.click(screen.getByRole("button", { name: /new view/i }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "My list" } });

    rerender(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    rerender(
      <ViewSelect
        kind="list"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={
          new ApiError(409, "A view named 'My list' already exists.", {
            error: {
              code: "ALREADY_EXISTS",
              message: "A view named 'My list' already exists.",
              details: { name: "My list" },
            },
          })
        }
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    expect(screen.getByRole("dialog")).toBeInTheDocument();
    expect(screen.getByText("A view named 'My list' already exists.")).toBeInTheDocument();
  });

  it("disables save in the create dialog while the name is blank", async () => {
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /new view/i }));

    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("cancelling the create dialog does not call onCreate", async () => {
    const onCreate = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /new view/i }));
    fireEvent.change(screen.getByLabelText("View name"), { target: { value: "Draft" } });
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(onCreate).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("shows no manage controls for a view the caller cannot manage", () => {
    render(
      <ViewSelect
        kind="table"
        views={[view({ can_manage: false })]}
        activeViewId="v1"
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    expect(screen.queryByRole("button", { name: /^rename$/i })).not.toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^delete$/i })).not.toBeInTheDocument();
  });

  it("shows no manage controls when no view is active", () => {
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId={null}
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={vi.fn()}
        canCreate
      />,
    );
    expect(screen.queryByRole("button", { name: /^rename$/i })).not.toBeInTheDocument();
  });

  it("renames the active view with the edited, trimmed name", async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId="v1"
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={onRename}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /^rename$/i }));
    const input = screen.getByLabelText("View name");
    expect(input).toHaveValue("Mine");
    fireEvent.change(input, { target: { value: "  Renamed  " } });
    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onRename).toHaveBeenCalledWith("v1", "Renamed");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancelling rename does not call onRename", async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId="v1"
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={onRename}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /^rename$/i }));
    await user.click(screen.getByRole("button", { name: /^cancel$/i }));

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("closing the rename dialog via its own close control also clears the draft", async () => {
    const onRename = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId="v1"
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={onRename}
        onDelete={vi.fn()}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /^rename$/i }));
    await user.click(screen.getByRole("button", { name: /^close$/i }));

    expect(onRename).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("deletes the active view after confirming, naming it in the confirmation", async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId="v1"
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={onDelete}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    expect(within(dialog).getByText(/Delete “Mine”\?/)).toBeInTheDocument();

    await user.click(within(dialog).getByRole("button", { name: /^delete$/i }));

    expect(onDelete).toHaveBeenCalledWith("v1");
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("cancelling the delete confirmation does not call onDelete", async () => {
    const onDelete = vi.fn();
    const user = userEvent.setup();
    render(
      <ViewSelect
        kind="table"
        views={[view()]}
        activeViewId="v1"
        onSelect={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        createError={null}
        onRename={vi.fn()}
        onDelete={onDelete}
        canCreate
      />,
    );

    await user.click(screen.getByRole("button", { name: /^delete$/i }));
    const dialog = screen.getByRole("dialog");
    await user.click(within(dialog).getByRole("button", { name: /^cancel$/i }));

    expect(onDelete).not.toHaveBeenCalled();
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { SchemaEditorDialog } from "./schema-editor-dialog";
import { ApiError } from "@/lib/api-client";
import type { TableRead } from "@/types/tables";

function table(overrides: Partial<TableRead> = {}): TableRead {
  return {
    id: "t1",
    name: "Orders",
    description: null,
    visibility: "private",
    owner_user_id: null,
    schema_version: 1,
    archived_at: null,
    created_at: "2026-09-23T00:00:00Z",
    updated_at: null,
    can_edit: true,
    columns: [
      {
        id: "c1",
        label: "Customer",
        type: "text",
        nullable: true,
        default: null,
        options: [],
        archived: false,
      },
      {
        id: "c2",
        label: "Status",
        type: "single_select",
        nullable: true,
        default: null,
        options: [{ id: "o1", label: "Open", archived: false }],
        archived: false,
      },
    ],
    ...overrides,
  };
}

describe("SchemaEditorDialog", () => {
  it("seeds one row per existing column", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    expect(screen.getByDisplayValue("Customer")).toBeInTheDocument();
    expect(screen.getByDisplayValue("Status")).toBeInTheDocument();
  });

  it("an existing column's type is locked", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    const typeSelects = screen.getAllByRole("combobox", { name: "Column type" });
    expect(typeSelects[0]).toBeDisabled();
  });

  it("editing a column's label updates the row", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    const label = screen.getByDisplayValue("Customer");

    await user.clear(label);
    await user.type(label, "Client");

    expect(screen.getByDisplayValue("Client")).toBeInTheDocument();
  });

  it("archives an existing column into the Archived section, and restores it", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={onSave}
        isSaving={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Archive Customer" }));
    expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
    expect(screen.getByText(/^Archived columns/)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Save" }));
    expect(onSave.mock.calls[0]?.[0][0]).toMatchObject({ label: "Customer", archived: true });

    await user.click(screen.getByRole("button", { name: "Restore" }));
    expect(screen.getAllByLabelText("Column label")).toHaveLength(2);
    expect(screen.queryByText(/^Archived columns/)).not.toBeInTheDocument();
  });

  it("adds a new blank column with a removable row, and removes it", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add column/i }));
    expect(screen.getAllByLabelText("Column label")).toHaveLength(3);

    await user.click(screen.getByRole("button", { name: /remove column/i }));
    expect(screen.getAllByLabelText("Column label")).toHaveLength(2);
  });

  it("a new column has no archive button, since nothing exists yet to archive", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table({ columns: [] })}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    expect(screen.queryByRole("button", { name: /^Archive/ })).not.toBeInTheDocument();
  });

  it("makes a column required with its switch, and optional again", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    const required = screen.getAllByRole("switch", { name: "Required" });
    expect(required[0]).not.toBeChecked();

    await user.click(required[0] as HTMLElement);
    expect(required[0]).toBeChecked();
    await user.click(required[0] as HTMLElement);
    expect(required[0]).not.toBeChecked();
  });

  it("shows option rows for a single_select column, each archived and restored in place", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    expect(screen.getByDisplayValue("Open")).toBeEnabled();

    await user.click(screen.getByRole("button", { name: "Archive Open" }));
    expect(screen.getByDisplayValue("Open")).toBeDisabled();
    await user.click(screen.getByRole("button", { name: "Restore Open" }));
    expect(screen.getByDisplayValue("Open")).toBeEnabled();
  });

  it("adds and renames an option on a select column", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add option/i }));
    const optionInputs = screen.getAllByLabelText("Option label");
    expect(optionInputs).toHaveLength(2);

    await user.type(optionInputs[1] as HTMLElement, "Closed");

    expect(screen.getByDisplayValue("Closed")).toBeInTheDocument();
  });

  it("a newly added option can be removed, since it has no id yet to archive", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /add option/i }));
    expect(screen.getAllByLabelText("Option label")).toHaveLength(2);

    await user.click(screen.getByRole("button", { name: /remove option/i }));

    expect(screen.getAllByLabelText("Option label")).toHaveLength(1);
  });

  it("an existing option has no remove control, only archive", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    expect(screen.queryByRole("button", { name: /remove option/i })).not.toBeInTheDocument();
  });

  it("a new column's own type select is not locked and can pick single_select to reveal option controls", async () => {
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table({ columns: [] })}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    await user.click(screen.getByRole("button", { name: /add column/i }));

    const typeSelect = screen.getByRole("combobox", { name: "Column type" });
    expect(typeSelect).toBeEnabled();
    await user.click(typeSelect);
    await user.click(screen.getByRole("option", { name: "Single select" }));

    expect(screen.getByRole("button", { name: /add option/i })).toBeInTheDocument();
  });

  it("shows field-level errors from the server beside the offending row", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={
          new ApiError(422, "invalid", {
            error: {
              code: "INVALID_SCHEMA",
              message: "invalid",
              details: {
                fields: [
                  { field: "columns.0.type", message: "Type cannot change" },
                  { field: "columns.0.default", message: "Default does not fit" },
                  { field: "columns.0.nullable", message: "Cannot become required" },
                  { field: "columns.1.options", message: "Too many options" },
                ],
              },
            },
          })
        }
      />,
    );
    expect(screen.getByText("Type cannot change")).toBeInTheDocument();
    expect(screen.getByText("Default does not fit")).toBeInTheDocument();
    expect(screen.getByText("Cannot become required")).toBeInTheDocument();
    expect(screen.getByText("Too many options")).toBeInTheDocument();
  });

  it("shows a field-level error for a blank or cleared column label", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={
          new ApiError(422, "invalid", {
            error: {
              code: "VALIDATION_ERROR",
              message: "invalid",
              details: { fields: [{ field: "columns.0.label", message: "Cannot be blank" }] },
            },
          })
        }
      />,
    );
    expect(screen.getByText("Cannot be blank")).toBeInTheDocument();
  });

  it("shows a dialog-level message for a failure the server named no field for", () => {
    // A schema-version conflict (`current_version`) or a dependency refusal
    // (`dependents`) is not a field problem - `details.fields` is absent, so
    // without a fallback, Save would appear to do nothing.
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={
          new ApiError(409, "The schema changed since you opened it.", {
            error: {
              code: "SCHEMA_VERSION_CONFLICT",
              message: "The schema changed since you opened it.",
              details: { expected_version: 1, current_version: 2 },
            },
          })
        }
      />,
    );
    expect(screen.getByText("The schema changed since you opened it.")).toBeInTheDocument();
  });

  it("lists what still uses a removed column instead of a bare refusal", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={
          new ApiError(409, "Other resources depend on this and must be changed first", {
            error: {
              code: "SCHEMA_DEPENDENCY",
              message: "Other resources depend on this and must be changed first",
              details: { dependents: [{ kind: "table_view", id: "v1", name: "Board" }] },
            },
          })
        }
      />,
    );
    expect(screen.getByText("Board")).toBeInTheDocument();
    expect(
      screen.queryByText("Other resources depend on this and must be changed first"),
    ).not.toBeInTheDocument();
  });

  it("shows no dialog-level message when every problem already landed on a row", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={
          new ApiError(422, "invalid", {
            error: {
              code: "INVALID_SCHEMA",
              message: "invalid",
              details: { fields: [{ field: "columns.0.type", message: "Type cannot change" }] },
            },
          })
        }
      />,
    );
    expect(screen.getByText("Type cannot change")).toBeInTheDocument();
    expect(screen.queryByText("invalid")).not.toBeInTheDocument();
  });

  it("submits the rows without their local key", async () => {
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={onSave}
        isSaving={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /^save$/i }));

    expect(onSave).toHaveBeenCalledTimes(1);
    const [submitted] = onSave.mock.calls[0] as [Array<Record<string, unknown>>];
    expect(submitted).toHaveLength(2);
    expect(submitted[0]).not.toHaveProperty("key");
    expect(submitted[0]?.label).toBe("Customer");
  });

  it("disables save while saving", () => {
    render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={true}
        error={null}
      />,
    );
    expect(screen.getByRole("button", { name: /^save$/i })).toBeDisabled();
  });

  it("cancel closes the dialog without saving", async () => {
    const onOpenChange = vi.fn();
    const onSave = vi.fn();
    const user = userEvent.setup();
    render(
      <SchemaEditorDialog
        open
        onOpenChange={onOpenChange}
        table={table()}
        onSave={onSave}
        isSaving={false}
        error={null}
      />,
    );

    await user.click(screen.getByRole("button", { name: /cancel/i }));

    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("re-seeds its rows when reopened on a new schema version", () => {
    const { rerender } = render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );

    rerender(
      <SchemaEditorDialog
        open={false}
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    rerender(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table({
          schema_version: 2,
          columns: [
            {
              id: "c3",
              label: "New column",
              type: "text",
              nullable: true,
              default: null,
              options: [],
              archived: false,
            },
          ],
        })}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );

    expect(screen.getByDisplayValue("New column")).toBeInTheDocument();
    expect(screen.queryByDisplayValue("Customer")).not.toBeInTheDocument();
  });

  it("does not re-seed rows while the dialog stays open and the schema version is unchanged", async () => {
    const user = userEvent.setup();
    const { rerender } = render(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );
    const label = screen.getByDisplayValue("Customer");
    await user.clear(label);
    await user.type(label, "Edited");

    rerender(
      <SchemaEditorDialog
        open
        onOpenChange={vi.fn()}
        table={table()}
        onSave={vi.fn()}
        isSaving={false}
        error={null}
      />,
    );

    expect(screen.getByDisplayValue("Edited")).toBeInTheDocument();
  });
});

import { act, fireEvent, render, screen } from "@testing-library/react";
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

  it("creates a private table with optional details folded, keeping its walkthrough reachable", async () => {
    const onCreate = vi.fn();
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={onCreate}
        isCreating={false}
        error={null}
      />,
    );
    expect(screen.queryByLabelText("Description")).toBeNull();
    expect(screen.queryByLabelText("Visibility")).toBeNull();
    const guide = document.querySelector('[data-tour="table-dialog-visibility"]');
    expect(guide).toContainElement(screen.getByRole("button", { name: "More options" }));
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Leads" } });
    await userEvent.click(screen.getByRole("button", { name: "Create table" }));
    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({ name: "Leads", visibility: "private", description: null }),
      null,
    );
  });

  it("clears a cancelled form before the next table", async () => {
    const onOpenChange = vi.fn();
    render(
      <CreateTableDialog
        open
        onOpenChange={onOpenChange}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );
    fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Cancelled draft" } });
    await userEvent.click(screen.getByRole("button", { name: "Add column" }));
    await userEvent.click(screen.getByRole("button", { name: "Cancel" }));
    expect(onOpenChange).toHaveBeenCalledWith(false);
    expect(screen.getByLabelText("Name")).toHaveValue("");
    expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
  });

  it("submits the trimmed name, description and visibility, with the Name column it starts with", async () => {
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
    await user.click(screen.getByRole("button", { name: "More options" }));
    fireEvent.change(screen.getByLabelText("Description"), { target: { value: "  " } });
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(
      {
        name: "Orders",
        description: null,
        visibility: "private",
        columns: [{ label: "Name", type: "text" }],
      },
      null,
    );
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

    await user.click(screen.getByRole("button", { name: "More options" }));
    await user.click(screen.getByRole("combobox", { name: "Visibility" }));
    await user.click(screen.getByRole("option", { name: "Organization" }));
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(expect.objectContaining({ visibility: "org" }), null);
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
    fireEvent.change(screen.getAllByLabelText("Column label")[1] as HTMLElement, {
      target: { value: "Total" },
    });
    await user.click(screen.getAllByRole("combobox", { name: "Column type" })[1] as HTMLElement);
    await user.click(screen.getByRole("option", { name: "Number" }));
    await user.click(screen.getByRole("button", { name: /create table/i }));

    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({
        columns: [
          { label: "Name", type: "text" },
          { label: "Total", type: "number" },
        ],
      }),
      null,
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

    expect(onCreate).toHaveBeenCalledWith(
      expect.objectContaining({ columns: [{ label: "Name", type: "text" }] }),
      null,
    );
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
      null,
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

    expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
    await user.click(screen.getByRole("button", { name: /add column/i }));
    expect(screen.getAllByLabelText("Column label")).toHaveLength(2);

    await user.click(screen.getAllByRole("button", { name: /remove column/i })[1] as HTMLElement);
    expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
    expect(screen.getByDisplayValue("Name")).toBeInTheDocument();
  });

  it("shows a field-level error beside the name input", () => {
    // The real shape a taken name comes back as: a 409 `AlreadyExistsError`
    // naming the value in `details.name`, not a structured `details.fields`
    // list - `submitFailure`'s `identifiedBy` is what routes it to this input.
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        error={
          new ApiError(409, "A table named 'Orders' already exists.", {
            error: {
              code: "ALREADY_EXISTS",
              message: "A table named 'Orders' already exists.",
              details: { name: "Orders" },
            },
          })
        }
      />,
    );
    expect(screen.getByText("A table named 'Orders' already exists.")).toBeInTheDocument();
  });

  it("shows no dialog-level message before any submission has failed", () => {
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        error={null}
      />,
    );
    expect(screen.queryByText(/unexpected/i)).not.toBeInTheDocument();
  });

  it("shows a dialog-level message for a validation failure the server named no input for", () => {
    // A duplicate column label is refused as `INVALID_SCHEMA` on `columns`, not
    // on any input this form renders - `submitFailure`'s `.toast` used to be
    // computed and then discarded, so the dialog looked unresponsive.
    render(
      <CreateTableDialog
        open
        onOpenChange={vi.fn()}
        onCreate={vi.fn()}
        isCreating={false}
        error={
          new ApiError(422, "invalid", {
            error: {
              code: "INVALID_SCHEMA",
              message: "invalid",
              details: {
                fields: [{ field: "columns", message: "Two live columns have the same label" }],
              },
            },
          })
        }
      />,
    );
    expect(screen.getByText("columns: Two live columns have the same label")).toBeInTheDocument();
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

  describe("started from a CSV file", () => {
    function renderDialog(onCreate = vi.fn()) {
      render(
        <CreateTableDialog
          open
          onOpenChange={vi.fn()}
          onCreate={onCreate}
          isCreating={false}
          error={null}
        />,
      );
      return onCreate;
    }

    async function choose(content: string, name = "Leads.csv") {
      await act(async () => {
        fireEvent.change(screen.getByLabelText("Start from a CSV file"), {
          target: { files: [new File([content], name)] },
        });
      });
    }

    it("imports a console export without turning system metadata into editable columns", async () => {
      const onCreate = renderDialog();
      await choose(
        "Name,created_at,updated_at,created_by,updated_by\nExample,2026-10-31,2026-10-31,user-1,user-1\n",
      );
      expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
      await userEvent.click(screen.getByRole("button", { name: "Create table" }));
      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({ columns: [{ label: "Name", type: "text" }] }),
        expect.objectContaining({ labels: ["Name", null, null, null, null] }),
      );
    });

    it("reads the name, the columns and their types from the file", async () => {
      const user = userEvent.setup();
      const onCreate = renderDialog();

      await choose("Company,Seats,Paid,,Company,Notes\nAcme,3,yes,a,x,one\nGlobex,12,no,b,y,two\n");

      expect(screen.getByLabelText("Name")).toHaveValue("Leads");
      expect(screen.getByText("Leads.csv - 2 rows to import")).toBeInTheDocument();
      const labels = screen
        .getAllByLabelText("Column label")
        .map((input) => (input as HTMLInputElement).value);
      expect(labels).toEqual(["Company", "Seats", "Paid", "Column 4", "Company 2", "Notes"]);
      // The last column is left out, so its file column is not imported.
      const removes = screen.getAllByRole("button", { name: "Remove column" });
      await user.click(removes.at(-1) as HTMLElement);
      await user.click(screen.getByRole("button", { name: /create table/i }));

      expect(onCreate).toHaveBeenCalledWith(
        expect.objectContaining({
          name: "Leads",
          columns: [
            { label: "Company", type: "text" },
            { label: "Seats", type: "integer" },
            { label: "Paid", type: "boolean" },
            { label: "Column 4", type: "text" },
            { label: "Company 2", type: "text" },
          ],
        }),
        {
          fileName: "Leads.csv",
          headers: ["Company", "Seats", "Paid", "", "Company", "Notes"],
          rows: [
            ["Acme", "3", "yes", "a", "x", "one"],
            ["Globex", "12", "no", "b", "y", "two"],
          ],
          labels: ["Company", "Seats", "Paid", "Column 4", "Company 2", null],
        },
      );
    });

    it("keeps a name already typed, and shortens a header too long for a label", async () => {
      renderDialog();
      fireEvent.change(screen.getByLabelText("Name"), { target: { value: "Mine" } });
      const long = "L".repeat(70);

      await choose(`${long},${long}\n1,2\n`);

      expect(screen.getByLabelText("Name")).toHaveValue("Mine");
      const labels = screen
        .getAllByLabelText("Column label")
        .map((input) => (input as HTMLInputElement).value);
      expect(labels).toEqual(["L".repeat(64), `${"L".repeat(62)} 2`]);
    });

    it("refuses a file with no rows or with more columns than a table holds", async () => {
      renderDialog();

      await choose("A,B\n");
      expect(screen.getByText("That file has no rows under its header.")).toBeInTheDocument();

      const wide = Array.from({ length: 101 }, (_, at) => `C${at}`);
      await choose(`${wide.join(",")}\n${wide.join(",")}\n`);
      expect(screen.getByText("A table holds at most 100 columns.")).toBeInTheDocument();
      // The table keeps the column it starts with.
      expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
    });

    it("ignores a file input left empty", async () => {
      renderDialog();
      await act(async () => {
        fireEvent.change(screen.getByLabelText("Start from a CSV file"), {
          target: { files: [] },
        });
      });
      // The table keeps the column it starts with.
      expect(screen.getAllByLabelText("Column label")).toHaveLength(1);
    });
  });
});

it("names organization identity column types in the creation picker", async () => {
  render(
    <CreateTableDialog
      open
      onOpenChange={vi.fn()}
      onCreate={vi.fn()}
      isCreating={false}
      error={null}
    />,
  );
  await userEvent.click(screen.getByRole("combobox", { name: "Column type" }));
  for (const name of ["Person", "People", "AI agent", "Multiple AI agents"]) {
    expect(screen.getByRole("option", { name })).toBeVisible();
  }
});

it("creates colored options with a typed default without changing other columns", async () => {
  const create = vi.fn();
  render(
    <CreateTableDialog
      open
      onOpenChange={vi.fn()}
      onCreate={create}
      isCreating={false}
      error={null}
    />,
  );
  await userEvent.type(screen.getByLabelText("Name"), "Projects");
  await userEvent.click(screen.getByRole("button", { name: "Add column" }));
  fireEvent.change(screen.getAllByLabelText("Column label")[1]!, { target: { value: "Status" } });
  await userEvent.click(screen.getAllByRole("combobox", { name: "Column type" })[1]!);
  await userEvent.click(screen.getByRole("option", { name: "Single select" }));
  fireEvent.change(screen.getByLabelText("Options, one per line"), {
    target: { value: "Open\nDone\nOpen" },
  });
  await userEvent.click(screen.getByRole("combobox", { name: "Color for Open" }));
  await userEvent.click(screen.getByRole("option", { name: "Green" }));
  await userEvent.click(screen.getAllByRole("button", { name: "Default value" })[1]!);
  await userEvent.click(screen.getByRole("combobox", { name: "Default value" }));
  await userEvent.click(screen.getByRole("option", { name: "Open" }));
  await userEvent.click(screen.getByRole("button", { name: "Create table" }));
  expect(create.mock.calls[0]?.[0].columns).toEqual([
    { label: "Name", type: "text" },
    expect.objectContaining({
      label: "Status",
      type: "single_select",
      default: "Open",
      options: [
        { label: "Open", color: "green" },
        { label: "Done", color: null },
      ],
    }),
  ]);
});
it("edits a new document column template while preserving other columns", async () => {
  const create = vi.fn();
  render(
    <CreateTableDialog
      open
      onOpenChange={vi.fn()}
      onCreate={create}
      isCreating={false}
      error={null}
    />,
  );
  await userEvent.type(screen.getByLabelText("Name"), "Notebook");
  await userEvent.click(screen.getByRole("button", { name: "Add column" }));
  fireEvent.change(screen.getAllByLabelText("Column label")[1]!, { target: { value: "Notes" } });
  await userEvent.click(screen.getAllByRole("combobox", { name: "Column type" })[1]!);
  await userEvent.click(screen.getByRole("option", { name: "Rich text (Markdown)" }));
  fireEvent.change(screen.getByRole("textbox", { name: "Default document template" }), {
    target: { value: "# Team template" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Create table" }));
  expect(create.mock.calls[0]?.[0].columns).toEqual([
    { label: "Name", type: "text" },
    expect.objectContaining({ label: "Notes", type: "rich_text", default: "# Team template" }),
  ]);
});

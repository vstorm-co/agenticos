import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SchemaUpdate, TableRead } from "@/types/tables";
import { DocumentTemplates } from "./document-templates";

const state = vi.hoisted(() => ({
  table: null as TableRead | null,
  save: vi.fn<(update: SchemaUpdate) => Promise<void>>(),
  loading: false,
  error: null as Error | null,
  busy: false,
}));
vi.mock("@/hooks/use-tables", async (original) => ({
  ...(await original<typeof import("@/hooks/use-tables")>()),
  useTable: () => ({
    table: state.table,
    isLoading: state.loading,
    error: state.error,
    changeSchema: { isPending: state.busy, mutateAsync: state.save },
  }),
}));

beforeEach(() => {
  state.loading = false;
  state.error = null;
  state.busy = false;
  state.table = {
    id: "table",
    name: "Projects",
    description: null,
    visibility: "private",
    owner_user_id: null,
    schema_version: 1,
    archived_at: null,
    created_at: "2026-10-31T00:00:00Z",
    updated_at: null,
    can_edit: true,
    can_restore: false,
    columns: [
      {
        id: "notes",
        label: "Notes",
        type: "rich_text",
        nullable: true,
        default: null,
        options: [],
        archived: false,
        document_templates: [],
        default_template_id: null,
      },
    ],
  };
  state.save.mockReset();
  state.save.mockImplementation(async (update: SchemaUpdate) => {
    if (state.table)
      state.table = {
        ...state.table,
        schema_version: state.table.schema_version + 1,
        columns: state.table.columns.map((column) => {
          const next = update.columns.find((item) => item.id === column.id);
          return {
            ...column,
            document_templates: next?.document_templates ?? [],
            default_template_id: next?.default_template_id ?? null,
            default: next?.default ?? null,
          };
        }),
      };
  });
});

describe("document template library", () => {
  it("saves the current document as a named reusable default", async () => {
    const apply = vi.fn();
    render(
      <DocumentTemplates tableId="table" columnId="notes" body="# Our brief" onApply={apply} />,
    );
    await userEvent.click(screen.getByRole("button", { name: "Document templates" }));
    await userEvent.click(screen.getByRole("button", { name: "New template" }));
    await userEvent.type(screen.getByRole("textbox", { name: "Template name" }), "Our process");
    expect(screen.getByRole("textbox", { name: "Markdown content" })).toHaveValue("# Our brief");
    await userEvent.click(screen.getByRole("checkbox", { name: "Use by default for new records" }));
    await userEvent.click(screen.getByRole("button", { name: "Save template" }));
    await waitFor(() => expect(state.save).toHaveBeenCalled());
    const saved = state.save.mock.calls[0]?.[0];
    if (!saved) throw new Error("Missing schema mutation");
    expect(saved.columns[0]?.document_templates?.[0]).toMatchObject({
      name: "Our process",
      body: "# Our brief",
    });
    expect(saved.columns[0]?.default_template_id).toBe(
      saved.columns[0]?.document_templates?.[0]?.id,
    );
    await screen.findByText("Our process");
    const card = screen.getByText("Our process").closest("div");
    if (!card?.parentElement) throw new Error("Missing template card");
    await userEvent.click(within(card.parentElement).getByRole("button", { name: "Use template" }));
    expect(apply).toHaveBeenCalledWith("# Our brief");
  });

  it("does not expose template creation when table editing is refused", async () => {
    if (state.table) state.table.can_edit = false;
    render(<DocumentTemplates tableId="table" columnId="notes" body="" onApply={vi.fn()} />);
    await userEvent.click(screen.getByRole("button", { name: "Document templates" }));
    expect(screen.getByRole("button", { name: "New template" })).toBeDisabled();
  });
});

function seedLibrary() {
  const table = state.table;
  const column = table?.columns[0];
  if (!table || !column) throw new Error("Missing seeded table");
  state.table = {
    ...table,
    columns: [
      {
        ...column,
        default: "# Brief",
        default_template_id: "brief",
        document_templates: [
          { id: "brief", name: "Brief", body: "# Brief" },
          { id: "meeting", name: "Meeting", body: "# Meeting" },
        ],
      },
    ],
  };
}
async function openLibrary() {
  const apply = vi.fn();
  const result = render(
    <DocumentTemplates tableId="table" columnId="notes" body="" onApply={apply} />,
  );
  await userEvent.click(screen.getByRole("button", { name: "Document templates" }));
  return { ...result, apply };
}
function templateCard(name: string) {
  const card = screen.getByText(name).closest("div")?.parentElement;
  if (!card) throw new Error("Missing template card");
  return within(card);
}
it("edits an existing default template and removes its automatic default", async () => {
  seedLibrary();
  await openLibrary();
  await userEvent.click(screen.getByRole("button", { name: "Edit Brief" }));
  await userEvent.clear(screen.getByRole("textbox", { name: "Markdown content" }));
  await userEvent.type(screen.getByRole("textbox", { name: "Markdown content" }), "## Revised");
  await userEvent.click(screen.getByRole("checkbox", { name: "Use by default for new records" }));
  await userEvent.click(screen.getByRole("button", { name: "Save template" }));
  await waitFor(() => expect(state.save).toHaveBeenCalled());
  expect(state.save.mock.calls[0]?.[0].columns[0]).toMatchObject({
    default: null,
    default_template_id: null,
    document_templates: [
      { id: "brief", name: "Brief", body: "## Revised" },
      { id: "meeting", name: "Meeting", body: "# Meeting" },
    ],
  });
});
it("chooses a stored default and can clear the column's current default", async () => {
  seedLibrary();
  await openLibrary();
  await userEvent.click(templateCard("Meeting").getByRole("button", { name: "Set as default" }));
  await waitFor(() => expect(state.save).toHaveBeenCalled());
  expect(state.save.mock.calls[0]?.[0].columns[0]?.default_template_id).toBe("meeting");
  await userEvent.click(screen.getByRole("button", { name: "Clear default" }));
  await waitFor(() => expect(state.save).toHaveBeenCalledTimes(2));
  expect(state.save.mock.calls[1]?.[0].columns[0]).toMatchObject({
    default: null,
    default_template_id: null,
  });
});
it.each(["Brief", "Meeting"])(
  "deletes %s while preserving the remaining templates",
  async (name) => {
    seedLibrary();
    await openLibrary();
    await userEvent.click(screen.getByRole("button", { name: `Delete ${name}` }));
    await waitFor(() => expect(state.save).toHaveBeenCalled());
    const column = state.save.mock.calls[0]?.[0].columns[0];
    expect(column?.document_templates).toHaveLength(1);
    expect(column?.default_template_id).toBe(name === "Brief" ? null : "brief");
  },
);
it("customizes a built-in, returns to the library and applies a built-in body", async () => {
  const { apply } = await openLibrary();
  await userEvent.click(screen.getAllByRole("button", { name: "Customize" })[0]!);
  expect(screen.getByRole("checkbox", { name: "Use by default for new records" })).toBeChecked();
  await userEvent.click(screen.getByRole("button", { name: "Back" }));
  await userEvent.click(screen.getAllByRole("button", { name: "Use template" })[0]!);
  expect(apply).toHaveBeenCalled();
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("closes the library from Done and from Escape", async () => {
  await openLibrary();
  await userEvent.click(screen.getByRole("button", { name: "Done" }));
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  await userEvent.click(screen.getByRole("button", { name: "Document templates" }));
  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
});
it("keeps an edited template after a rejected schema save", async () => {
  seedLibrary();
  state.save.mockRejectedValue(new Error("Schema changed"));
  await openLibrary();
  await userEvent.click(screen.getByRole("button", { name: "Edit Brief" }));
  await userEvent.click(screen.getByRole("button", { name: "Save template" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("Schema changed");
  expect(screen.getByRole("textbox", { name: "Template name" })).toHaveValue("Brief");
});
it("reports library loading and failure without offering writes", async () => {
  state.loading = true;
  state.error = new Error("Library unavailable");
  state.table = null;
  await openLibrary();
  expect(screen.getByRole("alert")).toHaveTextContent("Library unavailable");
  expect(screen.getByText("Loading templates…")).toBeVisible();
  expect(screen.getByRole("button", { name: "New template" })).toBeDisabled();
});

it("rechecks editing access before saving a form opened earlier", async () => {
  seedLibrary();
  const { rerender } = await openLibrary();
  await userEvent.click(screen.getByRole("button", { name: "Edit Brief" }));
  if (!state.table) throw new Error("Missing table");
  state.table = { ...state.table, can_edit: false };
  rerender(<DocumentTemplates tableId="table" columnId="notes" body="" onApply={vi.fn()} />);
  fireEvent.submit(screen.getByRole("textbox", { name: "Template name" }));
  expect(state.save).not.toHaveBeenCalled();
});
it("refuses an empty template name even if the form is submitted directly", async () => {
  await openLibrary();
  await userEvent.click(screen.getByRole("button", { name: "New template" }));
  fireEvent.submit(screen.getByRole("textbox", { name: "Template name" }));
  expect(state.save).not.toHaveBeenCalled();
});

import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import type { SchemaUpdate, TableRead } from "@/types/tables";
import { DocumentTemplates } from "./document-templates";

const state = vi.hoisted(() => ({
  table: null as TableRead | null,
  save: vi.fn<(update: SchemaUpdate) => Promise<void>>(),
}));
vi.mock("@/hooks/use-tables", async (original) => ({
  ...(await original<typeof import("@/hooks/use-tables")>()),
  useTable: () => ({
    table: state.table,
    isLoading: false,
    error: null,
    changeSchema: { isPending: false, mutateAsync: state.save },
  }),
}));

beforeEach(() => {
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

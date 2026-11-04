import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import type { ColumnDef, RecordRead } from "@/types/tables";

import { LinkCell, recordName } from "./link-cell";

const state = vi.hoisted(() => ({ query: vi.fn(), asked: [] as (string | null)[] }));

const name: ColumnDef = {
  id: "p-name",
  label: "Name",
  type: "text",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};

vi.mock("@/hooks", () => ({
  useTable: (tableId: string | null) => {
    state.asked.push(tableId);
    return { table: tableId ? { columns: [name] } : undefined };
  },
}));
vi.mock("@/lib/tables-api", () => ({ queryRecords: state.query }));

const record = (id: string, values: Record<string, string>, externalId: string | null = null) =>
  ({ id, external_id: externalId, values }) as unknown as RecordRead;

const items: ColumnDef = {
  ...name,
  id: "c-items",
  label: "Items",
  type: "link",
  link_table_id: "t1",
};

function renderCell(value: string[], onChange = vi.fn()) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={client}>{children}</QueryClientProvider>
  );
  render(
    <LinkCell
      id="cell"
      column={items}
      value={value}
      links={[{ id: "r1", label: "Atlas" }]}
      onChange={onChange}
    />,
    { wrapper },
  );
  return onChange;
}

beforeEach(() => {
  state.query.mockReset();
  state.asked = [];
  state.query.mockResolvedValue({
    items: [record("r1", { "p-name": "Atlas" }), record("r2", { "p-name": "Quill" })],
  });
});

describe("recordName", () => {
  it("names a record by its first text, then its external id, then its id's head", () => {
    expect(recordName(record("r1", { "p-name": "Atlas" }), [name])).toBe("Atlas");
    expect(recordName(record("r2", { "p-name": "  " }, "SKU-2"), [name])).toBe("SKU-2");
    expect(recordName(record("1234567890ab", {}), [])).toBe("12345678");
  });
});

describe("LinkCell", () => {
  it("shows the linked records by name, and asks nothing until opened", () => {
    renderCell(["r1", "r9"]);

    expect(screen.getByText("Atlas")).toBeVisible();
    expect(screen.getByText("A linked record")).toBeVisible();
    expect(state.query).not.toHaveBeenCalled();
    expect(state.asked.every((asked) => asked === null)).toBe(true);
  });

  it("says when nothing is linked", () => {
    renderCell([]);
    expect(screen.getByText("Not linked")).toBeVisible();
  });

  it("finds records of the linked table by what they say, and links and unlinks them", async () => {
    const user = userEvent.setup();
    const onChange = renderCell(["r1"]);

    await user.click(screen.getByRole("button", { name: /Atlas/ }));
    await waitFor(() => expect(screen.getByLabelText("Quill")).toBeInTheDocument());
    expect(state.query).toHaveBeenCalledWith("t1", { search: null, limit: 20 });
    await user.click(screen.getByLabelText("Quill"));
    await user.click(screen.getByLabelText("Atlas"));

    expect(onChange.mock.calls).toEqual([[["r1", "r2"]], [[]]]);

    await user.type(screen.getByRole("textbox", { name: "Find a record" }), "qu");
    await waitFor(() =>
      expect(state.query).toHaveBeenLastCalledWith("t1", { search: "qu", limit: 20 }),
    );
  });

  it("says when no record matches", async () => {
    const user = userEvent.setup();
    state.query.mockResolvedValue({ items: [] });
    renderCell([]);

    await user.click(screen.getByRole("button", { name: "Not linked" }));

    expect(await screen.findByText("No records match.")).toBeVisible();
  });
});

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TablesSection, grantsOf } from "./tables-section";
import type { CapabilityBindingSpec, CapabilityCatalogEntry } from "@/types/agents";

/**
 * Which tables an agent may use, and what it may do in each - a table and its
 * operations per row, because a generated form would draw a list of UUIDs.
 */

const tables = vi.fn();
vi.mock("@/hooks", () => ({ useTables: () => tables() }));

const LEADS = { id: "t-leads", name: "Leads", description: "Inbound leads" };
const ORDERS = { id: "t-orders", name: "Orders", description: null };

const DEFINITION: CapabilityCatalogEntry = {
  id: "virtual_tables",
  name: "Tables",
  category: "data",
  description: "Read and write the Virtual Tables this agent is granted.",
  side_effecting: false,
  scopes: ["tables:read"],
  tools: [],
  contracts: [],
  config_schema: {
    type: "object",
    properties: {
      tables: { type: "array" },
      allow_create: { type: "boolean", title: "Allow create" },
    },
  },
  requires_secret: null,
};

function mount(config: Record<string, unknown> = {}, disabled = false) {
  const onChange = vi.fn();
  render(
    <TablesSection
      definition={DEFINITION}
      binding={
        {
          id: "virtual_tables",
          config,
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        } satisfies CapabilityBindingSpec
      }
      onChange={onChange}
      disabled={disabled}
    />,
  );
  return onChange;
}

beforeEach(() => {
  tables.mockReturnValue({ tables: [LEADS, ORDERS], isLoading: false });
});

describe("TablesSection", () => {
  it("grants a table with reading only", async () => {
    const onChange = mount();

    await userEvent.click(screen.getByRole("checkbox", { name: "Let the agent use Leads" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { tables: [{ table_id: "t-leads", operations: ["read"] }] },
      }),
    );
  });

  it("adds an operation to a grant in a stable order, and keeps reading fixed", async () => {
    const onChange = mount({ tables: [{ table_id: "t-leads", operations: ["read", "delete"] }] });

    expect(screen.getByRole("button", { name: "Read" })).toBeDisabled();
    await userEvent.click(screen.getByRole("button", { name: "Update" }));

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: { tables: [{ table_id: "t-leads", operations: ["read", "update", "delete"] }] },
      }),
    );
  });

  it("changes one table's operations and leaves another's alone", async () => {
    const onChange = mount({
      tables: [
        { table_id: "t-leads", operations: ["read"] },
        { table_id: "t-orders", operations: ["read"] },
      ],
    });

    const [, ordersUpdate] = screen.getAllByRole("button", { name: "Update" });
    await userEvent.click(ordersUpdate as HTMLElement);

    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({
        config: {
          tables: [
            { table_id: "t-leads", operations: ["read"] },
            { table_id: "t-orders", operations: ["read", "update"] },
          ],
        },
      }),
    );
  });

  it("takes an operation off, and takes a table away", async () => {
    const onChange = mount({ tables: [{ table_id: "t-leads", operations: ["read", "create"] }] });

    await userEvent.click(screen.getByRole("button", { name: "Add" }));
    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: { tables: [{ table_id: "t-leads", operations: ["read"] }] },
      }),
    );

    await userEvent.click(screen.getByRole("checkbox", { name: "Let the agent use Leads" }));
    expect(onChange).toHaveBeenLastCalledWith(expect.objectContaining({ config: { tables: [] } }));
  });

  it("keeps a grant to a table that is gone visible rather than dropping it", () => {
    mount({ tables: [{ table_id: "t-gone", operations: ["read"] }] });
    expect(screen.getByText("t-gone")).toBeVisible();
  });

  it("says what to do when there are no tables yet", () => {
    tables.mockReturnValue({ tables: [], isLoading: false });
    mount();
    expect(screen.getByText(/There are no tables yet/)).toBeVisible();
  });

  it("shows a placeholder while the tables load", () => {
    tables.mockReturnValue({ tables: [], isLoading: true });
    mount();
    expect(screen.queryByText(/There are no tables yet/)).not.toBeInTheDocument();
  });

  it("draws the rest of the configuration from the schema, and keeps the grants", async () => {
    const onChange = mount({ tables: [{ table_id: "t-leads", operations: ["read"] }] });

    await userEvent.click(screen.getByLabelText("Allow create"));

    expect(onChange).toHaveBeenLastCalledWith(
      expect.objectContaining({
        config: expect.objectContaining({
          allow_create: true,
          tables: [{ table_id: "t-leads", operations: ["read"] }],
        }),
      }),
    );
  });

  it("draws nothing without a catalog entry", () => {
    const { container } = render(
      <TablesSection
        definition={undefined}
        binding={{
          id: "virtual_tables",
          config: {},
          approval: "default",
          tool_approval: {},
          tool_overrides: {},
          secret_id: null,
          enabled: true,
        }}
        onChange={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });
});

describe("grantsOf", () => {
  it("keeps only what reads as a grant, and reads a grant with no operations as reading", () => {
    expect(
      grantsOf({
        tables: [
          { table_id: "a", operations: ["read", "bogus"] },
          { table_id: "b", operations: [] },
          { table_id: 7 },
          "nonsense",
          null,
        ],
      }),
    ).toEqual([
      { table_id: "a", operations: ["read"] },
      { table_id: "b", operations: ["read"] },
    ]);
    expect(grantsOf({ tables: "nope" })).toEqual([]);
  });
});

import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { ColumnDef, RecordRead } from "@/types/tables";

import { RecordConflictNow } from "./record-conflict-now";

const column: ColumnDef = {
  id: "flag",
  label: "Active",
  type: "boolean",
  nullable: true,
  default: null,
  options: [],
  archived: false,
};
const record: RecordRead = {
  id: "r1",
  table_id: "t1",
  external_id: null,
  schema_version: 1,
  values: {},
  revision: 2,
  created_at: "2026-11-13T00:00:00Z",
};

describe("current conflict values", () => {
  it.each([true, false])("renders a localized boolean (%s) in the live comparison", (value) => {
    render(<RecordConflictNow column={column} record={{ ...record, values: { flag: value } }} />);
    expect(screen.getByRole("status")).toHaveTextContent(`Now: ${value ? "True" : "False"}`);
    expect(screen.getByRole("status")).toHaveTextContent("someone else");
  });
});

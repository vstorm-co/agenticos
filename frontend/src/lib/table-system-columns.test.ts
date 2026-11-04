import { describe, expect, it } from "vitest";
import { TABLE_SYSTEM_COLUMNS, systemCellValue } from "./table-system-columns";
import { recordCellText } from "./format-cell-value";
import type { RecordRead } from "@/types/tables";

const record: RecordRead = {
  id: "r1",
  table_id: "t1",
  external_id: null,
  schema_version: 1,
  revision: 1,
  created_at: "2026-10-31T10:00:00Z",
  created_by: "user-1",
  values: { __created_at: "forged" },
};
describe("immutable table metadata", () => {
  it("projects each system field from the record envelope, including the initial update date", () => {
    expect(TABLE_SYSTEM_COLUMNS.map((column) => column.system)).toEqual([
      "created_at",
      "updated_at",
      "created_by",
      "updated_by",
    ]);
    expect(systemCellValue("created_at", record)).toBe(record.created_at);
    expect(systemCellValue("updated_at", record)).toBe(record.created_at);
    expect(systemCellValue("created_by", record)).toBe("user-1");
    expect(systemCellValue("updated_by", record)).toBe(null);
    expect(recordCellText(TABLE_SYSTEM_COLUMNS[0]!, record, String)).toBe(record.created_at);
    expect(systemCellValue("updated_at", { ...record, updated_at: "2026-11-01T10:00:00Z" })).toBe(
      "2026-11-01T10:00:00Z",
    );
  });
});

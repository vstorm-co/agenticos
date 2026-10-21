import { describe, expect, it } from "vitest";

import type { SyncSourceRead } from "@/lib/rag-api";
import { syncSourceChanges, syncSourceForm } from "@/lib/sync-source-changes";

const SOURCE: SyncSourceRead = {
  id: "s1",
  organization_id: "o1",
  name: "Engineering docs",
  connector_type: "gdrive",
  collection_name: "handbook",
  config: { folder_id: "1AbC", recursive: true },
  secret_id: "sec-1",
  secret_hint: "abcd",
  organizational_unit: null,
  sync_mode: "full",
  schedule_minutes: null,
  is_active: true,
  last_sync_at: null,
  last_sync_status: null,
  last_error: null,
  created_at: null,
};

describe("syncSourceForm", () => {
  it("fills the form from the source", () => {
    expect(syncSourceForm(SOURCE)).toEqual({
      name: "Engineering docs",
      connector_type: "gdrive",
      collection_name: "handbook",
      config: { folder_id: "1AbC", recursive: true },
      secret_id: "sec-1",
      organizational_unit: null,
      sync_mode: "full",
      schedule_minutes: null,
    });
  });

  it("copies the config rather than sharing it", () => {
    const form = syncSourceForm(SOURCE);
    form.config.folder_id = "changed";
    expect(SOURCE.config.folder_id).toBe("1AbC");
  });
});

describe("syncSourceChanges", () => {
  it("is empty for an untouched form", () => {
    expect(syncSourceChanges(SOURCE, syncSourceForm(SOURCE))).toEqual({});
  });

  it("leaves an unchanged credential out, so it is not checked again", () => {
    const form = { ...syncSourceForm(SOURCE), name: "Renamed" };
    expect(syncSourceChanges(SOURCE, form)).toEqual({ name: "Renamed" });
  });

  it("sends every field that changed", () => {
    const form = {
      ...syncSourceForm(SOURCE),
      config: { folder_id: "2XyZ", recursive: true },
      secret_id: "sec-2",
      organizational_unit: "Finance",
      sync_mode: "new_only",
      schedule_minutes: 60,
    };
    expect(syncSourceChanges(SOURCE, form)).toEqual({
      config: { folder_id: "2XyZ", recursive: true },
      secret_id: "sec-2",
      organizational_unit: "Finance",
      sync_mode: "new_only",
      schedule_minutes: 60,
    });
  });

  it("sends a cleared value as null", () => {
    const before = { ...SOURCE, organizational_unit: "Finance", schedule_minutes: 60 };
    const form = {
      ...syncSourceForm(before),
      secret_id: undefined,
      organizational_unit: undefined,
      schedule_minutes: undefined,
    };
    expect(syncSourceChanges(before, form)).toEqual({
      secret_id: null,
      organizational_unit: null,
      schedule_minutes: null,
    });
  });

  it("notices a config key added or removed", () => {
    const added = { ...syncSourceForm(SOURCE), config: { ...SOURCE.config, extra: "x" } };
    expect(syncSourceChanges(SOURCE, added).config).toEqual({ ...SOURCE.config, extra: "x" });
    const removed = { ...syncSourceForm(SOURCE), config: { folder_id: "1AbC" } };
    expect(syncSourceChanges(SOURCE, removed).config).toEqual({
      folder_id: "1AbC",
      recursive: null,
    });
  });

  it("sends a cleared config field as null, so the server's merge removes it", () => {
    const form = {
      ...syncSourceForm(SOURCE),
      config: { folder_id: "1AbC", recursive: undefined },
    };
    expect(syncSourceChanges(SOURCE, form)).toEqual({
      config: { folder_id: "1AbC", recursive: null },
    });
  });
});

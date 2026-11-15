import { describe, expect, it } from "vitest";

import { sameLocalTarget } from "./local-target-content";
import type { LocalTarget } from "./commands";

describe("local target content", () => {
  const target: LocalTarget = {
    folder: "/work",
    mode: "read_only",
    device_id: "device",
    routine_grant: "receipt",
    operations: { read: true, write: false, execute: false },
  };
  it("ignores key order and server-filled defaults", () => {
    expect(
      sameLocalTarget(target, {
        operations: { execute: false, write: false, read: true },
        routine_grant: "receipt",
        device_id: "device",
        mode: "read_only",
        folder: "/work",
        browser: false,
        computer: false,
        mcp_services: [],
        model_service: null,
        coding_model: null,
        coding_effort: null,
      }),
    ).toBe(true);
    expect(sameLocalTarget(null, null)).toBe(true);
  });
  it("keeps permission receipts, operations, devices and folders meaningful", () => {
    expect(sameLocalTarget(target, { ...target, routine_grant: "other" })).toBe(false);
    expect(
      sameLocalTarget(target, {
        ...target,
        operations: { read: true, write: true, execute: false },
      }),
    ).toBe(false);
    expect(sameLocalTarget(target, { ...target, folder: "/elsewhere" })).toBe(false);
    expect(sameLocalTarget(target, { ...target, device_id: "other" })).toBe(false);
    expect(sameLocalTarget(target, null)).toBe(false);
  });
});

it("does not erase changes to services, computer consent or coding configuration", () => {
  const configured: LocalTarget = {
    folder: "/work",
    mode: "read_only",
    device_id: "device",
    routine_grant: "routine",
    computer_grant: "computer",
    computer_grant_agent: "agent",
    operations: { read: true, write: false, execute: false },
    model_service: "model",
    mcp_services: ["github"],
    computer: true,
    browser: true,
    coding_agent: "codex",
    coding_model: "existing-model",
    coding_effort: "high",
    skills: [],
  };
  expect(sameLocalTarget(configured, { ...configured })).toBe(true);
  expect(sameLocalTarget(configured, { ...configured, computer_grant: "replacement" })).toBe(false);
  expect(sameLocalTarget(configured, { ...configured, mcp_services: [] })).toBe(false);
  expect(sameLocalTarget(configured, { ...configured, coding_model: "another-model" })).toBe(false);
  expect(
    sameLocalTarget({ folder: "/work", mode: "read_only" }, { folder: "/work", mode: "read_only" }),
  ).toBe(true);
});

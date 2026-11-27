import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  readTransferSession,
  subscribeTransferSessions,
  transferSessionKey,
  writeTransferSession,
} from "./transfer-session";

const ID = "aeac9081-9af3-4055-b738-1f4f7741af71";
beforeEach(() => sessionStorage.clear());
afterEach(() => {
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

it("retains only an operation ID under its owner, organization and dialog scope", () => {
  const key = transferSessionKey("org", "user", "import:workflow");
  writeTransferSession(key, ID);
  expect(readTransferSession(key)).toBe(ID);
  expect(readTransferSession(transferSessionKey("other", "user", "import:workflow"))).toBeNull();
  expect(readTransferSession(transferSessionKey("org", "other", "import:workflow"))).toBeNull();
  expect(readTransferSession(transferSessionKey("org", "user", "export:workflow:one"))).toBeNull();
  writeTransferSession(key, null);
  expect(readTransferSession(key)).toBeNull();
});

it("ignores malformed saved metadata and unscoped sessions", () => {
  expect(transferSessionKey(null, "user", "import")).toBeNull();
  expect(transferSessionKey("org", null, "import")).toBeNull();
  expect(transferSessionKey("org", "user")).toBeNull();
  sessionStorage.setItem("bad", "../../other-endpoint");
  expect(readTransferSession("bad")).toBeNull();
  writeTransferSession(null, ID);
  expect(readTransferSession(null)).toBeNull();
});

it("keeps an in-memory operation usable when optional browser storage is unavailable", () => {
  vi.spyOn(window.sessionStorage, "getItem").mockImplementation(() => {
    throw new DOMException("Denied", "SecurityError");
  });
  vi.spyOn(window.sessionStorage, "setItem").mockImplementation(() => {
    throw new DOMException("Denied", "SecurityError");
  });
  expect(readTransferSession("key")).toBeNull();
  expect(() => writeTransferSession("key", ID)).not.toThrow();
  vi.stubGlobal("window", undefined);
  expect(readTransferSession("key")).toBeNull();
  expect(() => writeTransferSession("key", ID)).not.toThrow();
  subscribeTransferSessions(() => undefined)();
});

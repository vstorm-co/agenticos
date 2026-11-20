import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  appAuthorizationUrl,
  appConnectionGoalForToolkit,
  appConnectionLabel,
  appConnectionScopeKey,
  appConnectionUsable,
  clearAppConnectionCallback,
  readAppConnectionCallback,
  rememberAppConnectionGoal,
  rememberedAppConnectionGoal,
} from "./app-connection-journey";
import type { AppConnection } from "@/types/app-connections";

const usable = {
  is_enabled: true,
  authorized: true,
  status: "connected",
  readiness: "authorization_verified",
} as AppConnection;
beforeEach(() => {
  sessionStorage.clear();
  window.history.replaceState(null, "", "/connectors");
});

describe("app connection boundaries", () => {
  it("keeps separate labels visible when accounts share a provider identity", () => {
    const first = { ...usable, identity: "same@example.test", label: "Work", name: "Mail" };
    expect(appConnectionLabel(first)).toBe("Work · same@example.test");
    expect(appConnectionLabel({ ...first, label: "Personal" })).toBe(
      "Personal · same@example.test",
    );
    expect(appConnectionLabel({ ...first, label: first.identity })).toBe("same@example.test");
    expect(appConnectionLabel({ ...first, identity: null })).toBe("Work");
    expect(appConnectionLabel({ ...first, identity: null, label: null })).toBe("Mail");
  });
  it("matches chat-requested apps to a useful goal while preserving compatible choices", () => {
    expect(appConnectionGoalForToolkit("gmail", "day")).toBe("inbox");
    expect(appConnectionGoalForToolkit("googledrive", "day")).toBe("answers");
    expect(appConnectionGoalForToolkit("outlook", "day")).toBe("day");
    expect(appConnectionGoalForToolkit("outlook", "inbox")).toBe("inbox");
    expect(appConnectionGoalForToolkit("unknown", "day")).toBe("day");
  });
  it("requires server-verified authorization, enabled status, and readiness together", () => {
    expect(appConnectionUsable(usable)).toBe(true);
    for (const change of [
      { authorized: false },
      { is_enabled: false },
      { status: "pending" },
      { status: "expired" },
      { readiness: "unavailable" },
    ] as Partial<AppConnection>[])
      expect(appConnectionUsable({ ...usable, ...change })).toBe(false);
  });

  it("accepts identity-verifier callbacks without an attempt and never trusts a success query", () => {
    expect(readAppConnectionCallback("?status=success&connected_account_id=other")).toBeNull();
    expect(readAppConnectionCallback("?session_uri=verifier-token&status=success")).toEqual({
      session_uri: "verifier-token",
    });
    expect(
      readAppConnectionCallback(
        "?connection_attempt=attempt&connected_account_id=account&status=failed",
      ),
    ).toEqual({
      attempt_id: "attempt",
      connected_account_id: "account",
    });
    window.history.replaceState(
      { keep: true },
      "",
      "/connectors?app=gmail&session_uri=private&status=success#accounts",
    );
    clearAppConnectionCallback();
    expect(window.location.pathname + window.location.search + window.location.hash).toBe(
      "/connectors?app=gmail#accounts",
    );
    expect(window.history.state).toEqual({ keep: true });
  });

  it("rejects non-HTTPS and credential-bearing authorization addresses", () => {
    expect(appAuthorizationUrl("https://connect.example/authorize?state=a")).toBe(
      "https://connect.example/authorize?state=a",
    );
    for (const url of [
      "javascript:alert(1)",
      "http://connect.example",
      "//connect.example",
      "https://secret@connect.example",
      "invalid",
    ]) {
      expect(appAuthorizationUrl(url)).toBeNull();
    }
  });

  it("remembers only the chosen goal, isolated by user and organization", () => {
    const scope = { userId: "user-1", orgId: "org-1" };
    rememberAppConnectionGoal(scope, "inbox");
    expect(rememberedAppConnectionGoal(scope)).toBe("inbox");
    expect(rememberedAppConnectionGoal({ ...scope, orgId: "org-2" })).toBe("day");
    expect(rememberedAppConnectionGoal({ ...scope, userId: "user-2" })).toBe("day");
    sessionStorage.setItem("app-connection-goal:" + appConnectionScopeKey(scope), "unrecognized");
    expect(rememberedAppConnectionGoal(scope)).toBe("day");
    const get = vi.spyOn(sessionStorage, "getItem").mockImplementation(() => {
      throw new Error("blocked");
    });
    expect(rememberedAppConnectionGoal(scope)).toBe("day");
    get.mockRestore();
  });
});

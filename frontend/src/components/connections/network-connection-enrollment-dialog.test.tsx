import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { NetworkConnection, NetworkEnrollment } from "@/types/network-connections";
import { NetworkConnectionEnrollmentDialog } from "./network-connection-enrollment-dialog";

function connection(overrides: Partial<NetworkConnection> = {}): NetworkConnection {
  return {
    id: "network-1",
    organization_id: "org-1",
    owner_user_id: "user-1",
    scope: "user",
    name: "Home tailnet",
    desired_state: "active",
    auth_state: "sign_in_required",
    runtime_state: "starting",
    cleanup_state: "none",
    tailnet_name: null,
    node_id: null,
    last_seen_at: null,
    last_error_code: null,
    created_at: "2026-01-01T00:00:00Z",
    updated_at: "2026-01-01T00:00:00Z",
    can_manage: true,
    ...overrides,
  };
}

function renderDialog(loginUrl: string | null) {
  const network = connection();
  const enrollment: NetworkEnrollment = {
    attempt_id: "attempt-1",
    expires_at: "2030-01-01T00:00:00Z",
    login_url: loginUrl,
  };
  return render(
    <NetworkConnectionEnrollmentDialog
      open
      onOpenChange={() => {}}
      connection={network}
      enrollment={enrollment}
      currentState={network}
      stateLoading={false}
      stateError={false}
      canManage={true}
      available={true}
      refreshing={false}
      onRefreshStatus={() => {}}
      onRestart={() => {}}
    />,
  );
}

describe("private Tailscale sign-in link", () => {
  it("opens only the exact HTTPS Tailscale login origin and enrollment path", () => {
    renderDialog("https://login.tailscale.com/a/c-test-sign-in");

    const link = screen.getByRole("link", { name: "Open Tailscale sign-in" });
    expect(link).toHaveAttribute("href", "https://login.tailscale.com/a/c-test-sign-in");
    expect(link).toHaveAttribute("target", "_blank");
    expect(link).toHaveAttribute("rel", "noopener noreferrer");
  });

  it.each([
    "http://login.tailscale.com/a/c-test-sign-in",
    "https://login.tailscale.com.attacker.example/a/c-test-sign-in",
    "https://login.tailscale.com@attacker.example/a/c-test-sign-in",
    "https://login.tailscale.com/a/c-test-sign-in#fragment",
  ])("does not render an untrusted sign-in URL: %s", (loginUrl) => {
    renderDialog(loginUrl);

    expect(screen.queryByRole("link", { name: "Open Tailscale sign-in" })).toBeNull();
    expect(screen.getByText("Sign-in required")).toBeVisible();
  });

  it("does not show management actions to a viewer or while the runtime is unavailable", () => {
    const network = connection({
      auth_state: "authenticated",
      runtime_state: "stopped",
    });
    render(
      <NetworkConnectionEnrollmentDialog
        open
        onOpenChange={() => {}}
        connection={network}
        enrollment={{ attempt_id: null, expires_at: null, login_url: null }}
        currentState={network}
        stateLoading={false}
        stateError={false}
        canManage={false}
        available={false}
        refreshing={false}
        onRefreshStatus={() => {}}
        onRestart={() => {}}
      />,
    );

    expect(screen.queryByRole("button", { name: "Refresh status" })).toBeNull();
    expect(screen.queryByRole("button", { name: "Start enrollment again" })).toBeNull();
  });
});

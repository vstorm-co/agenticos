import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AddSecretDialog, RotateSecretDialog } from "./secret-dialog";
import { LOGIN, PROFILE } from "@/test-utils/browser-credential-fixtures";
import { useAuthStore } from "@/stores/auth-store";
import { useOrgStore } from "@/stores/org-store";
import type { Secret } from "@/types/secrets";
import type { ReactElement } from "react";

vi.mock("@/lib/api-client", async () => ({
  ...(await vi.importActual<typeof import("@/lib/api-client")>("@/lib/api-client")),
  apiClient: { get: vi.fn().mockResolvedValue({ items: [], total: 0 }) },
}));
vi.mock("sonner", () => ({ toast: { error: vi.fn(), success: vi.fn() } }));

const loginValue = {
  allowed_origins: ["https://accounts.example"],
  username: "demo",
  password: "p",
};
const owner = { id: "owner-a" } as NonNullable<ReturnType<typeof useAuthStore.getState>["user"]>;
const stored: Secret = {
  id: "credential-a",
  name: "Demo login",
  description: null,
  kind: "browser_login",
  hint: "MUST-NOT-SHOW",
  owner_user_id: owner.id,
  can_edit: true,
};
function setup(ui: ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}
beforeEach(() => {
  useAuthStore.setState({ user: owner });
  useOrgStore.setState({ activeOrgId: "org-a" });
});
afterEach(() => {
  useAuthStore.setState({ user: null });
  useOrgStore.setState({ activeOrgId: null });
});

describe("browser credential dialogs", () => {
  it("creates a private personal login and accepts an exact short password", async () => {
    const submit = vi.fn().mockResolvedValue({});
    setup(
      <AddSecretDialog
        open
        onOpenChange={vi.fn()}
        kinds={[LOGIN, PROFILE]}
        kind="browser_login"
        initial={{ name: "Demo login", value: loginValue }}
        onSubmit={submit}
        isPending={false}
      />,
    );
    expect(screen.queryByRole("combobox", { name: "Who can use it" })).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Store key" }));
    expect(submit).toHaveBeenCalledWith({
      name: "Demo login",
      description: null,
      value: { kind: "browser_login", ...loginValue },
      purpose: "custom",
      visibility: "private",
      usage_scope: "personal",
    });
  });

  it("does not display a stored hint and rotates using only newly entered values", async () => {
    const submit = vi.fn().mockResolvedValue({});
    setup(
      <RotateSecretDialog
        secret={stored}
        onOpenChange={vi.fn()}
        kinds={[LOGIN]}
        onSubmit={submit}
        isPending={false}
      />,
    );
    expect(screen.queryByText(/MUST-NOT-SHOW/)).not.toBeInTheDocument();
    expect(screen.getByLabelText("Password")).toHaveValue("");
    await userEvent.type(
      screen.getByRole("textbox", { name: "Allowed origins" }),
      "https://accounts.example",
    );
    await userEvent.type(screen.getByLabelText("Username"), "new-user");
    await userEvent.type(screen.getByLabelText("Password"), " new password ");
    await userEvent.click(screen.getByRole("button", { name: "Rotate" }));
    expect(submit).toHaveBeenCalledWith({
      id: stored.id,
      value: {
        kind: "browser_login",
        allowed_origins: ["https://accounts.example"],
        username: "new-user",
        password: " new password ",
      },
    });
  });

  it.each(["account", "organization"] as const)(
    "clears typed values when the %s changes and ignores an old completion",
    async (boundary) => {
      let finish!: () => void;
      const submit = vi.fn(
        () =>
          new Promise<void>((resolve) => {
            finish = resolve;
          }),
      );
      const close = vi.fn();
      setup(
        <AddSecretDialog
          open
          onOpenChange={close}
          kinds={[LOGIN]}
          kind="browser_login"
          onSubmit={submit}
          isPending={false}
        />,
      );
      await userEvent.type(screen.getByRole("textbox", { name: "Name" }), "Private login");
      await userEvent.type(
        screen.getByRole("textbox", { name: "Allowed origins" }),
        "https://accounts.example",
      );
      await userEvent.type(screen.getByLabelText("Username"), "old-user");
      await userEvent.type(screen.getByLabelText("Password"), "old-password");
      await userEvent.click(screen.getByRole("button", { name: "Store key" }));
      await act(async () => {
        if (boundary === "account") useAuthStore.setState({ user: { ...owner, id: "owner-b" } });
        else useOrgStore.setState({ activeOrgId: "org-b" });
      });
      expect(screen.getByLabelText("Password")).toHaveValue("");
      await act(async () => finish());
      await waitFor(() => expect(close).not.toHaveBeenCalled());
    },
  );
});

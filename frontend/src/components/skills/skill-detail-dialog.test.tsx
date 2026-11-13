import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { apiClient } from "@/lib/api-client";
import type { Skill } from "@/types/providers";
import { SkillDetailDialog } from "./skill-detail-dialog";
import { DIALOG_CANVAS, DIALOG_FILL } from "@/lib/dialog-sizes";

vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), put: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/sharing/share-resource-button", () => ({ ShareResourceButton: () => null }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => false, isLoading: false }),
}));
const skill: Skill = {
  id: "s1",
  name: "returns",
  description: "Returns policy",
  content: "Return within 30 days.",
  category: null,
  version: 1,
  latest_version_id: "v1",
  can_edit: true,
  visibility: "org",
  owner_user_id: null,
  resources: [],
};

describe("skill editor loading", () => {
  it("keeps the editor canvas through metadata loading and permits dismissal", async () => {
    let resolve: (value: Skill) => void = () => {
      throw new Error("pending read not initialized");
    };
    const pending = new Promise<Skill>((done) => {
      resolve = done;
    });
    vi.mocked(apiClient.get).mockImplementation(async (path: string) =>
      path === "/skills/s1"
        ? pending
        : { items: [], total: 0, categories: [], suggested_categories: [] },
    );
    const onClose = vi.fn();
    const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
    render(<SkillDetailDialog id="s1" name="returns" canEdit onClose={onClose} />, {
      wrapper: ({ children }: { children: ReactNode }) => (
        <QueryClientProvider client={client}>{children}</QueryClientProvider>
      ),
    });
    const loading = screen.getByRole("dialog");
    expect(screen.getByRole("status")).toHaveAttribute("aria-busy", "true");
    for (const token of [...DIALOG_CANVAS.split(" "), ...DIALOG_FILL.split(" ")])
      expect(loading).toHaveClass(token);
    expect(screen.getByRole("heading", { name: "returns" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(onClose).toHaveBeenCalledOnce();
    resolve(skill);
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
    const editor = screen.getByRole("dialog");
    expect(editor).toBe(loading);
    for (const token of [...DIALOG_CANVAS.split(" "), ...DIALOG_FILL.split(" ")])
      expect(editor).toHaveClass(token);
    expect(screen.getByRole("button", { name: "Save" })).toBeVisible();
    await userEvent.click(screen.getByRole("button", { name: "Open full view" }));
  });
});

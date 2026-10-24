import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import ContextPage from "@/app/[locale]/(dashboard)/context/page";
import SkillsPage from "@/app/[locale]/(dashboard)/skills/page";
import VaultPage from "@/app/[locale]/(dashboard)/vault/page";
import { apiClient } from "@/lib/api-client";

const permissions = vi.hoisted(() => ({ create: false }));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({
    can: (permission: string) => !permission.endsWith(":edit") || permissions.create,
    isLoading: false,
    isLoaded: true,
    error: null,
  }),
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
}));

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
});

it.each(["context", "skill", "secret"] as const)(
  "uses a %s's effective actions when its role-level permission disagrees",
  async (kind) => {
    permissions.create = false;
    const row = {
      id: "r1",
      name: "Granted resource",
      description: "Description",
      can_edit: true,
      enabled: true,
      visibility: "private",
      size_bytes: 10,
      excerpt: "",
      format: "md",
      mode: "inject",
      category: null,
      file_count: 0,
      built_in: false,
      version: 1,
      resources: [],
      content: "Body",
      kind: "api_key",
      hint: "abcd",
      purpose: "custom",
      owner_user_id: "owner",
    };
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path.startsWith("/context?") || path.startsWith("/skills?") || path === "/secrets")
        return { items: [row], total: 1 };
      if (path === "/context/r1" || path === "/skills/r1") return row;
      return { items: [], total: 0 };
    });
    render(
      kind === "context" ? <ContextPage /> : kind === "skill" ? <SkillsPage /> : <VaultPage />,
      { wrapper },
    );
    expect(
      await screen.findByRole("button", { name: "Delete Granted resource" }),
    ).toBeInTheDocument();
    if (kind !== "secret") {
      await userEvent.click(screen.getByText("Granted resource"));
      expect(await screen.findByRole("button", { name: /^Save/ })).toBeInTheDocument();
    }
  },
);

it.each(["context", "skill", "secret"] as const)(
  "keeps a read-only %s readable without offering role-based writes",
  async (kind) => {
    permissions.create = true;
    const row = {
      id: "r1",
      name: "Read-only resource",
      description: "Description",
      can_edit: false,
      enabled: true,
      visibility: "private",
      size_bytes: 10,
      excerpt: "",
      format: "md",
      mode: "inject",
      category: null,
      file_count: 0,
      built_in: false,
      version: 1,
      resources: [],
      content: "Body",
      kind: "api_key",
      hint: "abcd",
      purpose: "custom",
      owner_user_id: "owner",
    };
    vi.mocked(apiClient.get).mockImplementation(async (path) => {
      if (path.startsWith("/context?") || path.startsWith("/skills?") || path === "/secrets")
        return { items: [row], total: 1 };
      if (path === "/context/r1" || path === "/skills/r1") return row;
      return { items: [], total: 0 };
    });
    render(
      kind === "context" ? <ContextPage /> : kind === "skill" ? <SkillsPage /> : <VaultPage />,
      { wrapper },
    );
    expect(await screen.findByText("Read-only resource")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Delete Read-only resource" })).toBeNull();
    if (kind !== "secret") {
      await userEvent.click(screen.getByText("Read-only resource"));
      expect((await screen.findAllByRole("button", { name: "Close" })).length).toBeGreaterThan(0);
      expect(screen.queryByRole("button", { name: /^Save/ })).toBeNull();
    }
  },
);

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { Suspense, type ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import ContextPage from "@/app/[locale]/(dashboard)/context/page";
import SkillPage from "@/app/[locale]/(dashboard)/skills/[id]/page";
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

/** A skill is edited from its own page; context files and secrets from their lists. */
/** A skill page reads its usage; the server always answers with every field. */
const USAGE = { days: 30, since: "", loads: 0, agents: [], hidden_agents: 0, hidden_loads: 0 };

async function renderPage(kind: "context" | "skill" | "secret") {
  await act(async () => {
    render(
      kind === "context" ? (
        <ContextPage />
      ) : kind === "skill" ? (
        <Suspense fallback={null}>
          <SkillPage params={Promise.resolve({ id: "r1" })} />
        </Suspense>
      ) : (
        <VaultPage />
      ),
      { wrapper },
    );
  });
}

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
      latest_version_id: "v1",
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
      if (path.startsWith("/skills/r1/usage")) return USAGE;
      return { items: [], total: 0 };
    });
    await renderPage(kind);
    if (kind !== "secret") {
      await userEvent.click(
        kind === "skill"
          ? await screen.findByRole("button", { name: "Edit" })
          : await screen.findByText("Granted resource"),
      );
      expect(await screen.findByRole("button", { name: /^Save/ })).toBeInTheDocument();
      await userEvent.click(
        screen.getByRole("button", { name: "More actions for Granted resource" }),
      );
      expect(await screen.findByRole("menuitem", { name: /Delete/ })).toBeInTheDocument();
    } else {
      expect(
        await screen.findByRole("button", { name: "Delete Granted resource" }),
      ).toBeInTheDocument();
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
      latest_version_id: "v1",
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
      if (path.startsWith("/skills/r1/usage")) return USAGE;
      return { items: [], total: 0 };
    });
    await renderPage(kind);
    expect((await screen.findAllByText("Read-only resource")).length).toBeGreaterThan(0);
    expect(screen.queryByRole("button", { name: "Delete Read-only resource" })).toBeNull();
    if (kind !== "secret") {
      await userEvent.click(
        kind === "skill"
          ? screen.getByRole("button", { name: "Open" })
          : screen.getAllByText("Read-only resource")[0]!,
      );
      expect((await screen.findAllByRole("button", { name: "Close" })).length).toBeGreaterThan(0);
      expect(screen.queryByRole("button", { name: /^Save/ })).toBeNull();
    }
  },
);

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, expect, it, vi } from "vitest";

import SkillsPage from "@/app/[locale]/(dashboard)/skills/page";
import { apiClient } from "@/lib/api-client";

let params = new URLSearchParams();

vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn(), replace: vi.fn() }),
  usePathname: () => "/skills",
  useSearchParams: () => params,
}));
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: () => true, isLoading: false, isLoaded: true, error: null }),
}));
vi.mock("@/lib/api-client", async (original) => ({
  ...(await original<typeof import("@/lib/api-client")>()),
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), put: vi.fn(), delete: vi.fn() },
}));
vi.mock("@/components/chat/markdown-content", () => ({
  MarkdownContent: ({ content }: { content: string }) => <div>{content}</div>,
}));

const SKILL = {
  id: "s9",
  name: "returns-policy",
  description: "How returns work",
  content: "Ask for the order number.",
  category: null,
  version: 3,
  visibility: "org",
  owner_user_id: null,
  resources: [],
};

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

beforeEach(() => {
  vi.clearAllMocks();
  params = new URLSearchParams("skill=s9");
  window.history.replaceState({}, "", "/skills?skill=s9");
});

function serving(skill: typeof SKILL & { can_edit?: boolean }) {
  vi.mocked(apiClient.get).mockImplementation(async (path) =>
    path === "/skills/s9" ? skill : { items: [], total: 0 },
  );
}

it("opens the skill another page links to, even when it is not on the page of the list", async () => {
  serving({ ...SKILL, can_edit: true });
  render(<SkillsPage />, { wrapper });

  expect(await screen.findByRole("dialog", { name: "returns-policy" })).toBeInTheDocument();
  expect(await screen.findByRole("button", { name: /^Save/ })).toBeInTheDocument();

  await userEvent.keyboard("{Escape}");
  expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  expect(window.location.search).toBe("");
});

it("opens a linked skill read only for a reader who may not edit it", async () => {
  serving(SKILL);
  render(<SkillsPage />, { wrapper });

  expect(await screen.findByRole("dialog", { name: "returns-policy" })).toBeInTheDocument();
  expect((await screen.findAllByRole("button", { name: "Close" })).length).toBeGreaterThan(0);
  expect(screen.queryByRole("button", { name: /^Save/ })).toBeNull();
});

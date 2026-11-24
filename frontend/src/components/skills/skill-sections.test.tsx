import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import userEvent from "@testing-library/user-event";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SkillSections } from "./skill-sections";
import type { SectionFilters } from "./skill-section-pages";
import type { SkillSection, SkillSummary } from "@/types/providers";
import { apiClient } from "@/lib/api-client";

vi.mock("@/lib/api-client", () => ({ apiClient: { get: vi.fn() } }));
// Its own spec covers the picker; a card here only has to be drawn.
vi.mock("@/components/agents/add-to-agent", () => ({ AddToAgent: () => null }));

function skill(name: string): SkillSummary {
  return {
    id: `id-${name}`,
    name,
    description: `What ${name} is for.`,
    category: null,
    visibility: "org",
    file_count: 0,
    built_in: false,
    excerpt: "",
  };
}

const SUPPORT = { id: "a1", name: "Support desk", slug: "support-desk" };

function section(
  overrides: Partial<SkillSection> & Pick<SkillSection, "key" | "kind">,
): SkillSection {
  return { count: 1, items: [skill(overrides.key)], ...overrides };
}

const FILTERS: SectionFilters = { search: "", categories: [], sort: "name", groupId: null };

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

function renderSections(sections: SkillSection[], onOpen = vi.fn()) {
  render(<SkillSections sections={sections} filters={FILTERS} onOpen={onOpen} />, { wrapper });
  return onOpen;
}

function block(title: string): HTMLElement {
  const heading = screen.getByText(title);
  const found = heading.closest("details");
  if (!found) throw new Error(`no section titled ${title}`);
  return found;
}

describe("SkillSections", () => {
  beforeEach(() => vi.clearAllMocks());

  it("names each section the way its kind reads, with its count", () => {
    renderSections([
      section({ key: "agent:a1", kind: "agent", agent: SUPPORT, count: 2 }),
      section({ key: "drafted", kind: "drafted" }),
      section({ key: "unused", kind: "unused" }),
      section({ key: "origin:org", kind: "org" }),
      section({ key: "origin:private", kind: "private" }),
      section({ key: "origin:platform", kind: "platform" }),
      section({ key: "origin:gallery:finance", kind: "gallery", industry: "finance" }),
      section({ key: "category:customer-support", kind: "category", category: "customer-support" }),
      section({ key: "category:", kind: "uncategorized" }),
    ]);

    for (const title of [
      "Support desk",
      "Drafted only",
      "Not used by an agent you can see",
      "Organization",
      "Private",
      "Built-in · Platform",
      "Built-in · Finance and insurance",
      "Customer support",
      "Uncategorized",
    ]) {
      expect(block(title)).toHaveAttribute("open");
    }
    expect(within(block("Support desk")).getByText("2 skills")).toBeInTheDocument();
    expect(within(block("Drafted only")).getByText("1 skill")).toBeInTheDocument();
  });

  it("opens a skill from its card", async () => {
    const onOpen = renderSections([section({ key: "unused", kind: "unused" })]);

    await userEvent.click(screen.getByRole("button", { name: /unused/ }));

    expect(onOpen).toHaveBeenCalledWith("id-unused");
  });

  it("folds a section closed and keeps it so", () => {
    renderSections([section({ key: "unused", kind: "unused" })]);
    const details = block("Not used by an agent you can see") as HTMLDetailsElement;

    details.open = false;
    fireEvent(details, new Event("toggle"));

    expect(details).not.toHaveAttribute("open");
  });

  it("offers no more when a section already shows every card", () => {
    renderSections([section({ key: "unused", kind: "unused" })]);

    expect(screen.queryByRole("button", { name: /Show all/ })).not.toBeInTheDocument();
  });

  it("pages through the rest of a section under the same filters, and folds back", async () => {
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [skill("refunds"), skill("tone")],
      total: 2,
      categories: [],
      suggested_categories: [],
    });
    renderSections([
      section({
        key: "agent:a1",
        kind: "agent",
        agent: SUPPORT,
        count: 2,
        items: [skill("refunds")],
      }),
    ]);

    await userEvent.click(screen.getByRole("button", { name: "Show all 2" }));

    expect(await screen.findByText("tone")).toBeInTheDocument();
    expect(apiClient.get).toHaveBeenCalledWith(
      "/skills?sort=name&skip=0&limit=50&section=agent%3Aa1",
    );
    await userEvent.click(screen.getByRole("button", { name: "Show fewer" }));
    expect(screen.queryByText("tone")).not.toBeInTheDocument();
  });

  it("says when a section's pages could not be read, and tries again", async () => {
    vi.mocked(apiClient.get)
      .mockRejectedValueOnce(new Error("boom"))
      .mockResolvedValue({ items: [skill("tone")], total: 2, categories: [] });
    renderSections([section({ key: "unused", kind: "unused", count: 2 })]);

    await userEvent.click(screen.getByRole("button", { name: "Show all 2" }));
    await userEvent.click(await screen.findByRole("button", { name: "Retry" }));

    await waitFor(() => expect(screen.getByText("tone")).toBeInTheDocument());
  });
});

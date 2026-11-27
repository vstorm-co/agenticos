import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import {
  getMemoryInboxDecisions,
  getMemoryInboxRule,
  getMemoryObjectBackfill,
  runMemoryObjectBackfill,
  setMemoryInboxRule,
} from "@/lib/memory-api";
import { MemoryOperations } from "./memory-operations";

vi.mock("next-intl", () => ({ useTranslations: () => (key: string) => key }));
vi.mock("@/hooks/use-members", () => ({ useMembers: () => ({ members: [], error: null }) }));
vi.mock("@/components/orgs/member-picker", () => ({
  MemberPicker: ({ onToggle }: { onToggle: (id: string) => void }) => (
    <button type="button" onClick={() => onToggle("reviewer")}>
      Select reviewer
    </button>
  ),
}));
vi.mock("@/lib/memory-api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/memory-api")>()),
  getMemoryInboxDecisions: vi.fn(),
  getMemoryInboxRule: vi.fn(),
  getMemoryObjectBackfill: vi.fn(),
  runMemoryObjectBackfill: vi.fn(),
  setMemoryInboxRule: vi.fn(),
}));

it("saves a reviewed shadow rule and resumes the existing backfill", async () => {
  vi.mocked(getMemoryInboxRule).mockResolvedValue({
    version: 6,
    mode: "off",
    sources: ["gmail"],
    recipient_ids: [],
    include_review: false,
  });
  vi.mocked(getMemoryInboxDecisions).mockResolvedValue([]);
  const paused = { cutoff: "2026-11-27T00:00:00Z", completed_at: null, scanned: 200, linked: 3 };
  vi.mocked(getMemoryObjectBackfill).mockResolvedValue(paused);
  vi.mocked(runMemoryObjectBackfill).mockResolvedValue(paused);
  vi.mocked(setMemoryInboxRule).mockImplementation(async (rule) => ({ ...rule, version: 7 }));

  const user = userEvent.setup();
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  render(
    <QueryClientProvider client={query}>
      <MemoryOperations />
    </QueryClientProvider>,
  );

  await user.selectOptions(await screen.findByRole("combobox", { name: "modeLabel" }), "shadow");
  expect(screen.getByRole("button", { name: "save" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Select reviewer" }));
  await user.click(screen.getByRole("checkbox", { name: "includeReview" }));
  await user.click(screen.getByRole("button", { name: "save" }));
  expect(setMemoryInboxRule).toHaveBeenCalledWith(
    {
      version: 6,
      mode: "shadow",
      sources: ["gmail"],
      recipient_ids: ["reviewer"],
      include_review: true,
    },
    expect.anything(),
  );
  await user.click(await screen.findByRole("button", { name: "resume" }));
  expect(runMemoryObjectBackfill).toHaveBeenCalledWith(false, expect.anything());
});

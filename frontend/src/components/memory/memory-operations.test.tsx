import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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
  MemberPicker: ({
    onToggle,
    label,
    selected,
  }: {
    onToggle: (id: string) => void;
    label: (count: number) => string;
    selected: string[];
  }) => (
    <button type="button" aria-label="Select reviewer" onClick={() => onToggle("reviewer")}>
      {label(selected.length)}
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

function mount() {
  const query = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={query}>
      <MemoryOperations />
    </QueryClientProvider>,
  );
}

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
  mount();

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

it("refreshes a stale rule and reads outcomes from a chosen version", async () => {
  const rule = {
    version: 6,
    mode: "live",
    sources: ["gmail"],
    recipient_ids: ["reviewer"],
    include_review: false,
  } as const;
  vi.mocked(getMemoryInboxRule)
    .mockResolvedValue({ ...rule, sources: ["gmail"], recipient_ids: ["reviewer"] })
    .mockResolvedValueOnce({ ...rule, sources: ["gmail"], recipient_ids: ["reviewer"] });
  vi.mocked(getMemoryInboxDecisions).mockResolvedValue([
    { change: "review", outcome: "shadow", count: 2 },
  ]);
  vi.mocked(getMemoryObjectBackfill).mockResolvedValue(null);
  vi.mocked(setMemoryInboxRule).mockRejectedValueOnce(new Error("stale version"));
  mount();
  const user = userEvent.setup();
  const version = await screen.findByRole("spinbutton", { name: "version" });
  fireEvent.change(version, { target: { value: "5" } });
  expect(await screen.findByText("outcome")).toBeVisible();
  expect(getMemoryInboxDecisions).toHaveBeenCalledWith(5);
  await user.click(screen.getByRole("button", { name: "reload" }));
  await waitFor(() => expect(getMemoryInboxDecisions).toHaveBeenLastCalledWith(5));

  await user.click(screen.getByRole("checkbox", { name: "webhook" }));
  await user.click(screen.getByRole("checkbox", { name: "gmail" }));
  await user.click(screen.getByRole("button", { name: "Select reviewer" }));
  expect(screen.getByRole("button", { name: "save" })).toBeDisabled();
  await user.click(screen.getByRole("button", { name: "Select reviewer" }));
  await user.click(screen.getByRole("button", { name: "save" }));
  expect(await screen.findByRole("alert")).toHaveTextContent("saveFailed");
  await user.click(screen.getAllByRole("button", { name: "reload" })[0]!);
  await waitFor(() => expect(screen.queryByText("saveFailed")).toBeNull());
  expect(setMemoryInboxRule).toHaveBeenCalledWith(
    expect.objectContaining({ sources: ["webhook"] }),
    expect.anything(),
  );
});

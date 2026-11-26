import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  amendHistoricalClaim,
  getMemoryClaimDetail,
  getMemoryObjects,
  getMemoryTimeline,
  getSharedClaims,
  resolveSharedMemoryConflict,
  type MemoryClaim,
} from "@/lib/memory-api";
import { MemoryObjectLibrary, SharedMemoryClaims } from "./memory-object-library";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: () => "1 Jul 2020" }),
}));
const scopeOf = vi.fn();

vi.mock("@/hooks/use-permissions", () => ({ usePermissions: () => ({ scopeOf }) }));
vi.mock("@/lib/memory-api", () => ({
  amendHistoricalClaim: vi.fn(),
  getMemoryObjects: vi.fn(),
  getMemoryTimeline: vi.fn(),
  getMemoryClaimDetail: vi.fn(),
  getSharedClaims: vi.fn(),
  resolveSharedMemoryConflict: vi.fn(),
  getSharedNotes: vi.fn(),
}));

describe("company memory objects", () => {
  it("opens a business project and uses independent effective and knowledge dates", async () => {
    const project = { id: "xyz", kind: "project", name: "XYZ" } as const;
    vi.mocked(getMemoryObjects).mockResolvedValue({ items: [project], next_cursor: null });
    vi.mocked(getMemoryTimeline).mockResolvedValue({
      object: project,
      items: [],
      next_cursor: null,
    });
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryObjectLibrary library="organization" />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByRole("button", { name: /XYZ/ }));
    const effective = screen.getByLabelText("effectiveDate");
    const knowledge = screen.getByLabelText("knowledgeDate");
    expect(knowledge).toBeDisabled();
    fireEvent.change(effective, { target: { value: "2020-07-01" } });
    fireEvent.change(knowledge, { target: { value: "2026-11-15" } });
    await waitFor(() =>
      expect(getMemoryTimeline).toHaveBeenLastCalledWith(
        "organization",
        "xyz",
        "2020-07-01",
        "2026-11-15",
        null,
      ),
    );
  });

  it("amends one historical observation without changing its dates", async () => {
    const object = { id: "atlas", kind: "company", name: "Atlas" } as const;
    const claim: MemoryClaim = {
      id: "headcount",
      agent_id: null,
      agent_name: null,
      scope: "profile",
      subject: "headcount",
      statement: "20 employees",
      kind: "fact",
      origin: "agent",
      status: "superseded",
      observed_at: "2020-07-01T00:00:00Z",
      effective_from: "2020-07-01T00:00:00Z",
      effective_to: "2020-07-02T00:00:00Z",
      supersedes_id: null,
      derived_from_count: 0,
    };
    vi.mocked(getMemoryTimeline).mockResolvedValue({ object, items: [claim], next_cursor: null });
    vi.mocked(getMemoryClaimDetail).mockResolvedValue({
      ...claim,
      evidence: [],
      sources: [],
      superseded: null,
      withheld: 0,
      conflicts: [],
    });
    vi.mocked(amendHistoricalClaim).mockResolvedValue({ ...claim, statement: "22 employees" });
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <MemoryObjectLibrary library="personal" initialObject={object.id} />
      </QueryClientProvider>,
    );
    const user = userEvent.setup();
    await user.click(await screen.findByText(claim.statement));
    await user.click(await screen.findByRole("button", { name: "correct" }));
    const statement = screen.getByRole("textbox", { name: "statement" });
    await user.clear(statement);
    await user.type(statement, "22 employees");
    await user.click(screen.getByRole("button", { name: "save" }));
    await waitFor(() =>
      expect(amendHistoricalClaim).toHaveBeenCalledWith(claim.id, "22 employees", undefined),
    );
  });
});

describe("shared memory conflicts", () => {
  const mail: MemoryClaim = {
    id: "mail-deadline",
    object_id: "xyz",
    agent_id: null,
    agent_name: null,
    scope: "organization",
    subject: "deadline",
    statement: "Gmail says December 1",
    kind: "fact",
    origin: "agent",
    status: "disputed",
    observed_at: "2026-10-01T00:00:00Z",
    effective_from: "2026-10-01T00:00:00Z",
    effective_to: null,
    supersedes_id: null,
    derived_from_count: 0,
  };
  const published = { ...mail, id: "reviewed-chat", statement: "Chat says December 2" };

  function showConflict(permission: "all" | undefined) {
    scopeOf.mockReturnValue(permission);
    vi.mocked(getSharedClaims).mockResolvedValue({ items: [mail], total: 1 });
    vi.mocked(getMemoryClaimDetail).mockResolvedValue({
      ...mail,
      evidence: [],
      sources: [],
      superseded: null,
      withheld: 0,
      conflicts: [mail, published],
    });
    render(
      <QueryClientProvider
        client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
      >
        <SharedMemoryClaims />
      </QueryClientProvider>,
    );
  }

  it("filters disputes and only submits a value when the editor confirms", async () => {
    showConflict("all");
    vi.mocked(resolveSharedMemoryConflict).mockResolvedValue({ ...published, status: "current" });
    const user = userEvent.setup();
    await user.click(screen.getByRole("checkbox", { name: "conflictsOnly" }));
    await waitFor(() => expect(getSharedClaims).toHaveBeenLastCalledWith("", 0, true));
    await user.click(await screen.findByText(mail.statement));
    await user.click(await screen.findByRole("radio", { name: published.statement }));
    expect(resolveSharedMemoryConflict).not.toHaveBeenCalled();
    await user.click(screen.getByRole("button", { name: "conflictConfirm" }));
    await waitFor(() =>
      expect(resolveSharedMemoryConflict).toHaveBeenCalledWith(published.id, [
        mail.id,
        published.id,
      ]),
    );
  });

  it("shows a pending dispute without the decision form to a reader", async () => {
    showConflict(undefined);
    const user = userEvent.setup();
    await user.click(await screen.findByText(mail.statement));
    expect(await screen.findByText("conflictPending")).toBeVisible();
    expect(screen.queryByRole("button", { name: "conflictConfirm" })).toBeNull();
  });
});

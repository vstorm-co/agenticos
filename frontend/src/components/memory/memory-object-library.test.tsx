import type { ReactNode } from "react";
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
  getSharedNotes,
  resolveSharedMemoryConflict,
  type MemoryClaim,
} from "@/lib/memory-api";
import { ApiError } from "@/lib/api-error";
import { toast } from "sonner";
import {
  ClaimSources,
  MemoryObjectLibrary,
  SharedMemoryClaims,
  SharedMemoryNotes,
} from "./memory-object-library";

vi.mock("next-intl", () => ({
  useTranslations: () => (key: string) => key,
  useFormatter: () => ({ dateTime: () => "1 Jul 2020" }),
}));
const scopeOf = vi.fn();
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function mount(element: ReactNode) {
  return render(
    <QueryClientProvider
      client={new QueryClient({ defaultOptions: { queries: { retry: false } } })}
    >
      {element}
    </QueryClientProvider>,
  );
}

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
    fireEvent.change(effective, { target: { value: "" } });
    expect(knowledge).toHaveValue("");
    await user.click(screen.getByRole("button", { name: "back" }));
    expect(await screen.findByRole("button", { name: /XYZ/ })).toBeVisible();
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
    vi.mocked(amendHistoricalClaim)
      .mockRejectedValueOnce(new Error("Conflict"))
      .mockResolvedValue({ ...claim, statement: "22 employees" });
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
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected");
    await user.click(screen.getByRole("button", { name: "cancel" }));
    await user.click(screen.getByRole("button", { name: "correct" }));
    const revised = screen.getByRole("textbox", { name: "statement" });
    await user.clear(revised);
    await user.type(revised, "22 employees");
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

  it("refreshes a stale conflict and shows a normal submission error without dropping the candidate", async () => {
    showConflict("all");
    vi.mocked(resolveSharedMemoryConflict)
      .mockRejectedValueOnce(new ApiError(409, "Conflict"))
      .mockRejectedValueOnce(new Error("Unavailable"));
    const user = userEvent.setup();
    await user.click(await screen.findByText(mail.statement));
    await user.click(await screen.findByRole("radio", { name: published.statement }));
    await user.click(screen.getByRole("button", { name: "conflictConfirm" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("conflictChanged"));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: "conflictConfirm" })).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: "conflictConfirm" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("unexpected");
  });

  it("displays the readable sources and previous assertion as well as the withheld marker", async () => {
    vi.mocked(getMemoryClaimDetail).mockResolvedValue({
      ...mail,
      evidence: [
        {
          kind: "gmail",
          source_id: "gmail-1",
          quote: "Deadline line",
          occurred_at: mail.observed_at,
        },
        {
          kind: "webhook",
          source_id: "crm-1",
          quote: "CRM property",
          occurred_at: mail.observed_at,
        },
        {
          kind: "message",
          source_id: "message-1",
          quote: "Member words",
          occurred_at: mail.observed_at,
        },
      ],
      sources: [published],
      superseded: { ...published, id: "earlier" },
      withheld: 1,
      conflicts: [],
    });
    mount(<ClaimSources library="organization" claimId={mail.id} />);
    expect(await screen.findByText("gmailSource")).toBeVisible();
    for (const label of [
      "webhookSource",
      "message-1",
      "withheld",
      "previous",
      published.statement,
    ]) {
      expect(screen.getByText(label)).toBeVisible();
    }
  });
});

it("browses, filters and pages business objects, then shows a timeline error", async () => {
  const item = { id: "atlas", name: "Atlas", kind: "company" } as const;
  vi.mocked(getMemoryObjects).mockImplementation(async (_library, q, _kind, cursor) => {
    if (q === "bad") throw new Error("Unavailable");
    return {
      items: q === "missing" || cursor ? [] : [item],
      next_cursor: q || cursor ? null : "next",
    };
  });
  vi.mocked(getMemoryTimeline).mockRejectedValue(new Error("Unavailable"));
  const user = userEvent.setup();
  mount(<MemoryObjectLibrary library="organization" />);
  await user.click(await screen.findByRole("button", { name: "nextPage" }));
  expect(await screen.findByText("emptyObjects")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "firstPage" }));
  await user.click(screen.getByRole("button", { name: "kind.company" }));
  const input = screen.getByPlaceholderText("searchObjects");
  fireEvent.change(input, { target: { value: "bad" } });
  expect(await screen.findByRole("alert")).toBeVisible();
  fireEvent.change(input, { target: { value: "" } });
  await user.click(await screen.findByRole("button", { name: /Atlas/ }));
  expect(await screen.findByRole("alert")).toBeVisible();
});

it("loads shared notes by cursor and handles empty and unavailable pages", async () => {
  const user = userEvent.setup();
  vi.mocked(getSharedNotes)
    .mockResolvedValueOnce({
      items: [{ id: "note", name: "Handoff", content: "Reviewed text" }],
      next_cursor: "page-2",
    })
    .mockResolvedValueOnce({ items: [], next_cursor: null });
  const listing = mount(<SharedMemoryNotes />);
  await user.click(await screen.findByText("Handoff"));
  expect(screen.getByText("Reviewed text")).toBeVisible();
  await user.click(screen.getByRole("button", { name: "nextPage" }));
  expect(await screen.findByText("emptyNotes")).toBeVisible();
  listing.unmount();
  vi.mocked(getSharedNotes).mockRejectedValueOnce(new Error("Unavailable"));
  mount(<SharedMemoryNotes />);
  expect(await screen.findByRole("alert")).toBeVisible();
});

it("keeps the shared claim search separate from an unavailable source", async () => {
  vi.mocked(getSharedClaims).mockImplementation(async (q) => {
    if (q) throw new Error("Unavailable");
    return { items: [], total: 0 };
  });
  mount(<SharedMemoryClaims />);
  expect(await screen.findByText("emptyClaims")).toBeVisible();
  fireEvent.change(screen.getByPlaceholderText("searchShared"), { target: { value: "Atlas" } });
  expect(await screen.findByRole("alert")).toBeVisible();
});

it("labels a dated timeline as historical and reports unavailable evidence", async () => {
  const item = { id: "commitment", name: "XYZ handoff", kind: "commitment" } as const;
  const record: MemoryClaim = {
    id: "one",
    agent_id: null,
    agent_name: null,
    scope: "organization",
    subject: "deadline",
    statement: "Historical deadline",
    kind: "fact",
    origin: "agent",
    status: "current",
    observed_at: "2020-07-01T00:00:00Z",
    effective_from: "2020-07-01T00:00:00Z",
    effective_to: null,
    supersedes_id: null,
    derived_from_count: 0,
  };
  vi.mocked(getMemoryTimeline).mockResolvedValue({
    object: item,
    items: [record],
    next_cursor: null,
  });
  vi.mocked(getMemoryClaimDetail).mockRejectedValue(new Error("Unavailable"));
  mount(<MemoryObjectLibrary library="organization" initialObject={item.id} />);
  fireEvent.change(screen.getByLabelText("effectiveDate"), { target: { value: "2020-07-01" } });
  const user = userEvent.setup();
  await user.click(await screen.findByText(record.statement));
  expect(screen.getByText(/historical/i, { selector: "p" })).toBeVisible();
  expect(await screen.findByText("evidenceUnavailable")).toBeVisible();
});

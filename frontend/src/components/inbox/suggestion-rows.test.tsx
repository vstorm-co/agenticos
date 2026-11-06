import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SuggestionRows } from "./suggestion-rows";
import type { Suggestion } from "@/lib/suggestions-api";

/**
 * The inbox's rows (#2301): urgent first, where each came from and when, what it
 * is about, and the same answers the chat's cards give - in the row.
 */

const state = vi.hoisted(() => ({
  accept: vi.fn(),
  dismiss: vi.fn(),
  dialogs: 0,
  catalogLoading: false,
}));

vi.mock("@/hooks/use-suggestions", () => ({
  useSuggestions: () => ({ suggestions: [], accept: state.accept, dismiss: state.dismiss }),
}));
vi.mock("@/hooks", () => ({
  useMcpCatalog: () => ({
    servers: state.catalogLoading
      ? []
      : [{ key: "linear", name: "Linear", icon: "linear", url: null }],
    isLoading: state.catalogLoading,
  }),
}));
vi.mock("@/components/triggers/trigger-form-dialog", () => ({
  TriggerFormDialog: ({ onCreated }: { onCreated?: () => void }) => {
    state.dialogs += 1;
    return (
      <div role="dialog">
        <button type="button" onClick={() => onCreated?.()}>
          create
        </button>
      </div>
    );
  },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

function item(id: string, overrides: Partial<Suggestion> = {}): Suggestion {
  return {
    id,
    kind: "routine",
    status: "open",
    title: `Title ${id}`,
    detail: null,
    payload: {},
    created_at: new Date().toISOString(),
    ...overrides,
  };
}

beforeEach(() => {
  state.catalogLoading = false;
  state.accept.mockReset().mockResolvedValue(undefined);
  state.dismiss.mockReset().mockResolvedValue(undefined);
  state.dialogs = 0;
});

describe("SuggestionRows", () => {
  it("keeps full Inbox content and its actions available", async () => {
    render(
      <SuggestionRows
        expandedDetails
        items={[
          item("selected", {
            kind: "finding",
            detail: "Full context and the requested next step.",
          }),
        ]}
      />,
    );
    expect(screen.getByText("Full context and the requested next step.")).not.toHaveClass(
      "line-clamp-2",
    );
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(state.accept).toHaveBeenCalledWith("selected");
  });
  it("keeps an acknowledged finding actionable and labels its shared state", () => {
    render(
      <SuggestionRows items={[item("ack", { kind: "finding", outcome_status: "acknowledged" })]} />,
    );
    expect(screen.getByText("Acknowledged")).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Done" })).toBeEnabled();
  });
  it("leads with what cannot wait and says where each came from", () => {
    render(
      <SuggestionRows
        items={[
          item("idea", { detail: "You asked for it four times" }),
          item("eng", {
            kind: "finding",
            urgent: true,
            payload: { server: "linear", url: "https://linear.app/x/ENG-1" },
          }),
          item("own", { kind: "finding", payload: { server: "intranet" } }),
        ]}
      />,
    );

    const rows = screen.getAllByRole("listitem");
    expect(rows.map((row) => row.getAttribute("aria-label"))).toEqual([
      "Title eng",
      "Title idea",
      "Title own",
    ]);
    expect(rows[0]).toHaveTextContent("Urgent");
    expect(rows[0]).toHaveTextContent("Linear · just now");
    expect(within(rows[0]!).getByRole("link", { name: "Title eng" })).toHaveAttribute(
      "href",
      "https://linear.app/x/ENG-1",
    );
    expect(rows[1]).toHaveTextContent("Routine idea · just now");
    expect(screen.getByText("You asked for it four times")).toHaveClass("line-clamp-2");
    // A watch on a server the catalog does not know is still a watch.
    expect(rows[2]).toHaveTextContent("Routine · just now");
    expect(within(rows[2]!).queryByRole("link")).toBeNull();
  });

  it("answers in the row, and keeps one line of detail when dense", async () => {
    render(<SuggestionRows items={[item("idea", { detail: "Why" })]} dense />);

    expect(screen.getByText("Why")).toHaveClass("line-clamp-1");
    await userEvent.click(screen.getByRole("button", { name: "Set it up" }));
    expect(state.dialogs).toBeGreaterThan(0);
    expect(state.accept).not.toHaveBeenCalled();
    await userEvent.click(screen.getByRole("button", { name: "create" }));
    expect(state.accept).toHaveBeenCalledWith("idea");
    await userEvent.click(screen.getByRole("button", { name: "Not now" }));
    expect(state.dismiss).toHaveBeenCalledWith("idea");
  });
});

it.each([
  "javascript:alert(1)",
  "data:text/html,unsafe",
  "/relative",
  "not a URL",
  "https://user:password@example.com",
])("does not turn an unsafe source URL into a clickable title: %s", (url) => {
  render(<SuggestionRows items={[item("unsafe", { kind: "finding", payload: { url } })]} />);
  expect(screen.queryByRole("link", { name: "Title unsafe" })).not.toBeInTheDocument();
  expect(screen.getByText("Title unsafe")).toBeInTheDocument();
});

it("opens an internal web service over HTTP as well", () => {
  render(
    <SuggestionRows
      items={[
        item("internal", { kind: "finding", payload: { url: "http://intranet.example/task/1" } }),
      ]}
    />,
  );
  expect(screen.getByRole("link", { name: "Title internal" })).toHaveAttribute(
    "href",
    "http://intranet.example/task/1",
  );
});

it("opens the working chat without marking its draft as completed", async () => {
  const chat = "00000000-0000-4000-8000-000000000123";
  render(
    <SuggestionRows
      items={[item("draft", { kind: "finding", payload: { conversation_id: chat } })]}
    />,
  );
  expect(screen.getByRole("link", { name: "Open conversation" })).toHaveAttribute(
    "href",
    `/chat?id=${chat}`,
  );
  expect(state.accept).not.toHaveBeenCalled();
});

it("does not turn a malformed working chat reference into a navigation link", () => {
  render(
    <SuggestionRows
      items={[
        item("bad", { kind: "finding", payload: { conversation_id: "https://evil.example" } }),
      ]}
    />,
  );
  expect(screen.queryByRole("link", { name: "Open conversation" })).toBeNull();
});

it("links task titles to their table without a separate Open table action", () => {
  const table = "00000000-0000-4000-8000-000000000123";
  render(
    <SuggestionRows items={[item("task", { kind: "finding", payload: { table_id: table } })]} />,
  );
  const link = screen.getByRole("link", { name: "Title task" });
  expect(link).toHaveAttribute("href", `/tables/${table}`);
  expect(link).not.toHaveAttribute("target");
  expect(screen.queryByText("Open table")).not.toBeInTheDocument();
});

it("reserves source metadata instead of painting a temporary routine label", () => {
  state.catalogLoading = true;
  const finding = item("loading-source", { kind: "finding", payload: { server: "linear" } });
  const view = render(<SuggestionRows items={[finding]} />);
  const row = screen.getByRole("listitem", { name: finding.title });
  expect(row.querySelector(".animate-pulse")).not.toBeNull();
  expect(row).not.toHaveTextContent("Routine");
  state.catalogLoading = false;
  view.rerender(<SuggestionRows items={[finding]} />);
  expect(row).toHaveTextContent("Linear");
});

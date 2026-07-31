import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CreateSkillDialog } from "./create-skill-dialog";
import { apiClient } from "@/lib/api-client";
import { ApiError } from "@/lib/api-error";

vi.mock("@/lib/api-client", () => ({
  apiClient: { get: vi.fn(), post: vi.fn(), patch: vi.fn(), delete: vi.fn() },
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

import { toast } from "sonner";

function wrapper({ children }: { children: ReactNode }) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

const TAKEN =
  "A skill named 'refund-policy' already exists. The name is how a model refers to a skill and cannot be changed afterwards, so choose a different one - or open the existing skill and edit it, which reaches every agent bound to it.";

const NAME_TAKEN = new ApiError(409, TAKEN, {
  error: { code: "ALREADY_EXISTS", message: TAKEN, details: { name: "refund-policy" } },
});

const name = () => screen.getByLabelText("Name");
const description = () => screen.getByLabelText("Description");
// The body is SKILL.md in the file pane, as the workbench has it - editable
// only once the pane is flipped to Source.
const content = () => screen.getByLabelText("SKILL.md source");
const create = () => screen.getByRole("button", { name: "Create" });

async function fill() {
  await userEvent.type(name(), "refund-policy");
  await userEvent.type(description(), "How refunds work.");
  await userEvent.click(screen.getByRole("button", { name: "Source" }));
  await userEvent.type(content(), "## Refunds");
}

describe("CreateSkillDialog", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(apiClient.get).mockResolvedValue({
      items: [],
      total: 0,
      categories: ["ops-notes"],
      suggested_categories: ["marketing", "devops"],
    });
    render(<CreateSkillDialog open onOpenChange={vi.fn()} />, { wrapper });
  });

  it("lays the body out as SKILL.md, the way the editor will show it forever after", async () => {
    // The create form used to be the only place a skill did not look like a
    // folder. The second time anybody saw their skill it looked nothing like
    // the first - same tree, same pane, from the start.
    // Twice: once in the tree, once naming the open pane.
    expect(screen.getAllByText("SKILL.md")).toHaveLength(2);
    expect(screen.getByRole("button", { name: "Preview" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Source" })).toBeInTheDocument();
  });

  it("offers the shelves in use and the predefined ones, without constraining the field", async () => {
    // A select, so the list that already exists is visible before anybody
    // types - that is what keeps twenty skills off nineteen spellings of one
    // shelf. "New category…" is the way out: a category is the organization's
    // word, and anything typed stays as valid as anything picked.
    // Labels, not slugs: the stored value stays `ops-notes`, the reader sees
    // "Ops notes".
    await userEvent.click(screen.getByLabelText("Category"));
    expect(await screen.findByRole("option", { name: "Ops notes" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Marketing" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Devops" })).toBeInTheDocument();

    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), "something-nobody-suggested");
    expect(screen.getByLabelText("Category")).toHaveValue("something-nobody-suggested");
  });

  it("keeps the whole draft when the name is taken", async () => {
    // Content is a ten row editor. Losing it - or making somebody re-open a
    // dialog to find out what a toast said - is the cost of treating an
    // expected refusal as a failure.
    vi.mocked(apiClient.post).mockRejectedValue(NAME_TAKEN);
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(name()).toHaveAttribute("aria-invalid", "true"));
    expect(screen.getByText(TAKEN)).toBeInTheDocument();
    expect(content()).toHaveValue("## Refunds");
    expect(toast.error).not.toHaveBeenCalled();
  });

  it("tells the reader both ways out, in the server's own words", async () => {
    // The message is the product. A refusal that only states the fact leaves
    // somebody guessing whether a second skill or an edit is what they wanted.
    vi.mocked(apiClient.post).mockRejectedValue(NAME_TAKEN);
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(screen.getByText(TAKEN)).toBeInTheDocument());
    expect(screen.getByText(TAKEN)).toHaveTextContent("choose a different one");
    expect(screen.getByText(TAKEN)).toHaveTextContent("edit it");
  });

  it("puts a rejected length on the field it was rejected for", async () => {
    vi.mocked(apiClient.post).mockRejectedValue(
      new ApiError(422, "…", {
        error: {
          code: "VALIDATION_ERROR",
          message: "description: String should have at most 500 characters",
          details: {
            fields: [
              { field: "description", message: "String should have at most 500 characters" },
            ],
          },
        },
      }),
    );
    await fill();
    await userEvent.click(create());

    await waitFor(() => expect(description()).toHaveAttribute("aria-invalid", "true"));
    expect(name()).not.toHaveAttribute("aria-invalid", "true");
  });

  it("does not let an over-long name leave the browser", async () => {
    expect(name()).toHaveAttribute("maxLength", "64");
    expect(description()).toHaveAttribute("maxLength", "500");
    // The category cap lives on the free-text field behind "New category…" -
    // the select's own options are already-valid names.
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    expect(screen.getByLabelText("Category")).toHaveAttribute("maxLength", "64");
  });

  it("sends the category when one was picked", async () => {
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s1", name: "refund-policy" });
    await fill();
    await userEvent.click(screen.getByLabelText("Category"));
    await userEvent.click(screen.getByRole("option", { name: "New category…" }));
    await userEvent.type(screen.getByLabelText("Category"), "support");
    await userEvent.click(create());

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/skills",
        expect.objectContaining({ category: "support" }),
      ),
    );
  });

  it("sends no category rather than an empty one when the field is left blank", async () => {
    // "" is a category the backend refuses; a skill without one is
    // uncategorized, which is null.
    vi.mocked(apiClient.post).mockResolvedValue({ id: "s1", name: "refund-policy" });
    await fill();
    await userEvent.click(create());

    await waitFor(() =>
      expect(apiClient.post).toHaveBeenCalledWith(
        "/skills",
        expect.objectContaining({ category: null }),
      ),
    );
  });
});

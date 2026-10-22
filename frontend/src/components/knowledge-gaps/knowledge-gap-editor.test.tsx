import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ApiError } from "@/lib/api-error";
import type { KnowledgeGapDraft, KnowledgeGapTopicDetail } from "@/types/knowledge-gaps";
import { blanksIn, KnowledgeGapEditor } from "./knowledge-gap-editor";

const state = vi.hoisted(() => ({
  save: vi.fn(),
  add: vi.fn(),
  reset: vi.fn(),
  addError: null as unknown,
  pending: false,
}));
vi.mock("@/hooks/use-knowledge-gaps", async (original) => ({
  ...(await original<typeof import("@/hooks/use-knowledge-gaps")>()),
  useSaveKnowledgeGapContent: () => ({ mutate: state.save, isPending: state.pending }),
  useAddKnowledgeGapContent: () => ({
    mutate: state.add,
    reset: state.reset,
    isPending: false,
    error: state.addError,
  }),
}));
vi.mock("./knowledge-gap-draft-meta", () => ({
  KnowledgeGapDraftMeta: ({ draft }: { draft: { title: string } }) => (
    <p>{`meta ${draft.title}`}</p>
  ),
}));

const TOPIC: KnowledgeGapTopicDetail = {
  id: "t1",
  knowledge_base_id: "kb1",
  knowledge_base_name: "Handbook",
  status: "open",
  label: "visitor parking",
  question_count: 2,
  asker_count: 2,
  last_asked_at: "2026-10-12T09:00:00Z",
  examples: [],
  agents: [],
  dismissed_at: null,
  covered_at: null,
  covered_by: null,
  has_draft: false,
  can_edit: true,
  questions: [],
  draft: null,
};

const DRAFT: KnowledgeGapDraft = {
  title: "Visitor parking",
  content: "Visitors park on level {{level}}.",
  sources: [],
  unverified: 0,
  drafted_at: "2026-10-12T10:00:00Z",
  run_id: "r1",
  already_covered: false,
  blanks: ["level"],
  flags: [],
};

const ADD = { name: "Add to Handbook" };

function typeContent(text: string) {
  fireEvent.change(screen.getByRole("textbox", { name: "Content" }), { target: { value: text } });
}

describe("KnowledgeGapEditor", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    state.addError = null;
    state.pending = false;
  });

  it("starts empty, and adds what a person writes", async () => {
    render(<KnowledgeGapEditor topic={TOPIC} />);
    expect(screen.getByRole("button", ADD)).toBeDisabled();

    await userEvent.type(screen.getByLabelText("Title"), "Parking");
    typeContent("Visitors park on level -1.");
    await userEvent.click(screen.getByRole("button", ADD));

    expect(state.add).toHaveBeenCalledWith({
      topicId: "t1",
      title: "Parking",
      content: "Visitors park on level -1.",
      confirmIdentifying: false,
    });
    expect(state.reset).toHaveBeenCalled();
  });

  it("holds a draft back while a detail is still to fill in, and saves it meanwhile", async () => {
    render(<KnowledgeGapEditor topic={{ ...TOPIC, draft: DRAFT }} />);
    expect(screen.getByLabelText("Title")).toHaveValue("Visitor parking");
    expect(screen.getByRole("list", { name: "Still to fill in" })).toHaveTextContent("level");
    expect(screen.getByRole("button", ADD)).toBeDisabled();
    expect(screen.getByRole("button", { name: "Save" })).toBeDisabled();
    expect(screen.getByText("meta Visitor parking")).toBeInTheDocument();

    typeContent("Visitors park on level -1.");
    await userEvent.click(screen.getByRole("button", { name: "Save" }));

    expect(screen.queryByRole("list", { name: "Still to fill in" })).toBeNull();
    expect(screen.getByRole("button", ADD)).toBeEnabled();
    expect(state.save).toHaveBeenCalledWith({
      topicId: "t1",
      title: "Visitor parking",
      content: "Visitors park on level -1.",
    });
  });

  it("asks for confirmation of what the saved draft holds that may identify somebody", async () => {
    const draft = {
      ...DRAFT,
      content: "Order 7781 is parked. Mail ann@example.com",
      blanks: [],
      flags: [
        { kind: "shared" as const, value: "7781", count: 1 },
        { kind: "personal_data" as const, value: "email", count: 1 },
      ],
    };
    render(<KnowledgeGapEditor topic={{ ...TOPIC, draft }} />);
    expect(screen.getByText(/“7781” also appears in people's questions/)).toBeInTheDocument();
    expect(screen.getByText("One e-mail address")).toBeInTheDocument();
    expect(screen.getByRole("button", ADD)).toBeDisabled();

    await userEvent.click(screen.getByRole("checkbox"));
    await userEvent.click(screen.getByRole("button", ADD));

    expect(state.add).toHaveBeenCalledWith(expect.objectContaining({ confirmIdentifying: true }));
  });

  it("shows what the server flagged when adding was refused, until the text changes", () => {
    state.addError = new ApiError(409, "This content may identify somebody.", {
      error: {
        code: "IDENTIFYING_CONTENT",
        message: "This content may identify somebody.",
        details: { flags: [{ kind: "personal_data", value: "phone", count: 2 }] },
      },
    });
    render(<KnowledgeGapEditor topic={TOPIC} />);
    expect(screen.getByText("2 matches: phone number")).toBeInTheDocument();
    expect(screen.getByText("This content may identify somebody")).toBeInTheDocument();
  });

  it("reads a refusal with no flags in it as nothing to show", () => {
    state.addError = new ApiError(409, "x", {
      error: { code: "IDENTIFYING_CONTENT", message: "x", details: null },
    });
    render(<KnowledgeGapEditor topic={TOPIC} />);
    expect(screen.queryByRole("checkbox")).toBeNull();
  });

  it("keeps both actions off while one is in flight", () => {
    state.pending = true;
    render(
      <KnowledgeGapEditor topic={{ ...TOPIC, draft: { ...DRAFT, blanks: [], content: "x" } }} />,
    );
    expect(screen.getByRole("button", ADD)).toBeDisabled();
  });
});

describe("blanksIn", () => {
  it("lists each detail still to fill in once, and ignores an empty one", () => {
    expect(blanksIn("{{ level }} for {{hours}}; {{level}}, {{  }} and {x}")).toEqual([
      "level",
      "hours",
    ]);
  });
});

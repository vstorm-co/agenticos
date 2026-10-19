import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import type { KnowledgeGapQuestion } from "@/types/knowledge-gaps";
import { KnowledgeGapQuestionItem } from "./knowledge-gap-question";

function question(overrides: Partial<KnowledgeGapQuestion> = {}): KnowledgeGapQuestion {
  return {
    search_id: "s1",
    query: "parental leave duration",
    question: "How long can I take parental leave?",
    top_similarity: 0.4123,
    result_count: 3,
    agent: {
      id: "a1",
      name: "HR helper",
      slug: "hr-helper",
      has_avatar: false,
      avatar_color: null,
    },
    run_id: "r1",
    conversation_id: "c1",
    answer_message_id: "m1",
    down_rating_comment: null,
    asked_at: "2026-10-12T09:00:00Z",
    ...overrides,
  };
}

describe("KnowledgeGapQuestionItem", () => {
  it("shows what the person asked, what was searched, and how close the best match came", () => {
    render(<KnowledgeGapQuestionItem question={question()} />);
    expect(screen.getByText("How long can I take parental leave?")).toBeInTheDocument();
    expect(screen.getByText("Searched for: parental leave duration")).toBeInTheDocument();
    expect(screen.getByText("3 results, closest match 0.41")).toBeInTheDocument();
    expect(screen.getByText("HR helper")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "Open the run" })).toHaveAttribute(
      "href",
      "/runs?run=r1",
    );
  });

  it("says the search found nothing, and that no conversation was kept for an API run", () => {
    render(
      <KnowledgeGapQuestionItem
        question={question({ question: null, result_count: 0, top_similarity: null, agent: null })}
      />,
    );
    expect(screen.getByText(/No conversation is kept for this run/)).toBeInTheDocument();
    expect(screen.getByText("No results")).toBeInTheDocument();
    expect(screen.queryByText("HR helper")).toBeNull();
  });

  it("carries the comment left with a thumbs-down", () => {
    render(
      <KnowledgeGapQuestionItem question={question({ down_rating_comment: "Wrong policy" })} />,
    );
    expect(screen.getByText("Rated down: Wrong policy")).toBeInTheDocument();
  });
});

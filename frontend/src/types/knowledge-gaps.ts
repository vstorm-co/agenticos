/**
 * Knowledge gaps - the questions agents searched a knowledge base for and found
 * nothing relevant to, grouped into topics.
 *
 * Mirrors `app/schemas/knowledge_gap.py`. A topic belongs to one knowledge base;
 * nothing is ingested on its account - a person adds the missing document.
 */

export type KnowledgeGapStatus = "open" | "dismissed";

export interface KnowledgeGapAgent {
  id: string;
  name: string;
  slug: string;
  has_avatar: boolean;
  avatar_color: number | null;
}

export interface KnowledgeGapTopic {
  id: string;
  knowledge_base_id: string;
  knowledge_base_name: string;
  status: KnowledgeGapStatus;
  /** The topic's first question, as the agent searched it. */
  label: string;
  question_count: number;
  last_asked_at: string;
  /** Up to three of the questions, as searched. */
  examples: string[];
  agents: KnowledgeGapAgent[];
  dismissed_at: string | null;
  has_draft: boolean;
  /** Whether the caller may dismiss or reopen it: they may change its knowledge base. */
  can_edit: boolean;
}

/** How many topics one knowledge base holds, under the list's filters. */
export interface KnowledgeGapCollectionCount {
  knowledge_base_id: string;
  knowledge_base_name: string;
  topics: number;
  questions: number;
}

export interface KnowledgeGapTopicList {
  items: KnowledgeGapTopic[];
  total: number;
  by_knowledge_base: KnowledgeGapCollectionCount[];
  /** Misses waiting for the next grouping pass, so in no topic yet. */
  ungrouped: number;
}

/** One time a topic's question was asked, and what the search found. */
export interface KnowledgeGapQuestion {
  search_id: string;
  /** What the agent searched for. */
  query: string;
  /** What the person asked; null where no conversation is kept, as for an API run. */
  question: string | null;
  top_similarity: number | null;
  result_count: number;
  agent: KnowledgeGapAgent | null;
  run_id: string;
  conversation_id: string | null;
  answer_message_id: string | null;
  down_rating_comment: string | null;
  asked_at: string;
}

/** What a draft rests on, verified when it was kept: a document, or one of the topic's questions. */
export interface KnowledgeGapSource {
  kind: "document" | "question";
  id: string;
  /** The document's file name, or the question as searched. */
  label: string;
}

/** The passage a drafting agent proposed for a topic. Never added to a collection by itself. */
export interface KnowledgeGapDraft {
  title: string;
  /** Markdown. */
  content: string;
  /** At most twelve, each verified, and only those that still exist. */
  sources: KnowledgeGapSource[];
  /** Sources the draft named that could not be verified, and were left out. */
  unverified: number;
  drafted_at: string;
  /** The run that wrote it, in Activity. */
  run_id: string | null;
}

export interface KnowledgeGapTopicDetail extends KnowledgeGapTopic {
  /** The newest hundred. */
  questions: KnowledgeGapQuestion[];
  draft: KnowledgeGapDraft | null;
}

export interface KnowledgeGapCasesAdded {
  dataset_id: string;
  /** The version the cases were added in; null when none were. */
  version: number | null;
  added: number;
  /** Questions with no stored answer the caller may read. */
  skipped: number;
}

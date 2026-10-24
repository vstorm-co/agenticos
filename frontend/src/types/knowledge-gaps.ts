/**
 * Knowledge gaps - the questions agents searched a knowledge base for and found
 * nothing relevant to, grouped into topics.
 *
 * Mirrors `app/schemas/knowledge_gap.py`. A topic belongs to one knowledge base;
 * nothing is ingested on its account until a person adds its content as a document.
 */

/** `covered` once a person added its content; a topic whose document went reads open. */
export type KnowledgeGapStatus = "open" | "dismissed" | "covered";

/** The document a person added to cover a topic. */
export interface KnowledgeGapDocument {
  id: string;
  filename: string;
  /** The document's ingestion status. */
  status: string;
}

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
  /** Distinct people who asked; everybody who asked anonymously counts as one. */
  asker_count: number;
  last_asked_at: string;
  /** Up to three of the questions, as searched. */
  examples: string[];
  agents: KnowledgeGapAgent[];
  dismissed_at: string | null;
  covered_at: string | null;
  /** The document added for it, while it is covered. */
  covered_by: KnowledgeGapDocument | null;
  has_draft: boolean;
  /** Whether the caller may dismiss, reopen, draft or add its content: they may change its knowledge base. */
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
  /** Whether the caller may group a knowledge base's waiting misses now; false off its page. */
  can_regroup: boolean;
  /** Recent answers on a knowledge base's page that no model has read for gaps yet. */
  unchecked: number;
}

/** One time a topic's question was asked, and what the search found. */
/** What makes a question a miss: a search that found nothing, or an answer read as one. */
export type KnowledgeGapSignal = "retrieval" | "answer" | "rating";

export interface KnowledgeGapQuestion {
  search_id: string;
  /** What the agent searched for; the person's question when the answer was read as a miss. */
  query: string;
  signal: KnowledgeGapSignal;
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

/** What a draft rests on, verified when it was kept: a document, a question or a context file. */
export interface KnowledgeGapSource {
  kind: "document" | "question" | "context";
  id: string;
  /** The document's file name, the question as searched, or the context file's name. */
  label: string;
}

/** Something in a topic's content that may identify a person, for somebody to check. */
export interface KnowledgeGapFlag {
  /** `personal_data` for a detector's match, `shared` for a number repeated from the questions. */
  kind: "personal_data" | "shared";
  /** The detector's category, or the repeated token. */
  value: string;
  count: number;
}

/** A topic's content, drafted or written. Added to a collection only by a person. */
export interface KnowledgeGapDraft {
  title: string;
  /** Markdown. */
  content: string;
  /** At most twelve, each verified, and only those that still exist. */
  sources: KnowledgeGapSource[];
  /** Sources the draft named that could not be verified, and were left out. */
  unverified: number;
  drafted_at: string;
  /** The run that wrote it, in Activity; null for content a person wrote. */
  run_id: string | null;
  /** The drafter found the questions answered by a source it cites. */
  already_covered: boolean;
  /** Details still to fill in, each written `{{...}}` in the content. */
  blanks: string[];
  /** What may identify somebody; adding the content asks to confirm it. */
  flags: KnowledgeGapFlag[];
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

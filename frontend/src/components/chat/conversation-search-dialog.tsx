"use client";

import { useRef, useState } from "react";
import { Search } from "lucide-react";
import { ChatIcon as MessageSquare } from "@/components/icons/product-icons";
import { useLocale, useTranslations } from "next-intl";

import { Button, Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { useDebounced } from "@/components/ui/list-controls";
import { useConversationMessageSearch } from "@/hooks/use-conversation-message-search";
import { useConversationSearch } from "@/hooks/use-conversations";
import type {
  ConversationMessageSearchHit,
  ConversationMessageSearchTarget,
} from "@/lib/conversation-message-search-api";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { Conversation } from "@/types/conversation";
import { cn, timeAgo } from "@/lib/utils";

type SearchMode = "messages" | "titles";
type MessageHitWithTime = ConversationMessageSearchHit & { timeLabel: string };

/** Search message text by default, with title search for older conversations. */
export function ConversationSearchDialog({
  open,
  onOpenChange,
  onSelect,
  onSelectResult,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** Kept for callers that only know how to open a conversation. */
  onSelect: (id: string) => void;
  onSelectResult?: (target: ConversationMessageSearchTarget) => void;
}) {
  const t = useTranslations("chat.sidebar");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [term, setTerm] = useState("");
  const [mode, setMode] = useState<SearchMode>("messages");
  const preserveFocusAfterMessageSelection = useRef(false);
  const debounced = useDebounced(term);
  const messageSearch = useConversationMessageSearch(mode === "messages" ? debounced : "");
  const titleSearch = useConversationSearch(mode === "titles" ? debounced : "");
  const searching = debounced.trim() !== "";
  const messageResults = (messageSearch.data ?? []).map((hit) => ({
    ...hit,
    timeLabel: timeAgo(hit.matched_at, tTime, locale),
  }));
  const titleResults = titleSearch.data?.items ?? [];
  const hasResults = mode === "messages" ? messageResults.length > 0 : titleResults.length > 0;
  const isFetching = mode === "messages" ? messageSearch.isFetching : titleSearch.isFetching;
  const isError = mode === "messages" ? messageSearch.isError : titleSearch.isError;
  const canRetry =
    mode === "messages" ? messageSearch.data === undefined : titleSearch.data === undefined;
  const handleOpenChange = (next: boolean) => {
    onOpenChange(next);
    setTerm("");
    setMode("messages");
  };
  const retry = () => {
    void (mode === "messages" ? messageSearch.refetch() : titleSearch.refetch());
  };

  return (
    <Dialog open={open} onOpenChange={handleOpenChange}>
      <DialogContent
        className={cn(DIALOG_FORM, "gap-0 overflow-hidden p-0")}
        onCloseAutoFocus={(event) => {
          if (preserveFocusAfterMessageSelection.current) {
            preserveFocusAfterMessageSelection.current = false;
            event.preventDefault();
          }
        }}
      >
        <DialogTitle className="sr-only">{t("searchLabel")}</DialogTitle>
        <div className="border-border flex items-center gap-2.5 border-b px-4">
          <Search className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
          <select
            aria-label={t("searchModeLabel")}
            value={mode}
            onChange={(event) => setMode(event.target.value === "titles" ? "titles" : "messages")}
            className="text-muted-foreground max-w-32 shrink-0 bg-transparent text-xs outline-none"
          >
            <option value="messages">{t("searchModeMessages")}</option>
            <option value="titles">{t("searchModeTitles")}</option>
          </select>
          <input
            autoFocus
            maxLength={120}
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder={t("searchPlaceholder")}
            aria-label={t("searchLabel")}
            className="placeholder:text-muted-foreground h-12 min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm"
          />
        </div>
        <div className="max-h-[60vh] min-h-24 overflow-y-auto p-1.5">
          {!searching ? (
            <p className="text-muted-foreground px-3 py-6 text-center text-sm">
              {mode === "messages" ? t("searchHint") : t("searchTitleHint")}
            </p>
          ) : (
            <>
              {isError && (
                <div
                  role="alert"
                  className="flex items-center justify-center gap-3 px-3 py-4 text-sm"
                >
                  <span className="text-muted-foreground">{t("searchFailed")}</span>
                  {canRetry && (
                    <Button type="button" variant="outline" size="sm" onClick={retry}>
                      {t("retrySearch")}
                    </Button>
                  )}
                </div>
              )}
              {!hasResults && !isError && (
                <p className="text-muted-foreground px-3 py-6 text-center text-sm">
                  {isFetching
                    ? t("searching")
                    : mode === "messages"
                      ? t("noMessageSearchResults")
                      : t("noSearchResults")}
                </p>
              )}
              {mode === "messages" && hasResults && (
                <MessageSearchResults
                  results={messageResults}
                  untitled={t("untitled")}
                  onSelect={(hit) => {
                    if (onSelectResult) {
                      preserveFocusAfterMessageSelection.current = true;
                      const target: ConversationMessageSearchTarget = {
                        conversationId: hit.conversation_id,
                        messageId: hit.message_id,
                        ...(hit.thread_root_message_id
                          ? { threadRootMessageId: hit.thread_root_message_id }
                          : {}),
                      };
                      onSelectResult(target);
                    } else {
                      onSelect(hit.conversation_id);
                    }
                    handleOpenChange(false);
                  }}
                />
              )}
              {mode === "titles" && hasResults && (
                <TitleSearchResults
                  results={titleResults}
                  untitled={t("untitled")}
                  onSelect={(conversationId) => {
                    onSelect(conversationId);
                    handleOpenChange(false);
                  }}
                />
              )}
            </>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

function MessageSearchResults({
  results,
  untitled,
  onSelect,
}: {
  results: MessageHitWithTime[];
  untitled: string;
  onSelect: (hit: ConversationMessageSearchHit) => void;
}) {
  return (
    <ul>
      {results.map((hit) => (
        <li key={hit.message_id}>
          <button
            type="button"
            onClick={() => onSelect(hit)}
            className="hover:bg-accent flex w-full items-start gap-3 rounded-lg px-3 py-2.5 text-left"
          >
            <MessageSquare className="text-muted-foreground mt-0.5 h-4 w-4 shrink-0" aria-hidden />
            <span className="flex min-w-0 flex-1 flex-col gap-1">
              <span className="flex min-w-0 items-center gap-2">
                <span className="min-w-0 flex-1 truncate text-sm">{hit.title || untitled}</span>
                <span className="text-muted-foreground shrink-0 text-xs">{hit.timeLabel}</span>
              </span>
              <span className="text-muted-foreground line-clamp-2 text-xs leading-relaxed">
                {hit.speaker_name ? `${hit.speaker_name}: ` : ""}
                <HighlightedSnippet snippet={hit.snippet} />
              </span>
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

function TitleSearchResults({
  results,
  untitled,
  onSelect,
}: {
  results: Conversation[];
  untitled: string;
  onSelect: (conversationId: string) => void;
}) {
  return (
    <ul>
      {results.map((conversation) => (
        <li key={conversation.id}>
          <button
            type="button"
            onClick={() => onSelect(conversation.id)}
            className="hover:bg-accent flex w-full items-center gap-3 rounded-lg px-3 py-3 text-left"
          >
            <MessageSquare className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-sm">
              {conversation.title || untitled}
            </span>
          </button>
        </li>
      ))}
    </ul>
  );
}

/** Render `ts_headline`'s markers as text and `<mark>`, never as HTML. */
function HighlightedSnippet({ snippet }: { snippet: string }) {
  return (
    <>
      {snippet.split(/(\*\*[\s\S]*?\*\*)/g).map((part, index) =>
        part.startsWith("**") && part.endsWith("**") && part.length >= 4 ? (
          <mark key={index} className="bg-primary/15 text-foreground rounded-sm px-0.5">
            {part.slice(2, -2)}
          </mark>
        ) : (
          <span key={index}>{part}</span>
        ),
      )}
    </>
  );
}

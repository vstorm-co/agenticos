"use client";

import { useState } from "react";
import { MessageSquare, Search } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { Dialog, DialogContent, DialogTitle } from "@/components/ui";
import { useDebounced } from "@/components/ui/list-controls";
import { useConversationSearch } from "@/hooks";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn, timeAgo } from "@/lib/utils";

/**
 * Search the reader's conversations in a window of its own, as the global
 * search opens - the chat's sidebar keeps three icons instead of a search box
 * that took a row of its own above the list.
 *
 * Matched on the server against the title, archived threads included, and
 * nothing is asked until something is typed. A pick opens the conversation.
 */
export function ConversationSearchDialog({
  open,
  onOpenChange,
  onSelect,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onSelect: (id: string) => void;
}) {
  const t = useTranslations("chat.sidebar");
  const tTime = useTranslations("time");
  const locale = useLocale();
  const [term, setTerm] = useState("");
  const debounced = useDebounced(term);
  const { data, isFetching } = useConversationSearch(debounced);
  const results = data?.items ?? [];
  const searching = debounced.trim() !== "";

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        onOpenChange(next);
        if (!next) setTerm("");
      }}
    >
      <DialogContent className={cn(DIALOG_FORM, "gap-0 overflow-hidden p-0")}>
        <DialogTitle className="sr-only">{t("searchLabel")}</DialogTitle>
        <div className="border-border flex items-center gap-2.5 border-b px-4">
          <Search className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
          <input
            autoFocus
            value={term}
            onChange={(event) => setTerm(event.target.value)}
            placeholder={t("searchLabel")}
            aria-label={t("searchLabel")}
            className="placeholder:text-muted-foreground h-12 min-w-0 flex-1 bg-transparent text-sm outline-none"
          />
        </div>
        <div className="max-h-[60vh] min-h-24 overflow-y-auto p-1.5">
          {!searching ? (
            <p className="text-muted-foreground px-3 py-6 text-center text-sm">{t("searchHint")}</p>
          ) : results.length === 0 ? (
            <p className="text-muted-foreground px-3 py-6 text-center text-sm">
              {isFetching ? t("searching") : t("noSearchResults")}
            </p>
          ) : (
            <ul>
              {results.map((conversation) => (
                <li key={conversation.id}>
                  <button
                    type="button"
                    onClick={() => {
                      onSelect(conversation.id);
                      onOpenChange(false);
                      setTerm("");
                    }}
                    className="hover:bg-accent flex w-full items-center gap-3 rounded-lg px-3 py-2.5 text-left"
                  >
                    <MessageSquare className="text-muted-foreground h-4 w-4 shrink-0" aria-hidden />
                    <span className="min-w-0 flex-1 truncate text-sm">
                      {conversation.title || t("untitled")}
                    </span>
                    <span className="text-muted-foreground shrink-0 text-xs">
                      {timeAgo(conversation.updated_at || conversation.created_at, tTime, locale)}
                    </span>
                  </button>
                </li>
              ))}
            </ul>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}

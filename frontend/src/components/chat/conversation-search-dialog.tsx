"use client";

import { useState } from "react";
import { Command } from "cmdk";
import { Search } from "lucide-react";
import { ChatIcon as MessageSquare } from "@/components/icons/product-icons";
import { useLocale, useTranslations } from "next-intl";

import { COMMAND_ITEM_FOCUS, MENU_ROW, SEARCH_FIELD_FOCUS } from "@/components/ui/control-styles";
import { Button, Dialog, DialogContent, DialogTitle, Spinner } from "@/components/ui";
import { useDebounced } from "@/components/ui/list-controls";
import { useConversationSearch } from "@/hooks";
import { DIALOG_COLUMN, DIALOG_FORM } from "@/lib/dialog-sizes";
import { cn, timeAgo } from "@/lib/utils";

/** Plain text only: SQL's emphasis markers are never interpreted as HTML. */
function SearchExcerpt({ text }: { text: string }) {
  return text.split(/(\*\*[^*]+\*\*)/g).map((piece, index) =>
    piece.startsWith("**") && piece.endsWith("**") ? (
      <mark key={index} className="bg-foreground/10 text-foreground rounded-sm">
        {piece.slice(2, -2)}
      </mark>
    ) : (
      <span key={index}>{piece}</span>
    ),
  );
}

function SearchTitle({ text, term }: { text: string; term: string }) {
  const start = text.toLocaleLowerCase().indexOf(term.toLocaleLowerCase());
  if (start < 0 || !term) return text;
  return (
    <>
      {text.slice(0, start)}
      <mark className="bg-foreground/10 text-foreground rounded-sm">
        {text.slice(start, start + term.length)}
      </mark>
      {text.slice(start + term.length)}
    </>
  );
}

/** Search readable titles and message text without fetching whole transcripts. */
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
  const tc = useTranslations("common");
  const locale = useLocale();
  const [term, setTerm] = useState("");
  const debounced = useDebounced(term);
  const { data, isFetching, isError, refetch } = useConversationSearch(open ? debounced : "");
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
      <DialogContent className={cn(DIALOG_FORM, DIALOG_COLUMN, "gap-0 p-0")}>
        <DialogTitle className="sr-only">{t("searchLabel")}</DialogTitle>
        <Command shouldFilter={false} label={t("searchLabel")} className="flex min-h-0 flex-col">
          <div
            className={cn(
              SEARCH_FIELD_FOCUS,
              "border-border flex shrink-0 items-center gap-2.5 border-b px-4 pr-12",
            )}
          >
            <Search className="text-muted-foreground size-4 shrink-0" aria-hidden />
            <Command.Input
              autoFocus
              value={term}
              onValueChange={setTerm}
              maxLength={500}
              placeholder={t("searchLabel")}
              aria-label={t("searchLabel")}
              className="placeholder:text-muted-foreground h-14 min-w-0 flex-1 bg-transparent text-base outline-none md:text-sm"
            />
            {isFetching && <Spinner className="size-4" />}
          </div>
          {isError && (
            <div
              role="alert"
              className="text-destructive flex items-center justify-between gap-3 px-4 py-3 text-sm"
            >
              {t("searchFailed")}
              <Button
                size="sm"
                variant="ghost"
                onClick={() => void refetch()}
                onKeyDown={(event) => {
                  if (event.key === "Enter") event.stopPropagation();
                }}
              >
                {tc("retry")}
              </Button>
            </div>
          )}
          <Command.List
            className="max-h-[min(60dvh,480px)] min-h-0 flex-1 overflow-y-auto overscroll-contain p-2"
            aria-busy={isFetching}
          >
            {!searching ? (
              <p className="text-muted-foreground px-3 py-8 text-center text-sm">
                {t("searchHint")}
              </p>
            ) : results.length === 0 && !isError ? (
              <p className="text-muted-foreground px-3 py-8 text-center text-sm">
                {isFetching ? t("searching") : t("noSearchResults")}
              </p>
            ) : (
              results.map((conversation) => (
                <Command.Item
                  key={conversation.id}
                  value={conversation.id}
                  onSelect={() => {
                    onSelect(conversation.id);
                    onOpenChange(false);
                    setTerm("");
                  }}
                  className={cn(
                    COMMAND_ITEM_FOCUS,
                    MENU_ROW,
                    "cursor-pointer items-start gap-3 px-3 py-3",
                  )}
                >
                  <MessageSquare
                    className="text-muted-foreground mt-0.5 size-4 shrink-0"
                    aria-hidden
                  />
                  <div className="min-w-0 flex-1 space-y-1.5">
                    <div className="flex items-start justify-between gap-3">
                      <span className="line-clamp-2 text-sm font-medium">
                        <SearchTitle
                          text={conversation.title || t("untitled")}
                          term={debounced.trim()}
                        />
                      </span>
                      <span className="text-muted-foreground shrink-0 pt-0.5 text-[11px]">
                        {timeAgo(
                          conversation.updated_at || conversation.created_at || "",
                          tTime,
                          locale,
                        )}
                      </span>
                    </div>
                    {conversation.snippet && (
                      <p className="text-muted-foreground line-clamp-3 text-[13px] leading-relaxed break-words">
                        <SearchExcerpt text={conversation.snippet} />
                      </p>
                    )}
                    {conversation.hits !== undefined && (
                      <span className="text-muted-foreground text-[11px]">
                        {t("searchMatches", { count: conversation.hits })}
                      </span>
                    )}
                  </div>
                </Command.Item>
              ))
            )}
          </Command.List>
          <div className="text-muted-foreground border-t px-4 py-2.5 text-[11px]">
            {t("searchKeys")}
          </div>
        </Command>
      </DialogContent>
    </Dialog>
  );
}

"use client";

import { useEffect, useId, useState } from "react";
import { useTranslations } from "next-intl";
import { Button, Input, Label } from "@/components/ui";
import { getErrorMessage } from "@/lib/api-error";
import { useRoomThreadContextConversationSearch } from "@/hooks/use-room-thread-context";

interface RoomThreadContextSourcePickerProps {
  destinationConversationId: string;
  destinationTitle: string;
  sourceConversationId: string;
  sourceTitle?: string | null;
  disabled?: boolean;
  onChange: (conversationId: string, title: string) => void;
}

/** Select a readable source conversation without changing the destination chat. */
export function RoomThreadContextSourcePicker({
  destinationConversationId,
  destinationTitle,
  sourceConversationId,
  sourceTitle,
  disabled = false,
  onChange,
}: RoomThreadContextSourcePickerProps) {
  const t = useTranslations("chat.roomThreadContext");
  const tErrors = useTranslations("errors");
  const pickerId = useId();
  const [open, setOpen] = useState(false);
  const [searchText, setSearchText] = useState("");
  const [searchTerm, setSearchTerm] = useState("");
  useEffect(() => {
    const timer = setTimeout(() => setSearchTerm(searchText.trim()), 250);
    return () => clearTimeout(timer);
  }, [searchText]);
  const search = useRoomThreadContextConversationSearch(searchTerm);
  const selectedTitle =
    sourceConversationId === destinationConversationId
      ? destinationTitle || t("source.untitled")
      : (search.items.find((item) => item.id === sourceConversationId)?.title ??
        sourceTitle ??
        t("source.selected"));
  const results = search.items.filter((item) => item.id !== destinationConversationId);

  const choose = (conversationId: string, title: string) => {
    onChange(conversationId, title);
    setOpen(false);
    setSearchText("");
  };

  return (
    <div role="group" aria-label={t("source.label")} className="space-y-2">
      <p className="text-sm font-medium">{t("source.label")}</p>
      <div className="flex items-center gap-2">
        <p className="text-muted-foreground min-w-0 flex-1 truncate text-sm">{selectedTitle}</p>
        <Button
          type="button"
          size="sm"
          variant="outline"
          disabled={disabled}
          aria-expanded={open}
          aria-controls={`${pickerId}-results`}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t("source.closePicker") : t("source.choose")}
        </Button>
      </div>
      {open && (
        <div className="space-y-2 rounded-lg border p-3">
          <Label htmlFor={`${pickerId}-search`}>{t("source.search")}</Label>
          <Input
            id={`${pickerId}-search`}
            type="search"
            value={searchText}
            onChange={(event) => setSearchText(event.target.value)}
            placeholder={t("source.searchPlaceholder")}
            autoFocus
          />
          <div id={`${pickerId}-results`} className="max-h-52 overflow-y-auto">
            <div role="listbox" aria-label={t("source.results")} className="space-y-1">
              <SourceOption
                selected={sourceConversationId === destinationConversationId}
                title={destinationTitle || t("source.untitled")}
                label={destinationTitle || t("source.untitled")}
                description={t("source.currentConversation")}
                onSelect={() => choose(destinationConversationId, destinationTitle)}
              />
              {search.isError ? (
                <div role="alert" className="space-y-2 p-2 text-sm">
                  <p>{getErrorMessage(search.error, tErrors, t("source.searchFailed"))}</p>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    onClick={() => void search.refetch()}
                  >
                    {t("source.retry")}
                  </Button>
                </div>
              ) : (search.isFetching && !search.isFetchingNextPage) ||
                searchText.trim() !== searchTerm ? (
                <p role="status" className="text-muted-foreground p-2 text-sm">
                  {t("source.searching")}
                </p>
              ) : searchText.trim() === "" ? (
                <p className="text-muted-foreground p-2 text-sm">{t("source.searchHint")}</p>
              ) : results.length === 0 && !search.hasNextPage ? (
                <p className="text-muted-foreground p-2 text-sm">{t("source.empty")}</p>
              ) : results.length === 0 ? (
                <p role="status" className="text-muted-foreground p-2 text-sm">
                  {t("source.noMatchesYet")}
                </p>
              ) : (
                results.map((conversation) => (
                  <SourceOption
                    key={conversation.id}
                    selected={sourceConversationId === conversation.id}
                    title={conversation.title ?? t("source.untitled")}
                    label={conversation.title ?? t("source.untitled")}
                    description={
                      conversation.room_visibility === "public"
                        ? t("source.publicRoom")
                        : conversation.room_visibility === "private" ||
                            conversation.project_id != null
                          ? t("source.projectRoom")
                          : conversation.share_permission != null
                            ? t("source.sharedConversation")
                            : t("source.conversation")
                    }
                    onSelect={() =>
                      choose(conversation.id, conversation.title ?? t("source.untitled"))
                    }
                  />
                ))
              )}
            </div>
            {search.hasNextPage &&
              !search.isError &&
              searchText.trim() !== "" &&
              searchText.trim() === searchTerm && (
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="mt-1 w-full"
                  disabled={search.isFetchingNextPage}
                  onClick={() => void search.fetchNextPage()}
                >
                  {search.isFetchingNextPage ? t("source.loadingMore") : t("source.loadMore")}
                </Button>
              )}
          </div>
        </div>
      )}
    </div>
  );
}

function SourceOption({
  selected,
  title,
  label,
  description,
  onSelect,
}: {
  selected: boolean;
  title: string;
  label: string;
  description?: string;
  onSelect: () => void;
}) {
  return (
    <Button
      type="button"
      role="option"
      aria-selected={selected}
      title={title}
      variant={selected ? "secondary" : "ghost"}
      className="h-auto w-full justify-start px-2 py-2 text-left"
      onClick={onSelect}
    >
      <span className="min-w-0">
        <span className="block truncate">{label}</span>
        {description && (
          <span className="text-muted-foreground block truncate text-xs">{description}</span>
        )}
      </span>
    </Button>
  );
}

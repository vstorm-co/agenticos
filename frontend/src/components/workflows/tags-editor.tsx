"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { Plus, X } from "lucide-react";

import { Badge, Input, Popover, PopoverContent, PopoverTrigger } from "@/components/ui";

const MAX_TAGS = 10;

/** A tag as the service keeps it: trimmed, lower case, at most 32 characters. */
export function normalTag(text: string): string {
  return text.trim().toLowerCase().slice(0, 32);
}

/**
 * A workflow's tags: chips, and for an editor a way to add one (Enter) or take
 * one off. Each change is saved at once, like the name.
 */
export function TagsEditor({
  tags,
  canEdit,
  onChange,
}: {
  tags: string[];
  canEdit: boolean;
  onChange: (tags: string[]) => void;
}) {
  const t = useTranslations("pages.workflows");
  const [draft, setDraft] = useState("");

  const add = () => {
    const tag = normalTag(draft);
    setDraft("");
    if (tag !== "" && !tags.includes(tag)) onChange([...tags, tag]);
  };

  return (
    <div className="flex flex-wrap items-center gap-1">
      {tags.map((tag) => (
        <Badge key={tag} variant="outline" className="text-muted-foreground gap-1 font-normal">
          {tag}
          {canEdit && (
            <button
              type="button"
              aria-label={t("removeTag", { tag })}
              className="hover:text-foreground"
              onClick={() => onChange(tags.filter((item) => item !== tag))}
            >
              <X className="size-3" />
            </button>
          )}
        </Badge>
      ))}
      {canEdit && tags.length < MAX_TAGS && (
        <Popover>
          <PopoverTrigger asChild>
            <button
              type="button"
              className="text-muted-foreground hover:text-foreground inline-flex items-center gap-0.5 rounded-md px-1 text-xs"
            >
              <Plus className="size-3" /> {t("addTag")}
            </button>
          </PopoverTrigger>
          <PopoverContent align="start" className="w-56 p-2">
            <Input
              aria-label={t("addTag")}
              placeholder={t("tagPlaceholder")}
              value={draft}
              maxLength={32}
              onChange={(event) => setDraft(event.target.value)}
              onKeyDown={(event) => {
                if (event.key === "Enter") {
                  event.preventDefault();
                  add();
                }
              }}
            />
          </PopoverContent>
        </Popover>
      )}
    </div>
  );
}

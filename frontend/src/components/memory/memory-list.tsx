"use client";

import type { ReactNode } from "react";
import { ChevronRight, ChevronLeft, type LucideIcon } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button, ListCardFootRow } from "@/components/ui";

export function MemoryRow({
  title,
  icon: Icon,
  children,
  onOpen,
  muted = false,
}: {
  title: string;
  icon: LucideIcon;
  children: ReactNode;
  onOpen: () => void;
  muted?: boolean;
}) {
  return (
    <li>
      <button
        type="button"
        onClick={onOpen}
        className="hover:bg-muted/50 focus-visible:ring-ring flex w-full items-center gap-3 px-4 py-4 text-left outline-none focus-visible:ring-2 focus-visible:ring-inset sm:gap-4 sm:px-5"
      >
        <span className="bg-muted text-muted-foreground flex size-10 shrink-0 items-center justify-center rounded-xl">
          <Icon className="size-4" aria-hidden />
        </span>
        <span className="min-w-0 flex-1 space-y-1.5">
          <span
            className={`line-clamp-2 max-w-4xl text-sm leading-6 font-medium ${muted ? "text-muted-foreground" : "text-foreground"}`}
          >
            {title}
          </span>
          <span className="text-muted-foreground flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
            {children}
          </span>
        </span>
        <ChevronRight className="text-muted-foreground size-4 shrink-0" aria-hidden />
      </button>
    </li>
  );
}

export function MemoryPager({
  skip,
  count,
  total,
  size,
  onPage,
}: {
  skip: number;
  count: number;
  total: number;
  size: number;
  onPage: (skip: number) => void;
}) {
  const t = useTranslations("pages.memory");
  if (total <= size) return null;
  return (
    <ListCardFootRow className="flex items-center justify-between gap-3">
      <span className="text-muted-foreground text-xs">
        {t("showing", { from: count ? skip + 1 : 0, to: skip + count, total })}
      </span>
      <div className="flex gap-2">
        <Button
          variant="outline"
          size="sm"
          disabled={skip === 0}
          onClick={() => onPage(Math.max(0, skip - size))}
        >
          <ChevronLeft className="size-4" aria-hidden />
          <span className="sr-only sm:not-sr-only">{t("newer")}</span>
        </Button>
        <Button
          variant="outline"
          size="sm"
          disabled={skip + count >= total}
          onClick={() => onPage(skip + size)}
        >
          <span className="sr-only sm:not-sr-only">{t("older")}</span>
          <ChevronRight className="size-4" aria-hidden />
        </Button>
      </div>
    </ListCardFootRow>
  );
}

"use client";

import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import { cn } from "@/lib/utils";

/** Catalog breakpoints and slots mirror the document and resource cards, including their footer. */
export function CatalogLoading({
  kind,
  rows = 3,
}: {
  kind: "document" | "resource" | "project";
  rows?: number;
}) {
  const t = useTranslations("states");
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={t("loading")}
      className="grid grid-cols-1 gap-3 md:grid-cols-2 xl:grid-cols-3"
    >
      {Array.from({ length: rows }, (_, i) => (
        <div
          key={i}
          aria-hidden="true"
          className="bg-card flex min-w-0 flex-col overflow-hidden rounded-xl border"
        >
          {kind === "document" && <Skeleton className="h-32 w-full rounded-none max-sm:hidden" />}
          <div className="flex flex-1 gap-3 p-4">
            {kind !== "document" && <Skeleton className="size-10 shrink-0 rounded-xl" />}
            <div className="min-w-0 flex-1 space-y-2">
              <Skeleton className="h-5 w-3/5" />
              {kind === "resource" && <Skeleton className="h-4 w-2/5" />}
              <div className="min-h-10 space-y-2 pt-1">
                <Skeleton className="h-3 w-full" />
                <Skeleton className="h-3 w-4/5" />
              </div>
            </div>
          </div>
          {kind === "document" && (
            <div className="mx-4 mb-3">
              <Skeleton className="h-4 w-24" />
            </div>
          )}
          <div
            className={cn(
              "mt-auto flex items-center justify-between gap-3 px-4 py-3",
              kind === "document" && "border-t",
            )}
          >
            <Skeleton className="h-3 w-28" />
            <Skeleton
              className={
                kind === "document" ? "touch:min-h-11 h-8 w-28 rounded-lg" : "size-7 rounded-md"
              }
            />
          </div>
        </div>
      ))}
    </div>
  );
}

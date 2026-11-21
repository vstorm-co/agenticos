"use client";

import { useTranslations } from "next-intl";
import { Skeleton } from "@/components/ui/skeleton";
import {
  ResourceCard,
  ResourceCardHeader,
  ResourceCardFooter,
} from "@/components/ui/resource-card";
import { cn } from "@/lib/utils";

/** Loading reserves the selected resource-card layout, including its description and footer. */
export function CatalogLoading({
  kind,
  rows = 3,
}: {
  kind: "document" | "resource" | "project" | "agent" | "group";
  rows?: number;
}) {
  const t = useTranslations("states");
  return (
    <div
      role="status"
      aria-busy="true"
      aria-label={t("loading")}
      className={cn(
        "grid grid-cols-1 gap-3 xl:grid-cols-3",
        kind === "group" ? "sm:grid-cols-2" : "md:grid-cols-2",
      )}
    >
      {Array.from({ length: rows }, (_, index) => (
        <ResourceCard
          key={index}
          aria-hidden="true"
          className={cn(kind === "document" && "overflow-hidden p-0")}
        >
          {kind === "document" && <Skeleton className="h-32 w-full rounded-none max-sm:hidden" />}
          <div className={cn("flex flex-1 flex-col", kind === "document" && "p-5")}>
            <ResourceCardHeader>
              {kind !== "document" && (
                <Skeleton
                  className={cn("size-10 shrink-0 rounded-xl", kind === "agent" && "rounded-full")}
                />
              )}
              <div className="min-w-0 flex-1 space-y-2">
                <Skeleton className="h-5 w-3/5" />
                <Skeleton className="h-3 w-2/5" />
              </div>
            </ResourceCardHeader>
            <div className="my-5 flex-1 space-y-2">
              <Skeleton className="h-3 w-full" />
              <Skeleton className="h-3 w-4/5" />
            </div>
            <ResourceCardFooter className="justify-between">
              <Skeleton className="h-4 w-24 rounded-full" />
              <Skeleton className="h-7 w-16 rounded-lg" />
            </ResourceCardFooter>
          </div>
        </ResourceCard>
      ))}
    </div>
  );
}

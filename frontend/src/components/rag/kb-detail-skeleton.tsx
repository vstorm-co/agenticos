"use client";

import { Skeleton } from "@/components/ui";

/** Skeleton mirroring the page layout: header, meta strip, and a few doc rows. */
export function KBDetailSkeleton() {
  return (
    <div className="pb-8">
      <div className="mb-6 flex flex-wrap items-start justify-between gap-4">
        <div className="space-y-2">
          <Skeleton className="h-3 w-40" />
          <Skeleton className="h-7 w-56" />
          <Skeleton className="h-4 w-72" />
        </div>
        <div className="flex gap-2">
          <Skeleton className="h-9 w-24 rounded-lg" />
          <Skeleton className="h-9 w-24 rounded-lg" />
        </div>
      </div>

      <Skeleton className="mb-6 h-4 w-64" />

      <Skeleton className="mb-3 h-4 w-24" />
      <div className="border-border bg-card divide-border divide-y overflow-hidden rounded-xl border">
        {Array.from({ length: 3 }).map((_, i) => (
          <div key={i} className="flex items-center gap-3 px-4 py-3">
            <Skeleton className="h-8 w-8 shrink-0 rounded-lg" />
            <Skeleton className="h-4 flex-1" />
            <Skeleton className="h-5 w-20 rounded-full" />
          </div>
        ))}
      </div>
    </div>
  );
}

"use client";

import { Loader2 } from "lucide-react";
import { useTranslations } from "next-intl";

import { Progress } from "@/components/ui";
import type { UploadProgress } from "@/hooks/use-knowledge-bases";
import { cn } from "@/lib/utils";

/**
 * One bar per upload still in the air.
 *
 * A determinate percentage only while the browser reports one; past 100 the
 * bytes have arrived and the server is still parsing, which is a different wait
 * and says so rather than sitting at a full bar.
 */
export function UploadProgressList({ uploads }: { uploads: UploadProgress[] }) {
  const t = useTranslations("pages.kb");
  if (uploads.length === 0) return null;
  return (
    <section className="border-border bg-card mb-6 space-y-3 rounded-xl border p-4">
      {uploads.map((up) => (
        <div key={up.uploadId}>
          <div className="mb-1.5 flex items-center justify-between gap-3 text-xs">
            <span className="text-foreground flex min-w-0 items-center gap-2 font-medium">
              <Loader2 className="h-3.5 w-3.5 shrink-0 animate-spin" />
              <span className="truncate" title={up.filename}>
                {up.filename}
              </span>
            </span>
            <span className="text-muted-foreground shrink-0 tabular-nums">
              {up.percent === null
                ? t("uploading2")
                : up.percent >= 100
                  ? t("processing")
                  : `${up.percent}%`}
            </span>
          </div>
          <Progress
            value={up.percent ?? undefined}
            className={cn(up.percent === null && "animate-pulse")}
          />
        </div>
      ))}
    </section>
  );
}

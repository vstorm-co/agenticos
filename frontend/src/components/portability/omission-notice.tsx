"use client";

import { AlertTriangle } from "lucide-react";
import { useTranslations } from "next-intl";
import type { BundlePath, BundleResource } from "@/lib/portability-api";

export function OmissionNotice({
  omissions,
  resources,
  completed = false,
}: {
  omissions: Record<string, BundlePath[]>;
  resources: BundleResource[];
  completed?: boolean;
}) {
  const t = useTranslations("portability");
  const count = Object.values(omissions).reduce((total, paths) => total + paths.length, 0);
  if (!count) return null;
  return (
    <div role="status" className="border-warning/40 bg-warning/5 rounded-xl border p-3 text-sm">
      <div className="flex items-start gap-2">
        <AlertTriangle className="text-warning mt-0.5 size-4 shrink-0" aria-hidden="true" />
        <p>{t(completed ? "omittedAfter" : "omittedBefore", { count })}</p>
      </div>
      <p className="text-muted-foreground mt-2">{t("reviewBeforePublish")}</p>
      <details className="mt-2">
        <summary className="cursor-pointer">{t("affectedBindings")}</summary>
        <ul className="mt-2 space-y-2">
          {Object.entries(omissions).map(([key, paths]) => (
            <li key={key} className="min-w-0">
              <span className="font-medium">
                {resources.find((resource) => resource.key === key)?.name ?? key}
              </span>
              <ul className="text-muted-foreground mt-1 space-y-1 text-xs">
                {paths.map((path) => (
                  <li key={JSON.stringify(path)} className="break-all">
                    {path.join(" › ")}
                  </li>
                ))}
              </ul>
            </li>
          ))}
        </ul>
      </details>
    </div>
  );
}

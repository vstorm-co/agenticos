"use client";
import { useTranslations } from "next-intl";
import type { WikiSnapshot } from "@/lib/wiki-workspace";
export function WikiDiagnostics({ graph }: { graph: WikiSnapshot }) {
  const t = useTranslations("wikiGraph");
  return (
    <div className="space-y-2">
      {" "}
      {(graph.skipped.length > 0 || graph.failed.length > 0 || graph.truncated) && (
        <details className="text-sm">
          <summary>{t("partial")}</summary>
          <p>{t("limits")}</p>
          <ul>
            {graph.skipped.map((path) => (
              <li key={path}>{t("skipped", { path })}</li>
            ))}
            {graph.failed.map((path) => (
              <li key={path}>{t("unreadable", { path })}</li>
            ))}
          </ul>
        </details>
      )}
      {graph.pages.some((entry) => entry.invalidFrontmatter) && (
        <p role="alert" className="text-sm">
          {t("invalidFrontmatter", {
            paths: graph.pages
              .filter((entry) => entry.invalidFrontmatter)
              .map((entry) => entry.path)
              .join(", "),
          })}
        </p>
      )}
    </div>
  );
}

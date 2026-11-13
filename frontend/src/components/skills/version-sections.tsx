"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { DiffView } from "@/components/authoring/diff-view";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { MarkdownModeToggle, type MarkdownMode } from "@/components/ui";
import type { SkillVersionRead } from "@/types/skill-versions";

/** A saved version, read as a document; History retains comparisons between changes. */
export function VersionSections({ version }: { version: SkillVersionRead }) {
  const t = useTranslations("skills.page.content");
  const [mode, setMode] = useState<MarkdownMode>("preview");
  return (
    <>
      <section className="space-y-2">
        <h3 className="text-muted-foreground text-xs font-medium">{t("description")}</h3>
        <p className="text-sm leading-relaxed">{version.description}</p>
      </section>
      <section className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h3 className="text-muted-foreground text-xs font-medium">{t("instructions")}</h3>
          <MarkdownModeToggle mode={mode} onChange={setMode} />
        </div>
        {mode === "preview" ? (
          <div className="max-h-[32rem] overflow-auto rounded-xl border p-4">
            <MarkdownContent content={version.content} inertImages />
          </div>
        ) : (
          <DiffView before={version.content} after={version.content} modes={false} />
        )}
      </section>
      <section className="space-y-2">
        <h3 className="text-muted-foreground text-xs font-medium">{t("files")}</h3>
        {version.resources.length === 0 ? (
          <p className="text-muted-foreground text-xs">{t("noFiles")}</p>
        ) : (
          <ul className="divide-y rounded-xl border px-4">
            {version.resources.map((file) => (
              <li key={file.name} className="py-3 text-xs [overflow-wrap:anywhere]">
                <span className="font-mono">{file.name}</span>
                {file.description && (
                  <p className="text-muted-foreground mt-1">{file.description}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>
    </>
  );
}

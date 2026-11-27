"use client";
import { useTranslations } from "next-intl";
import { writtenOut } from "@/lib/hidden-characters";
import type { Hunk } from "@/types/authoring";

/** A proposed resource, still absent from the skill library until Accept. */
export function NewSkillPreview({ hunk }: { hunk: Hunk }) {
  const t = useTranslations("authoring.newSkill");
  return (
    <section className="space-y-3">
      <h4 className="text-sm font-medium">{writtenOut(hunk.new_name ?? "")}</h4>
      <p className="text-muted-foreground text-sm">{writtenOut(hunk.new_description ?? "")}</p>
      <pre className="bg-muted/40 overflow-auto rounded-md p-3 text-sm break-words whitespace-pre-wrap md:max-h-80">
        {writtenOut(hunk.new_text)}
      </pre>
      <p className="text-muted-foreground text-xs">{t("binding")}</p>
      {hunk.blocked === "create_skill_permission" && (
        <p role="status" className="text-warning-ink text-sm">
          {t("permission")}
        </p>
      )}
    </section>
  );
}

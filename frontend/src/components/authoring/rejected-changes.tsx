"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Badge, Button } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { AuthoringRequest, ProposedSkill, RejectedChange } from "@/types/authoring";
import { IdeaSkillDialog } from "./idea-skill-dialog";

type CreateSkill = (index: number, skill: ProposedSkill) => Promise<boolean>;

/**
 * What the assistant proposed and nothing recorded, and why - a passage it could
 * not find, a tool the agent lacks, a field it may not change.
 *
 * Without it a request that proposed six changes and recorded none looks like a
 * request that found nothing to say. Absent when every change was recorded.
 *
 * A new skill the assistant wrote in full but did not add is still a person's to
 * create, given `onCreateSkill` - passed only to someone who may create skills.
 */
export function RejectedChanges({
  report,
  onCreateSkill,
}: {
  report: AuthoringRequest["report"];
  onCreateSkill?: CreateSkill;
}) {
  const t = useTranslations("authoring.rejected");
  const rejected = report?.rejected ?? [];
  if (rejected.length === 0) return null;
  const more = report?.rejected_more ?? 0;
  const total = rejected.length + more;
  const decide = onCreateSkill ? rejected.filter(creatable).length : 0;
  return (
    <details>
      <summary className="cursor-pointer text-sm font-medium">
        {decide === 0
          ? t("title", { count: total })
          : decide === total
            ? t("decide", { count: decide })
            : t("decideSome", { count: total, decide })}
      </summary>
      <ul className="space-y-3 pt-3">
        {rejected.map((item, index) => (
          <li key={`${item.reason}-${index}`} className="space-y-1">
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="outline">{t(`kind.${item.kind}`)}</Badge>
              <span className="text-sm">{t(`reason.${item.reason}`)}</span>
            </div>
            <Proposed item={item} />
            {item.kind === "create_skill" && (
              <IdeaSkill
                item={item}
                onCreate={onCreateSkill && ((skill) => onCreateSkill(index, skill))}
              />
            )}
          </li>
        ))}
      </ul>
      {more > 0 && (
        <p className="text-muted-foreground pt-2 text-xs">{t("more", { count: more })}</p>
      )}
    </details>
  );
}

function creatable(item: RejectedChange): boolean {
  return item.kind === "create_skill" && !!item.change.content && !item.skill_id;
}

function IdeaSkill({
  item,
  onCreate,
}: {
  item: RejectedChange;
  onCreate?: (skill: ProposedSkill) => Promise<boolean>;
}) {
  const t = useTranslations("authoring.rejected");
  const [previewing, setPreviewing] = useState(false);
  if (item.skill_id) {
    return (
      <p className="text-sm">
        {t("created")}{" "}
        <Link className="underline" href={`${ROUTES.SKILLS}/${item.skill_id}`}>
          {t("openSkill")}
        </Link>
      </p>
    );
  }
  if (!onCreate || !creatable(item)) return null;
  return (
    <>
      <Button size="sm" variant="outline" onClick={() => setPreviewing(true)}>
        {t("createSkill")}
      </Button>
      {previewing && (
        <IdeaSkillDialog change={item.change} onCreate={onCreate} onOpenChange={setPreviewing} />
      )}
    </>
  );
}

function Proposed({ item }: { item: RejectedChange }) {
  const t = useTranslations("authoring.rejected");
  const { change } = item;
  if (item.kind === "finding") {
    return (
      <div className="text-muted-foreground space-y-1 text-xs">
        <p>{change.text}</p>
        {change.edit && (
          <p className="font-mono break-words whitespace-pre-wrap">
            {t("about", { line: change.edit })}
          </p>
        )}
      </div>
    );
  }
  const subject =
    item.kind === "create_skill"
      ? change.name
      : item.kind === "tool_override"
        ? `${change.capability_id} / ${change.tool_id}`
        : item.kind === "spec_field"
          ? `${change.op} ${change.path}`
          : change.old_text || (change.after ? t("after", { passage: change.after }) : t("atEnd"));
  const proposed =
    item.kind === "tool_override"
      ? [change.name, change.description].filter(Boolean).join(" - ")
      : item.kind === "spec_field"
        ? JSON.stringify(change.value ?? null)
        : change.new_text;
  return (
    <div className="text-muted-foreground space-y-1 text-xs">
      <p className="font-mono break-words whitespace-pre-wrap">{subject}</p>
      {proposed && (
        <p className="break-words whitespace-pre-wrap">{t("proposed", { text: proposed })}</p>
      )}
      {change.rationale && <p>{change.rationale}</p>}
    </div>
  );
}

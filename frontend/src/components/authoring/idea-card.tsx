"use client";

import { useState } from "react";
import Link from "next/link";
import { useTranslations } from "next-intl";

import { Button, Card, CardContent } from "@/components/ui";
import { ROUTES } from "@/lib/constants";
import type { ProposedSkill, RejectedChange } from "@/types/authoring";
import { IdeaSkillDialog } from "./idea-skill-dialog";

/**
 * A new skill the assistant wrote in full but did not add, because too few
 * answers asked for it. A person creates it - into the library and the draft -
 * or dismisses it; a dismissal can be undone, a created skill is the skill's now.
 */
export function IdeaCard({
  item,
  busy,
  onCreate,
  onDecide,
}: {
  item: RejectedChange;
  busy: boolean;
  /** Given only to somebody who may create skills. */
  onCreate?: (skill: ProposedSkill) => Promise<boolean>;
  onDecide: (action: "dismiss" | "undo") => void;
}) {
  const t = useTranslations("authoring.rejected");
  const tSuggestion = useTranslations("authoring.suggestion");
  const { change } = item;
  return (
    <Card data-testid="idea">
      <CardContent className="space-y-2 pt-4 text-sm">
        <p className="font-mono break-words">{change.name}</p>
        {change.description && <p>{change.description}</p>}
        <p className="text-muted-foreground text-xs">{t(`reason.${item.reason}`)}</p>
        {item.skill_id ? (
          <p>
            {t("created")}{" "}
            <Link className="underline" href={`${ROUTES.SKILLS}/${item.skill_id}`}>
              {t("openSkill")}
            </Link>
          </p>
        ) : item.dismissed ? (
          <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecide("undo")}>
            {tSuggestion("undo")}
          </Button>
        ) : (
          <div className="flex flex-wrap gap-2">
            {onCreate && <CreateIdea change={change} onCreate={onCreate} />}
            <Button size="sm" variant="ghost" disabled={busy} onClick={() => onDecide("dismiss")}>
              {tSuggestion("dismiss")}
            </Button>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

function CreateIdea({
  change,
  onCreate,
}: {
  change: RejectedChange["change"];
  onCreate: (skill: ProposedSkill) => Promise<boolean>;
}) {
  const t = useTranslations("authoring.rejected");
  const [previewing, setPreviewing] = useState(false);
  return (
    <>
      <Button size="sm" onClick={() => setPreviewing(true)}>
        {t("createSkill")}
      </Button>
      {previewing && (
        <IdeaSkillDialog change={change} onCreate={onCreate} onOpenChange={setPreviewing} />
      )}
    </>
  );
}

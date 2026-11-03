"use client";

import { useState, type ReactNode } from "react";
import { useRouter } from "next/navigation";
import { AlertTriangle } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { toast } from "sonner";

import {
  Alert,
  AlertDescription,
  Button,
  Checkbox,
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  Label,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useSkillVersionWrites } from "@/hooks/use-skill-versions";
import { getErrorMessage } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { DIALOG_FORM } from "@/lib/dialog-sizes";
import type { BindingTarget } from "@/lib/skill-versions-api";
import type { SkillAgentUsage, SkillFork } from "@/types/skill-versions";
import { bindingLabel } from "./skill-lines";

/** Whether two bindings name the same thing to follow. */
function sameTarget(a: BindingTarget, b: BindingTarget): boolean {
  if (a.state === "pinned" && b.state === "pinned") return a.version === b.version;
  if (a.state === "fork" && b.state === "fork") return a.fork_id === b.fork_id;
  return a.state === b.state;
}

/**
 * Move one agent to main, a pinned main version, or a fork.
 *
 * It publishes a new version of the agent from its published one, with only this
 * binding changed, so nothing unfinished in its draft goes live. A version the
 * agent is not on now has not been checked on it, and the person says so before
 * the change is made.
 */
export function ChangeVersionDialog({
  skillId,
  skillName,
  usage,
  forks,
  mainLatest,
  onClose,
}: {
  skillId: string;
  skillName: string;
  usage: SkillAgentUsage;
  forks: SkillFork[];
  /** Main's newest version number. */
  mainLatest: number;
  onClose: () => void;
}) {
  const t = useTranslations("skills.page.changeVersion");
  const tPage = useTranslations("skills.page");
  const tErrors = useTranslations("errors");
  const locale = useLocale();
  const router = useRouter();
  const { changeBinding } = useSkillVersionWrites(skillId);
  const current: BindingTarget =
    usage.binding.state === "pinned"
      ? { state: "pinned", version: usage.binding.version.number }
      : usage.binding.state === "fork"
        ? { state: "fork", fork_id: usage.binding.fork?.id ?? "" }
        : { state: "main" };
  const [target, setTarget] = useState<BindingTarget>(current);
  const [understood, setUnderstood] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const unchanged = sameTarget(target, current);
  const name = usage.agent.name;
  const pinned = target.state === "pinned" ? String(target.version) : "";
  // Main numbers its versions from 1 without gaps, so every one of them can be pinned.
  const pinnable = Array.from({ length: mainLatest }, (_, index) => mainLatest - index);
  const firstPin = current.state === "pinned" ? current.version : pinnable[0];

  async function submit() {
    setError(null);
    try {
      const result = await changeBinding.mutateAsync({ agentId: usage.agent.id, target });
      if (result.published) {
        const list = new Intl.ListFormat(locale, { type: "conjunction" });
        toast.success(
          t("published", {
            name,
            environments: list.format(result.environments),
            count: result.environments.length,
          }),
        );
      } else {
        toast.info(t("savedInDraft", { name }), {
          action: {
            label: t("openBuilder"),
            onClick: () => router.push(ROUTES.AGENT_DETAIL(usage.agent.id)),
          },
        });
      }
      onClose();
    } catch (refusal) {
      setError(getErrorMessage(refusal, tErrors));
    }
  }

  const option = (choice: BindingTarget, label: string, extra?: ReactNode) => (
    <label className="flex items-start gap-2 text-sm">
      <input
        type="radio"
        name="skill-binding"
        className="mt-1"
        checked={
          target.state === choice.state && (choice.state !== "fork" || sameTarget(choice, target))
        }
        onChange={() => {
          setTarget(choice);
          setUnderstood(false);
        }}
      />
      <span className="min-w-0 flex-1 space-y-1.5">
        <span className="block">{label}</span>
        {extra}
      </span>
    </label>
  );

  return (
    <Dialog open onOpenChange={(open) => !open && onClose()}>
      <DialogContent className={DIALOG_FORM}>
        <DialogHeader>
          <DialogTitle>{t("title", { skill: skillName, name })}</DialogTitle>
          <DialogDescription>
            {t("now", { binding: bindingLabel(tPage, usage.binding) })}
          </DialogDescription>
        </DialogHeader>
        <fieldset className="space-y-3">
          <legend className="sr-only">{t("legend")}</legend>
          {option({ state: "main" }, t("followMain"))}
          {firstPin !== undefined &&
            option(
              { state: "pinned", version: firstPin },
              t("pin"),
              target.state === "pinned" && (
                <Select
                  value={pinned}
                  onValueChange={(value) => setTarget({ state: "pinned", version: Number(value) })}
                >
                  <SelectTrigger className="w-40" aria-label={t("pinVersion")}>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {pinnable.map((number) => (
                      <SelectItem key={number} value={String(number)}>
                        {t("versionOption", { number })}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              ),
            )}
          {forks.map((fork) => (
            <div key={fork.id}>
              {option({ state: "fork", fork_id: fork.id }, t("fork", { name: fork.name }))}
            </div>
          ))}
        </fieldset>
        {!unchanged && (
          <Alert variant="warning">
            <AlertTriangle className="h-4 w-4" />
            <AlertDescription className="space-y-2">
              <p>{t("unchecked", { name })}</p>
              <div className="flex items-center gap-2">
                <Checkbox
                  id="skill-binding-understood"
                  checked={understood}
                  onCheckedChange={(checked) => setUnderstood(checked === true)}
                />
                <Label htmlFor="skill-binding-understood">{t("understood")}</Label>
              </div>
            </AlertDescription>
          </Alert>
        )}
        <p className="text-muted-foreground text-sm">
          {usage.can_publish ? t("publishes", { name }) : t("savesToDraft", { name })}
        </p>
        {error !== null && (
          <p role="alert" className="text-destructive text-sm">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose}>
            {t("cancel")}
          </Button>
          <Button
            onClick={() => void submit()}
            disabled={unchanged || !understood}
            loading={changeBinding.isPending}
          >
            {usage.can_publish ? t("submit") : t("submitDraft")}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

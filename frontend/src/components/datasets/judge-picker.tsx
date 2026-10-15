"use client";

import Link from "next/link";
import { Plus } from "lucide-react";
import { useTranslations } from "next-intl";

import {
  Button,
  FormField,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui";
import { useJudges } from "@/hooks/use-agents";
import { ROUTES } from "@/lib/constants";

/** The select's value for the default judge, which a dataset names as null. */
const DEFAULT = "default";

interface JudgePickerProps {
  /** The judge picked in the draft; null is the default one. */
  value: string | null;
  onChange: (agentId: string | null) => void;
  disabled: boolean;
  /** Opens the dialog creating a judge of the dataset's own; absent for who may not. */
  onCreate?: () => void;
}

/**
 * Which judge grades the dataset: the default one, or a judge of the organization's.
 *
 * The picked judge links to its page, where its prompt and model are edited. A
 * judge picked once and deleted since is still shown, so the gap reads as one.
 */
export function JudgePicker({ value, onChange, disabled, onCreate }: JudgePickerProps) {
  const t = useTranslations("datasets.scoring");
  const { agents: judges } = useJudges();
  const seeded = judges.find((judge) => judge.system_key != null);
  const own = judges.filter((judge) => judge.system_key == null);
  const picked = value === null ? seeded : judges.find((judge) => judge.id === value);

  return (
    <div className="flex flex-wrap items-end gap-2">
      <FormField htmlFor="grading-judge" label={t("judgePick")} className="min-w-64 flex-1">
        <Select
          value={value ?? DEFAULT}
          onValueChange={(next) => onChange(next === DEFAULT ? null : next)}
          disabled={disabled}
        >
          <SelectTrigger id="grading-judge">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={DEFAULT}>
              {seeded ? t("judgeDefaultNamed", { name: seeded.name }) : t("judgeDefault")}
            </SelectItem>
            {own.map((judge) => (
              <SelectItem key={judge.id} value={judge.id}>
                {judge.name}
              </SelectItem>
            ))}
            {value !== null && picked === undefined && (
              <SelectItem value={value}>{t("judgeGone")}</SelectItem>
            )}
          </SelectContent>
        </Select>
      </FormField>
      {picked && (
        <Button variant="link" size="sm" asChild>
          <Link href={ROUTES.AGENT_DETAIL(picked.id)}>{t("judgeOpen")}</Link>
        </Button>
      )}
      {onCreate && (
        <Button variant="outline" size="sm" onClick={onCreate} disabled={disabled}>
          <Plus className="h-4 w-4" />
          {t("createJudgeForDataset")}
        </Button>
      )}
    </div>
  );
}

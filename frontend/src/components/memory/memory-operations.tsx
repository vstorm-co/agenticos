"use client";

import { useId, useState } from "react";
import { useTranslations } from "next-intl";
import { MemberPicker } from "@/components/orgs/member-picker";
import { Button, Input, NativeSelect } from "@/components/ui";
import { useMembers } from "@/hooks/use-members";
import {
  useMemoryInboxDecisions,
  useMemoryInboxRule,
  useMemoryObjectBackfill,
} from "@/hooks/use-memory-operations";
import { MEMORY_INBOX_MODES, MEMORY_INBOX_SOURCES, type MemoryInboxRule } from "@/lib/memory-api";
import { useOrgStore } from "@/stores";

export function MemoryOperations() {
  const t = useTranslations("pages.memory.operations");
  const org = useOrgStore((state) => state.activeOrgId) ?? "";
  const { rule, save } = useMemoryInboxRule(org);
  return (
    <section className="grid gap-4 rounded-md border p-3 lg:grid-cols-2" aria-label={t("title")}>
      <div className="space-y-3">
        <h2 className="text-sm font-medium">{t("inbox")}</h2>
        {rule.isPending && <p role="status">{t("loading")}</p>}
        {rule.isError && <p role="alert">{t("loadFailed")}</p>}
        {rule.data && (
          <>
            <InboxRuleForm
              key={rule.data.version}
              org={org}
              current={rule.data}
              save={(draft) => save.mutate(draft)}
              pending={save.isPending}
              failed={save.isError}
              reload={() => {
                save.reset();
                void rule.refetch();
              }}
            />
            {rule.data.version > 0 && <InboxDecisions org={org} version={rule.data.version} />}
          </>
        )}
      </div>
      <ObjectBackfill org={org} />
    </section>
  );
}

function InboxRuleForm({
  org,
  current,
  save,
  pending,
  failed,
  reload,
}: {
  org: string;
  current: MemoryInboxRule;
  save: (rule: MemoryInboxRule) => void;
  pending: boolean;
  failed: boolean;
  reload: () => void;
}) {
  const t = useTranslations("pages.memory.operations");
  const formId = useId();
  const [draft, setDraft] = useState(current);
  const { members, error } = useMembers(org);
  const invalid = draft.mode !== "off" && (!draft.recipient_ids.length || !draft.sources.length);
  return (
    <form
      className="space-y-2"
      aria-labelledby={formId}
      onSubmit={(event) => {
        event.preventDefault();
        if (!invalid) save(draft);
      }}
    >
      <fieldset disabled={pending} className="space-y-2">
        <legend id={formId} className="text-muted-foreground text-xs">
          {t("inboxHint")}
        </legend>
        <label className="grid gap-1 text-sm">
          {t("modeLabel")}
          <NativeSelect
            name="mode"
            value={draft.mode}
            onChange={(event) => {
              const mode = MEMORY_INBOX_MODES.find((value) => value === event.target.value);
              if (mode) setDraft({ ...draft, mode });
            }}
          >
            {MEMORY_INBOX_MODES.map((mode) => (
              <option key={mode} value={mode}>
                {t(mode)}
              </option>
            ))}
          </NativeSelect>
        </label>
        <fieldset className="flex flex-wrap gap-2">
          <legend className="text-sm">{t("sources")}</legend>
          {MEMORY_INBOX_SOURCES.map((source) => (
            <label key={source} className="flex items-center gap-1 text-sm">
              <input
                type="checkbox"
                name="sources"
                value={source}
                checked={draft.sources.includes(source)}
                onChange={(event) =>
                  setDraft({
                    ...draft,
                    sources: event.target.checked
                      ? [...draft.sources, source]
                      : draft.sources.filter((item) => item !== source),
                  })
                }
              />
              {t(source)}
            </label>
          ))}
        </fieldset>
        <MemberPicker
          members={members}
          selected={draft.recipient_ids}
          onToggle={(id) => {
            const selected = draft.recipient_ids.includes(id);
            if (selected || draft.recipient_ids.length < 50) {
              setDraft({
                ...draft,
                recipient_ids: selected
                  ? draft.recipient_ids.filter((item) => item !== id)
                  : [...draft.recipient_ids, id],
              });
            }
          }}
          label={(count) => t("recipients", { count })}
          scope={t("inbox")}
        />
        {error && <p role="alert">{t("loadFailed")}</p>}
        <label className="flex items-center gap-2 text-sm">
          <input
            type="checkbox"
            name="include_review"
            checked={draft.include_review}
            onChange={(event) => setDraft({ ...draft, include_review: event.target.checked })}
          />
          {t("includeReview")}
        </label>
      </fieldset>
      {invalid && <p className="text-muted-foreground text-sm">{t("ruleRequired")}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" size="sm" disabled={pending || invalid}>
          {t("save")}
        </Button>
        {failed && (
          <Button type="button" variant="outline" size="sm" onClick={reload}>
            {t("reload")}
          </Button>
        )}
      </div>
      {failed && (
        <p role="alert" className="text-destructive text-sm">
          {t("saveFailed")}
        </p>
      )}
    </form>
  );
}

function InboxDecisions({ org, version }: { org: string; version: number }) {
  const t = useTranslations("pages.memory.operations");
  const [selected, setSelected] = useState(version);
  const results = useMemoryInboxDecisions(org, selected);
  return (
    <div className="space-y-2">
      <h3 className="text-sm font-medium">{t("outcomes")}</h3>
      <div className="flex items-end gap-2">
        <label className="grid gap-1 text-sm">
          {t("version")}
          <Input
            type="number"
            min={1}
            max={version}
            value={selected || ""}
            onChange={(event) => setSelected(Number(event.target.value) || 0)}
            className="w-24"
          />
        </label>
        <Button
          variant="outline"
          size="sm"
          disabled={!selected}
          onClick={() => void results.refetch()}
        >
          {t("reload")}
        </Button>
      </div>
      {results.isError && <p role="alert">{t("loadFailed")}</p>}
      {results.data?.length === 0 && (
        <p className="text-muted-foreground text-sm">{t("noOutcomes")}</p>
      )}
      <ul className="space-y-1 text-sm">
        {results.data?.map(({ change, outcome, count }) => (
          <li key={`${change}:${outcome}`}>{t("outcome", { change, outcome, count })}</li>
        ))}
      </ul>
    </div>
  );
}

function ObjectBackfill({ org }: { org: string }) {
  const t = useTranslations("pages.memory.operations");
  const { backfill, run } = useMemoryObjectBackfill(org);
  const state = backfill.data;
  return (
    <section className="space-y-2">
      <h2 className="text-sm font-medium">{t("backfill")}</h2>
      <p className="text-muted-foreground text-sm">{t("backfillHint")}</p>
      {state && (
        <p className="text-sm">
          {t("progress", { scanned: state.scanned, linked: state.linked })}
          {state.completed_at && ` · ${t("completed")}`}
        </p>
      )}
      <Button
        size="sm"
        variant="outline"
        disabled={backfill.isPending || backfill.isError || run.isPending}
        onClick={() => run.mutate(Boolean(state?.completed_at))}
      >
        {t(!state ? "start" : state.completed_at ? "restart" : "resume")}
      </Button>
      {(backfill.isError || run.isError) && (
        <p role="alert" className="text-destructive text-sm">
          {t("backfillFailed")}
        </p>
      )}
    </section>
  );
}

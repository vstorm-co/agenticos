"use client";

import { useId, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Box, Brain, FileText } from "lucide-react";
import { useFormatter, useTranslations } from "next-intl";
import { ErrorState, LoadingState } from "@/components/states";
import { Button, Input, ListCard, ListCardEmpty, SearchInput } from "@/components/ui";
import {
  amendHistoricalClaim,
  getMemoryClaimDetail,
  getMemoryObjects,
  getMemoryTimeline,
  getSharedClaims,
  getSharedNotes,
  type DecisionEpisode,
  type MemoryClaim,
  type MemoryLibrary,
  type MemoryObjectKind,
} from "@/lib/memory-api";
import { qk } from "@/lib/query-keys";
import { useOrgStore } from "@/stores";
import { ClaimEditor } from "./claim-editor";
import { MemoryPager, MemoryRow } from "./memory-list";

const KINDS = ["all", "person", "company", "project", "commitment"] as const;

export function ClaimSources({ library, claimId }: { library: MemoryLibrary; claimId: string }) {
  const t = useTranslations("pages.memory.library");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const { data, isPending, error } = useQuery({
    queryKey: [...qk.memory.all(org), "detail", library, claimId],
    queryFn: () => getMemoryClaimDetail(library, claimId),
  });
  if (isPending) return <p className="text-muted-foreground text-sm">{t("loadingEvidence")}</p>;
  if (error || !data) return <p role="alert">{t("evidenceUnavailable")}</p>;
  if (!data.sources.length && !data.evidence.length && !data.superseded && !data.withheld)
    return null;
  return (
    <section className="space-y-2">
      <h4 className="text-sm font-medium">{t("evidence")}</h4>
      {data.evidence.map((source) => (
        <blockquote className="border-s-2 ps-2 text-sm wrap-anywhere" key={source.source_id}>
          {source.quote}
          <footer className="text-muted-foreground text-xs">
            {source.kind === "gmail" ? t("gmailSource") : source.source_id}
          </footer>
        </blockquote>
      ))}
      {data.sources.map((source) => (
        <p key={source.id} className="text-muted-foreground text-sm wrap-anywhere">
          {source.statement}
        </p>
      ))}
      {data.superseded && (
        <p className="text-muted-foreground text-sm wrap-anywhere">
          {t("previous", { statement: data.superseded.statement })}
        </p>
      )}
      {!!data.withheld && <p className="text-muted-foreground text-sm">{t("withheld")}</p>}
    </section>
  );
}

function TimelineClaim({
  library,
  claim,
  snapshot,
}: {
  library: MemoryLibrary;
  claim: MemoryClaim;
  snapshot?: boolean;
}) {
  const t = useTranslations("pages.memory.library");
  const status = useTranslations("pages.memory.claims.status");
  const format = useFormatter();
  const [opened, setOpened] = useState(false);
  const [openedAt] = useState(() => Date.now());
  const date = (value: string | null) =>
    value
      ? format.dateTime(new Date(value), { dateStyle: "medium", timeZone: "UTC" })
      : t("unknown");
  return (
    <details className="space-y-2 py-3" onToggle={(event) => setOpened(event.currentTarget.open)}>
      <summary className="cursor-pointer text-sm wrap-anywhere">{claim.statement}</summary>
      <p className="text-muted-foreground text-xs">
        {t("validity", { start: date(claim.effective_from), end: date(claim.effective_to) })}
        {" · "}
        {snapshot ? t("historical") : status(claim.status)}
      </p>
      {opened && <ClaimSources library={library} claimId={claim.id} />}
      {opened &&
        !snapshot &&
        library === "personal" &&
        ["current", "disputed", "superseded"].includes(claim.status) &&
        claim.effective_from &&
        claim.effective_to &&
        Date.parse(claim.effective_to) <= openedAt &&
        Date.parse(claim.effective_from) < Date.parse(claim.effective_to) && (
          <HistoricalCorrection claim={claim} />
        )}
    </details>
  );
}

function HistoricalCorrection({ claim }: { claim: MemoryClaim }) {
  const t = useTranslations("pages.memory.claims");
  const errors = useTranslations("errors");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const client = useQueryClient();
  const [editing, setEditing] = useState(false);
  const save = useMutation({
    mutationFn: ({ statement, episode }: { statement: string; episode?: DecisionEpisode }) =>
      amendHistoricalClaim(claim.id, statement, episode),
    onSuccess: async () => {
      await client.invalidateQueries({ queryKey: qk.memory.all(org) });
      setEditing(false);
    },
  });
  if (!editing) {
    return (
      <Button size="sm" variant="outline" onClick={() => setEditing(true)}>
        {t("correct")}
      </Button>
    );
  }
  return (
    <>
      <ClaimEditor
        claim={claim}
        historical
        onCancel={() => {
          save.reset();
          setEditing(false);
        }}
        onSave={async (statement, _date, episode) => {
          await save.mutateAsync({ statement, episode }).catch(() => undefined);
        }}
      />
      {save.error && (
        <p role="alert" className="text-sm">
          {errors("unexpected")}
        </p>
      )}
    </>
  );
}

function ObjectTimeline({
  library,
  objectId,
  onClose,
}: {
  library: MemoryLibrary;
  objectId: string;
  onClose: () => void;
}) {
  const t = useTranslations("pages.memory.library");
  const asOfId = useId();
  const knownAtId = useId();
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const [asOf, setAsOf] = useState("");
  const [knownAt, setKnownAt] = useState("");
  const [cursor, setCursor] = useState<string | null>(null);
  const timeline = useQuery({
    queryKey: [...qk.memory.all(org), "timeline", library, objectId, asOf, knownAt, cursor],
    queryFn: () => getMemoryTimeline(library, objectId, asOf, knownAt, cursor),
  });
  return (
    <ListCard
      fill
      title={timeline.data?.object.name ?? t("timeline")}
      controls={
        <Button variant="outline" onClick={onClose}>
          {t("back")}
        </Button>
      }
    >
      <fieldset className="grid gap-3 border-b px-3 pb-3 sm:grid-cols-2">
        <legend className="sr-only">{t("timeline")}</legend>
        <div className="space-y-1">
          <label htmlFor={asOfId} className="text-muted-foreground text-xs">
            {t("effectiveDate")}
          </label>
          <Input
            id={asOfId}
            type="date"
            value={asOf}
            onChange={(event) => {
              setAsOf(event.target.value);
              if (!event.target.value) setKnownAt("");
              setCursor(null);
            }}
          />
        </div>
        <div className="space-y-1">
          <label htmlFor={knownAtId} className="text-muted-foreground text-xs">
            {t("knowledgeDate")}
          </label>
          <Input
            id={knownAtId}
            type="date"
            disabled={!asOf}
            value={knownAt}
            onChange={(event) => {
              setKnownAt(event.target.value);
              setCursor(null);
            }}
          />
        </div>
      </fieldset>
      {timeline.isPending ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : timeline.error ? (
        <ErrorState />
      ) : !timeline.data?.items.length ? (
        <ListCardEmpty icon={Brain} title={t("emptyTimeline")} />
      ) : (
        <div className="divide-border min-h-0 flex-1 divide-y overflow-auto px-3">
          {timeline.data.items.map((claim) => (
            <TimelineClaim
              key={claim.id}
              claim={claim}
              library={library}
              snapshot={Boolean(asOf)}
            />
          ))}
        </div>
      )}
      <CursorControls cursor={cursor} next={timeline.data?.next_cursor} onPage={setCursor} />
    </ListCard>
  );
}

function CursorControls({
  cursor,
  next,
  onPage,
}: {
  cursor: string | null;
  next?: string | null;
  onPage: (cursor: string | null) => void;
}) {
  const t = useTranslations("pages.memory.library");
  if (!cursor && !next) return null;
  return (
    <div className="flex gap-2 border-t px-3 py-2">
      {cursor && (
        <Button variant="ghost" onClick={() => onPage(null)}>
          {t("firstPage")}
        </Button>
      )}
      {next && (
        <Button variant="outline" onClick={() => onPage(next)}>
          {t("nextPage")}
        </Button>
      )}
    </div>
  );
}

export function MemoryObjectLibrary({
  library,
  initialObject,
}: {
  library: MemoryLibrary;
  initialObject?: string;
}) {
  const t = useTranslations("pages.memory.library");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const [q, setQ] = useState("");
  const [kind, setKind] = useState<MemoryObjectKind | "all">("all");
  const [cursor, setCursor] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(initialObject ?? null);
  const objects = useQuery({
    queryKey: [...qk.memory.all(org), "objects", library, q, kind, cursor],
    queryFn: () => getMemoryObjects(library, q.trim(), kind, cursor),
    enabled: !selected,
  });
  if (selected)
    return (
      <ObjectTimeline library={library} objectId={selected} onClose={() => setSelected(null)} />
    );
  return (
    <ListCard
      fill
      title={t("objects")}
      controls={
        <search className="flex flex-wrap gap-2" aria-label={t("searchObjects")}>
          <SearchInput
            value={q}
            onChange={(value) => {
              setQ(value);
              setCursor(null);
            }}
            maxLength={160}
            placeholder={t("searchObjects")}
          />
          <div className="flex flex-wrap gap-1">
            {KINDS.map((value) => (
              <Button
                key={value}
                size="sm"
                variant={kind === value ? "secondary" : "ghost"}
                aria-pressed={kind === value}
                onClick={() => {
                  setKind(value);
                  setCursor(null);
                }}
              >
                {t(`kind.${value}`)}
              </Button>
            ))}
          </div>
        </search>
      }
    >
      {objects.isPending ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : objects.error ? (
        <ErrorState />
      ) : !objects.data?.items.length ? (
        <ListCardEmpty icon={Box} title={t("emptyObjects")} />
      ) : (
        <ul className="divide-border min-h-0 flex-1 divide-y overflow-auto">
          {objects.data.items.map((item) => (
            <MemoryRow
              key={item.id}
              title={item.name}
              icon={Box}
              onOpen={() => setSelected(item.id)}
            >
              {t(`kind.${item.kind}`)}
            </MemoryRow>
          ))}
        </ul>
      )}
      <CursorControls cursor={cursor} next={objects.data?.next_cursor} onPage={setCursor} />
    </ListCard>
  );
}

export function SharedMemoryClaims() {
  const t = useTranslations("pages.memory.library");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const [q, setQ] = useState("");
  const [skip, setSkip] = useState(0);
  const page = useQuery({
    queryKey: [...qk.memory.all(org), "shared-claims", q, skip],
    queryFn: () => getSharedClaims(q, skip),
  });
  return (
    <ListCard
      fill
      title={t("sharedClaims")}
      controls={
        <SearchInput
          value={q}
          onChange={(value) => {
            setQ(value);
            setSkip(0);
          }}
          maxLength={200}
          placeholder={t("searchShared")}
        />
      }
    >
      {page.isPending ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : page.error ? (
        <ErrorState />
      ) : !page.data?.items.length ? (
        <ListCardEmpty icon={Brain} title={t("emptyClaims")} />
      ) : (
        <div className="divide-border min-h-0 flex-1 divide-y overflow-auto px-3">
          {page.data.items.map((claim) => (
            <TimelineClaim key={claim.id} library="organization" claim={claim} />
          ))}
        </div>
      )}
      {page.data && !page.error && (
        <MemoryPager
          skip={skip}
          count={page.data.items.length}
          total={page.data.total}
          size={30}
          onPage={setSkip}
        />
      )}
    </ListCard>
  );
}

export function SharedMemoryNotes() {
  const t = useTranslations("pages.memory.library");
  const org = useOrgStore((state) => state.activeOrgId) ?? "current";
  const [cursor, setCursor] = useState<string | null>(null);
  const page = useQuery({
    queryKey: [...qk.memory.all(org), "shared-notes", cursor],
    queryFn: () => getSharedNotes(cursor),
  });
  return (
    <ListCard fill title={t("sharedNotes")}>
      {page.isPending ? (
        <LoadingState variant="skeleton-list" rows={3} />
      ) : page.error ? (
        <ErrorState />
      ) : !page.data?.items.length ? (
        <ListCardEmpty icon={FileText} title={t("emptyNotes")} />
      ) : (
        <div className="divide-border min-h-0 flex-1 divide-y overflow-auto px-3">
          {page.data.items.map((note) => (
            <details className="space-y-2 py-3" key={note.id}>
              <summary className="cursor-pointer text-sm wrap-anywhere">{note.name}</summary>
              <p className="text-sm wrap-anywhere whitespace-pre-wrap">{note.content}</p>
            </details>
          ))}
        </div>
      )}
      <CursorControls cursor={cursor} next={page.data?.next_cursor} onPage={setCursor} />
    </ListCard>
  );
}

"use client";

import { useTranslations } from "next-intl";

import type {
  AnyBindingParts,
  ArtifactDisclosure,
  BindingParts,
  DisclosedDerivation,
  WorkflowLogParts,
} from "@/types/artifact";

type Translate = ReturnType<typeof useTranslations>;

/** One operand as the server words it: text in quotes, a list joined. */
function operand(value: BindingParts["filters"][number]["value"]): string {
  return Array.isArray(value)
    ? value.map((item) => JSON.stringify(item)).join(", ")
    : JSON.stringify(value);
}

export function derivation(t: Translate, derived: DisclosedDerivation): string {
  const table = derived.table ?? "";
  switch (derived.kind) {
    case "formula":
      return derived.inputs.length > 0
        ? t("parts.formula", { inputs: derived.inputs.join(", ") })
        : t("parts.formulaBare");
    case "link":
      return derived.column === null
        ? t("parts.linkIds", { table })
        : t("parts.link", { table, column: derived.column });
    case "lookup":
      return t("parts.lookup", { table, column: derived.column ?? "?" });
    case "rollup":
      return derived.aggregate === "count"
        ? t("parts.rollupCount", { table })
        : t("parts.rollup", {
            aggregate: derived.aggregate ?? "count",
            table,
            column: derived.column ?? "?",
          });
  }
}

export function condition(t: Translate, filter: BindingParts["filters"][number]): string {
  if (filter.op === "is_null") {
    return t(filter.value ? "parts.isEmpty" : "parts.notEmpty", { column: filter.column });
  }
  return t("parts.filterOp", {
    column: filter.column,
    op: filter.op,
    value: operand(filter.value),
  });
}

export function order(t: Translate, sort: BindingParts["sort"]): string {
  if (sort.record_time !== null) {
    return t("parts.sortRecordTime", { time: sort.record_time, direction: sort.direction });
  }
  const column = sort.column ?? "";
  return sort.derived === null
    ? t("parts.sortColumn", { column, direction: sort.direction })
    : t("parts.sortDerived", {
        column,
        derived: derivation(t, sort.derived),
        direction: sort.direction,
      });
}

/** One field in words: the name the page reads it by, and what it reads. */
export function fieldInWords(
  t: Translate,
  types: Translate,
  item: BindingParts["fields"][number],
): string {
  return t("field", {
    field: item.name,
    reads:
      item.derived === null
        ? t("parts.fieldPlain", { column: item.column, type: types(item.type) })
        : t("parts.fieldDerived", { column: item.column, derived: derivation(t, item.derived) }),
  });
}

/** What a log query keeps, one condition each: the step, the outcomes, the run. */
function logConditions(t: Translate, query: WorkflowLogParts): string[] {
  return [
    ...(query.step === null ? [] : [t("log.step", { step: query.step })]),
    ...(query.outcomes.length === 0
      ? []
      : [t("log.outcomes", { outcomes: query.outcomes.join(", ") })]),
    ...(query.run === null ? [] : [t("log.run", { run: query.run })]),
  ];
}

/** What a log query keeps as a sentence, and whether it reads test runs. */
export function logKeeps(t: Translate, query: WorkflowLogParts): string {
  const conditions = logConditions(t, query);
  const lines =
    conditions.length === 0
      ? t("log.allLines")
      : t("log.filters", { conditions: conditions.join("; ") });
  return `${lines} ${t(query.include_test ? "log.testsIncluded" : "log.testsLeftOut")}`;
}

/** What a log query serves: the newest lines, or counts per day. */
export function logServes(t: Translate, query: WorkflowLogParts): string {
  return query.mode === "lines"
    ? t("log.lines", { count: query.lines ?? 0 })
    : t("log.perDay", { days: query.days ?? 0, tz: query.tz ?? "UTC" });
}

/** A log query on one line, for a change that says what it was and what it is. */
export function logInWords(t: Translate, query: WorkflowLogParts): string {
  return t("log.summary", {
    workflow: query.workflow,
    keeps: logKeeps(t, query),
    serves: logServes(t, query),
  });
}

/** One workflow-log query in words: its workflow, what it keeps and what it serves. */
function LogQueryInWords({ name, query }: { name: string; query: WorkflowLogParts }) {
  const t = useTranslations("artifacts.consent");
  return (
    <li className="space-y-1 rounded-md border p-3">
      <p className="font-medium">{t("bindingLog", { name, workflow: query.workflow })}</p>
      <p className="text-muted-foreground">{logKeeps(t, query)}</p>
      <p className="text-muted-foreground">{logServes(t, query)}</p>
    </li>
  );
}

/**
 * One page query in words: its table, what it filters on, its order, its limit,
 * its fields and the tables it reaches through links - from the server's parts,
 * worded in the reader's language.
 */
export function QueryInWords({ name, query }: { name: string; query: AnyBindingParts }) {
  const t = useTranslations("artifacts.consent");
  const types = useTranslations("tables.schema.types");
  if (query.kind === "workflow_log") return <LogQueryInWords name={name} query={query} />;
  return (
    <li className="space-y-1 rounded-md border p-3">
      <p className="font-medium">{t("bindingTable", { name, table: query.table })}</p>
      <p className="text-muted-foreground">
        {query.filters.length === 0
          ? t("noFilters")
          : t("filters", {
              conditions: query.filters.map((item) => condition(t, item)).join("; "),
            })}
      </p>
      <p className="text-muted-foreground">
        {t("sortAndLimit", { sort: order(t, query.sort), limit: query.limit })}
      </p>
      <ul className="list-disc pl-5">
        {query.fields.map((item) => (
          <li key={item.name}>{fieldInWords(t, types, item)}</li>
        ))}
      </ul>
      {query.linked.length > 0 && (
        <p className="text-muted-foreground">
          {t("parts.linkedTables", { tables: query.linked.join(", ") })}
        </p>
      )}
    </li>
  );
}

/**
 * Who reads the data once it is confirmed: the roles that open every page, by
 * name, then the page's visibility and the people and groups it is shared with -
 * now and whoever joins them later.
 */
function Audience({ disclosure }: { disclosure: ArtifactDisclosure }) {
  const t = useTranslations("artifacts.consent");
  const roles = useTranslations("dashboard.widgets.members.roles");
  return (
    <div className="space-y-1">
      <p className="font-medium">{t("audienceTitle")}</p>
      <ul className="text-muted-foreground list-disc space-y-0.5 pl-5">
        <li>
          {t("audienceRoles", { roles: disclosure.roles.map((role) => roles(role)).join(", ") })}
        </li>
        <li>{t("audienceVisibility", { visibility: disclosure.visibility })}</li>
        {disclosure.people.length > 0 && (
          <li>{t("audiencePeople", { people: disclosure.people.join(", ") })}</li>
        )}
        {disclosure.groups.length > 0 && (
          <li>{t("audienceGroups", { groups: disclosure.groups.join(", ") })}</li>
        )}
      </ul>
    </div>
  );
}

/** The page queries and the tables they read, without the members' audience. */
export function ConsentQueries({ disclosure }: { disclosure: ArtifactDisclosure }) {
  const t = useTranslations("artifacts.consent");
  return (
    <>
      <ul className="space-y-2">
        {Object.entries(disclosure.parts).map(([name, query]) => (
          <QueryInWords key={name} name={name} query={query} />
        ))}
      </ul>
      {disclosure.tables.length > 0 && (
        <p>{t("tablesRead", { tables: disclosure.tables.join(", ") })}</p>
      )}
    </>
  );
}

/**
 * What confirming a version shares and with whom: the queries - each as its owner
 * reads the tables now - and the audience, worded by the console in the reader's
 * language from the server's parts. Filters may name columns no field shows, and a worked-out field says
 * what it is made from, so everything the records reveal is on this page.
 */
export function ConsentDisclosure({ disclosure }: { disclosure: ArtifactDisclosure }) {
  return (
    <div className="space-y-4 text-sm">
      <ConsentQueries disclosure={disclosure} />
      <Audience disclosure={disclosure} />
    </div>
  );
}

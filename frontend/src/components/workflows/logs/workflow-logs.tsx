"use client";

import { useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import { ListFilter, X } from "lucide-react";
import { useLocale, useTranslations } from "next-intl";

import { EmptyState, ErrorState } from "@/components/states";
import {
  Badge,
  Button,
  Column,
  DataTable,
  Input,
  Label,
  ListCard,
  PaginationBar,
  SearchInput,
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
  Switch,
  useDebounced,
} from "@/components/ui";
import {
  useNodeCatalog,
  useUrlList,
  useUrlState,
  useWorkflow,
  useWorkflowLogs,
  useWorkflowVersion,
} from "@/hooks";
import { fieldProblems } from "@/lib/api-error";
import { ROUTES } from "@/lib/constants";
import { formatDateTimeSeconds } from "@/lib/utils";
import { LogAlerts } from "./log-alerts";
import { outcomeLabels } from "./outcome-labels";
import { LOG_PAGE } from "@/lib/workflows/logs-api";
import { effectiveDefinition, ERROR_PORT } from "@/lib/workflows/ports";
import { nodeDisplayName, type NodeInstance, type WorkflowLogEntry } from "@/lib/workflows/types";

// Not port ids: a port may be called anything, and the NUL character is not a name.
const ALL = "\u0000all";
/** The outcome filter's value while the address names several outcomes. */
const MANY = "\u0000many";
const HOUR_MS = 3_600_000;
/** How far back each "written within" choice reaches. */
const SINCE_MS: Record<string, number> = {
  "1h": HOUR_MS,
  "24h": 24 * HOUR_MS,
  "7d": 7 * 24 * HOUR_MS,
  "30d": 30 * 24 * HOUR_MS,
};

/**
 * One workflow's log: the lines its steps' quick logs wrote, newest first, a page
 * at a time, narrowed by step, outcome, how recently and the text of the message -
 * every filter applied on the server, all but the text kept in the address. Lines from test runs
 * are left out until asked for. A row opens the run that wrote it.
 */
export function WorkflowLogs({ workflowId }: { workflowId: string }) {
  const t = useTranslations("pages.workflows");
  const locale = useLocale();
  const router = useRouter();
  const { workflow } = useWorkflow(workflowId);
  const { nodes: catalog } = useNodeCatalog();
  const [step, setStep] = useUrlState("step");
  // Repeated when a link carries several: an alert's counts every one of its outcomes.
  const [outcomes, setOutcomes] = useUrlList("outcome");
  const [since, setSince] = useUrlState("since");
  const [test, setTest] = useUrlState("test");
  const [run, setRun] = useUrlState("run");
  const [pageParam, setPage] = useUrlState("page");
  // What "the last 24 hours" counts back from: the page's opening, or the moment
  // the choice was made - not each render, which would make every read a new query.
  const [anchor, setAnchor] = useState(() => Date.now());
  const reach = since === null ? undefined : SINCE_MS[since];
  const page = Math.max(0, Number(pageParam ?? "0") || 0);
  // A request, not a filter: the log is paged by the database. Kept out of the
  // address, which would be rewritten on every pause in typing.
  const [typed, setTyped] = useState("");
  const searched = useDebounced(typed).trim();
  // The run field is the address's own value, so a link to a run's lines and a
  // typed id are the same thing; the query waits for typing to pause.
  // A value chosen, not typed (a row's action, the x), has nothing to wait out: it
  // applies at once and settles at once, so typing right after it starts from it.
  const [picked, setPicked] = useState<string | null>(null);
  const instant = picked !== null && picked === (run ?? "");
  const settledRun = useDebounced(run ?? "", instant ? 0 : 300);
  const searchedRun = instant ? (run ?? "") : settledRun;

  const { entries, total, isLoading, error, refetch } = useWorkflowLogs({
    workflowId,
    nodeInstanceId: step ?? undefined,
    outcomes: outcomes.length === 0 ? undefined : outcomes,
    from: reach === undefined ? undefined : new Date(anchor - reach).toISOString(),
    q: searched === "" ? undefined : searched,
    run: searchedRun === "" ? undefined : searchedRun,
    includeTest: test === "1",
    page,
  });

  // The steps that log, and the ways they leave by: what the filters offer. The
  // draft's and the live version's both, so a step still live but gone from the
  // draft is offered while its lines are still being written.
  const { version } = useWorkflowVersion(workflowId, workflow?.current_version_id ?? null);
  const { steps, ports, stepPorts, labels } = useMemo(() => {
    const instances = new Map<string, NodeInstance>();
    for (const graph of [workflow?.draft_graph, version?.graph]) {
      for (const node of graph?.nodes ?? []) {
        if (node.quick_log && !instances.has(node.id)) instances.set(node.id, node);
      }
    }
    const ports = new Set<string>([ERROR_PORT]);
    // Per step, the ways its quick log writes a line: `error` always, and the ports
    // it logs - every output port unless the log names some.
    const stepPorts = new Map<string, string[]>();
    const labelOf = new Map<string, string>();
    const named = [...instances.values()].map((node) => {
      const definition = catalog.find(
        (entry) => entry.id === node.definition_id && entry.version === node.definition_version,
      );
      const own = [ERROR_PORT];
      if (definition !== undefined) {
        const logged = node.quick_log?.outputs;
        for (const port of effectiveDefinition(node, definition).ports) {
          if (port.kind !== "output") continue;
          ports.add(port.id);
          if (logged == null || logged.includes(port.id)) own.push(port.id);
        }
      }
      stepPorts.set(node.id, own);
      for (const [id, label] of outcomeLabels(node, definition)) {
        if (!labelOf.has(id)) labelOf.set(id, label);
      }
      const name = nodeDisplayName(
        definition?.name ?? node.definition_id,
        node.id,
        true,
        node.label,
      );
      return [node.id, name] as [string, string];
    });
    return { steps: named, ports: [...ports], stepPorts, labels: labelOf };
  }, [workflow, version, catalog]);
  // A value the address carries stays an option when no graph has it any more, so
  // the select never reads blank: named by a line that step wrote, else as it is.
  const stepOptions: [string, string][] =
    step === null || steps.some(([id]) => id === step)
      ? steps
      : [
          ...steps,
          [step, entries.find((entry) => entry.node_instance_id === step)?.step_label ?? step],
        ];
  // Values the address carries stay options when no graph has them. Several at once
  // (an alert's link) read as one option naming them all, until another is chosen.
  const single = outcomes.length === 1 ? (outcomes[0] as string) : null;
  const outcomeOptions: [string, string][] = (
    single === null || ports.includes(single) ? ports : [...ports, single]
  ).map((port) => [port, labels.get(port) ?? port]);
  if (outcomes.length > 1) {
    outcomeOptions.push([MANY, outcomes.map((port) => labels.get(port) ?? port).join(", ")]);
  }

  // A run the server refused ("3f2" is too short to mean one): its own words on the
  // field, in place of the list, which would only read as empty.
  const runProblem = fieldProblems(error).find((problem) => problem.field === "run")?.message;
  /** The run field took a value: typed, pasted, or chosen from a row. */
  const setRunFilter = (value: string, picked = false) => {
    const cleaned = value.replace(/\s/g, "");
    setPicked(picked ? cleaned : null);
    setRun(cleaned || null);
    setPage(null);
  };

  /** A filter changed: back to the first page, which is where its results start. */
  const narrow = (set: (value: string | null) => void) => (value: string) => {
    set(value === ALL ? null : value);
    setPage(null);
  };

  const columns: Column<WorkflowLogEntry>[] = [
    {
      key: "time",
      header: t("logColumns.time"),
      cell: (entry) => formatDateTimeSeconds(entry.created_at, locale),
    },
    {
      key: "step",
      header: t("logColumns.step"),
      cell: (entry) => entry.step_label,
    },
    {
      key: "outcome",
      header: t("logColumns.outcome"),
      cell: (entry) => <LogOutcome entry={entry} label={labels.get(entry.outcome)} />,
    },
    {
      key: "message",
      header: t("logColumns.message"),
      cell: (entry) => <span className="break-words whitespace-pre-wrap">{entry.message}</span>,
    },
    {
      key: "actions",
      header: <span className="sr-only">{t("logColumns.actions")}</span>,
      align: "right",
      cell: (entry) => (
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7"
          aria-label={t("logShowOnlyRun")}
          title={t("logShowOnlyRun")}
          onClick={(event) => {
            // The row opens its run; this narrows the log to it instead.
            event.stopPropagation();
            setRunFilter(entry.run_id, true);
          }}
        >
          <ListFilter className="h-3.5 w-3.5" />
        </Button>
      ),
    },
  ];

  const filtered =
    step !== null ||
    outcomes.length > 0 ||
    run !== null ||
    reach !== undefined ||
    test === "1" ||
    searched !== "";
  return (
    <div className="space-y-4">
      <ListCard
        title={t("logsTitle")}
        // Nothing to count while the read is failing: a number there would be a claim.
        counted={isLoading ? null : error !== null ? "" : t("logsCount", { count: total })}
        data-tour="workflow-logs"
        controls={
          <div className="flex flex-wrap items-center gap-2">
            <SearchInput
              value={typed}
              onChange={(next) => {
                setTyped(next);
                setPage(null);
              }}
              placeholder={t("logSearch")}
              className="sm:w-56"
              maxLength={200}
            />
            <RunFilter value={run ?? ""} onChange={setRunFilter} problem={runProblem} />
            <Filter
              label={t("logFilterStep")}
              any={t("logFilterAnyStep")}
              value={step ?? ALL}
              onChange={narrow(setStep)}
              options={stepOptions}
            />
            <Filter
              label={t("logFilterOutcome")}
              any={t("logFilterAnyOutcome")}
              value={outcomes.length === 0 ? ALL : (single ?? MANY)}
              onChange={(value) => {
                // Choosing the several again leaves them as they are.
                if (value !== MANY) setOutcomes(value === ALL ? [] : [value]);
                setPage(null);
              }}
              options={outcomeOptions}
            />
            <Filter
              label={t("logFilterSince")}
              any={t("logFilterAnySince")}
              value={reach === undefined ? ALL : (since as string)}
              onChange={(value) => {
                setAnchor(Date.now());
                narrow(setSince)(value);
              }}
              options={Object.keys(SINCE_MS).map((value) => [value, t(`runSince.${value}`)])}
            />
            <div className="flex items-center gap-2">
              <Switch
                id="log-include-test"
                checked={test === "1"}
                onCheckedChange={(on) => {
                  setTest(on ? "1" : null);
                  setPage(null);
                }}
              />
              <Label htmlFor="log-include-test" className="text-xs">
                {t("logIncludeTest")}
              </Label>
            </div>
          </div>
        }
      >
        {runProblem !== undefined ? null : error !== null ? (
          <ErrorState
            title={t("logsFailed")}
            description={t("logsFailedDetail")}
            cta={{ label: t("logsRetry"), onClick: () => void refetch() }}
          />
        ) : (
          <>
            <DataTable
              columns={columns}
              rows={entries}
              getRowKey={(entry) => entry.id}
              loading={isLoading}
              onRowClick={(entry) =>
                router.push(ROUTES.WORKFLOW_RUN_DETAIL(entry.workflow_id, entry.run_id))
              }
              empty={
                filtered ? (
                  <EmptyState title={t("logsNoMatch")} description={t("logsNoMatchDetail")} />
                ) : (
                  <EmptyState title={t("logsEmpty")} description={t("logsEmptyDetail")} />
                )
              }
            />
            <PaginationBar
              page={page}
              pageSize={LOG_PAGE}
              total={total}
              isLoading={isLoading}
              onPage={(next) => setPage(next === 0 ? null : String(next))}
            />
          </>
        )}
      </ListCard>
      <LogAlerts
        workflowId={workflowId}
        canEdit={workflow?.can_edit === true}
        steps={steps}
        stepPorts={stepPorts}
        labels={labels}
      />
    </div>
  );
}

/**
 * A text filter for one run: paste its id or type the start of it. Deliberately not a
 * dropdown - a workflow has as many runs as it has had, and the person looking has an id.
 */
function RunFilter({
  value,
  onChange,
  problem,
}: {
  value: string;
  onChange: (value: string, picked?: boolean) => void;
  /** Why the server refused the value, when it did. */
  problem: string | undefined;
}) {
  const t = useTranslations("pages.workflows");
  return (
    <div className="flex flex-col gap-1">
      <div className="relative sm:w-64">
        <Input
          value={value}
          onChange={(event) => onChange(event.target.value)}
          placeholder={t("logFilterRun")}
          aria-label={t("logFilterRun")}
          aria-invalid={problem !== undefined}
          aria-describedby={problem === undefined ? undefined : "log-run-problem"}
          maxLength={36}
          className="border-foreground/12 h-8 rounded-lg border pr-8 font-mono md:text-[13px]"
        />
        {value !== "" && (
          <button
            type="button"
            aria-label={t("logClearRun")}
            className="text-muted-foreground hover:text-foreground absolute top-1/2 right-2 -translate-y-1/2"
            onClick={() => onChange("", true)}
          >
            <X className="h-3.5 w-3.5" />
          </button>
        )}
      </div>
      {problem !== undefined && (
        <p id="log-run-problem" role="alert" className="text-destructive text-xs">
          {problem}
        </p>
      )}
    </div>
  );
}

/** The way a step left by; a failure in the destructive colour, a test line marked. */
export function LogOutcome({ entry, label }: { entry: WorkflowLogEntry; label?: string }) {
  const t = useTranslations("pages.workflows");
  return (
    <span className="inline-flex flex-wrap items-center gap-1.5">
      <span className={entry.outcome === ERROR_PORT ? "text-destructive" : undefined}>
        {label ?? entry.outcome}
      </span>
      {entry.is_test && <Badge variant="outline">{t("logTest")}</Badge>}
      {entry.is_pinned && <Badge variant="outline">{t("logPinned")}</Badge>}
    </span>
  );
}

function Filter({
  label,
  any,
  value,
  onChange,
  options,
}: {
  label: string;
  /** What the filter reads when it narrows nothing: "Any step". */
  any: string;
  value: string;
  onChange: (value: string) => void;
  options: [string, string][];
}) {
  return (
    <Select value={value} onValueChange={onChange}>
      <SelectTrigger className="h-8 w-auto min-w-32 text-xs" aria-label={label}>
        <SelectValue />
      </SelectTrigger>
      <SelectContent>
        <SelectItem value={ALL}>{any}</SelectItem>
        {options.map(([option, text]) => (
          <SelectItem key={option} value={option}>
            {text}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  );
}

"use client";

import dynamic from "next/dynamic";
import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { Badge, Button, Skeleton } from "@/components/ui";

import type { EditorApi } from "./editor-controller";
import { danglingBindings } from "./clipboard";
import { MockWorkflowServer, saveWorkflow, type ServerBehaviour } from "./mock-workflow-api";
import { syntheticGraph } from "./perf";
import { GraphParseError, fromSdkScope, toSdkScope } from "./sdk-adapter";
import type { SaveOutcome } from "./save-handler";
import { graphsEqual, replaceScope, scopeAt, type WorkflowGraph } from "./typed-graph";
import type { SaveMode } from "./editor-host";

/**
 * The evaluation lab: one SDK editor, the mocks around it, and a panel that drives
 * each case in the #1781 list. Development only; the route 404s in production.
 *
 * The SDK stays behind `next/dynamic` so that nothing here pulls it (or its
 * stylesheet, which restyles `body`) into another route's bundle.
 */
const EditorHost = dynamic(() => import("./editor-host"), {
  ssr: false,
  loading: () => <Skeleton className="h-full w-full" />,
});

/** What one editor mount starts from. A new object is a new mount. */
interface MountSpec {
  key: string;
  id: number;
  scopePath: string[];
  initialScope: WorkflowGraph;
}

const ORGS = ["acme", "globex"] as const;
const WORKFLOWS = ["wf-a", "wf-b"] as const;

/** MOCK: shared by every mount of the lab for the life of the tab. */
const server = new MockWorkflowServer();

function Row({ children }: { children: React.ReactNode }) {
  return <div className="flex flex-wrap items-center gap-2">{children}</div>;
}

function Group({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <section className="border-border bg-card flex flex-col gap-2 rounded-lg border p-3">
      <h2 className="text-muted-foreground text-xs font-medium tracking-wide uppercase">{title}</h2>
      {children}
    </section>
  );
}

export function WorkflowSdkLab() {
  const [orgId, setOrgId] = useState<(typeof ORGS)[number]>("acme");
  const [workflowId, setWorkflowId] = useState<(typeof WORKFLOWS)[number]>("wf-a");
  const [spec, setSpec] = useState<MountSpec | null>(null);
  const [mounted, setMounted] = useState(true);
  const [saveMode, setSaveMode] = useState<SaveMode>("guarded");
  const [outcome, setOutcome] = useState<SaveOutcome | null>(null);
  const [revision, setRevision] = useState(0);
  const [logs, setLogs] = useState<string[]>([]);
  const [status, setStatus] = useState({ canUndo: false, canRedo: false, history: 0 });

  const key = `${orgId}/${workflowId}`;
  const graphRef = useRef<WorkflowGraph | null>(null);
  const scopePath = spec?.scopePath ?? [];

  /** Mount a fresh editor on `path` of `graph`. The graph becomes the working copy. */
  const mountEditor = useCallback(
    (graph: WorkflowGraph, path: string[]) => {
      graphRef.current = graph;
      setSpec((previous) => ({
        key,
        id: (previous?.id ?? 0) + 1,
        scopePath: path,
        initialScope: scopeAt(graph, path),
      }));
    },
    [key],
  );
  const revisionRef = useRef(0);
  const apiRef = useRef<EditorApi | null>(null);

  const log = useCallback((line: string) => {
    setLogs((previous) =>
      [`${new Date().toISOString().slice(11, 23)} ${line}`, ...previous].slice(0, 60),
    );
  }, []);

  // Load whenever the workflow or the organization changes; the editor remounts.
  useEffect(() => {
    let cancelled = false;
    void server.load(key).then((doc) => {
      if (cancelled) return;
      revisionRef.current = doc.revision;
      setRevision(doc.revision);
      setOutcome(null);
      mountEditor(doc.graph, []);
      log(`loaded ${key} at r${doc.revision}`);
    });
    return () => {
      cancelled = true;
    };
  }, [key, log, mountEditor]);

  // Exposed so a browser test can read the server's document, which the page
  // otherwise shows only as ids in the log.
  useEffect(() => {
    Object.assign(window, { __workflowSdkLab: { server } });
  }, []);

  const onApi = useCallback((api: EditorApi | null) => {
    apiRef.current = api;
  }, []);

  // History depth is read off the editor; poll rather than thread a subscription
  // through the SDK's tree.
  useEffect(() => {
    const timer = setInterval(() => {
      const api = apiRef.current;
      setStatus({
        canUndo: api?.canUndo ?? false,
        canRedo: api?.canRedo ?? false,
        history: api?.historySize ?? 0,
      });
    }, 300);
    return () => clearInterval(timer);
  }, []);

  const persist = useCallback(
    async (graph: WorkflowGraph, expectedRevision: number) => {
      const saved = await saveWorkflow(server, key, graph, expectedRevision);
      log(
        `persisted ${key} r${saved.revision}: ${graph.nodes.map((node) => `${node.id}=${node.label}`).join(" ")}`,
      );
      graphRef.current = graph;
      revisionRef.current = saved.revision;
      setRevision(saved.revision);
      return saved;
    },
    [key, log],
  );

  const onOutcome = useCallback(
    (next: SaveOutcome) => {
      setOutcome(next);
      log(`save ${JSON.stringify(next)}`);
    },
    [log],
  );

  const remount = () => {
    if (graphRef.current) mountEditor(graphRef.current, scopePath);
  };

  const enterBody = () => {
    const api = apiRef.current;
    const graph = graphRef.current;
    if (!api || !graph) return;
    try {
      const [id] = api.selectedIds();
      const live = api.scope();
      const merged = replaceScope(graph, scopePath, live);
      const target = id ? live.nodes.find((node) => node.id === id) : undefined;
      if (target?.config.kind !== "foreach") {
        log("select one foreach node first");
        return;
      }
      mountEditor(merged, [...scopePath, target.id]);
    } catch (error) {
      log(error instanceof GraphParseError ? error.problems.join("; ") : String(error));
    }
  };

  const leaveTo = (depth: number) => {
    const api = apiRef.current;
    const graph = graphRef.current;
    if (!api || !graph) return;
    try {
      mountEditor(replaceScope(graph, scopePath, api.scope()), scopePath.slice(0, depth));
    } catch (error) {
      log(String(error));
    }
  };

  const roundTrip = () => {
    const graph = graphRef.current;
    if (!graph) return;
    const check = (path: string[]): boolean => {
      const scope = scopeAt(graph, path);
      const sdk = toSdkScope(scope);
      const back = fromSdkScope(scope, sdk.nodes, sdk.edges);
      const ok = graphsEqual(scope, back);
      log(`round trip [${path.join(" > ") || "root"}]: ${ok ? "identical" : "DIFFERENT"}`);
      const bodies = scope.nodes.flatMap((node) =>
        node.config.kind === "foreach" ? [[...path, node.id]] : [],
      );
      return bodies.map(check).every(Boolean) && ok;
    };
    log(check([]) ? "round trip: every scope identical" : "round trip: differences found");
  };

  const loadSynthetic = (count: number) => {
    mountEditor(syntheticGraph(count), []);
    log(`loaded a synthetic graph of ${count} nodes`);
  };

  const dangling = () => {
    const api = apiRef.current;
    const graph = graphRef.current;
    if (!api || !graph) return;
    const live = replaceScope(graph, scopePath, api.scope());
    const found = danglingBindings(live);
    log(found.length === 0 ? "no dangling bindings" : `dangling: ${found.join(", ")}`);
  };

  const run = (label: string, action: () => unknown) => {
    try {
      const result = action();
      if (result instanceof Promise) {
        void result.then(
          (value) => log(`${label}: ${String(value)}`),
          (error: unknown) => log(`${label} threw: ${String(error)}`),
        );
      } else if (result !== undefined) {
        log(`${label}: ${String(result)}`);
      }
    } catch (error) {
      log(`${label} threw: ${String(error)}`);
    }
  };

  const behave = (next: ServerBehaviour) => {
    server.forced = next;
    log(`the next save will answer: ${next}`);
  };

  const scopeName = `${key}${scopePath.length > 0 ? `::${scopePath.join("/")}` : ""}`;

  return (
    <div
      className="flex min-h-0 flex-1 flex-col gap-3 pb-4 lg:flex-row"
      data-testid="workflow-sdk-lab"
    >
      <div className="flex min-h-[70vh] min-w-0 flex-1 flex-col gap-2">
        <Row>
          <Badge variant="outline">{scopeName}</Badge>
          <Badge variant="outline">local r{revision}</Badge>
          <Badge variant="outline">server r{server.revisionOf(key)}</Badge>
          {outcome && <Badge data-testid="save-outcome">{outcome.status}</Badge>}
        </Row>
        {outcome?.status === "conflict" && (
          <div
            role="alert"
            className="border-border bg-card flex flex-wrap items-center gap-2 rounded-lg border p-3 text-sm"
          >
            <span>
              Saved against r{outcome.expectedRevision}, the server is at r{outcome.serverRevision}.
            </span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                revisionRef.current = outcome.serverRevision;
                setRevision(outcome.serverRevision);
                run("save", () => apiRef.current?.save());
              }}
            >
              Overwrite
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                void server.load(key).then((doc) => {
                  revisionRef.current = doc.revision;
                  setRevision(doc.revision);
                  setOutcome(null);
                  mountEditor(doc.graph, []);
                });
              }}
            >
              Reload
            </Button>
          </div>
        )}
        <div
          className="border-border relative min-h-[60vh] flex-1 overflow-hidden rounded-lg border"
          data-testid="editor-frame"
        >
          {mounted && spec?.key === key ? (
            <EditorHost
              key={spec.id}
              name={scopeName}
              scopePath={spec.scopePath}
              initialScope={spec.initialScope}
              getGraph={() => graphRef.current ?? { nodes: [], edges: [] }}
              getRevision={() => revisionRef.current}
              persist={persist}
              saveMode={saveMode}
              onOutcome={onOutcome}
              onApi={onApi}
              onLog={log}
              onSingletonViolation={log}
            />
          ) : (
            <Skeleton className="h-full w-full" />
          )}
        </div>
      </div>

      <aside className="flex w-full shrink-0 flex-col gap-3 lg:w-96 lg:overflow-y-auto">
        <Group title="Workflow / organization">
          <Row>
            {ORGS.map((org) => (
              <Button
                key={org}
                size="sm"
                variant={org === orgId ? "default" : "outline"}
                onClick={() => setOrgId(org)}
              >
                {org}
              </Button>
            ))}
            {WORKFLOWS.map((workflow) => (
              <Button
                key={workflow}
                size="sm"
                variant={workflow === workflowId ? "default" : "outline"}
                onClick={() => setWorkflowId(workflow)}
              >
                {workflow}
              </Button>
            ))}
          </Row>
          <Row>
            <Button size="sm" variant="outline" onClick={() => setMounted((previous) => !previous)}>
              {mounted ? "Unmount editor" : "Mount editor"}
            </Button>
            <Button size="sm" variant="outline" onClick={remount}>
              Remount
            </Button>
            <Button size="sm" variant="outline" asChild>
              <Link href="/agents">Navigate to Agents</Link>
            </Button>
          </Row>
        </Group>

        <Group title="Nested foreach">
          <Row>
            <Button
              size="sm"
              variant="outline"
              onClick={() => leaveTo(0)}
              disabled={scopePath.length === 0}
            >
              Root
            </Button>
            {scopePath.map((id, index) => (
              <Button key={id} size="sm" variant="outline" onClick={() => leaveTo(index + 1)}>
                {id}
              </Button>
            ))}
            <Button size="sm" onClick={enterBody}>
              Enter selected foreach
            </Button>
          </Row>
          <Row>
            <Button size="sm" variant="outline" onClick={roundTrip}>
              Round trip
            </Button>
            <Button size="sm" variant="outline" onClick={dangling}>
              Dangling bindings
            </Button>
          </Row>
        </Group>

        <Group title="Save">
          <Row>
            <Button size="sm" onClick={() => run("save", () => apiRef.current?.save())}>
              Save
            </Button>
            <Button
              size="sm"
              variant={saveMode === "naive" ? "default" : "outline"}
              onClick={() => setSaveMode(saveMode === "naive" ? "guarded" : "naive")}
            >
              Handler: {saveMode}
            </Button>
          </Row>
          <Row>
            <Button size="sm" variant="outline" onClick={() => behave("conflict")}>
              Force 409
            </Button>
            <Button size="sm" variant="outline" onClick={() => behave("error")}>
              Force 500
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => log(`another tab saved: server is at r${server.bumpRevision(key)}`)}
            >
              Another tab saves
            </Button>
          </Row>
        </Group>

        <Group title="History and clipboard">
          <Row>
            <Button
              size="sm"
              variant="outline"
              disabled={!status.canUndo}
              onClick={() => apiRef.current?.undo()}
            >
              Undo
            </Button>
            <Button
              size="sm"
              variant="outline"
              disabled={!status.canRedo}
              onClick={() => apiRef.current?.redo()}
            >
              Redo
            </Button>
            <Badge variant="outline">{status.history} steps</Badge>
          </Row>
          <Row>
            <Button
              size="sm"
              variant="outline"
              onClick={() => run("copy", () => apiRef.current?.copy())}
            >
              Copy
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => run("cut", () => apiRef.current?.cut())}
            >
              Cut
            </Button>
            <Button
              size="sm"
              variant="outline"
              onClick={() => run("paste", () => apiRef.current?.paste())}
            >
              Paste
            </Button>
          </Row>
        </Group>

        <Group title="Scale">
          <Row>
            {[50, 200, 1000].map((count) => (
              <Button key={count} size="sm" variant="outline" onClick={() => loadSynthetic(count)}>
                {count} nodes
              </Button>
            ))}
          </Row>
        </Group>

        <Group title="Log">
          <ol
            className="max-h-64 space-y-1 overflow-y-auto font-mono text-xs"
            data-testid="lab-log"
          >
            {logs.map((line, index) => (
              <li key={`${index}-${line}`}>{line}</li>
            ))}
          </ol>
        </Group>
      </aside>
    </div>
  );
}

/**
 * When a step runs, as a condition on the choices earlier steps make - the client
 * mirror of `backend/app/workflows/graph/joins.py`.
 *
 * The executor runs a step once every step before it has settled, if **any** incoming
 * wire is live. So a step's *run condition* is the OR, over its incoming edges, of the
 * source's condition AND the edge's literal: `(source, port)` when the source takes one
 * way out of several (an If, a Switch, a decision, a step that routes its errors),
 * nothing otherwise. Choices at one such step exclude each other; choices at different
 * steps are independent. Each scope (the top level, each loop body) is analysed on its
 * own, a body rooted at its loop.
 *
 * A condition is a set of *terms*, each a set of `(step, port)` choices, read as their
 * disjunction, kept small by two rules applied to a fixed point: terms `t + {D: p}` for
 * every output port of D are the single term `t` (an unwired port blocks this, rightly),
 * and a term that contains another is dropped. Past {@link MAX_TERMS} - or when an
 * analysis has spent its work budget - the condition is `unknown`: "can run together"
 * answers yes and "runs whenever" no, so the rules built on them refuse rather than
 * accept.
 *
 * The run-time half (`evaluate_join`) is the dispatcher's alone and has no mirror.
 */

import type { NodeInstance, WorkflowEdge, WorkflowGraph } from "@/lib/workflows/types";
import { routesErrors } from "@/lib/workflows/ports";

import { kahn, type DefinitionMap } from "./topology";

/** The most terms a condition keeps before it is `unknown`. */
export const MAX_TERMS = 64;
/** Element operations one analysis may spend building conditions and precede sets. */
export const BUILD_BUDGET = 4_000_000;
/** Element operations one analysis may spend answering questions afterwards. */
export const QUESTION_BUDGET = 1_000_000;

/** A count of element operations left, so no graph costs unbounded work. */
class Budget {
  constructor(public left: number) {}

  get spent(): boolean {
    return this.left < 0;
  }

  take(cost: number): void {
    this.left -= cost;
  }
}

/** One edge into a step, by the edge's own id. */
export interface JoinWire {
  edgeId: string;
  sourceNodeId: string;
  sourcePort: string;
}

/** One `(step, port)` choice, as `step\u0000port`. */
type Choice = string;
type Term = Set<Choice>;

/**
 * When a step runs: the disjunction of `terms`, each a set of choices. `unknown` is set
 * when the condition outgrew {@link MAX_TERMS}; `terms` is then empty.
 */
export interface RunCondition {
  terms: Term[];
  unknown: boolean;
}

const ALWAYS: RunCondition = { terms: [new Set()], unknown: false };
const UNKNOWN: RunCondition = { terms: [], unknown: true };

function choice(step: string, port: string): Choice {
  return `${step}\u0000${port}`;
}

/** What the publish rules and the binding picker both need to know about one graph. */
export interface GraphAnalysis {
  graph: WorkflowGraph;
  definitions: DefinitionMap;
  nodeScope: Map<string, string>;
  /** The steps that take one way out of several per run. */
  exclusive: Set<string>;
  incoming: Map<string, JoinWire[]>;
  /** A step only when something reaches it, in its own scope. */
  conditions: Map<string, RunCondition>;
  /** The steps before each step that run whenever it does, itself included. */
  precede: Map<string, Set<string>>;
  ancestors: Map<string, Set<string>>;
  /** Work left for questions, and the answers already given - private to this module. */
  questions: Budget;
  answers: Map<RunCondition, Map<RunCondition, boolean>>;
}

/** Whether a step takes exactly one of its output ports per run. */
export function branchesExclusively(node: NodeInstance, definitions: DefinitionMap): boolean {
  return routesErrors(node) || definitions.get(node.id)?.exclusive_branches === true;
}

/** `nodeId`, or the loop enclosing it that sits directly in scope `level`. */
export function atLevelOf(
  nodeId: string,
  level: string | null,
  nodeScope: Map<string, string>,
): string | null {
  let current: string | null = nodeId;
  while (current !== null && (nodeScope.get(current) ?? null) !== level) {
    current = nodeScope.get(current) ?? null;
  }
  return current;
}

function outputPorts(definitions: DefinitionMap): Map<string, string[]> {
  const ports = new Map<string, string[]>();
  for (const [nodeId, definition] of definitions) {
    if (definition !== null) {
      ports.set(
        nodeId,
        definition.ports.filter((port) => port.kind === "output").map((port) => port.id),
      );
    }
  }
  return ports;
}

// Conditions

function termKey(term: Term): string {
  return [...term].sort().join("\u0001");
}

function isSubset(small: Term, large: Term): boolean {
  return small.size <= large.size && [...small].every((entry) => large.has(entry));
}

function unique(terms: Term[]): Term[] {
  return [...new Map(terms.map((term) => [termKey(term), term])).values()];
}

/** `terms` without any that contains another. */
function absorb(terms: Term[], budget: Budget): Term[] {
  const kept: Term[] = [];
  for (const term of [...unique(terms)].sort((left, right) => left.size - right.size)) {
    let contained = false;
    for (const smaller of kept) {
      budget.take(smaller.size + 1);
      if (isSubset(smaller, term)) {
        contained = true;
        break;
      }
    }
    if (budget.spent) break;
    if (!contained) kept.push(term);
  }
  return kept;
}

function split(entry: Choice): [string, string] {
  return entry.split("\u0000") as [string, string];
}

/**
 * `terms` with every set of terms that covers all of a step's ports folded into one, or
 * null. Only a step whose every port appears somewhere can fold, so the rest are not
 * looked at.
 */
function mergePorts(terms: Term[], ports: Map<string, string[]>, budget: Budget): Term[] | null {
  const seen = new Map<string, Set<string>>();
  for (const term of terms) {
    budget.take(term.size + 1);
    for (const entry of term) {
      const [step, port] = split(entry);
      seen.set(step, (seen.get(step) ?? new Set<string>()).add(port));
    }
  }
  const candidates = new Set<string>();
  for (const [step, ways] of seen) {
    const all = ports.get(step) ?? [];
    if (all.length === ways.size && all.every((port) => ways.has(port))) candidates.add(step);
  }
  if (candidates.size === 0 || budget.spent) return null;
  const taken = new Map<string, { step: string; rest: Term; ways: Set<string> }>();
  for (const term of terms) {
    for (const entry of term) {
      const [step, port] = split(entry);
      if (!candidates.has(step)) continue;
      budget.take(term.size + 1);
      const rest = new Set(term);
      rest.delete(entry);
      const key = `${step}\u0002${termKey(rest)}`;
      const found = taken.get(key) ?? { step, rest, ways: new Set<string>() };
      found.ways.add(port);
      taken.set(key, found);
    }
  }
  const folded = new Set<string>();
  const rests: Term[] = [];
  for (const [key, { step, rest, ways }] of taken) {
    const all = ports.get(step) as string[];
    if (all.length === ways.size && all.every((port) => ways.has(port))) {
      folded.add(key);
      rests.push(rest);
    }
  }
  if (folded.size === 0 || budget.spent) return null;
  const stays = terms.filter((term) => {
    budget.take(term.size * term.size + 1);
    return ![...term].some((entry) => {
      const step = split(entry)[0];
      if (!candidates.has(step)) return false;
      const rest = new Set(term);
      rest.delete(entry);
      return folded.has(`${step}\u0002${termKey(rest)}`);
    });
  });
  return [...stays, ...rests];
}

/** The condition of `terms` (at most {@link MAX_TERMS}), folded and absorbed to a fixed point; `UNKNOWN` once the budget is spent. */
function normalise(terms: Term[], ports: Map<string, string[]>, budget: Budget): RunCondition {
  let current = absorb(terms, budget);
  while (!budget.spent) {
    const merged = mergePorts(current, ports, budget);
    if (merged === null) break;
    current = absorb(merged, budget);
  }
  return budget.spent ? UNKNOWN : { terms: current, unknown: false };
}

/** The condition under which any of `conditions` holds; `UNKNOWN` once the terms pass the cap. */
function either(
  conditions: RunCondition[],
  ports: Map<string, string[]>,
  budget: Budget,
): RunCondition {
  const terms: Term[] = [];
  for (const condition of conditions) {
    if (condition.unknown) return UNKNOWN;
    terms.push(...condition.terms);
    // Past the cap whatever they fold to: do not even try.
    if (unique(terms).length > MAX_TERMS) return UNKNOWN;
  }
  return normalise(terms, ports, budget);
}

/** `condition` and one more choice. */
function both(condition: RunCondition, extra: Choice | null): RunCondition {
  if (extra === null || condition.unknown) return condition;
  return {
    terms: condition.terms.map((term) => new Set([...term, extra])),
    unknown: false,
  };
}

/**
 * Whether `inner` holds whenever `outer` does: each term of `outer` has a term of `inner`
 * in it. Cheap when `inner` is always true or equals `outer`; with a `budget`, false
 * once it is spent.
 */
export function covers(inner: RunCondition, outer: RunCondition, budget?: Budget): boolean {
  if (inner.unknown || outer.unknown) return false;
  if (inner.terms.some((term) => term.size === 0) || sameCondition(inner, outer)) return true;
  if (budget?.spent) return false;
  const found = outer.terms.every((term) =>
    inner.terms.some((small) => {
      budget?.take(small.size + 1);
      return isSubset(small, term);
    }),
  );
  return found && !budget?.spent;
}

function sameCondition(left: RunCondition, right: RunCondition): boolean {
  if (left === right) return true;
  const keys = new Set(left.terms.map(termKey));
  return left.terms.length === right.terms.length && right.terms.every((t) => keys.has(termKey(t)));
}

function compatible(first: Term, second: Term): boolean {
  const chosen = new Map([...second].map(split));
  return [...first].every((entry) => {
    const [step, port] = split(entry);
    return (chosen.get(step) ?? port) === port;
  });
}

/** Whether the two can hold in one run; yes when either is unknown or the budget is spent. */
export function mayHoldTogether(
  first: RunCondition,
  second: RunCondition,
  budget?: Budget,
): boolean {
  if (first.unknown || second.unknown || budget?.spent) return true;
  const found = first.terms.some((a) =>
    second.terms.some((b) => {
      budget?.take(a.size + 1);
      return compatible(a, b);
    }),
  );
  return found || budget?.spent === true;
}

/** The wires into each step: one per (source, port), edges naming a missing step left out. */
function distinctWires(graph: WorkflowGraph): Map<string, JoinWire[]> {
  const known = new Set(graph.nodes.map((n) => n.id));
  const seen = new Map<string, Map<string, JoinWire>>();
  for (const e of graph.edges) {
    if (!known.has(e.source_node_id) || !known.has(e.target_node_id)) continue;
    const wires = seen.get(e.target_node_id) ?? new Map<string, JoinWire>();
    const key = choice(e.source_node_id, e.source_port);
    if (!wires.has(key)) {
      wires.set(key, { edgeId: e.id, sourceNodeId: e.source_node_id, sourcePort: e.source_port });
    }
    seen.set(e.target_node_id, wires);
  }
  return new Map([...seen].map(([target, wires]) => [target, [...wires.values()]]));
}

/**
 * The run conditions, wires and precede sets of `graph`. A graph whose outer part is
 * cyclic has no order to compute conditions in: they stay empty.
 */
export function analyse(
  graph: WorkflowGraph,
  definitions: DefinitionMap,
  nodeScope: Map<string, string>,
  acyclic: boolean,
  budgets: { build?: number; questions?: number } = {},
): GraphAnalysis {
  const analysis: GraphAnalysis = {
    graph,
    definitions,
    nodeScope,
    exclusive: new Set(
      graph.nodes.filter((n) => branchesExclusively(n, definitions)).map((n) => n.id),
    ),
    incoming: distinctWires(graph),
    conditions: new Map(),
    precede: new Map(),
    ancestors: new Map(),
    questions: new Budget(budgets.questions ?? QUESTION_BUDGET),
    answers: new Map(),
  };
  if (!acyclic) return analysis;
  const ports = outputPorts(definitions);
  const build = new Budget(budgets.build ?? BUILD_BUDGET);
  for (const level of [null, ...new Set(nodeScope.values())]) {
    analyseScope(analysis, ports, build, level);
  }
  return analysis;
}

/** Conditions, ancestors and precede sets of the steps directly in scope `level`. */
function analyseScope(
  analysis: GraphAnalysis,
  ports: Map<string, string[]>,
  build: Budget,
  level: string | null,
): void {
  const { graph, conditions } = analysis;
  const members = graph.nodes
    .map((n) => n.id)
    .filter((id) => (analysis.nodeScope.get(id) ?? null) === level);
  const inside = new Set(members);
  const sources = new Map<string, { source: string; port: string }[]>();
  const within: WorkflowEdge[] = [];
  for (const [target, wires] of analysis.incoming) {
    if (!inside.has(target)) continue;
    for (const wire of wires) {
      const source = atLevelOf(wire.sourceNodeId, level, analysis.nodeScope) ?? wire.sourceNodeId;
      if (source !== level && !inside.has(source)) continue;
      sources.set(target, [...(sources.get(target) ?? []), { source, port: wire.sourcePort }]);
      if (inside.has(source)) {
        within.push({
          id: wire.edgeId,
          source_node_id: source,
          source_port: wire.sourcePort,
          target_node_id: target,
          target_port: "in",
        });
      }
    }
  }
  const { order } = kahn(members, within);
  for (const nodeId of order) {
    if (nodeId === graph.entry_node_id && level === null) {
      conditions.set(nodeId, ALWAYS);
      continue;
    }
    const arriving: { condition: RunCondition; added: boolean }[] = [];
    for (const { source, port } of sources.get(nodeId) ?? []) {
      const base = source === level ? ALWAYS : conditions.get(source);
      if (base === undefined) continue;
      const added = source !== level && analysis.exclusive.has(source);
      arriving.push({ condition: both(base, added ? choice(source, port) : null), added });
    }
    const [only] = arriving;
    if (arriving.length === 1 && only !== undefined && !only.added) {
      // One way in that adds no choice: what runs the step before runs this one.
      conditions.set(nodeId, only.condition);
    } else if (arriving.length > 0) {
      conditions.set(
        nodeId,
        either(
          arriving.map((found) => found.condition),
          ports,
          build,
        ),
      );
    }
  }
  for (const nodeId of order) {
    const condition = conditions.get(nodeId);
    if (condition === undefined) continue;
    const before = new Set<string>();
    for (const { source } of sources.get(nodeId) ?? []) {
      if (source === level) before.add(source);
      else if (conditions.has(source)) {
        before.add(source);
        for (const earlier of analysis.ancestors.get(source) as Set<string>) before.add(earlier);
      }
    }
    analysis.ancestors.set(nodeId, before);
    analysis.precede.set(
      nodeId,
      new Set([
        nodeId,
        ...[...before].filter(
          (step) =>
            step === level || covers(conditions.get(step) as RunCondition, condition, build),
        ),
      ]),
    );
  }
}

// Questions

/** `nodeId` and the loops around it, innermost first. */
function enclosing(nodeId: string, nodeScope: Map<string, string>): string[] {
  const chain = [nodeId];
  for (let next = nodeScope.get(nodeId); next !== undefined; next = nodeScope.get(next)) {
    chain.push(next);
  }
  return chain;
}

/** Each step, or the loop around it, lifted to the scope both sit in. */
function sameLevel(analysis: GraphAnalysis, first: string, second: string): [string, string] {
  const levelsOfSecond = new Map(
    enclosing(second, analysis.nodeScope).map((id) => [analysis.nodeScope.get(id) ?? null, id]),
  );
  let lifted = first;
  while (!levelsOfSecond.has(analysis.nodeScope.get(lifted) ?? null)) {
    lifted = analysis.nodeScope.get(lifted) as string;
  }
  return [lifted, levelsOfSecond.get(analysis.nodeScope.get(lifted) ?? null) as string];
}

/** Whether one run can reach both steps. A step nothing reaches runs with nothing. */
export function canRunTogether(analysis: GraphAnalysis, first: string, second: string): boolean {
  const [a, b] = sameLevel(analysis, first, second);
  if (a === b) return true;
  const conditionA = analysis.conditions.get(a);
  const conditionB = analysis.conditions.get(b);
  return (
    conditionA !== undefined &&
    conditionB !== undefined &&
    mayHoldTogether(conditionA, conditionB, analysis.questions)
  );
}

/** `covers`, remembered per pair and paid for from the analysis's question budget. */
function askedCovers(analysis: GraphAnalysis, inner: RunCondition, outer: RunCondition): boolean {
  const byOuter = analysis.answers.get(inner) ?? new Map<RunCondition, boolean>();
  analysis.answers.set(inner, byOuter);
  const answered = byOuter.get(outer) ?? covers(inner, outer, analysis.questions);
  byOuter.set(outer, answered);
  return answered;
}

/**
 * Whether `step` has certainly run whenever `later` does: it comes before it and covers
 * it. Only `later` is lifted, to the scope `step` sits in: a step inside a loop does not
 * run whenever a step after the loop does, but the loop itself does.
 */
export function runsWhenever(analysis: GraphAnalysis, step: string, later: string): boolean {
  const scope = analysis.nodeScope.get(step) ?? null;
  const lifted = enclosing(later, analysis.nodeScope).find(
    (id) => (analysis.nodeScope.get(id) ?? null) === scope,
  );
  if (lifted === undefined) return false;
  if (step === lifted) return true;
  const conditionA = analysis.conditions.get(step);
  const conditionB = analysis.conditions.get(lifted);
  return (
    conditionA !== undefined &&
    conditionB !== undefined &&
    (analysis.ancestors.get(lifted) as Set<string>).has(step) &&
    askedCovers(analysis, conditionA, conditionB)
  );
}

/** When `wire` is live: its source runs and leaves by its port. Undefined if nothing reaches the source. */
export function wireCondition(
  analysis: GraphAnalysis,
  target: string,
  wire: JoinWire,
): RunCondition | undefined {
  const level = analysis.nodeScope.get(target) ?? null;
  const source = atLevelOf(wire.sourceNodeId, level, analysis.nodeScope) ?? wire.sourceNodeId;
  const base = source === level ? ALWAYS : analysis.conditions.get(source);
  if (base === undefined) return undefined;
  const extra =
    source !== level && analysis.exclusive.has(source) ? choice(source, wire.sourcePort) : null;
  return both(base, extra);
}

function wireConditions(analysis: GraphAnalysis, target: string): RunCondition[] {
  return (analysis.incoming.get(target) ?? []).flatMap((wire) => {
    const condition = wireCondition(analysis, target, wire);
    return condition === undefined ? [] : [condition];
  });
}

/** Whether two of the wires into `target` can be live in one run. */
export function anyPairRunsTogether(analysis: GraphAnalysis, target: string): boolean {
  const conditions = wireConditions(analysis, target);
  return conditions.some((first, index) =>
    conditions
      .slice(index + 1)
      .some((second) => mayHoldTogether(first, second, analysis.questions)),
  );
}

/** Whether `wire` is live whenever `target` runs. */
export function wireRunsWhenever(analysis: GraphAnalysis, target: string, wire: JoinWire): boolean {
  const condition = wireCondition(analysis, target, wire);
  const later = analysis.conditions.get(target);
  return condition !== undefined && later !== undefined && askedCovers(analysis, condition, later);
}

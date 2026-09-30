import {
  ArrowLeftRight,
  ArrowLeftToLine,
  ArrowRightToLine,
  Bell,
  Bot,
  Braces,
  Bug,
  CalendarClock,
  CircleX,
  Code2,
  Combine,
  Download,
  File,
  FileCode2,
  FileImage,
  FilePen,
  FileText,
  Filter,
  Flag,
  Gauge,
  GitBranch,
  GitMerge,
  Globe,
  Hourglass,
  ImageIcon,
  Library,
  ListChecks,
  MessageSquare,
  MessageSquareText,
  PhoneIncoming,
  Play,
  Repeat,
  Scale,
  ScanText,
  Search,
  SearchCheck,
  Send,
  Server,
  ShieldAlert,
  Siren,
  Split,
  Table2,
  TableProperties,
  Terminal,
  type LucideIcon,
  Upload,
  UserCheck,
  Users,
  Webhook,
  Workflow,
  Zap,
} from "lucide-react";

/**
 * How a node looks wherever the editor shows one - its card on the canvas, its
 * row in the step picker, its settings dialog - so they agree.
 *
 * Every tile is neutral, the way the rest of the console is: the icon says what
 * a step is, and colour is kept for meaning - an error step's tile is red. A
 * chat platform's steps carry the platform's own mark, since "which of these is
 * the Slack one" is the first question asked of a graph.
 */

import type { ComponentType, SVGProps } from "react";

import { brandMark } from "@/components/icons/brand-icon";

/** An icon a tile draws: a lucide icon, or a brand's mark. */
export type NodeIcon = LucideIcon | ComponentType<Omit<SVGProps<SVGSVGElement>, "name">>;

export type NodeTone = "neutral" | "danger";

const TONE_CLASS: Record<NodeTone, string> = {
  neutral: "bg-muted text-foreground",
  danger: "bg-destructive/10 text-destructive",
};

const BY_ID: Record<string, NodeIcon> = {
  "trigger.manual": Play,
  "core.input": Server,
  "trigger.chat": MessageSquare,
  "trigger.webhook": Webhook,
  "trigger.schedule": CalendarClock,
  "trigger.table_record": TableProperties,
  "trigger.workflow_failed": Siren,
  "trigger.workflow_call": PhoneIncoming,
  "logic.switch": Split,
  "flow.wait": Hourglass,
  "data.filter": Filter,
  "data.combine": Combine,
  "workflow.run": Workflow,
  "core.output": Flag,
  "logic.if": GitBranch,
  "logic.merge": GitMerge,
  "control.foreach": Repeat,
  "loop.item": ArrowRightToLine,
  "loop.yield": ArrowLeftToLine,
  "error.handle": ShieldAlert,
  "error.raise": CircleX,
  "http.download": Download,
  "http.upload": Upload,
  "file.read": FileText,
  "file.write": FilePen,
  "text.extract": ScanText,
  "convert.csv_to_json": ArrowLeftRight,
  "convert.json_to_csv": ArrowLeftRight,
  "convert.text_to_file": File,
  "convert.pdf_to_png": FileImage,
  "image.transform": ImageIcon,
  "code.python.simple": Code2,
  "code.python.sandbox": Terminal,
  "code.javascript.sandbox": FileCode2,
  "decide.yes_no": Scale,
  "decide.choose": ListChecks,
  "decide.score": Gauge,
  "table.exists": TableProperties,
  "table.record.exists": SearchCheck,
};

const BY_CATEGORY: Record<string, NodeIcon> = {
  triggers: Zap,
  core: Flag,
  agent: Bot,
  decide: Scale,
  knowledge: Library,
  data: Braces,
  tables: Table2,
  files: File,
  code: Code2,
  logic: GitBranch,
  control: Repeat,
  error: ShieldAlert,
  http: Globe,
  notification: Bell,
  people: UserCheck,
  debug: Bug,
};

/** The chat platforms whose steps form a group of their own, drawn with the platform's mark. */
const PLATFORM_MARKS: Record<string, NodeIcon> = {
  slack: brandMark("slack"),
  mattermost: brandMark("mattermost"),
  telegram: brandMark("telegram"),
};

/**
 * What a platform step does, by the operation its id ends with (`slack.message.send`),
 * in the order a group lists them: acting first, then reading, then looking up.
 */
const OPERATION_ICONS: Record<string, NodeIcon> = {
  "message.send": Send,
  "messages.read": MessageSquareText,
  "members.list": Users,
  "channels.find": Search,
};

/** Where a step sorts within its group: a platform's operations in their own order. */
export function operationRank(definitionId: string): number {
  const operation = definitionId.split(".").slice(1).join(".");
  const index = Object.keys(OPERATION_ICONS).indexOf(operation);
  return index === -1 ? Object.keys(OPERATION_ICONS).length : index;
}

const DANGER_CATEGORIES: ReadonlySet<string> = new Set(["error"]);

/**
 * The picker's sections, in the order a workflow reads, and the groups under
 * each. A group is a catalog `category`; a category no section names is shown
 * last, under its own name.
 */
export const PICKER_SECTIONS = [
  { id: "start", groups: ["triggers"] },
  { id: "ai", groups: ["agent", "decide", "knowledge"] },
  { id: "flow", groups: ["logic", "control", "error", "people", "core"] },
  { id: "data", groups: ["tables", "data", "files", "code"] },
  { id: "apps", groups: ["slack", "mattermost", "telegram", "http", "notification"] },
] as const;

/** Every group in picker order - what `categoryRank` sorts by. */
export const CATEGORY_ORDER: readonly string[] = PICKER_SECTIONS.flatMap(
  (section) => section.groups,
);

/** Categories a builder never needs in the picker. */
export const HIDDEN_CATEGORIES: ReadonlySet<string> = new Set(["debug"]);

export interface NodeVisual {
  icon: NodeIcon;
  /** Classes for the icon tile: its background and the icon's colour. */
  tileClass: string;
}

function tile(category: string): string {
  return TONE_CLASS[DANGER_CATEGORIES.has(category) ? "danger" : "neutral"];
}

/** How one step is drawn: its own icon, its platform's mark, or its group's icon. */
export function nodeVisual(definitionId: string, category: string): NodeVisual {
  const icon = BY_ID[definitionId] ?? PLATFORM_MARKS[category] ?? BY_CATEGORY[category] ?? Zap;
  return { icon, tileClass: tile(category) };
}

/**
 * How one step is drawn among its group's steps in the picker: a platform
 * step by what it does, since every row beside it carries the same mark.
 */
export function operationVisual(definitionId: string, category: string): NodeVisual {
  if (PLATFORM_MARKS[category] === undefined) return nodeVisual(definitionId, category);
  const operation = definitionId.split(".").slice(1).join(".");
  return { icon: OPERATION_ICONS[operation] ?? Zap, tileClass: tile(category) };
}

/** How a group is drawn in the picker: its platform's mark, or its own icon. */
export function groupVisual(category: string): NodeVisual {
  return {
    icon: PLATFORM_MARKS[category] ?? BY_CATEGORY[category] ?? Zap,
    tileClass: tile(category),
  };
}

/** Where `category` sorts in the picker; an unknown one goes last, alphabetically. */
export function categoryRank(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

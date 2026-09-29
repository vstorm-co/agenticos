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
  Download,
  File,
  FileImage,
  FilePen,
  FileText,
  Flag,
  GitBranch,
  GitMerge,
  Globe,
  ImageIcon,
  Library,
  MessageSquare,
  Play,
  Repeat,
  ScanText,
  ShieldAlert,
  Table2,
  TableProperties,
  Terminal,
  Upload,
  Webhook,
  Zap,
  type LucideIcon,
} from "lucide-react";

/**
 * How a node looks wherever the editor shows one - its palette row, its card on
 * the canvas, the property panel's header - so the three agree.
 *
 * Tinted by what a step touches rather than by its catalog `kind`: an author
 * scans a graph for "where does it call the agent" or "where does it write the
 * table", not for which steps are control nodes. The tints stay low-chroma, the
 * way the rest of the console uses colour.
 */

export type NodeTone =
  "neutral" | "agent" | "logic" | "data" | "network" | "danger" | "file" | "code";

const TONE_CLASS: Record<NodeTone, string> = {
  neutral: "bg-muted text-foreground",
  agent: "bg-violet-500/10 text-violet-600 dark:text-violet-300",
  logic: "bg-amber-500/10 text-amber-700 dark:text-amber-300",
  data: "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
  network: "bg-sky-500/10 text-sky-700 dark:text-sky-300",
  danger: "bg-rose-500/10 text-rose-700 dark:text-rose-300",
  file: "bg-orange-500/10 text-orange-700 dark:text-orange-300",
  code: "bg-indigo-500/10 text-indigo-700 dark:text-indigo-300",
};

const BY_ID: Record<string, { icon: LucideIcon; tone: NodeTone }> = {
  "core.input": { icon: Play, tone: "neutral" },
  "trigger.chat": { icon: MessageSquare, tone: "neutral" },
  "trigger.webhook": { icon: Webhook, tone: "neutral" },
  "trigger.schedule": { icon: CalendarClock, tone: "neutral" },
  "trigger.table_record": { icon: TableProperties, tone: "neutral" },
  "core.output": { icon: Flag, tone: "neutral" },
  "logic.if": { icon: GitBranch, tone: "logic" },
  "logic.merge": { icon: GitMerge, tone: "logic" },
  "control.foreach": { icon: Repeat, tone: "logic" },
  "loop.item": { icon: ArrowRightToLine, tone: "logic" },
  "loop.yield": { icon: ArrowLeftToLine, tone: "logic" },
  "error.handle": { icon: ShieldAlert, tone: "danger" },
  "error.raise": { icon: CircleX, tone: "danger" },
  "http.download": { icon: Download, tone: "network" },
  "http.upload": { icon: Upload, tone: "network" },
  "file.read": { icon: FileText, tone: "file" },
  "file.write": { icon: FilePen, tone: "file" },
  "text.extract": { icon: ScanText, tone: "file" },
  "convert.csv_to_json": { icon: ArrowLeftRight, tone: "file" },
  "convert.json_to_csv": { icon: ArrowLeftRight, tone: "file" },
  "convert.text_to_file": { icon: File, tone: "file" },
  "convert.pdf_to_png": { icon: FileImage, tone: "file" },
  "image.transform": { icon: ImageIcon, tone: "file" },
  "code.python.simple": { icon: Code2, tone: "code" },
  "code.python.sandbox": { icon: Terminal, tone: "code" },
};

const BY_CATEGORY: Record<string, { icon: LucideIcon; tone: NodeTone }> = {
  agent: { icon: Bot, tone: "agent" },
  knowledge: { icon: Library, tone: "agent" },
  data: { icon: Braces, tone: "data" },
  tables: { icon: Table2, tone: "data" },
  files: { icon: File, tone: "file" },
  code: { icon: Code2, tone: "code" },
  http: { icon: Globe, tone: "network" },
  notification: { icon: Bell, tone: "network" },
  debug: { icon: Bug, tone: "neutral" },
};

/** The order palette groups appear in: how a workflow reads, start to finish. */
export const CATEGORY_ORDER = [
  "triggers",
  "core",
  "agent",
  "knowledge",
  "data",
  "tables",
  "files",
  "code",
  "logic",
  "control",
  "error",
  "http",
  "notification",
] as const;

/** Categories a builder never needs in the palette. */
export const HIDDEN_CATEGORIES: ReadonlySet<string> = new Set(["debug"]);

export interface NodeVisual {
  icon: LucideIcon;
  /** Classes for the icon tile: its background and the icon's colour. */
  tileClass: string;
}

export function nodeVisual(definitionId: string, category: string): NodeVisual {
  const entry = BY_ID[definitionId] ?? BY_CATEGORY[category] ?? { icon: Zap, tone: "neutral" };
  return { icon: entry.icon, tileClass: TONE_CLASS[entry.tone] };
}

/** Where `category` sorts in the palette; an unknown one goes last, alphabetically. */
export function categoryRank(category: string): number {
  const index = (CATEGORY_ORDER as readonly string[]).indexOf(category);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

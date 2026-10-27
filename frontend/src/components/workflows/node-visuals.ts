import {
  ArrowLeftRight,
  ArrowLeftToLine,
  ArrowRightToLine,
  ArrowUpDown,
  Bell,
  Bot,
  Braces,
  Bug,
  CalendarClock,
  CircleX,
  ClipboardList,
  Code2,
  CodeXml,
  Combine,
  CopyX,
  Diff,
  Download,
  File,
  FileCode2,
  FileImage,
  FilePen,
  FileText,
  Filter,
  FingerprintPattern,
  Flag,
  Gauge,
  GitBranch,
  GitMerge,
  Globe,
  Hourglass,
  Link2,
  ImageIcon,
  Layers,
  Library,
  ListChecks,
  ListEnd,
  Mail,
  MessageSquare,
  MessageSquareText,
  MessagesSquare,
  PhoneIncoming,
  Plug,
  Play,
  Repeat,
  Reply,
  Scale,
  ScanText,
  Search,
  SearchCheck,
  Send,
  Server,
  ShieldAlert,
  Sigma,
  Siren,
  Split,
  Table2,
  TableProperties,
  Terminal,
  type LucideIcon,
  Ungroup,
  Upload,
  UserCheck,
  Users,
  WandSparkles,
  Webhook,
  Workflow,
  Zap,
  BookPlus,
  Languages,
  ScanSearch,
  Sparkles,
  Tags,
} from "lucide-react";

/**
 * How a node looks wherever the editor shows one - its card on the canvas, its
 * row in the step picker, its settings dialog - so they agree.
 *
 * A step is drawn by its family, the picker's sections: an ink round Start,
 * a solid violet AI tile, a teal Data tile, an outlined white Apps tile, a grey
 * Flow tile and a red Error tile. Lightness and shape differ as well as hue, so
 * the families survive colour blindness and a canvas zoomed out past reading.
 * The icon still says what a step is; the family says what sort of thing it is.
 *
 * "Simple" is the person's switch back to the console's usual restraint: every
 * tile neutral, colour kept for meaning - an error step's tile is red. A chat
 * platform's steps carry the platform's own mark either way, since "which of
 * these is the Slack one" is the first question asked of a graph.
 */

import type { ComponentType, SVGProps } from "react";

import { brandMark } from "@/components/icons/brand-icon";
import type { NodeStyle } from "@/stores/workflow-node-style-store";

/** An icon a tile draws: a lucide icon, or a brand's mark. */
export type NodeIcon = LucideIcon | ComponentType<Omit<SVGProps<SVGSVGElement>, "name">>;

export type NodeTone = "neutral" | "danger";

/** What sort of step a node is - the picker's sections, plus the red Error family. */
export type NodeFamily = "start" | "ai" | "flow" | "data" | "apps" | "error";

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
  "trigger.form": ClipboardList,
  "trigger.channel_message": MessagesSquare,
  "trigger.github": brandMark("github"),
  "trigger.gmail": brandMark("gmail"),
  "trigger.outlook": brandMark("microsoft"),
  "logic.switch": Split,
  "flow.wait": Hourglass,
  "flow.resume_link": Link2,
  "data.filter": Filter,
  "data.combine": Combine,
  "transform.edit_fields": WandSparkles,
  "transform.sort": ArrowUpDown,
  "transform.limit": ListEnd,
  "transform.remove_duplicates": CopyX,
  "transform.aggregate": Layers,
  "transform.split_out": Ungroup,
  "transform.summarize": Sigma,
  "transform.date_time": CalendarClock,
  "transform.crypto": FingerprintPattern,
  "workflow.run": Workflow,
  "core.output": Flag,
  "webhook.respond": Reply,
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
  "text.compare": Diff,
  "html.parse": CodeXml,
  "convert.csv_to_json": ArrowLeftRight,
  "convert.json_to_csv": ArrowLeftRight,
  "convert.text_to_file": File,
  "convert.pdf_to_png": FileImage,
  "image.transform": ImageIcon,
  "code.python.simple": Code2,
  "code.python.sandbox": Terminal,
  "code.javascript.sandbox": FileCode2,
  "ai.prompt": MessageSquareText,
  "ai.classify": Tags,
  "ai.extract": ScanSearch,
  "ai.rewrite": Languages,
  "knowledge.add": BookPlus,
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
  model: Sparkles,
  decide: Scale,
  knowledge: Library,
  data: Braces,
  transform: WandSparkles,
  tables: Table2,
  files: File,
  code: Code2,
  logic: GitBranch,
  control: Repeat,
  error: ShieldAlert,
  http: Globe,
  mcp: Plug,
  email: Mail,
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
  { id: "ai", groups: ["agent", "model", "decide", "knowledge"] },
  { id: "flow", groups: ["logic", "control", "error", "people", "core"] },
  { id: "data", groups: ["tables", "data", "transform", "files", "code"] },
  {
    id: "apps",
    groups: ["slack", "mattermost", "telegram", "mcp", "http", "email", "notification"],
  },
] as const;

/** Every group in picker order - what `categoryRank` sorts by. */
export const CATEGORY_ORDER: readonly string[] = PICKER_SECTIONS.flatMap(
  (section) => section.groups,
);

/** Categories a builder never needs in the picker. */
export const HIDDEN_CATEGORIES: ReadonlySet<string> = new Set(["debug"]);

/** The family a catalog `category` is drawn in; one no section names is Flow. */
export function nodeFamily(category: string): NodeFamily {
  if (DANGER_CATEGORIES.has(category)) return "error";
  const section = PICKER_SECTIONS.find((candidate) =>
    (candidate.groups as readonly string[]).includes(category),
  );
  return section?.id ?? "flow";
}

/** Tile colours by family, as the `node-tile-*` classes in the stylesheet; Flow and Error keep today's. */
const FAMILY_TILE: Record<NodeFamily, string> = {
  start: "node-tile-start rounded-full",
  ai: "node-tile-ai",
  flow: TONE_CLASS.neutral,
  data: "node-tile-data",
  apps: "node-tile-apps",
  error: TONE_CLASS.danger,
};

/** The ink of the "Family · Kind" label above a card's name. */
const FAMILY_LABEL: Record<NodeFamily, string> = {
  start: "text-foreground",
  ai: "text-[var(--family-ai-ink)]",
  flow: "text-muted-foreground",
  data: "text-[var(--family-data-ink)]",
  apps: "text-[var(--family-apps-ink)]",
  error: "text-[var(--family-error-ink)]",
};

/** The ink of a family's label: its colour, or grey in Simple. */
export function familyLabelClass(family: NodeFamily, style: NodeStyle): string {
  return style === "colour" ? FAMILY_LABEL[family] : "text-muted-foreground";
}

/** A picker section's swatch beside its heading; the catch-all "More" section has none. */
const SECTION_SWATCH: Record<string, string> = {
  start: "bg-primary",
  ai: "bg-[var(--family-ai)]",
  flow: "bg-muted-foreground/40",
  data: "bg-[var(--family-data-ink)]",
  apps: "bg-[var(--family-apps-ink)]",
};

export function sectionSwatchClass(sectionId: string): string | undefined {
  return SECTION_SWATCH[sectionId];
}

export interface NodeVisual {
  icon: NodeIcon;
  /** Classes for the icon tile: its background and the icon's colour. */
  tileClass: string;
  family: NodeFamily;
}

/** Triggers drawn with a brand's mark, which sits on the white tile like an Apps step's. */
const BRAND_TRIGGERS: ReadonlySet<string> = new Set(["trigger.github", "trigger.gmail"]);

function tile(
  category: string,
  style: NodeStyle,
  definitionId = "",
): { tileClass: string; family: NodeFamily } {
  const family = nodeFamily(category);
  if (style === "colour") {
    const branded = BRAND_TRIGGERS.has(definitionId);
    return { tileClass: branded ? "node-tile-apps rounded-full" : FAMILY_TILE[family], family };
  }
  return { tileClass: TONE_CLASS[family === "error" ? "danger" : "neutral"], family };
}

/** A step's own icon, its platform's mark, or its group's icon. */
function nodeIcon(definitionId: string, category: string): NodeIcon {
  return BY_ID[definitionId] ?? PLATFORM_MARKS[category] ?? BY_CATEGORY[category] ?? Zap;
}

/** How one step is drawn: its icon and its family's tile. */
export function nodeVisual(definitionId: string, category: string, style: NodeStyle): NodeVisual {
  return { icon: nodeIcon(definitionId, category), ...tile(category, style, definitionId) };
}

/**
 * How one step is drawn among its group's steps in the picker: a platform
 * step by what it does, since every row beside it carries the same mark.
 */
export function operationVisual(
  definitionId: string,
  category: string,
  style: NodeStyle,
): NodeVisual {
  if (PLATFORM_MARKS[category] === undefined) return nodeVisual(definitionId, category, style);
  const operation = definitionId.split(".").slice(1).join(".");
  return { icon: OPERATION_ICONS[operation] ?? Zap, ...tile(category, style) };
}

/** How a group is drawn in the picker: its platform's mark, or its own icon. */
export function groupVisual(category: string, style: NodeStyle): NodeVisual {
  return {
    icon: PLATFORM_MARKS[category] ?? BY_CATEGORY[category] ?? Zap,
    ...tile(category, style),
  };
}

/** Where `category` sorts in the picker; an unknown one goes last, alphabetically. */
export function categoryRank(category: string): number {
  const index = CATEGORY_ORDER.indexOf(category);
  return index === -1 ? CATEGORY_ORDER.length : index;
}

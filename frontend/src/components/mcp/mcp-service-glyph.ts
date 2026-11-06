import {
  BookOpen,
  CalendarDays,
  ChartNoAxesCombined,
  Cloud,
  Database,
  FileText,
  FolderOpen,
  GitBranch,
  Mail,
  MessagesSquare,
  Palette,
  Search,
  ShieldCheck,
  ShoppingBag,
  SquareCheckBig,
  Workflow,
  Wrench,
  type LucideIcon,
} from "lucide-react";

export const MCP_SERVICE_GLYPHS = {
  calendar: CalendarDays,
  mail: Mail,
  data: Database,
  storage: FolderOpen,
  document: FileText,
  search: Search,
  communication: MessagesSquare,
  analytics: ChartNoAxesCombined,
  knowledge: BookOpen,
  development: GitBranch,
  automation: Workflow,
  tasks: SquareCheckBig,
  design: Palette,
  commerce: ShoppingBag,
  finance: ShieldCheck,
  cloud: Cloud,
  other: Wrench,
} satisfies Record<string, LucideIcon>;

type ServiceKind = keyof typeof MCP_SERVICE_GLYPHS;

const SERVICES: readonly [RegExp, ServiceKind][] = [
  [/calendar|scheduling|appointment/i, "calendar"],
  [/gmail|outlook|\bmail\b|email/i, "mail"],
  [/spreadsheet|sheets|database|postgres|\bsql\b/i, "data"],
  [/\bdrive\b|storage|\bfiles?\b/i, "storage"],
  [/\bdocs\b|documents?|\bpdf\b/i, "document"],
  [/search|retrieve|retrieval/i, "search"],
  [/\bchat\b|messaging/i, "communication"],
];

const CATEGORIES: Readonly<Record<string, ServiceKind>> = {
  communication: "communication",
  productivity: "calendar",
  data: "data",
  analytics: "analytics",
  observability: "analytics",
  knowledge: "knowledge",
  storage: "storage",
  development: "development",
  automation: "automation",
  "project-management": "tasks",
  design: "design",
  commerce: "commerce",
  finance: "finance",
  support: "communication",
  marketing: "analytics",
  sales: "commerce",
  media: "design",
  other: "cloud",
};

/** A service pictogram for an unbranded listing, never a guessed vendor logo. */
export function mcpServiceKind(name: string, category?: string): ServiceKind | null {
  const service = SERVICES.find(([pattern]) => pattern.test(name));
  return (
    service?.[1] ?? (category && category !== "custom" ? (CATEGORIES[category] ?? "other") : null)
  );
}

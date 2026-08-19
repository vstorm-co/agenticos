import {
  BarChart3,
  BookOpen,
  Code2,
  FilePenLine,
  FilePlus2,
  FileText,
  FolderOpen,
  Globe,
  ImageIcon,
  Plug,
  Search,
  TerminalSquare,
  Users,
  Wrench,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";

import type { StepKind } from "@/lib/tool-catalog";

/**
 * One mark per kind of thing a tool does.
 *
 * Beside `tool-catalog.ts` rather than inside the component that first drew it:
 * the chat's step list and the agent map both answer "what kind of tool is
 * this", and two tables would disagree the first time a kind was added to one
 * of them - which is #144's rule applied to the second reader.
 */
export const STEP_ICONS: Record<StepKind, LucideIcon> = {
  write: FilePlus2,
  edit: FilePenLine,
  read: FileText,
  list: FolderOpen,
  search: Search,
  shell: TerminalSquare,
  chart: BarChart3,
  image: ImageIcon,
  knowledge: BookOpen,
  web: Globe,
  skill: BookOpen,
  code: Code2,
  delegate: Users,
  mcp: Plug,
  tool: Wrench,
};

import {
  AudioLines,
  Bot,
  Brain,
  CalendarClock,
  FolderKanban,
  ListTodo,
  NotebookText,
  Radar,
  Table2,
  BarChart3,
  BookOpen,
  Clapperboard,
  Code2,
  FilePenLine,
  FilePlus2,
  FileText,
  FolderOpen,
  Globe,
  ImageIcon,
  Inbox,
  KeyRound,
  MessageSquare,
  PanelsTopLeft,
  Workflow,
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
  audio: AudioLines,
  video: Clapperboard,
  knowledge: BookOpen,
  web: Globe,
  skill: BookOpen,
  code: Code2,
  delegate: Users,
  mcp: Plug,
  tool: Wrench,
};

/** Object marks for platform operations; other services retain their own marks. */
export function toolIcon(name: string, kind: StepKind = "tool"): LucideIcon {
  const platform = name.startsWith("agenticos_");
  const action = platform ? name.slice("agenticos_".length) : name;
  if (
    (platform || /^(read|write|save|edit|delete|correct|share|search)_memory$/.test(name)) &&
    /(^|_)(memory|memories)(_|$)/.test(action)
  )
    return Brain;
  if (!platform) return STEP_ICONS[kind];
  if (/(^|_)tasks?(_|$)/.test(action)) return ListTodo;
  if (/(^|_)tables?(_|$)/.test(action)) return Table2;
  if (/(^|_)projects?(_|$)/.test(action)) return FolderKanban;
  if (/(^|_)watch(?:es)?(_|$)/.test(action)) return Radar;
  if (/(^|_)(routines?|triggers?)(_|$)/.test(action)) return CalendarClock;
  if (/(^|_)agents?(_|$)/.test(action)) return Bot;
  if (/(^|_)context(_|$)/.test(action)) return NotebookText;
  if (/(^|_)skills?(_|$)/.test(action)) return BookOpen;
  if (/(^|_)(documents?|files?)(_|$)/.test(action)) return FileText;
  if (/(^|_)folders?(_|$)/.test(action)) return FolderOpen;
  if (/(^|_)apps?(_|$)/.test(action)) return PanelsTopLeft;
  if (/(^|_)workflows?(_|$)/.test(action)) return Workflow;
  if (/(^|_)(users?|members?|groups?)(_|$)/.test(action)) return Users;
  if (/(^|_)channels?(_|$)/.test(action)) return MessageSquare;
  if (/(^|_)(inbox|cases?|notifications?)(_|$)/.test(action)) return Inbox;
  if (/(^|_)(secrets?|credentials?)(_|$)/.test(action)) return KeyRound;
  if (action.startsWith("search_")) return Search;
  return STEP_ICONS[kind];
}

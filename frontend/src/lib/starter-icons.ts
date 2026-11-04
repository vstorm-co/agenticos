import {
  Compass,
  Search,
  CalendarClock,
  Mail,
  Code2,
  ChartNoAxesColumn,
  FileText,
  Lightbulb,
  CheckCheck,
  Globe,
  Sparkles,
  type LucideIcon,
} from "lucide-react";
import { ChatIcon as MessageSquare } from "@/components/icons/product-icons";
import type { StarterIcon } from "@/types/agents";

/** Stable icon ids are shared with the agent spec; SVG components stay in the console. */
export const STARTER_ICONS: Record<StarterIcon, LucideIcon> = {
  message: MessageSquare,
  compass: Compass,
  search: Search,
  calendar: CalendarClock,
  mail: Mail,
  code: Code2,
  chart: ChartNoAxesColumn,
  file: FileText,
  lightbulb: Lightbulb,
  check: CheckCheck,
  globe: Globe,
  sparkles: Sparkles,
};
export const STARTER_ICON_IDS = [
  "message",
  "compass",
  "search",
  "calendar",
  "mail",
  "code",
  "chart",
  "file",
  "lightbulb",
  "check",
  "globe",
  "sparkles",
] as const satisfies readonly StarterIcon[];

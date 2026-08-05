/**
 * Who sees which sections, in what order, at what widths.
 *
 * A layout is data: an ordered list of sections, each an ordered list of
 * `{widget, span, titleKey?}` entries. Span and title ride the entry rather
 * than a widget-keyed lookup, so one widget can appear twice on a page with
 * different widths and names (the viewer's "Agents shared with you" is the
 * my-agents widget under another title).
 *
 * The layout only proposes; the registry's gates dispose. The page filters
 * every entry through its widget's gate, and a section whose entries all fail
 * renders nothing - not even its heading.
 */

import type { Permission } from "@/types/permissions";
import { WIDGETS, type Span, type WidgetId } from "./registry";

export interface LayoutEntry {
  widget: WidgetId;
  span: Span;
  /** i18n key under `dashboard`, overriding the widget's default title. */
  titleKey?: string;
}

export interface SectionDef {
  id: string;
  /** i18n key under `dashboard.sections`, or null for an untitled section. */
  titleKey: string | null;
  entries: LayoutEntry[];
}

export type AudienceId = "app_admin" | "steward" | "builder" | "operator" | "member" | "viewer";

/**
 * Role to audience. The app admin outranks the role; an unknown role - a
 * future custom one - lands on the member layout, the narrowest that still
 * shows the person their own work.
 */
export function resolveAudience(role: string, isAppAdmin: boolean): AudienceId {
  if (isAppAdmin) return "app_admin";
  switch (role) {
    case "owner":
    case "admin":
      return "steward";
    case "builder":
      return "builder";
    case "operator":
      return "operator";
    case "viewer":
      return "viewer";
    default:
      return "member";
  }
}

/**
 * Span to grid class. Literal strings so Tailwind's scanner sees them; below
 * `lg` everything stacks full-width. There is deliberately no span-to-pixels
 * table anywhere - charts measure themselves.
 */
export const SPAN_CLASS: Record<Span, string> = {
  s3: "lg:col-span-3",
  s4: "lg:col-span-4",
  s5: "lg:col-span-5",
  s6: "lg:col-span-6",
  s7: "lg:col-span-7",
  s8: "lg:col-span-8",
  s12: "lg:col-span-12",
};

const STEWARD_SECTIONS: SectionDef[] = [
  {
    id: "attention",
    titleKey: "attention",
    entries: [
      { widget: "approvals", span: "s7" },
      { widget: "recent-failures", span: "s5" },
      { widget: "budget-headroom", span: "s4" },
      { widget: "mcp-health", span: "s4" },
      { widget: "knowledge-freshness", span: "s4" },
    ],
  },
  {
    id: "usage",
    titleKey: "usage",
    entries: [
      { widget: "runs", span: "s8" },
      { widget: "outcomes", span: "s4" },
      { widget: "surfaces", span: "s6" },
      { widget: "agents", span: "s6" },
      { widget: "spend", span: "s6" },
      { widget: "model-mix", span: "s6" },
      { widget: "latency", span: "s4" },
      { widget: "active-users", span: "s8" },
    ],
  },
  {
    id: "people",
    titleKey: "people",
    entries: [
      { widget: "members", span: "s6" },
      { widget: "org-ratings", span: "s6" },
    ],
  },
  {
    id: "workspace",
    titleKey: "workspace",
    entries: [
      { widget: "my-agents", span: "s6" },
      { widget: "conversations", span: "s6" },
      { widget: "my-activity", span: "s12" },
    ],
  },
];

export const LAYOUTS: Record<AudienceId, SectionDef[]> = {
  app_admin: [
    {
      id: "deployment",
      titleKey: "deployment",
      entries: [
        { widget: "platform", span: "s8" },
        { widget: "health", span: "s4" },
        { widget: "top-orgs", span: "s7" },
        { widget: "platform-ratings", span: "s5" },
      ],
    },
    ...STEWARD_SECTIONS,
  ],
  steward: STEWARD_SECTIONS,
  operator: [
    {
      id: "attention",
      titleKey: "attention",
      entries: [
        { widget: "approvals", span: "s7" },
        { widget: "recent-failures", span: "s5" },
      ],
    },
    {
      id: "health",
      titleKey: "health",
      entries: [
        { widget: "outcomes", span: "s4" },
        { widget: "latency", span: "s3" },
        { widget: "org-ratings", span: "s5" },
      ],
    },
    {
      id: "usage",
      titleKey: "usage",
      entries: [
        { widget: "runs", span: "s8" },
        { widget: "surfaces", span: "s4" },
        { widget: "agents", span: "s6" },
        { widget: "spend", span: "s6" },
      ],
    },
    {
      id: "workspace",
      titleKey: "workspace",
      entries: [
        { widget: "my-agents", span: "s6" },
        { widget: "conversations", span: "s6" },
        { widget: "my-activity", span: "s12" },
      ],
    },
  ],
  builder: [
    {
      id: "build",
      titleKey: "build",
      entries: [
        { widget: "my-agents", span: "s7" },
        { widget: "conversations", span: "s5" },
      ],
    },
    {
      id: "adoption",
      titleKey: "adoption",
      entries: [
        { widget: "version-compare", span: "s6" },
        { widget: "agents", span: "s6" },
        { widget: "recent-failures", span: "s7" },
        { widget: "org-ratings", span: "s5" },
        { widget: "mcp-health", span: "s6" },
        { widget: "knowledge-freshness", span: "s6" },
      ],
    },
    {
      id: "usage",
      titleKey: "usage",
      entries: [
        { widget: "runs", span: "s8" },
        { widget: "outcomes", span: "s4" },
        { widget: "model-mix", span: "s6" },
        { widget: "surfaces", span: "s6" },
        { widget: "latency", span: "s4" },
        { widget: "active-users", span: "s8" },
      ],
    },
    {
      id: "activity",
      titleKey: null,
      entries: [{ widget: "my-activity", span: "s12" }],
    },
  ],
  member: [
    {
      id: "workspace",
      titleKey: null,
      entries: [
        { widget: "my-agents", span: "s7" },
        { widget: "conversations", span: "s5" },
        { widget: "my-activity", span: "s8" },
        { widget: "shared-with-you", span: "s4" },
        { widget: "my-top-agents", span: "s6" },
        { widget: "my-quality", span: "s6" },
      ],
    },
  ],
  viewer: [
    {
      id: "workspace",
      titleKey: null,
      entries: [
        { widget: "my-agents", span: "s8", titleKey: "widgets.my-agents.sharedTitle" },
        { widget: "shared-with-you", span: "s4" },
      ],
    },
  ],
};

/**
 * The layout, with every entry the caller may not see removed and every
 * section that ended up empty dropped - heading included. This is the whole
 * of the page's authorization: a widget that fails its gate is never
 * mounted, so its queries are never issued either.
 */
export function visibleSections(
  audience: AudienceId,
  can: (permission: Permission) => boolean,
  isAppAdmin: boolean,
): SectionDef[] {
  return LAYOUTS[audience]
    .map((section) => ({
      ...section,
      entries: section.entries.filter((entry) => WIDGETS[entry.widget].gate(can, isAppAdmin)),
    }))
    .filter((section) => section.entries.length > 0);
}

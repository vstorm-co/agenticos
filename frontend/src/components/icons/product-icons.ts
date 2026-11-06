import { createLucideIcon } from "lucide-react";

/** Product landmarks share a 24px grid and rounded geometry. Preserve Lucide's
 * ref, size and accessibility contract; provider logos stay in BrandIcon. */
export const AgentIcon = /* @__PURE__ */ createLucideIcon("Agent", [
  ["rect", { key: "0", x: 4, y: 5, width: 16, height: 14, rx: 6 }],
  ["path", { key: "1", d: "M9 10v4m6-4v4" }],
]);
export const ChatIcon = /* @__PURE__ */ createLucideIcon("Chat", [
  [
    "path",
    {
      key: "21",
      d: "M8 4.5h8A4.5 4.5 0 0 1 20.5 9v5a4.5 4.5 0 0 1-4.5 4.5h-5l-5.5 2v-4A4.5 4.5 0 0 1 3.5 13V9A4.5 4.5 0 0 1 8 4.5Z",
    },
  ],
  ["path", { key: "2", d: "M8 10h8m-8 4h5" }],
]);
export const InboxIcon = /* @__PURE__ */ createLucideIcon("Inbox", [
  [
    "path",
    {
      key: "22",
      d: "m4 12 2-6a2 2 0 0 1 1.9-1.5h8.2A2 2 0 0 1 18 6l2 6v5.5a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2Z",
    },
  ],
  ["path", { key: "3", d: "M4 12h4l1.5 3h5l1.5-3h4" }],
]);
export const BackgroundIcon = /* @__PURE__ */ createLucideIcon("Background", [
  ["path", { key: "4", d: "M12 3.5A8.5 8.5 0 1 1 3.5 12M4.8 7.5l.1-.1M8 4.5l.1-.1M12 8v4l3 2" }],
]);
export const AppIcon = /* @__PURE__ */ createLucideIcon("App", [
  ["rect", { key: "5", x: 3.5, y: 4.5, width: 17, height: 15, rx: 3 }],
  ["path", { key: "6", d: "M3.5 9h17M9 9v10.5" }],
]);
export const ProjectIcon = /* @__PURE__ */ createLucideIcon("Project", [
  [
    "path",
    {
      key: "23",
      d: "M3.5 8V6a2 2 0 0 1 2-2h4l2 3h7a2 2 0 0 1 2 2v9a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V8Z",
    },
  ],
  ["path", { key: "7", d: "M8 12v3m4-3v5m4-5v2" }],
]);
export const DocumentIcon = /* @__PURE__ */ createLucideIcon("Document", [
  ["path", { key: "8", d: "M13 3.5H7a2 2 0 0 0-2 2v13a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2v-9L13 3.5Z" }],
  ["path", { key: "9", d: "M13 3.5v4a2 2 0 0 0 2 2h4M9 13h6m-6 4h4" }],
]);
export const KnowledgeIcon = /* @__PURE__ */ createLucideIcon("Knowledge", [
  [
    "path",
    {
      key: "24",
      // i18n-exempt: SVG path coordinates, not user-facing text.
      d: "M12 6c-2.5-2-5.5-2-8.5-1v14c3-1 6-1 8.5 1 2.5-2 5.5-2 8.5-1V5c-3-1-6-1-8.5 1Zm0 0v14",
    },
  ],
]);
export const ContextIcon = /* @__PURE__ */ createLucideIcon("Context", [
  ["rect", { key: "10", x: 5, y: 3.5, width: 14, height: 17, rx: 2.5 }],
  ["path", { key: "11", d: "M10 3.5v7l2-1.5 2 1.5v-7M9 15h6m-6 3h4" }],
]);
export const SkillIcon = /* @__PURE__ */ createLucideIcon("Skill", [
  ["rect", { key: "12", x: 4, y: 4, width: 6, height: 6, rx: 1.75 }],
  ["rect", { key: "13", x: 14, y: 14, width: 6, height: 6, rx: 1.75 }],
  ["path", { key: "14", d: "M15 4v6m-3-3h6M4 14v4a2 2 0 0 0 2 2h4" }],
]);
export const RoutineIcon = /* @__PURE__ */ createLucideIcon("Routine", [
  ["path", { key: "15", d: "M4 8a8.5 8.5 0 1 1 0 8M3.5 3.5V8H8M12 7.5V12l3 2" }],
]);
export const WorkflowIcon = /* @__PURE__ */ createLucideIcon("Workflow", [
  ["rect", { key: "16", x: 3.5, y: 8.5, width: 6, height: 7, rx: 2 }],
  ["rect", { key: "17", x: 15, y: 3.5, width: 5.5, height: 6, rx: 1.75 }],
  ["rect", { key: "18", x: 15, y: 14.5, width: 5.5, height: 6, rx: 1.75 }],
  [
    "path",
    {
      key: "25",
      d: "M9.5 12H11a2 2 0 0 0 2-2V8.5a2 2 0 0 1 2-2m-5.5 5.5H11a2 2 0 0 1 2 2v1.5a2 2 0 0 0 2 2",
    },
  ],
]);
export const TableIcon = /* @__PURE__ */ createLucideIcon("Table", [
  ["rect", { key: "19", x: 3.5, y: 4.5, width: 17, height: 15, rx: 2.5 }],
  ["path", { key: "20", d: "M3.5 9.5h17m-17 5h17M9 9.5v10" }],
]);

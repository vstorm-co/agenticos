# Workflows and Tables console review — 2026-10-31

This implementation review follows the Agents console layout and the user's
screenshots. It covers the list, editor, run, table and document surfaces in
PR #1925. Backend acceptance evidence remains in
[the acceptance map](56-milestone-acceptance.md).

| Surface | Finding | Implemented correction |
| --- | --- | --- |
| Workflow and table catalogs | Descriptions shifted footers; height and pagination were inconsistent | Flex card bodies, aligned footers, full-height panels and bottom pagination |
| Run history | Expansion was necessary and pagination followed the first rows | Fill the workspace by default, remove expansion control, pin pagination |
| Run detail | Large summary tiles competed with a small graph and scattered results | Compact summary, growing canvas, single results panel for steps, output and files |
| Step configuration | Dense warnings, cramped inputs and unclear data flow | Window-sized Input / Parameters / Output panes, independent scrolling and contextual setup feedback |
| MCP selection | Generic node and only connected services hindered discovery | Service groups, catalog and registry search, inline connection/refresh and discovered actions |
| Email and channels | No direct account setup | Connect Gmail/Outlook and choose its actual tool; create/select channel bots inline with existing permissions |
| AI steps | Main settings were hidden | Expose supported effort, temperature and instructions; show Jev's supported decision controls |
| HTTP, files and data | Main operation controls were folded away | Expose method, authentication, headers/body, format/content, parsing, filters and resource selections |
| Canvas | Metadata crowded the editor; menus and notes lacked space | Metadata in Settings, spaced menus, resizable notes, default colors and minimap |
| Triggers/templates | Single entry; templates needed manual table setup | Independent entries, explicit start selection, templates provisioning private typed tables |
| Import | File and JSON inputs competed | Separate modes, styled file drop zone, JSON formatting and inline validation |
| Table grid | Quick add floated far from records; raw Markdown overwhelmed cells | Quick add after rows, bounded previews and direct record opening |
| Kanban | Abrupt native dragging and cramped Move action | Pointer overlay, target highlight, optimistic animated moves, rollback and keyboard Move menu |
| List | Long secondary values obscured titles | Page icons, status chips, bounded metadata, no raw document source in secondary values |
| Columns | Missing defaults and option colors | Typed defaults and persistent select/multi-select colors |
| Record/document | Narrow panel, repeated borders and metadata, raw Markdown first | Wider properties, document preview first, window-sized editing, toolbar and media rendering |
| Properties | Users maintained system YAML manually | Managed properties above Markdown; locked dates and author metadata |
| Document templates | Every document started empty | Editable column template applied on creation; replacing existing content requires confirmation |
| Attribution | User IDs concealed agent/API/workflow writes | Trusted source snapshots with avatars/icons; original creator preserved |
| Architect | Fragmented automation/table instructions | Dedicated skills and AgenticOS MCP tools for discovery, drafts, tests, published runs and records |

## Verification and boundaries

Chromium exercised step panes, catalog footers, bottom pagination, import,
document preview and mobile layouts. A separate private fixture verified an actual
pointer drag, persisted status/revision and updated author against PostgreSQL;
the fixture was archived afterwards. The user's example table was preserved.

Scoped frontend tests cover layout, dragging, configuration, connections and
source badges. Backend tests cover defaults, attribution, MCP, approvals, API view
visibility and trigger isolation. Migration 0244 completed a local upgrade,
downgrade and upgrade; schema drift checks passed. Lint, types, translations and
the strict documentation build run locally; full coverage and E2E remain CI checks.

External OAuth sign-ins and paid model conversations were not performed. MCP
actions come from actual discovered tools and allowlists. Historical origins are
not guessed: older records retain their recorded principal. Stored resource-scoped
capability bindings remain supported to preserve existing access limits.

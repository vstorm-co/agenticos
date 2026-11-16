"use client";

import { useState } from "react";
import { useTranslations } from "next-intl";
import { FileText, Search, Wrench, ListFilter, ChevronRight } from "lucide-react";

import { CopyButton } from "@/components/chat/copy-button";
import { MarkdownContent } from "@/components/chat/markdown-content";
import { Badge, Button, Input, Tabs, TabsList, TabsTrigger, TabsContent } from "@/components/ui";
import { PROMPT_VARIABLE_CLASS, promptVariablePieces } from "@/lib/prompt-variables";
import { RunInputSummary } from "./run-input-summary";
import { RunWaterfall } from "./run-waterfall";
import type { ManifestTool, RunManifest, ToolVisibility } from "@/types/runs";

const VISIBILITY = ["visible", "deferred", "withheld", "via_history"] as const;
const VISIBILITY_KEYS = {
  visible: "inputVisible",
  deferred: "inputDeferred",
  withheld: "inputWithheld",
  via_history: "inputViaHistory",
} as const;

/** Recorded input, with discovery policy separated from the last request's catalog. */
export function RunModelInput({ manifest }: { manifest: RunManifest }) {
  const t = useTranslations("pages.runs");
  const last = manifest.requests.at(-1);
  return (
    <div className="min-w-0 space-y-5">
      {manifest.tool_search && (
        <div className="bg-muted/30 flex flex-wrap items-center gap-3 rounded-xl border px-4 py-3">
          <div className="bg-background rounded-lg border p-2">
            <Search className="size-4" aria-hidden />
          </div>
          <div className="min-w-0 flex-1">
            <p className="text-sm font-medium">{t("inputSearchEnabled")}</p>
            <p className="text-muted-foreground mt-0.5 text-xs">
              {t("inputSearchPolicy", {
                count: manifest.tool_search.max_results,
                strategy: manifest.tool_search.strategy,
              })}
            </p>
          </div>
          <Badge variant="outline">{t("inputLastRequest")}</Badge>
        </div>
      )}
      {last?.tool_counts && (
        <dl className="grid grid-cols-4 gap-1.5">
          {VISIBILITY.map((visibility) => (
            <div key={visibility} className="rounded-lg border px-2.5 py-2">
              <dt className="text-muted-foreground text-xs">{t(VISIBILITY_KEYS[visibility])}</dt>
              <dd className="mt-1 text-xl font-semibold tabular-nums">
                {last.tool_counts?.[visibility]}
              </dd>
            </div>
          ))}
        </dl>
      )}
      <RunInputSummary manifest={manifest} />
      <Tabs defaultValue="prompt">
        <TabsList>
          <TabsTrigger value="prompt">
            <FileText className="size-3.5" aria-hidden />
            {t("inputPrompt")}
          </TabsTrigger>
          <TabsTrigger value="tools">
            <Wrench className="size-3.5" aria-hidden />
            {t("inputTools")}
            <span className="text-muted-foreground text-xs tabular-nums">
              {manifest.tools.length}
            </span>
          </TabsTrigger>
          <TabsTrigger value="requests">
            <ListFilter className="size-3.5" aria-hidden />
            {t("inputRequests")}
            <span className="text-muted-foreground text-xs tabular-nums">
              {manifest.requests.length}
            </span>
          </TabsTrigger>
        </TabsList>
        <TabsContent value="prompt" className="pt-3">
          <PromptReader manifest={manifest} />
        </TabsContent>
        <TabsContent value="tools" className="space-y-4 pt-3">
          <ToolCatalog manifest={manifest} />
        </TabsContent>
        <TabsContent value="requests" className="space-y-5 pt-3">
          <RunWaterfall requests={manifest.requests} />
          <RequestTools manifest={manifest} />
        </TabsContent>
      </Tabs>
    </div>
  );
}

function PromptReader({ manifest }: { manifest: RunManifest }) {
  const t = useTranslations("pages.runs");
  const [source, setSource] = useState(false);
  const blocks = [
    ...(manifest.instructions === null
      ? []
      : [{ label: t("inputInstructions"), text: manifest.instructions }]),
    ...manifest.system_prompts.map((text, index) => ({
      label: t("inputSystemBlock", { index: index + 1 }),
      text,
    })),
  ];
  return (
    <div className="space-y-3">
      <p className="text-muted-foreground text-xs leading-relaxed">{t("inputPromptHint")}</p>
      <section className="overflow-hidden rounded-xl border">
        <header className="bg-muted/20 flex items-center justify-between gap-2 border-b px-4 py-2">
          <h4 className="text-sm font-medium">{t("systemPrompt")}</h4>
          <div className="flex items-center gap-1">
            <Button
              variant="ghost"
              size="sm"
              aria-pressed={source}
              onClick={() => setSource(!source)}
            >
              {t(source ? "inputRead" : "inputSource")}
            </Button>
            <CopyButton
              className="opacity-100"
              text={blocks.map((block) => block.text).join("\n\n")}
            />
          </div>
        </header>
        {blocks.length === 0 ? (
          <p className="text-muted-foreground p-4 text-sm">{t("noInstructionsSent")}</p>
        ) : (
          <div className="divide-y">
            {blocks.map((block, index) => (
              <div key={index} className="min-w-0 p-4 sm:p-5">
                {source ? (
                  <>
                    <p className="text-muted-foreground mb-3 text-xs">{block.label}</p>
                    <pre className="font-mono text-xs leading-relaxed break-words whitespace-pre-wrap">
                      {promptVariablePieces(block.text).map((piece, index) => (
                        <span
                          key={index}
                          className={piece.variable ? PROMPT_VARIABLE_CLASS : undefined}
                        >
                          {piece.text}
                        </span>
                      ))}
                    </pre>
                  </>
                ) : (
                  <div className="text-sm leading-relaxed [overflow-wrap:anywhere] break-words">
                    <MarkdownContent content={block.text} inertImages highlightVariables />
                  </div>
                )}
              </div>
            ))}
          </div>
        )}
      </section>
    </div>
  );
}

function ToolCatalog({ manifest }: { manifest: RunManifest }) {
  const t = useTranslations("pages.runs");
  const [query, setQuery] = useState("");
  const [filter, setFilter] = useState<ToolVisibility | "all">("all");
  const [limit, setLimit] = useState(20);
  const known = manifest.tools.some((tool) => tool.visibility != null);
  const tools = manifest.tools.filter(
    (tool) =>
      (filter === "all" || tool.visibility === filter) &&
      `${tool.name} ${tool.description ?? ""}`.toLowerCase().includes(query.toLowerCase()),
  );
  const policy = manifest.tool_search;
  const exceptions = policy
    ? [...policy.exclude_capabilities, ...policy.exclude_mcp_servers, ...policy.exclude_tools]
    : [];
  return (
    <>
      <div>
        <h4 className="text-sm font-medium">{t("inputCatalog")}</h4>
        <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
          {t(known ? "inputCatalogHint" : "inputVisibilityUnknown")}
        </p>
      </div>
      {policy && (
        <details className="rounded-lg border px-3 py-2 text-xs">
          <summary className="cursor-pointer font-medium">{t("inputAlwaysVisible")}</summary>
          <p className="text-muted-foreground mt-2 break-words">
            {exceptions.length ? exceptions.join(", ") : t("inputNoExceptions")}
          </p>
        </details>
      )}
      <Input
        aria-label={t("inputToolsSearch")}
        placeholder={t("inputToolsSearch")}
        value={query}
        onChange={(event) => {
          setQuery(event.target.value);
          setLimit(20);
        }}
      />
      {known && (
        <div className="flex flex-wrap gap-1.5">
          <Button
            size="sm"
            variant={filter === "all" ? "secondary" : "ghost"}
            aria-pressed={filter === "all"}
            onClick={() => {
              setFilter("all");
              setLimit(20);
            }}
          >
            {t("inputCatalog")}
          </Button>
          {VISIBILITY.map((visibility) => (
            <Button
              key={visibility}
              size="sm"
              variant={filter === visibility ? "secondary" : "ghost"}
              aria-pressed={filter === visibility}
              onClick={() => {
                setFilter(visibility);
                setLimit(20);
              }}
            >
              {t(VISIBILITY_KEYS[visibility])}
            </Button>
          ))}
        </div>
      )}
      <p className="text-muted-foreground text-xs" role="status">
        {t("inputToolCount", { matched: tools.length, total: manifest.tools.length })}
      </p>
      {manifest.tools.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("noToolsSent")}</p>
      ) : tools.length === 0 ? (
        <p className="text-muted-foreground text-sm">{t("inputNoMatches")}</p>
      ) : (
        <ul className="divide-y overflow-hidden rounded-xl border">
          {tools.slice(0, limit).map((tool) => (
            <ToolRow key={`${tool.kind}-${tool.name}`} tool={tool} />
          ))}
        </ul>
      )}
      {tools.length > limit && (
        <Button variant="outline" onClick={() => setLimit(limit + 20)}>
          {t("inputShowMore")}
        </Button>
      )}
    </>
  );
}

function ToolRow({ tool }: { tool: ManifestTool }) {
  const t = useTranslations("pages.runs");
  // ToolText's known wrappers are formatting, not HTML to execute.
  const description = tool.description
    ?.replace(/<\/?(?:summary|description|returns|example)>/g, "\n")
    .trim();
  return (
    <li className="px-4 py-3">
      <details className="group">
        <summary className="cursor-pointer list-none space-y-1.5 [&::-webkit-details-marker]:hidden">
          <div className="flex items-start justify-between gap-3">
            <ChevronRight
              className="text-muted-foreground mt-0.5 size-3 shrink-0 transition-transform group-open:rotate-90"
              aria-hidden
            />
            <span className="min-w-0 flex-1 font-mono text-xs font-medium break-all">
              {tool.name}
            </span>
            <Badge variant="outline" className="shrink-0 text-[10px]">
              {t(tool.visibility ? VISIBILITY_KEYS[tool.visibility] : "inputUnknown")}
            </Badge>
          </div>
          {description && (
            <p className="text-muted-foreground line-clamp-2 text-xs leading-relaxed group-open:line-clamp-none">
              {description}
            </p>
          )}
        </summary>
        <p className="text-muted-foreground mt-3 mb-1 text-xs">{t("argumentSchema")}</p>
        <pre className="bg-muted/40 max-h-60 overflow-auto rounded p-3 text-xs">
          {JSON.stringify(tool.parameters_json_schema, null, 2)}
        </pre>
      </details>
    </li>
  );
}

function RequestTools({ manifest }: { manifest: RunManifest }) {
  const t = useTranslations("pages.runs");
  return (
    <section className="space-y-3">
      <div>
        <h4 className="text-sm font-medium">{t("inputRequestTools")}</h4>
        <p className="text-muted-foreground mt-1 text-xs leading-relaxed">
          {t("inputRequestHint")}
        </p>
      </div>
      {manifest.requests.map((request) => (
        <details key={request.index} className="rounded-lg border p-3">
          <summary className="cursor-pointer text-sm">
            <span className="font-medium">{t("inputRequest", { index: request.index + 1 })}</span>
            <span className="text-muted-foreground ml-2 text-xs">
              {request.tool_counts
                ? t("inputVisible") + ": " + request.tool_counts.visible
                : t("inputUnknown")}
            </span>
          </summary>
          <div className="mt-3 space-y-2 text-xs">
            {request.tool_counts && (
              <div className="flex flex-wrap gap-2">
                {VISIBILITY.map((visibility) => (
                  <Badge variant="secondary" key={visibility}>
                    {t(VISIBILITY_KEYS[visibility])}: {request.tool_counts?.[visibility]}
                  </Badge>
                ))}
              </div>
            )}
            <p className="text-muted-foreground font-mono leading-relaxed break-words">
              {request.visible_tool_names?.join(", ") ?? t("inputNoVisibleNames")}
            </p>
          </div>
        </details>
      ))}
    </section>
  );
}

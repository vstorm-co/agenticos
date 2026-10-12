"use client";

import { useTranslations } from "next-intl";

import { MarkdownContent } from "@/components/chat/markdown-content";
import { cn } from "@/lib/utils";
import { curlExample, type HttpMethod, type ReferenceOperation } from "@/lib/openapi/reference";
import { CopyCode } from "@/components/settings/copy-code";
import { FieldTable } from "./field-table";

const METHOD_STYLE: Record<HttpMethod, string> = {
  get: "bg-muted text-foreground",
  post: "bg-foreground text-background",
  put: "bg-foreground/80 text-background",
  patch: "bg-foreground/80 text-background",
  delete: "bg-destructive/12 text-destructive",
};

/** One endpoint: a row that opens to its parameters, body, responses and a curl call. */
export function ApiOperation({
  operation,
  baseUrl,
}: {
  operation: ReferenceOperation;
  baseUrl: string;
}) {
  const t = useTranslations("apiReference");
  return (
    <details className="group border-b last:border-0" id={operation.id}>
      <summary className="hover:bg-accent/50 flex cursor-pointer list-none items-center gap-3 rounded-md px-2 py-2.5 focus-visible:outline-offset-[-2px] [&::-webkit-details-marker]:hidden">
        <span
          className={cn(
            "w-16 shrink-0 rounded-md py-0.5 text-center font-mono text-[11px] font-semibold uppercase",
            METHOD_STYLE[operation.method],
          )}
        >
          {operation.method}
        </span>
        <span className="min-w-0 flex-1 truncate font-mono text-[13px]">{operation.path}</span>
        <span className="text-muted-foreground hidden max-w-[45%] truncate text-xs md:block">
          {operation.summary}
        </span>
      </summary>
      <div className="space-y-4 px-2 pt-1 pb-5 md:pl-[5.25rem]">
        <p className="text-sm font-medium md:hidden">{operation.summary}</p>
        {operation.description && (
          <div className="text-muted-foreground text-sm">
            <MarkdownContent content={operation.description} inertImages />
          </div>
        )}
        {operation.parameters.length > 0 && (
          <section className="space-y-1.5">
            <h4 className="text-xs font-semibold">{t("parameters")}</h4>
            <FieldTable rows={operation.parameters} showLocation />
          </section>
        )}
        {operation.bodyType && (
          <section className="space-y-1.5">
            <h4 className="text-xs font-semibold">
              {t("requestBody")}{" "}
              <span className="text-muted-foreground font-mono font-normal">
                {operation.bodyType}
              </span>
            </h4>
            {operation.body.length > 0 && <FieldTable rows={operation.body} showLocation={false} />}
          </section>
        )}
        <section className="space-y-1.5">
          <h4 className="text-xs font-semibold">{t("responses")}</h4>
          <ul className="space-y-1 text-xs">
            {operation.responses.map((response) => (
              <li key={response.status} className="flex gap-3">
                <span className="w-10 shrink-0 font-mono font-semibold">{response.status}</span>
                <span className="text-muted-foreground">{response.description}</span>
              </li>
            ))}
          </ul>
        </section>
        <section className="space-y-1.5">
          <h4 className="text-xs font-semibold">{t("example")}</h4>
          <CopyCode code={curlExample(operation, baseUrl)} />
        </section>
      </div>
    </details>
  );
}

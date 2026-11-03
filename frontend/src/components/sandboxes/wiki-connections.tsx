"use client";
import { useTranslations } from "next-intl";
import { FileIcon } from "@/components/files";
import type { WikiGraph } from "@/lib/wiki-graph";
export function Connections({
  graph,
  path,
  onSelect,
}: {
  graph: WikiGraph;
  path: string;
  onSelect: (path: string) => void;
}) {
  const t = useTranslations("wikiGraph");
  return (
    <div className="space-y-3 text-sm">
      {(["outgoing", "backlinks"] as const).map((direction) => {
        const edges = graph.edges.filter((edge) =>
          direction === "outgoing" ? edge.source === path : edge.target === path,
        );
        return (
          <section key={direction}>
            <h4 className="text-muted-foreground mb-1 text-xs">{t(direction)}</h4>
            <ul>
              {edges.map((edge) => {
                const target = direction === "outgoing" ? edge.target : edge.source;
                return (
                  <li key={target}>
                    <button
                      type="button"
                      className="hover:bg-accent flex w-full items-center gap-2 rounded-lg px-2 py-2 text-left"
                      title={target}
                      aria-label={target}
                      onClick={() => onSelect(target)}
                    >
                      <FileIcon name={target} className="text-muted-foreground size-4 shrink-0" />
                      <span className="min-w-0">
                        <span className="block truncate text-xs">
                          {graph.pages.find((page) => page.path === target)?.title ??
                            target.split("/").at(-1)}
                        </span>
                        <span className="text-muted-foreground block truncate text-[10px]">
                          {target}
                        </span>
                      </span>
                    </button>
                  </li>
                );
              })}
            </ul>
            {edges.length === 0 && <p className="text-muted-foreground">{t("none")}</p>}
          </section>
        );
      })}
      {graph.unresolved.some((link) => link.source === path) && (
        <section>
          <h4 className="text-muted-foreground mb-1 text-xs">{t("unresolved")}</h4>
          <ul>
            {graph.unresolved
              .filter((link) => link.source === path)
              .map((link) => (
                <li className="break-all" key={link.target}>
                  {t(link.reason, { target: link.target })}
                </li>
              ))}
          </ul>
        </section>
      )}
    </div>
  );
}

"use client";

import { useMemo, useRef, useState } from "react";
import { useTranslations } from "next-intl";
import { Minus, Plus, RotateCcw } from "lucide-react";
import { Button } from "@/components/ui";
import { layoutWiki } from "@/lib/wiki-layout";
import type { WikiGraph } from "@/lib/wiki-graph";

export function WikiCanvas({
  graph,
  selected,
  visible,
  onSelect,
}: {
  graph: WikiGraph;
  selected: string | null;
  visible: Set<string>;
  onSelect: (path: string) => void;
}) {
  const t = useTranslations("wikiGraph");
  const points = useMemo(() => layoutWiki(graph), [graph]);
  const [zoom, setZoom] = useState(1);
  const [pan, setPan] = useState({ x: 0, y: 0 });
  const drag = useRef<{ x: number; y: number; px: number; py: number } | null>(null);
  return (
    <div className="bg-card relative min-h-[24rem] min-w-0 overflow-hidden rounded-xl border lg:flex-1">
      <div className="bg-background absolute top-3 right-3 z-10 flex gap-1 rounded-lg border p-1">
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("zoomIn")}
          disabled={zoom >= 3}
          onClick={() => setZoom(Math.min(3, zoom + 0.25))}
        >
          <Plus className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("zoomOut")}
          disabled={zoom <= 0.5}
          onClick={() => setZoom(Math.max(0.5, zoom - 0.25))}
        >
          <Minus className="size-4" />
        </Button>
        <Button
          size="icon"
          variant="ghost"
          aria-label={t("reset")}
          onClick={() => {
            setZoom(1);
            setPan({ x: 0, y: 0 });
          }}
        >
          <RotateCcw className="size-4" />
        </Button>
      </div>
      <svg
        viewBox="0 0 1000 700"
        className="h-full min-h-[24rem] w-full touch-none"
        aria-label={t("title")}
        onPointerDown={(event) => {
          if (event.target !== event.currentTarget) return;
          event.currentTarget.setPointerCapture(event.pointerId);
          drag.current = { x: event.clientX, y: event.clientY, px: pan.x, py: pan.y };
        }}
        onPointerMove={(event) => {
          if (!drag.current) return;
          const scale = 1000 / event.currentTarget.getBoundingClientRect().width;
          setPan({
            x: drag.current.px + (event.clientX - drag.current.x) * scale,
            y: drag.current.py + (event.clientY - drag.current.y) * scale,
          });
        }}
        onPointerUp={() => {
          drag.current = null;
        }}
        onPointerCancel={() => {
          drag.current = null;
        }}
      >
        <g
          transform={`translate(${pan.x + 500 * (1 - zoom)} ${pan.y + 350 * (1 - zoom)}) scale(${zoom})`}
        >
          {graph.edges.map((edge) => {
            const a = points.get(edge.source),
              b = points.get(edge.target);
            if (!a || !b) return null;
            const active = selected === edge.source || selected === edge.target;
            return (
              <line
                key={JSON.stringify([edge.source, edge.target])}
                x1={a.x}
                y1={a.y}
                x2={b.x}
                y2={b.y}
                className={active ? "stroke-primary" : "stroke-muted-foreground/25"}
                strokeWidth={active ? 2 : 1}
                opacity={visible.has(edge.source) && visible.has(edge.target) ? 1 : 0.06}
                pointerEvents="none"
              />
            );
          })}
          {[...points.values()]
            .filter(({ page }) => visible.has(page.path))
            .map(({ page, ...point }) => {
              return (
                <g key={page.path} transform={`translate(${point.x} ${point.y})`}>
                  <circle r={selected === page.path ? 9 : 6} className="fill-primary" />
                  <text
                    y={-14}
                    textAnchor="middle"
                    className={
                      selected === page.path
                        ? "fill-foreground text-[34px] sm:text-[12px]"
                        : "fill-foreground hidden text-[34px] sm:block sm:text-[12px]"
                    }
                    pointerEvents="none"
                  >
                    {page.title.slice(0, 40)}
                  </text>
                  <circle
                    r={18}
                    fill="transparent"
                    role="button"
                    tabIndex={0}
                    aria-label={page.title}
                    aria-pressed={selected === page.path}
                    className="focus:stroke-primary cursor-pointer [r:64px] focus:outline-none sm:[r:18px]"
                    onClick={() => onSelect(page.path)}
                    onKeyDown={(event) => {
                      if (event.key === "Enter" || event.key === " ") {
                        event.preventDefault();
                        onSelect(page.path);
                      }
                    }}
                  >
                    <title>{page.path}</title>
                  </circle>
                </g>
              );
            })}
        </g>
      </svg>
    </div>
  );
}

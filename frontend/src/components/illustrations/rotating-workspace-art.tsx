"use client";

import { useEffect, useState } from "react";
import { Pause, Play } from "lucide-react";
import { useTranslations } from "next-intl";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { WorkspaceAtmosphere, type AtmosphereScene } from "./workspace-atmosphere";
import styles from "./rotating-workspace-art.module.css";

const SCENES: readonly AtmosphereScene[] = ["landscape", "orbit", "contours"];

export function RotatingWorkspaceArt() {
  const t = useTranslations("chat.empty");
  const reduced = useReducedMotion();
  const [paused, setPaused] = useState(false);
  const [scene, setScene] = useState(0);
  useEffect(() => {
    if (paused || reduced) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setScene((current) => (current + 1) % SCENES.length);
    }, 18000);
    return () => window.clearInterval(timer);
  }, [paused, reduced]);
  return (
    <>
      <div className="pointer-events-none absolute inset-0" aria-hidden>
        {SCENES.map((name, index) => (
          <div key={name} className={styles.scene} data-active={index === scene}>
            <WorkspaceAtmosphere
              scene={name}
              animated={index === scene && !paused && !reduced}
              className="h-full w-full"
            />
          </div>
        ))}
      </div>
      {!reduced && (
        <button
          type="button"
          onClick={() => setPaused((current) => !current)}
          aria-label={t(paused ? "playArtwork" : "pauseArtwork")}
          title={t(paused ? "playArtwork" : "pauseArtwork")}
          className="pressable-icon text-muted-foreground hover:text-foreground hover:bg-accent focus-visible:ring-ring touch:min-h-11 touch:min-w-11 absolute right-0 bottom-0 flex size-8 items-center justify-center rounded-lg outline-none focus-visible:ring-2"
        >
          {paused ? (
            <Play className="size-3.5" aria-hidden />
          ) : (
            <Pause className="size-3.5" aria-hidden />
          )}
        </button>
      )}
    </>
  );
}

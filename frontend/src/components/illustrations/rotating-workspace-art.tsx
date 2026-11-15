"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { WorkspaceAtmosphere, type AtmosphereScene } from "./workspace-atmosphere";
import styles from "./rotating-workspace-art.module.css";

const SCENES: readonly AtmosphereScene[] = ["landscape", "orbit", "contours"];

export function RotatingWorkspaceArt() {
  const reduced = useReducedMotion();
  const [scene, setScene] = useState(0);
  useEffect(() => {
    if (reduced) return;
    const timer = window.setInterval(() => {
      if (!document.hidden) setScene((current) => (current + 1) % SCENES.length);
    }, 18000);
    return () => window.clearInterval(timer);
  }, [reduced]);
  return (
    <div className="pointer-events-none absolute inset-0" aria-hidden>
      {SCENES.map((name, index) => (
        <div key={name} className={styles.scene} data-active={index === scene}>
          <WorkspaceAtmosphere
            scene={name}
            animated={index === scene && !reduced}
            className="h-full w-full"
          />
        </div>
      ))}
    </div>
  );
}

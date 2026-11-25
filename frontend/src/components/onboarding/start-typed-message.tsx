"use client";

import { useEffect, useState } from "react";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import styles from "./start-typed-message.module.css";

/** Reserve the full text's geometry; assistive technology hears one complete message. */
export function StartTypedMessage({ message }: { message: string }) {
  const [length, setLength] = useState(0);
  const reducedMotion = useReducedMotion();
  useEffect(() => {
    if (reducedMotion) {
      const frame = requestAnimationFrame(() => setLength(message.length));
      return () => cancelAnimationFrame(frame);
    }
    let frame: number;
    const started = performance.now();
    const tick = (now: number) => {
      const next = Math.min(message.length, Math.ceil(((now - started) / 1400) * message.length));
      setLength(next);
      if (next < message.length) frame = requestAnimationFrame(tick);
    };
    frame = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(frame);
  }, [message, reducedMotion]);
  return (
    <span className={styles.message}>
      <span className={styles.full}>{message}</span>
      <span className={styles.typed} aria-hidden>
        {message.slice(0, length)}
      </span>
    </span>
  );
}

"use client";

import { Face } from "@/components/desktop/blobby-pickers";
import { faceOf } from "@/lib/desktop/blobby-cast";
import styles from "./companions.module.css";

/** Decorative members of the product's existing blobby cast, never real teammates. */
export function StartCompanions({
  members = ["pebble", "mochi", "byte"],
}: {
  members?: readonly string[];
}) {
  return (
    <div className={styles.companions} aria-hidden="true">
      {members.map((id) => (
        <span key={id} className={styles.character}>
          <Face face={faceOf({ kind: "cast", id })} size={64} />
        </span>
      ))}
    </div>
  );
}

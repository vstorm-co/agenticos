"use client";

import { Face } from "@/components/desktop/blobby-pickers";
import { AVATAR_TRAITS } from "@/lib/avatar-policy";
import { faceOf } from "@/lib/desktop/blobby-cast";
import styles from "./companions.module.css";

/** Soft, pastel versions of the blobby cast for decorative setup illustrations. */
export function StartCompanions({
  members = ["pebble", "mochi", "byte"],
}: {
  members?: readonly string[];
}) {
  return (
    <div className={styles.companions} aria-hidden="true">
      {members.map((id) => {
        const rectangular = ["mochi", "byte", "sunny"].includes(id);
        const face = {
          ...faceOf({ kind: "cast", id }),
          traits: {
            ...AVATAR_TRAITS,
            shape: rectangular ? 0.54 : 0.1,
            tone: 0.1,
            "body.r": rectangular ? 0.95 : 0.65,
            "body.ratio": 0.5,
            "body.n": rectangular ? 0.15 : 1 / 6,
            "body.rot": 0.5,
          },
        };
        return (
          <span key={id} className={styles.character}>
            <Face face={face} size={64} />
          </span>
        );
      })}
    </div>
  );
}

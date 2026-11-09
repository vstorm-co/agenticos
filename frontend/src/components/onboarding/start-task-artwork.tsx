import type { StartGoal } from "@/lib/onboarding-api";
import styles from "./start.module.css";

/** Decorative task-shaped paper illustrations; they do not represent execution progress. */
export function StartTaskArtwork({ goal }: { goal: StartGoal }) {
  return (
    <div className={styles.artwork} aria-hidden="true">
      <svg viewBox="0 0 160 112" fill="none">
        {goal === "meeting" ? (
          <>
            <rect
              className={styles.artPaper}
              x="28"
              y="18"
              width="87"
              height="76"
              rx="7"
              transform="rotate(-8 28 18)"
            />
            <rect className={styles.artPaper} x="48" y="12" width="85" height="86" rx="7" />
            <path className={styles.artInk} d="M62 30h35M62 47l3 3 5-6M62 64l3 3 5-6" />
            <path className={styles.artFaint} d="M80 47h36M80 64h28M80 81h34" />
            <rect className={styles.artFaint} x="62" y="77" width="8" height="8" rx="2" />
          </>
        ) : goal === "document" ? (
          <>
            <rect
              className={styles.artPaper}
              x="39"
              y="10"
              width="78"
              height="91"
              rx="7"
              transform="rotate(-5 39 10)"
            />
            <path className={styles.artInk} d="M55 29h35M55 44h42" />
            <path className={styles.artFaint} d="M55 56h34M55 68h25M55 80h34" />
            <circle className={styles.artPaper} cx="111" cy="72" r="22" />
            <circle className={styles.artInk} cx="109" cy="70" r="9" />
            <path className={styles.artInk} d="m116 77 7 7" />
          </>
        ) : (
          <>
            <rect
              className={styles.artPaper}
              x="17"
              y="30"
              width="43"
              height="65"
              rx="5"
              transform="rotate(-6 17 30)"
            />
            <rect
              className={styles.artPaper}
              x="102"
              y="24"
              width="43"
              height="65"
              rx="5"
              transform="rotate(6 102 24)"
            />
            <rect className={styles.artPaper} x="57" y="14" width="49" height="83" rx="6" />
            <path
              className={styles.artFaint}
              d="M28 46h19M28 58h16M117 43h15M117 56h15M69 34h25M69 47h25"
            />
            <circle className={styles.artInk} cx="81" cy="73" r="11" />
            <path className={styles.artInk} d="m76 73 3 3 7-7" />
          </>
        )}
      </svg>
    </div>
  );
}

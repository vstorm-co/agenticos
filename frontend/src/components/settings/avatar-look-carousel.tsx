"use client";

import { useEffect, useId, useRef, useState } from "react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import { CONTROL_FOCUS } from "@/components/ui/control-styles";
import { AVATAR_COLORS } from "@/lib/avatar-color";
import styles from "./avatar-look-carousel.module.css";

const LOOKS = [null, ...AVATAR_COLORS.map(({ slot }) => slot)];

/** Browse the finite account palette without saving until a person chooses a look. */
function nearestLook(element: HTMLDivElement): number {
  const center = element.scrollLeft + element.clientWidth / 2;
  let chosen = 0;
  let distance = Infinity;
  Array.from(element.children).forEach((child, index) => {
    if (!(child instanceof HTMLElement)) return;
    const delta = Math.abs(child.offsetLeft + child.offsetWidth / 2 - center);
    if (delta < distance) {
      distance = delta;
      chosen = index;
    }
  });
  return chosen;
}

export function AvatarLookCarousel({
  seed,
  value,
  onChange,
  disabled,
  hint,
}: {
  seed: string;
  value: number | null;
  onChange: (slot: number | null) => void;
  disabled?: boolean;
  hint?: string;
}) {
  const t = useTranslations("avatarColor");
  const id = useId();
  const track = useRef<HTMLDivElement>(null);
  const pending = useRef<number | null>(null);
  const interacted = useRef(false);
  const [current, setCurrent] = useState(0);
  const [announced, setAnnounced] = useState<number | null>(null);
  const name = (slot: number | null) => (slot === null ? t("auto") : t("option", { n: slot }));
  const move = (index: number, behavior: ScrollBehavior = "auto") => {
    const element = track.current;
    const child = element?.children[index];
    if (!element || !(child instanceof HTMLElement)) return;
    pending.current = index;
    setCurrent(index);
    element.scrollTo({
      left: child.offsetLeft + child.offsetWidth / 2 - element.clientWidth / 2,
      behavior,
    });
  };
  useEffect(() => {
    const element = track.current;
    if (!element) return;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let frame: number | undefined;
    const settle = () => {
      const index = nearestLook(element);
      if (pending.current !== null && index !== pending.current) return;
      pending.current = null;
      setCurrent(index);
      if (interacted.current) setAnnounced(index);
    };
    const hasScrollEnd = "onscrollend" in element;
    const scroll = () => {
      if (pending.current === null && frame === undefined) {
        frame = requestAnimationFrame(() => {
          setCurrent(nearestLook(element));
          frame = undefined;
        });
      }
      if (!hasScrollEnd) {
        clearTimeout(timer);
        timer = setTimeout(settle, 140);
      }
    };
    element.addEventListener("scroll", scroll, { passive: true });
    if (hasScrollEnd) element.addEventListener("scrollend", settle);
    return () => {
      element.removeEventListener("scroll", scroll);
      element.removeEventListener("scrollend", settle);
      clearTimeout(timer);
      if (frame !== undefined) cancelAnimationFrame(frame);
    };
  }, []);
  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      const index = LOOKS.indexOf(value);
      const element = track.current;
      const child = element?.children[index];
      if (!element || !(child instanceof HTMLElement)) return;
      pending.current = index;
      setCurrent(index);
      element.scrollTo({
        left: child.offsetLeft + child.offsetWidth / 2 - element.clientWidth / 2,
        behavior: "instant",
      });
    });
    return () => cancelAnimationFrame(frame);
  }, [value]);
  const navigate = (direction: -1 | 1) => {
    interacted.current = true;
    const element = track.current;
    if (!element) return;
    const index = pending.current ?? nearestLook(element);
    const target = Math.max(0, Math.min(LOOKS.length - 1, index + direction));
    if (index === target) return;
    move(target);
  };
  return (
    <section
      className={styles.carousel}
      aria-roledescription={t("carouselRole")}
      aria-labelledby={id}
    >
      <div className={styles.heading}>
        <div>
          <h3 id={id}>{t("chooseLook")}</h3>
          <p>{hint ?? t("lookHint")}</p>
        </div>
        <div className={styles.controls}>
          <button
            type="button"
            className={CONTROL_FOCUS}
            aria-label={t("previousLook")}
            aria-disabled={current === 0}
            disabled={disabled}
            onClick={() => navigate(-1)}
          >
            <ChevronLeft size={16} aria-hidden />
          </button>
          <button
            type="button"
            className={CONTROL_FOCUS}
            aria-label={t("nextLook")}
            aria-disabled={current === LOOKS.length - 1}
            disabled={disabled}
            onClick={() => navigate(1)}
          >
            <ChevronRight size={16} aria-hidden />
          </button>
        </div>
      </div>
      <div
        ref={track}
        className={styles.track}
        onPointerDown={() => {
          interacted.current = true;
          pending.current = null;
        }}
        onWheel={() => {
          interacted.current = true;
          pending.current = null;
        }}
        onKeyDown={() => {
          interacted.current = true;
          pending.current = null;
        }}
      >
        {LOOKS.map((slot, index) => (
          <div
            key={slot ?? "auto"}
            role="group"
            data-current={index === current}
            aria-roledescription={t("slideRole")}
            aria-label={t("lookPosition", { current: index + 1, total: LOOKS.length })}
          >
            <button
              type="button"
              className={CONTROL_FOCUS}
              aria-label={name(slot)}
              aria-pressed={value === slot}
              disabled={disabled}
              onClick={() => {
                interacted.current = true;
                move(index);
                onChange(slot);
              }}
            >
              <span className={styles.face} aria-hidden>
                <AvatarFace seed={seed} colorSlot={slot} />
              </span>
              <span className={styles.caption}>
                {name(slot)}
                {value === slot && <Check size={12} aria-hidden />}
              </span>
            </button>
          </div>
        ))}
      </div>
      <span className="sr-only" role="status">
        {announced === null
          ? ""
          : t("lookPosition", { current: announced + 1, total: LOOKS.length })}
      </span>
    </section>
  );
}

"use client";

import { useEffect, useId, useRef, useState, type KeyboardEvent, type PointerEvent } from "react";
import { animate, motion, useMotionValue, useTransform, type MotionValue } from "motion/react";
import { Check, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslations } from "next-intl";
import { AvatarFace } from "@/components/ui/avatar-face";
import { CONTROL_FOCUS } from "@/components/ui/control-styles";
import { useReducedMotion } from "@/hooks/use-reduced-motion";
import { AVATAR_COLORS } from "@/lib/avatar-color";
import styles from "./avatar-look-carousel.module.css";

const LOOKS = [null, ...AVATAR_COLORS.map(({ slot }) => slot)];
const GAP = 20;
const SNAP_SPRING = { type: "spring", stiffness: 340, damping: 34, mass: 0.85 } as const;
const clamp = (index: number) => Math.max(0, Math.min(LOOKS.length - 1, index));
const lookIndex = (value: number | null) => Math.max(0, LOOKS.indexOf(value));

interface Drag {
  pointer: number;
  startX: number;
  startY: number;
  origin: number;
  lastX: number;
  lastTime: number;
  velocity: number;
  sideways: boolean;
  capture: HTMLElement;
}

function releaseCapture(gesture: Drag) {
  if (gesture.capture.hasPointerCapture?.(gesture.pointer))
    gesture.capture.releasePointerCapture(gesture.pointer);
}

/** Browse the real account palette; a gesture never changes the saved colour. */
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
  const reduced = useReducedMotion();
  const viewport = useRef<HTMLDivElement>(null);
  const buttons = useRef(new Map<number, HTMLButtonElement>());
  const target = useRef(lookIndex(value));
  const previousValue = useRef(value);
  const position = useMotionValue(lookIndex(value));
  const spring = useRef<ReturnType<typeof animate> | null>(null);
  const drag = useRef<Drag | null>(null);
  const suppressClick = useRef(false);
  const clickReset = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [current, setCurrent] = useState(() => lookIndex(value));
  const [announced, setAnnounced] = useState<number | null>(null);
  const [dragging, setDragging] = useState(false);
  const [cardWidth, setCardWidth] = useState(176);
  const step = cardWidth + GAP;
  const x = useTransform(position, (index) => -index * step - cardWidth / 2);
  const name = (slot: number | null) => (slot === null ? t("auto") : t("option", { n: slot }));

  const browse = (index: number, announce = true) => {
    const next = clamp(index);
    target.current = next;
    setCurrent(next);
    spring.current?.stop();
    if (reduced) {
      position.jump(next);
      if (announce) setAnnounced(next);
    } else {
      spring.current = animate(position, next, {
        ...SNAP_SPRING,
        onComplete: () => {
          if (announce) setAnnounced(next);
        },
      });
    }
  };

  useEffect(() => {
    const element = viewport.current;
    if (!element) return;
    const measure = () => {
      if (element.clientWidth > 0)
        setCardWidth(Math.min(176, Math.max(148, element.clientWidth * 0.3)));
    };
    const frame = requestAnimationFrame(measure);
    const observer = new ResizeObserver(measure);
    observer.observe(element);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, []);
  useEffect(() => {
    if (previousValue.current === value) return;
    previousValue.current = value;
    const frame = requestAnimationFrame(() => {
      const index = lookIndex(value);
      if (target.current === index) return;
      spring.current?.stop();
      const gesture = drag.current;
      drag.current = null;
      if (gesture) releaseCapture(gesture);
      target.current = index;
      position.jump(index);
      setCurrent(index);
      setDragging(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [value, position]);
  useEffect(() => {
    if (!reduced && !disabled) return;
    const gesture = drag.current;
    drag.current = null;
    if (gesture) releaseCapture(gesture);
    if (reduced) {
      spring.current?.stop();
      position.jump(target.current);
    } else if (gesture) {
      spring.current = animate(position, target.current, SNAP_SPRING);
    }
    const frame = requestAnimationFrame(() => {
      setCurrent(target.current);
      setDragging(false);
    });
    return () => cancelAnimationFrame(frame);
  }, [reduced, disabled, position]);
  useEffect(
    () => () => {
      spring.current?.stop();
      const gesture = drag.current;
      drag.current = null;
      if (gesture) releaseCapture(gesture);
      position.stop();
      clearTimeout(clickReset.current);
    },
    [position],
  );

  const pointerDown = (event: PointerEvent<HTMLDivElement>) => {
    if (disabled || event.button !== 0 || drag.current) return;
    clearTimeout(clickReset.current);
    suppressClick.current = false;
    spring.current?.stop();
    const capture =
      event.target instanceof Element
        ? (event.target.closest("button") ?? event.currentTarget)
        : event.currentTarget;
    drag.current = {
      capture,
      pointer: event.pointerId,
      startX: event.clientX,
      startY: event.clientY,
      origin: position.get(),
      lastX: event.clientX,
      lastTime: event.timeStamp,
      velocity: 0,
      sideways: false,
    };
    capture.setPointerCapture?.(event.pointerId);
  };
  const pointerMove = (event: PointerEvent<HTMLDivElement>) => {
    const gesture = drag.current;
    if (disabled || !gesture || gesture.pointer !== event.pointerId) return;
    const dx = event.clientX - gesture.startX;
    const dy = event.clientY - gesture.startY;
    if (!gesture.sideways) {
      if (Math.max(Math.abs(dx), Math.abs(dy)) < 8) return;
      if (Math.abs(dy) >= Math.abs(dx)) {
        drag.current = null;
        releaseCapture(gesture);
        browse(target.current, false);
        return;
      }
      gesture.sideways = true;
      spring.current?.stop();
      suppressClick.current = true;
      setDragging(true);
    }
    event.preventDefault();
    const now = event.timeStamp;
    gesture.velocity = Math.max(
      -1.2,
      Math.min(1.2, (event.clientX - gesture.lastX) / Math.max(16, now - gesture.lastTime)),
    );
    gesture.lastX = event.clientX;
    gesture.lastTime = now;
    const candidate = gesture.origin - dx / step;
    const boundary = clamp(candidate);
    position.set(boundary + Math.max(-0.38, Math.min(0.38, (candidate - boundary) * 0.16)));
    setCurrent(clamp(Math.round(candidate)));
  };
  const pointerEnd = (event: PointerEvent<HTMLDivElement>, cancelled = false) => {
    const gesture = drag.current;
    if (!gesture || gesture.pointer !== event.pointerId) return;
    drag.current = null;
    setDragging(false);
    releaseCapture(gesture);
    const velocity = !cancelled && event.timeStamp - gesture.lastTime < 80 ? gesture.velocity : 0;
    browse(
      gesture.sideways ? Math.round(position.get() - (velocity * 100) / step) : target.current,
      gesture.sideways && !cancelled,
    );
    // A pointer release can dispatch a click on the card where the swipe began.
    clickReset.current = setTimeout(() => {
      suppressClick.current = false;
    }, 0);
  };
  const keyDown = (event: KeyboardEvent<HTMLDivElement>) => {
    const next =
      event.key === "ArrowRight"
        ? target.current + 1
        : event.key === "ArrowLeft"
          ? target.current - 1
          : event.key === "Home"
            ? 0
            : event.key === "End"
              ? LOOKS.length - 1
              : null;
    if (next === null || disabled) return;
    event.preventDefault();
    browse(next);
    buttons.current.get(clamp(next))?.focus({ preventScroll: true });
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
            onClick={() => browse(target.current - 1)}
          >
            <ChevronLeft size={17} aria-hidden />
          </button>
          <button
            type="button"
            className={CONTROL_FOCUS}
            aria-label={t("nextLook")}
            aria-disabled={current === LOOKS.length - 1}
            disabled={disabled}
            onClick={() => browse(target.current + 1)}
          >
            <ChevronRight size={17} aria-hidden />
          </button>
        </div>
      </div>
      <div
        ref={viewport}
        className={styles.viewport}
        data-avatar-carousel-viewport
        data-motion={reduced ? "instant" : "spring"}
        data-dragging={dragging || undefined}
        onPointerDown={pointerDown}
        onPointerMove={pointerMove}
        onPointerUp={(event) => pointerEnd(event)}
        onPointerCancel={(event) => pointerEnd(event, true)}
        onLostPointerCapture={(event) => pointerEnd(event, true)}
        onKeyDown={keyDown}
        onClickCapture={(event) => {
          if (suppressClick.current) {
            event.preventDefault();
            event.stopPropagation();
          }
        }}
      >
        <div className={styles.stageLight} aria-hidden />
        <motion.div className={styles.track} style={{ x }} data-avatar-carousel-track>
          {LOOKS.map((slot, index) => (
            <Look
              key={slot ?? "auto"}
              seed={seed}
              slot={slot}
              index={index}
              position={position}
              current={current}
              selected={value === slot}
              width={cardWidth}
              reduced={reduced}
              label={name(slot)}
              positionLabel={t("lookPosition", { current: index + 1, total: LOOKS.length })}
              slideRole={t("slideRole")}
              disabled={disabled}
              buttonRef={(button) => {
                if (button) buttons.current.set(index, button);
                else buttons.current.delete(index);
              }}
              onFocus={() => {
                if (target.current !== index) browse(index);
              }}
              onChoose={() => {
                if (!suppressClick.current) {
                  browse(index);
                  onChange(slot);
                }
              }}
            />
          ))}
        </motion.div>
      </div>
      <div className={styles.position} aria-hidden>
        <span className={styles.positionMarks}>
          {LOOKS.map((slot, index) => (
            <span key={slot ?? "auto"} data-current={index === current} />
          ))}
        </span>
        <span>{t("lookPosition", { current: current + 1, total: LOOKS.length })}</span>
      </div>
      <span className="sr-only" role="status">
        {announced === null
          ? ""
          : t("lookPosition", { current: announced + 1, total: LOOKS.length })}
      </span>
    </section>
  );
}

function Look({
  seed,
  slot,
  index,
  position,
  current,
  selected,
  width,
  reduced,
  label,
  positionLabel,
  slideRole,
  disabled,
  buttonRef,
  onFocus,
  onChoose,
}: {
  seed: string;
  slot: number | null;
  index: number;
  position: MotionValue<number>;
  current: number;
  selected: boolean;
  width: number;
  reduced: boolean;
  label: string;
  positionLabel: string;
  slideRole: string;
  disabled?: boolean;
  buttonRef: (button: HTMLButtonElement | null) => void;
  onFocus: () => void;
  onChoose: () => void;
}) {
  const distance = useTransform(position, (value) => index - value);
  const scale = useTransform(distance, [-2, -1, 0, 1, 2], [0.72, 0.86, 1, 0.86, 0.72]);
  const opacity = useTransform(distance, [-2, -1, 0, 1, 2], [0.35, 0.8, 1, 0.8, 0.35]);
  const rotate = useTransform(distance, [-2, -1, 0, 1, 2], [-9, -5, 0, 5, 9]);
  const y = useTransform(distance, [-2, -1, 0, 1, 2], [28, 12, 0, 12, 28]);
  return (
    <motion.div
      role="group"
      aria-roledescription={slideRole}
      aria-label={positionLabel}
      className={styles.look}
      data-current={index === current}
      style={{
        width,
        scale: reduced ? 1 : scale,
        opacity,
        rotate: reduced ? 0 : rotate,
        y: reduced ? 0 : y,
      }}
    >
      <button
        ref={buttonRef}
        type="button"
        className={CONTROL_FOCUS}
        aria-label={label}
        aria-pressed={selected}
        tabIndex={index === current ? 0 : -1}
        disabled={disabled}
        onFocus={onFocus}
        onClick={onChoose}
      >
        <span className={styles.face} aria-hidden>
          <AvatarFace seed={seed} colorSlot={slot} />
        </span>
        <span className={styles.caption}>
          {label}
          {selected && <Check size={13} aria-hidden />}
        </span>
      </button>
    </motion.div>
  );
}

"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { ChevronLeft, ChevronRight, Inbox, Sparkles } from "lucide-react";
import { useTranslations } from "next-intl";

import { glideOrJump } from "@/lib/motion";
import { ChatHomeInbox } from "./chat-home-inbox";

/** Two finite, manually navigated pages; cached Inbox stays mounted while browsing prompts. */
export function ChatHomeCarousel({
  suggestionsRef,
}: {
  suggestionsRef: (node: HTMLDivElement | null) => void;
}) {
  const t = useTranslations("chat.homeCarousel");
  const track = useRef<HTMLDivElement>(null);
  const previous = useRef<HTMLButtonElement>(null);
  const markers = useRef<HTMLDivElement>(null);
  const next = useRef<HTMLButtonElement>(null);
  const pending = useRef<number | null>(null);
  const [current, setCurrent] = useState(0);
  const [announcement, setAnnouncement] = useState("");
  const labels = [t("inbox"), t("prompts")] as const;
  const select = useCallback((index: number) => {
    const disabled = index === 0 ? previous.current : next.current;
    if (document.activeElement === disabled) {
      markers.current
        ?.querySelectorAll<HTMLButtonElement>("button")
        .item(index)
        ?.focus({ preventScroll: true });
    }
    setCurrent(index);
  }, []);

  useEffect(() => {
    const node = track.current;
    if (!node) return;
    let frame = 0;
    let timer: ReturnType<typeof setTimeout> | undefined;
    let settled = 0;
    const nearest = () =>
      Math.min(1, Math.round(Math.abs(node.scrollLeft) / (node.clientWidth || 1)));
    const finish = () => {
      const index = nearest();
      if (pending.current !== null && index !== pending.current) return;
      pending.current = null;
      select(index);
      if (index !== settled) {
        settled = index;
        setAnnouncement(t("position", { current: index + 1, total: 2 }));
      }
    };
    const nativeEnd = "onscrollend" in node;
    const scroll = () => {
      if (!frame && pending.current === null) {
        frame = requestAnimationFrame(() => {
          frame = 0;
          select(nearest());
        });
      }
      if (!nativeEnd) {
        clearTimeout(timer);
        timer = setTimeout(finish, 120);
      }
    };
    const interrupt = () => {
      pending.current = null;
    };
    node.addEventListener("scroll", scroll);
    if (nativeEnd) node.addEventListener("scrollend", finish);
    node.addEventListener("pointerdown", interrupt);
    node.addEventListener("keydown", interrupt);
    node.addEventListener("wheel", interrupt, { passive: true });
    return () => {
      cancelAnimationFrame(frame);
      clearTimeout(timer);
      node.removeEventListener("scroll", scroll);
      node.removeEventListener("scrollend", finish);
      node.removeEventListener("pointerdown", interrupt);
      node.removeEventListener("keydown", interrupt);
      node.removeEventListener("wheel", interrupt);
    };
  }, [t, select]);

  const go = (index: number) => {
    const node = track.current;
    const slide = node?.children.item(index);
    if (!node || !(slide instanceof HTMLElement)) return;
    select(index);
    if (Math.abs(node.scrollLeft - slide.offsetLeft) < 1) {
      pending.current = null;
      return;
    }
    pending.current = index;
    node.scrollTo({ left: slide.offsetLeft, behavior: glideOrJump() });
  };

  return (
    <section
      className="chat-home-carousel"
      aria-label={t("title")}
      aria-roledescription={t("carousel")}
    >
      <div className="chat-home-carousel-controls">
        <div ref={markers} className="chat-home-carousel-markers">
          {labels.map((label, index) => {
            const Icon = index === 0 ? Inbox : Sparkles;
            return (
              <button
                key={label}
                type="button"
                aria-current={current === index ? "true" : undefined}
                onClick={() => go(index)}
              >
                <Icon className="size-3.5 shrink-0" aria-hidden />
                <span className="truncate">{label}</span>
              </button>
            );
          })}
        </div>
        <div className="flex shrink-0 gap-1">
          <button
            ref={previous}
            type="button"
            aria-label={t("previous")}
            disabled={current === 0}
            onClick={() => go(0)}
          >
            <ChevronLeft className="size-4" aria-hidden />
          </button>
          <button
            ref={next}
            type="button"
            aria-label={t("next")}
            disabled={current === 1}
            onClick={() => go(1)}
          >
            <ChevronRight className="size-4" aria-hidden />
          </button>
        </div>
      </div>
      <div
        ref={track}
        className="chat-home-carousel-track"
        // eslint-disable-next-line jsx-a11y/no-noninteractive-tabindex -- Native scroll tracks need focus for arrow-key scrolling.
        tabIndex={0}
        role="group"
        aria-label={t("pages")}
      >
        <div
          role="group"
          aria-roledescription={t("slide")}
          aria-label={t("page", { name: labels[0], current: 1, total: 2 })}
        >
          <ChatHomeInbox />
        </div>
        <div
          role="group"
          aria-roledescription={t("slide")}
          aria-label={t("page", { name: labels[1], current: 2, total: 2 })}
        >
          <div ref={suggestionsRef} className="chat-home-starters" />
        </div>
      </div>
      <p role="status" aria-live="polite" className="sr-only">
        {announcement}
      </p>
    </section>
  );
}

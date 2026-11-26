"use client";

import { createContext, useContext, useState, type ReactNode } from "react";
import { createPortal } from "react-dom";
import { ArrowLeft } from "lucide-react";
import { useTranslations } from "next-intl";
import { Button } from "@/components/ui";
import styles from "./administration.module.css";

type Slots = { back: HTMLDivElement | null; forward: HTMLDivElement | null };
const NavigationSlots = createContext<Slots | undefined>(undefined);

export function StartNavigation({
  children,
  onBack,
}: {
  children: ReactNode;
  onBack?: () => void;
}) {
  const [back, setBack] = useState<HTMLDivElement | null>(null);
  const [forward, setForward] = useState<HTMLDivElement | null>(null);
  return (
    <NavigationSlots.Provider value={{ back, forward }}>
      {children}
      <footer className={styles.wizardNavigation} data-start-navigation>
        <div ref={setBack} data-start-back>
          {onBack && <StartBack onClick={onBack} />}
        </div>
        <div ref={setForward} className={styles.wizardForward} data-start-forward />
      </footer>
    </NavigationSlots.Provider>
  );
}

export function StartNavigationScope({
  active,
  children,
}: {
  active: boolean;
  children: ReactNode;
}) {
  const slots = useContext(NavigationSlots);
  return (
    <NavigationSlots.Provider value={active ? slots : undefined}>
      {children}
    </NavigationSlots.Provider>
  );
}

export function StartActions({ back, children }: { back?: ReactNode; children?: ReactNode }) {
  const slots = useContext(NavigationSlots);
  if (!slots)
    return (
      <>
        {back}
        {children}
      </>
    );
  return (
    <>
      {back && slots.back && createPortal(back, slots.back)}
      {children && slots.forward && createPortal(children, slots.forward)}
    </>
  );
}

export function StartBack({ onClick, disabled }: { onClick: () => void; disabled?: boolean }) {
  const t = useTranslations("start.guided");
  return (
    <Button variant="ghost" type="button" disabled={disabled} onClick={onClick}>
      <ArrowLeft size={15} aria-hidden />
      {t("back")}
    </Button>
  );
}

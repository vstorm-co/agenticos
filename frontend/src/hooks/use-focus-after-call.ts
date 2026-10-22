"use client";

import { useEffect, useRef } from "react";

/**
 * Put focus somewhere when a voice call ends (#54). The call bar takes focus
 * when a call starts and takes it away when it goes, so `place` runs once, on
 * the render after `onCall` turns false, with `lost`: whether focus went with
 * the bar (it is on nothing) rather than where the person has since put it.
 * The `place` of the latest render is the one called.
 */
export function useFocusAfterCall(onCall: boolean, place: (lost: boolean) => void): void {
  const placeRef = useRef(place);
  useEffect(() => {
    placeRef.current = place;
  });
  const wasOnCall = useRef(false);
  useEffect(() => {
    if (wasOnCall.current && !onCall) {
      const focused = document.activeElement;
      // A pill fading out still holds focus for its exit: that focus is lost too.
      placeRef.current(
        focused === null ||
          focused === document.body ||
          focused.closest("[data-floating-pill]") !== null,
      );
    }
    wasOnCall.current = onCall;
  }, [onCall]);
}

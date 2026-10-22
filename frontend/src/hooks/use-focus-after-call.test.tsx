import { renderHook } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { useFocusAfterCall } from "./use-focus-after-call";

afterEach(() => {
  document.body.innerHTML = "";
});

describe("useFocusAfterCall", () => {
  it("places focus once, when a call ends, and says whether the bar took focus with it", () => {
    const place = vi.fn();
    const view = renderHook(({ onCall }) => useFocusAfterCall(onCall, place), {
      initialProps: { onCall: false },
    });
    // Mounting and starting a call are not an end.
    view.rerender({ onCall: true });
    expect(place).not.toHaveBeenCalled();

    view.rerender({ onCall: false });
    expect(place).toHaveBeenCalledExactlyOnceWith(true);

    // Nor is a render while no call is on.
    view.rerender({ onCall: false });
    expect(place).toHaveBeenCalledOnce();
  });

  it("tells the caller focus was not lost when the person put it somewhere else", () => {
    const elsewhere = document.createElement("button");
    document.body.append(elsewhere);
    const place = vi.fn();
    const view = renderHook(({ onCall }) => useFocusAfterCall(onCall, place), {
      initialProps: { onCall: true },
    });
    elsewhere.focus();

    view.rerender({ onCall: false });

    expect(place).toHaveBeenCalledExactlyOnceWith(false);
  });

  it("calls the latest placement, not the one the call started with", () => {
    const first = vi.fn();
    const latest = vi.fn();
    const view = renderHook(({ onCall, place }) => useFocusAfterCall(onCall, place), {
      initialProps: { onCall: true, place: first },
    });

    view.rerender({ onCall: false, place: latest });

    expect(first).not.toHaveBeenCalled();
    expect(latest).toHaveBeenCalledOnce();
  });

  it("counts focus still in a pill that is fading out as lost", () => {
    const pill = document.createElement("div");
    pill.setAttribute("data-floating-pill", "");
    const end = document.createElement("button");
    pill.append(end);
    document.body.append(pill);
    const place = vi.fn();
    const view = renderHook(({ onCall }) => useFocusAfterCall(onCall, place), {
      initialProps: { onCall: true },
    });
    end.focus();

    view.rerender({ onCall: false });

    expect(place).toHaveBeenCalledExactlyOnceWith(true);
  });
});

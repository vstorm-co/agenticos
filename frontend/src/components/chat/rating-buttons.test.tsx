import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { RatingButtons } from "./rating-buttons";
import { RatingValue, type UserRating } from "@/types";

vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

let fetchMock: ReturnType<typeof vi.fn>;

function respond(response: Partial<Response> = {}) {
  fetchMock = vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: () => Promise.resolve({}),
    ...response,
  });
  vi.stubGlobal("fetch", fetchMock);
  return fetchMock;
}

function mount({
  currentRating = null as UserRating,
  ratingCount,
  conversationId = "c-1",
  isAssistant = true,
}: {
  currentRating?: UserRating;
  ratingCount?: { likes: number; dislikes: number };
  conversationId?: string;
  isAssistant?: boolean;
} = {}) {
  const onRatingChange = vi.fn();
  const { unmount } = render(
    <RatingButtons
      messageId="m-1"
      conversationId={conversationId}
      currentRating={currentRating}
      ratingCount={ratingCount}
      onRatingChange={onRatingChange}
      isAssistant={isAssistant}
    />,
  );
  return Object.assign(onRatingChange, { unmount });
}

const up = () => screen.getByTitle("helpful");
const down = () => screen.getByTitle("notHelpful");

beforeEach(() => {
  vi.clearAllMocks();
  respond();
});

afterEach(() => vi.unstubAllGlobals());

/**
 * Rating an answer.
 *
 * Three rules, and each one is about not lying to the person who clicked.
 *
 * A thumbs-down opens the comment box; a thumbs-up does not. The asymmetry is
 * deliberate - "that was wrong" is worth a sentence, and asking for one after
 * every good answer would train people to ignore the dialog.
 *
 * Clicking the rating already given removes it. Sending the same rating twice
 * would be a no-op the server has to deduplicate, and there would be no way to
 * take back a mis-click.
 *
 * The counts are computed locally rather than refetched, so the number moves as
 * soon as the click lands - which means the arithmetic has to hold for every
 * transition, including a switch from up to down where two counts change at once.
 */
describe("rating an answer", () => {
  it("shows nothing at all on a person's own message", () => {
    // There is nothing to rate about what somebody typed themselves.
    const { container } = render(
      <RatingButtons
        messageId="m-1"
        conversationId="c-1"
        currentRating={null}
        isAssistant={false}
      />,
    );

    expect(container).toBeEmptyDOMElement();
  });

  it("sends a thumbs-up without asking for a comment", async () => {
    const onRatingChange = mount();

    await userEvent.click(up());

    expect(fetchMock).toHaveBeenCalledWith("/api/conversations/c-1/messages/m-1/rate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      credentials: "include",
      body: JSON.stringify({ rating: RatingValue.LIKE, comment: null }),
    });
    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: RatingValue.LIKE,
        rating_count: { likes: 1, dislikes: 0 },
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("thankYouFeedback");
  });

  it("asks what went wrong on a thumbs-down, before sending anything", async () => {
    mount();

    await userEvent.click(down());

    expect(screen.getByText("whatWentWrong")).toBeInTheDocument();
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("sends the comment somebody wrote", async () => {
    const onRatingChange = mount();
    await userEvent.click(down());

    await userEvent.type(screen.getByRole("textbox"), "It cited the wrong document.");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));

    expect(fetchMock.mock.calls[0]![1].body).toBe(
      JSON.stringify({
        rating: RatingValue.DISLIKE,
        comment: "It cited the wrong document.",
      }),
    );
    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: RatingValue.DISLIKE,
        rating_count: { likes: 0, dislikes: 1 },
      }),
    );
  });

  it("sends a whitespace-only comment as no comment", async () => {
    // Otherwise the ratings screen shows a row with an empty comment on it.
    mount();
    await userEvent.click(down());

    await userEvent.type(screen.getByRole("textbox"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));

    expect(fetchMock.mock.calls[0]![1].body).toBe(
      JSON.stringify({ rating: RatingValue.DISLIKE, comment: null }),
    );
  });

  it("records the rating when the comment is skipped", async () => {
    // The rating is the signal; the sentence is a bonus.
    mount();
    await userEvent.click(down());

    await userEvent.click(screen.getByRole("button", { name: "skipComment" }));

    expect(fetchMock.mock.calls[0]![1].body).toBe(
      JSON.stringify({ rating: RatingValue.DISLIKE, comment: null }),
    );
  });

  it("sends nothing when the dialog is dismissed", async () => {
    mount();
    await userEvent.click(down());
    await userEvent.type(screen.getByRole("textbox"), "typed something");

    await userEvent.click(screen.getByRole("button", { name: "cancel" }));

    expect(fetchMock).not.toHaveBeenCalled();
    await waitFor(() => expect(screen.queryByText("whatWentWrong")).toBeNull());
  });

  it("forgets an abandoned comment rather than reopening with it", async () => {
    mount();
    await userEvent.click(down());
    await userEvent.type(screen.getByRole("textbox"), "abandoned");
    await userEvent.click(screen.getByRole("button", { name: "cancel" }));

    await userEvent.click(down());

    expect(screen.getByRole("textbox")).toHaveValue("");
  });

  it("caps the comment, and says how much room is left", async () => {
    mount();
    await userEvent.click(down());

    expect(screen.getByRole("textbox")).toHaveAttribute("maxLength", "2000");
    expect(screen.getByText("0 / 2000")).toBeInTheDocument();
    await userEvent.type(screen.getByRole("textbox"), "four");
    expect(screen.getByText("4 / 2000")).toBeInTheDocument();
  });

  it("removes the rating when the same one is clicked again", async () => {
    // A mis-click has to be retractable, and re-sending the same rating would be
    // a no-op the server has to deduplicate.
    const onRatingChange = mount({
      currentRating: RatingValue.LIKE,
      ratingCount: { likes: 3, dislikes: 1 },
    });

    await userEvent.click(up());

    expect(fetchMock).toHaveBeenCalledWith("/api/conversations/c-1/messages/m-1/rate", {
      method: "DELETE",
      credentials: "include",
    });
    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: null,
        rating_count: { likes: 2, dislikes: 1 },
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("ratingRemoved");
  });

  it("moves both counts when a rating is switched", async () => {
    // The arithmetic nobody notices until the numbers drift: the old rating comes
    // off as the new one goes on.
    const onRatingChange = mount({
      currentRating: RatingValue.LIKE,
      ratingCount: { likes: 3, dislikes: 1 },
    });

    await userEvent.click(down());
    await userEvent.click(screen.getByRole("button", { name: "skipComment" }));

    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: RatingValue.DISLIKE,
        rating_count: { likes: 2, dislikes: 2 },
      }),
    );
  });

  it("moves both counts the other way round too", async () => {
    // The mirror of the case above, and a separate branch: switching off a
    // dislike decrements a different counter than switching off a like, and
    // only one of the two was ever exercised.
    const onRatingChange = mount({
      currentRating: RatingValue.DISLIKE,
      ratingCount: { likes: 3, dislikes: 2 },
    });

    await userEvent.click(up());

    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: RatingValue.LIKE,
        rating_count: { likes: 4, dislikes: 1 },
      }),
    );
  });

  it("never counts below zero, however out of step the tally was", async () => {
    // The count arrives from the server and the rating from the local store; they
    // can disagree after a reload, and a negative count on screen is worse than
    // one that is briefly stale.
    const onRatingChange = mount({
      currentRating: RatingValue.LIKE,
      ratingCount: { likes: 0, dislikes: 0 },
    });

    await userEvent.click(up());

    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: null,
        rating_count: { likes: 0, dislikes: 0 },
      }),
    );
  });

  it("shows each count only once there is one", () => {
    // A zero beside a thumb reads as a rating of zero rather than as no ratings.
    const first = mount({ ratingCount: { likes: 2, dislikes: 0 } });
    expect(screen.getByText("2")).toBeInTheDocument();
    expect(screen.queryByText("0")).toBeNull();
    first.unmount();

    mount({ ratingCount: { likes: 0, dislikes: 5 } });
    expect(screen.getByText("5")).toBeInTheDocument();
  });

  it("counts from zero when the server sent no tally at all", async () => {
    const onRatingChange = mount();

    await userEvent.click(up());

    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: RatingValue.LIKE,
        rating_count: { likes: 1, dislikes: 0 },
      }),
    );
  });

  it("marks the rating already given", () => {
    const first = mount({ currentRating: RatingValue.LIKE });
    expect(up()).toHaveClass("text-success");
    first.unmount();

    mount({ currentRating: RatingValue.DISLIKE });
    expect(down()).toHaveClass("text-destructive");
  });

  it("cannot rate a turn in a conversation the server has not saved yet", async () => {
    // The first turn of a new chat has no id until the socket answers, and the
    // rating endpoint is addressed by conversation. The disabled button is the
    // enforcement as well as the explanation - React fires no click on it.
    mount({ conversationId: "" });
    // Both thumbs say the same thing, because neither can be used yet.
    const [thumbUp, thumbDown] = screen.getAllByTitle("saveConversationToRate");

    expect(thumbUp).toBeDisabled();
    expect(thumbDown).toBeDisabled();
    await userEvent.click(thumbUp!);

    expect(fetchMock).not.toHaveBeenCalled();
  });

  it("says why a refused rating was refused", async () => {
    respond({
      ok: false,
      status: 403,
      json: () => Promise.resolve({ message: "This conversation is not yours" }),
    });
    const onRatingChange = mount();

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("This conversation is not yours"));
    expect(onRatingChange).not.toHaveBeenCalled();
  });

  it("falls back to its own sentence when the refusal carries none", async () => {
    respond({ ok: false, status: 500, json: () => Promise.resolve({}) });
    mount();

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("failedSubmitRating"));
  });

  it("still says something when the refusal is not JSON", async () => {
    respond({ ok: false, status: 502, json: () => Promise.reject(new Error("not json")) });
    mount();

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("unknownError"));
  });

  it("reports a failure to remove a rating, and keeps the rating", async () => {
    respond({ ok: false, status: 500, json: () => Promise.resolve({}) });
    const onRatingChange = mount({ currentRating: RatingValue.LIKE });

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("failedRemoveRating"));
    expect(onRatingChange).not.toHaveBeenCalled();
  });

  it("says what the server said about a refused removal", async () => {
    respond({
      ok: false,
      status: 409,
      json: () => Promise.resolve({ message: "Already removed" }),
    });
    mount({ currentRating: RatingValue.DISLIKE });

    await userEvent.click(down());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("Already removed"));
  });

  it("survives a removal whose refusal is not JSON", async () => {
    respond({ ok: false, status: 502, json: () => Promise.reject(new Error("not json")) });
    mount({ currentRating: RatingValue.LIKE });

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("unknownError"));
  });

  it("accepts no second click while the first is in flight", async () => {
    // Two ratings for one message is a tally that never settles.
    let release: (value: unknown) => void = () => {};
    fetchMock = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    mount();

    await userEvent.click(up());
    await waitFor(() => expect(up()).toBeDisabled());
    expect(down()).toBeDisabled();

    release({ ok: true, status: 200, json: () => Promise.resolve({}) });
    await waitFor(() => expect(up()).toBeEnabled());
    expect(fetchMock).toHaveBeenCalledTimes(1);
  });

  it("spins on the thumb that was pressed, not on both", async () => {
    // Which one is working is the whole point of a spinner.
    let release: (value: unknown) => void = () => {};
    fetchMock = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    mount({ currentRating: RatingValue.LIKE });

    await userEvent.click(up());

    await waitFor(() => expect(up().querySelector(".animate-spin")).not.toBeNull());
    expect(down().querySelector(".animate-spin")).toBeNull();

    release({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });

  it("spins one thumb on a message nobody has rated yet", async () => {
    // An unrated message has currentRating === null, the case a spinner keyed
    // on the rating cannot tell apart - and the normal one.
    let release: (value: unknown) => void = () => {};
    fetchMock = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    mount();

    await userEvent.click(up());

    await waitFor(() => expect(up().querySelector(".animate-spin")).not.toBeNull());
    expect(down().querySelector(".animate-spin")).toBeNull();

    release({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });

  it("spins one thumb when a rating is being removed", async () => {
    let release: (value: unknown) => void = () => {};
    fetchMock = vi.fn().mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    vi.stubGlobal("fetch", fetchMock);
    mount({ currentRating: RatingValue.DISLIKE });

    await userEvent.click(down());

    await waitFor(() => expect(down().querySelector(".animate-spin")).not.toBeNull());
    expect(up().querySelector(".animate-spin")).toBeNull();

    release({ ok: true, status: 200, json: () => Promise.resolve({}) });
  });
});

describe("a refusal the proxy minted", () => {
  it("resolves its code against the catalog rather than showing it humanized", async () => {
    // The proxy has no locale, so it refuses with a code and no sentence. Read
    // through a hand-built `new Error(body.message)` the code was thrown away
    // and the toast said "Backend unavailable" - the humanized code - under
    // every locale (#655). This file's translator answers with the key, which
    // is the proof either way: `errors.backendUnavailable` is a catalog lookup
    // and "Backend unavailable" is a string built from the code.
    respond({
      ok: false,
      status: 503,
      json: () => Promise.resolve({ code: "BACKEND_UNAVAILABLE" }),
    });
    mount();

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("backendUnavailable"));
    expect(toast.error).not.toHaveBeenCalledWith("Backend unavailable");
  });
});

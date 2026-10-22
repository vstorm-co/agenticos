import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { toast } from "sonner";

import { RatingButtons } from "./rating-buttons";
import { RatingValue, type UserRating } from "@/types";
import { ApiError } from "@/lib/api-error";
import { Perm } from "@/types/permissions";

vi.mock("next-intl", async () => ({
  useTranslations: (await import("@/test-utils/intl")).keyTranslations(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));
const push = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push }),
  useSearchParams: () => new URLSearchParams(),
}));

const rateMessage =
  vi.fn<(body: { rating: RatingValue; comment: string | null }) => Promise<unknown>>();
const removeRating = vi.fn<() => Promise<unknown>>();
vi.mock("@/hooks/use-message-rating", () => ({
  useMessageRating: () => ({ rateMessage, removeRating }),
}));

const datasets = vi.hoisted(() => ({
  granted: [] as string[],
  add: vi.fn(),
  list: [] as { id: string; name: string; can_edit: boolean }[],
}));
const EDITABLE = [
  { id: "d1", name: "refunds", can_edit: true },
  { id: "d2", name: "returns", can_edit: true },
];
vi.mock("@/hooks/use-permissions", () => ({
  usePermissions: () => ({ can: (perm: string) => datasets.granted.includes(perm) }),
}));
vi.mock("@/hooks/use-datasets", () => ({
  // The server's `editable` filter, as the listing applies it.
  useDatasets: (query: { editable?: boolean }) => {
    const rows = query.editable
      ? datasets.list.filter((dataset) => dataset.can_edit)
      : datasets.list;
    return {
      datasets: rows,
      total: rows.length,
      isLoading: false,
      create: { mutateAsync: vi.fn(), isPending: false },
    };
  },
  useAddToDataset: () => ({ mutateAsync: datasets.add, isPending: false }),
}));

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
  localStorage.clear();
  datasets.granted = [];
  datasets.add.mockResolvedValue({});
  rateMessage.mockResolvedValue({});
  removeRating.mockResolvedValue({});
});

afterEach(() => vi.unstubAllGlobals());

/**
 * Rating an answer.
 *
 * A thumbs-down opens the comment box; a thumbs-up does not - "that was wrong"
 * is worth a sentence, and asking after every good answer trains people to
 * ignore the dialog. Clicking the rating already given removes it. The counts
 * move locally as soon as the click lands, so the arithmetic has to hold for
 * every transition, including a switch where two counts change at once.
 */
describe("rating an answer", () => {
  it("shows nothing at all on a person's own message", () => {
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

    expect(rateMessage).toHaveBeenCalledWith({ rating: RatingValue.LIKE, comment: null });
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
    expect(rateMessage).not.toHaveBeenCalled();
  });

  it("sends the comment somebody wrote", async () => {
    const onRatingChange = mount();
    await userEvent.click(down());

    await userEvent.type(screen.getByRole("textbox"), "It cited the wrong document.");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));

    expect(rateMessage).toHaveBeenCalledWith({
      rating: RatingValue.DISLIKE,
      comment: "It cited the wrong document.",
    });
    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: RatingValue.DISLIKE,
        rating_count: { likes: 0, dislikes: 1 },
      }),
    );
  });

  it("sends a whitespace-only comment as no comment", async () => {
    mount();
    await userEvent.click(down());

    await userEvent.type(screen.getByRole("textbox"), "   ");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));

    expect(rateMessage).toHaveBeenCalledWith({ rating: RatingValue.DISLIKE, comment: null });
  });

  it("records the rating when the comment is skipped", async () => {
    mount();
    await userEvent.click(down());

    await userEvent.click(screen.getByRole("button", { name: "skipComment" }));

    expect(rateMessage).toHaveBeenCalledWith({ rating: RatingValue.DISLIKE, comment: null });
  });

  it("sends nothing when the dialog is dismissed", async () => {
    mount();
    await userEvent.click(down());
    await userEvent.type(screen.getByRole("textbox"), "typed something");

    await userEvent.click(screen.getByRole("button", { name: "cancel" }));

    expect(rateMessage).not.toHaveBeenCalled();
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
    const onRatingChange = mount({
      currentRating: RatingValue.LIKE,
      ratingCount: { likes: 3, dislikes: 1 },
    });

    await userEvent.click(up());

    expect(removeRating).toHaveBeenCalled();
    await waitFor(() =>
      expect(onRatingChange).toHaveBeenCalledWith({
        rating: null,
        rating_count: { likes: 2, dislikes: 1 },
      }),
    );
    expect(toast.success).toHaveBeenCalledWith("ratingRemoved");
  });

  it("moves both counts when a rating is switched", async () => {
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
    mount({ conversationId: "" });
    const [thumbUp, thumbDown] = screen.getAllByTitle("saveConversationToRate");

    expect(thumbUp).toBeDisabled();
    expect(thumbDown).toBeDisabled();
    await userEvent.click(thumbUp!);

    expect(rateMessage).not.toHaveBeenCalled();
  });

  it("reports a refused rating and leaves the counts alone", async () => {
    rateMessage.mockRejectedValueOnce(new Error("This conversation is not yours"));
    const onRatingChange = mount();

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onRatingChange).not.toHaveBeenCalled();
  });

  it("reports a failure to remove a rating, and keeps the rating", async () => {
    removeRating.mockRejectedValueOnce(new Error("nope"));
    const onRatingChange = mount({ currentRating: RatingValue.LIKE });

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(onRatingChange).not.toHaveBeenCalled();
  });

  it("accepts no second click while the first is in flight", async () => {
    let release: (value: unknown) => void = () => {};
    rateMessage.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    mount();

    await userEvent.click(up());
    await waitFor(() => expect(up()).toBeDisabled());
    expect(down()).toBeDisabled();

    release({});
    await waitFor(() => expect(up()).toBeEnabled());
    expect(rateMessage).toHaveBeenCalledTimes(1);
  });

  it("spins on the thumb that was pressed, not on both", async () => {
    let release: (value: unknown) => void = () => {};
    rateMessage.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    mount({ currentRating: RatingValue.LIKE });

    await userEvent.click(down());
    await userEvent.click(screen.getByRole("button", { name: "skipComment" }));

    await waitFor(() => expect(down().querySelector(".animate-spin")).not.toBeNull());
    expect(up().querySelector(".animate-spin")).toBeNull();

    release({});
  });

  it("spins one thumb when a rating is being removed", async () => {
    let release: (value: unknown) => void = () => {};
    removeRating.mockReturnValue(
      new Promise((resolve) => {
        release = resolve;
      }),
    );
    mount({ currentRating: RatingValue.DISLIKE });

    await userEvent.click(down());

    await waitFor(() => expect(down().querySelector(".animate-spin")).not.toBeNull());
    expect(up().querySelector(".animate-spin")).toBeNull();

    release({});
  });
});

describe("a refusal the proxy minted", () => {
  it("resolves its code against the catalog rather than showing it humanized", async () => {
    // The proxy sits outside `[locale]` and has no translator, so it refuses
    // with a code and no sentence. Read through `.message` the code was shown
    // humanized - "Backend unavailable" - under every locale, where the catalog
    // says something else and Polish says nothing at all (#655). This file's
    // translator answers with the key, which is the proof either way:
    // `backendUnavailable` is a catalog lookup, and "Backend unavailable" is a
    // string built from the code.
    rateMessage.mockRejectedValueOnce(
      new ApiError(503, "Backend unavailable", { code: "BACKEND_UNAVAILABLE" }),
    );
    mount();

    await userEvent.click(up());

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("backendUnavailable"));
    expect(toast.error).not.toHaveBeenCalledWith("Backend unavailable");
  });
});

/**
 * Adding the answer to a dataset from the rate-down dialog: a second, separate
 * write after the rating, offered only to somebody who edits a dataset.
 */
/** The action a toast offered, as sonner was handed it. */
function toastAction(call: number): { label: string; onClick: () => void } {
  const options = vi.mocked(toast.success).mock.calls[call]?.[1];
  return (options as unknown as { action: { label: string; onClick: () => void } }).action;
}

describe("adding a rated-down answer to a dataset", () => {
  const alsoAdd = () => screen.getByRole("checkbox", { name: "alsoAddToDataset" });

  beforeEach(() => {
    datasets.granted = [Perm.datasetsEdit];
    datasets.list = EDITABLE;
  });

  it("is offered to a member whose role edits no dataset but a grant edits one", async () => {
    datasets.granted = [Perm.datasetsView];
    mount();
    await userEvent.click(down());
    expect(alsoAdd()).toBeInTheDocument();
  });

  it("is not offered to somebody who edits no dataset", async () => {
    datasets.granted = [Perm.datasetsView];
    datasets.list = [{ id: "d3", name: "theirs", can_edit: false }];
    mount();
    await userEvent.click(down());
    expect(screen.queryByRole("checkbox", { name: "alsoAddToDataset" })).toBeNull();
  });

  it("adds nothing unless asked to", async () => {
    mount();
    await userEvent.click(down());
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    await waitFor(() => expect(rateMessage).toHaveBeenCalled());
    expect(datasets.add).not.toHaveBeenCalled();
  });

  it("rates first, then adds the answer as a counter-example to the dataset chosen", async () => {
    const order: string[] = [];
    rateMessage.mockImplementation(async () => order.push("rate"));
    datasets.add.mockImplementation(async () => order.push("add"));
    mount();
    await userEvent.click(down());
    expect(screen.getByText("alsoAddAsCounterExample")).toBeInTheDocument();
    await userEvent.click(alsoAdd());
    await userEvent.click(screen.getByRole("combobox", { name: "dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));
    await userEvent.type(screen.getByPlaceholderText("describeIssue"), "Wrong window");
    await userEvent.click(screen.getByRole("button", { name: "submit" }));

    await waitFor(() =>
      expect(datasets.add).toHaveBeenCalledWith({
        datasetId: "d2",
        messageId: "m-1",
        answerAs: "counter_example",
      }),
    );
    expect(order).toEqual(["rate", "add"]);
    expect(toast.success).toHaveBeenCalledWith("addedTo", {
      action: { label: "openDataset", onClick: expect.any(Function) },
    });
    act(() => toastAction(1).onClick());
    expect(push).toHaveBeenCalledWith("/datasets/d2?tab=cases");
    await waitFor(() => expect(screen.queryByText("whatWentWrong")).toBeNull());
  });

  it("keeps the rating when the add is refused, and says which half failed", async () => {
    datasets.add.mockRejectedValue(new Error("Dataset not found"));
    const onRatingChange = mount();
    await userEvent.click(down());
    await userEvent.click(alsoAdd());
    await userEvent.click(screen.getByRole("button", { name: "skipComment" }));

    await waitFor(() => expect(toast.error).toHaveBeenCalledWith("addAfterRatingFailed"));
    expect(onRatingChange).toHaveBeenCalledWith(
      expect.objectContaining({ rating: RatingValue.DISLIKE }),
    );
    expect(toast.success).toHaveBeenCalledWith("thankYouFeedback");
  });

  it("points at creating a dataset when there is none to add to, and adds nothing", async () => {
    const all = datasets.list;
    datasets.list = [{ id: "d3", name: "theirs", can_edit: false }];
    try {
      mount();
      await userEvent.click(down());
      await userEvent.click(alsoAdd());
      expect(screen.getByText("noDatasetToAddTo")).toBeInTheDocument();
      await userEvent.click(screen.getByRole("button", { name: "submit" }));
      await waitFor(() => expect(rateMessage).toHaveBeenCalled());
      expect(datasets.add).not.toHaveBeenCalled();
    } finally {
      datasets.list = all;
    }
  });

  it("offers a thumbs-up answer as a reference through the toast, without asking what to keep it as", async () => {
    mount();
    await userEvent.click(up());
    await waitFor(() => expect(toast.success).toHaveBeenCalled());
    expect(vi.mocked(toast.success).mock.calls[0]![0]).toBe("thankYouFeedback");
    const action = toastAction(0);
    expect(action.label).toBe("addToDataset");
    expect(vi.mocked(toast.success).mock.calls[0]![1]).toEqual(
      expect.objectContaining({ duration: 10_000 }),
    );
    expect(screen.queryByRole("dialog")).toBeNull();

    act(() => action.onClick());
    expect(screen.getByText("addAsReferenceBody")).toBeInTheDocument();
    expect(screen.queryByRole("combobox", { name: "keepAnswerAs" })).toBeNull();
    await userEvent.click(screen.getByRole("button", { name: "add" }));
    await waitFor(() =>
      expect(datasets.add).toHaveBeenCalledWith({
        datasetId: "d1",
        messageId: "m-1",
        answerAs: "reference_answer",
        withHistory: false,
      }),
    );
    await waitFor(() => expect(screen.queryByText("addAsReferenceBody")).toBeNull());
  });

  it("starts the next add from the dataset added to last", async () => {
    mount();
    await userEvent.click(down());
    await userEvent.click(alsoAdd());
    await userEvent.click(screen.getByRole("combobox", { name: "dataset" }));
    await userEvent.click(screen.getByRole("option", { name: "returns" }));
    await userEvent.click(screen.getByRole("button", { name: "skipComment" }));
    await waitFor(() => expect(datasets.add).toHaveBeenCalledTimes(1));

    await userEvent.click(up());
    await waitFor(() => expect(toast.success).toHaveBeenCalledTimes(3));
    act(() => toastAction(2).onClick());
    await userEvent.click(screen.getByRole("button", { name: "add" }));
    await waitFor(() =>
      expect(datasets.add).toHaveBeenLastCalledWith(expect.objectContaining({ datasetId: "d2" })),
    );
  });

  it("offers no add on a thumbs-up to somebody who edits no dataset", async () => {
    datasets.granted = [];
    datasets.list = [];
    mount();
    await userEvent.click(up());
    await waitFor(() => expect(toast.success).toHaveBeenCalledWith("thankYouFeedback"));
    expect(vi.mocked(toast.success).mock.calls[0]).toHaveLength(1);
  });

  it("adds nothing when the rating itself is refused", async () => {
    rateMessage.mockRejectedValue(new Error("down"));
    mount();
    await userEvent.click(down());
    await userEvent.click(alsoAdd());
    await userEvent.click(screen.getByRole("button", { name: "submit" }));
    await waitFor(() => expect(toast.error).toHaveBeenCalled());
    expect(datasets.add).not.toHaveBeenCalled();
    expect(screen.getByText("whatWentWrong")).toBeInTheDocument();
  });
});

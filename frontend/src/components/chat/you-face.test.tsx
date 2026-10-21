import { render } from "@testing-library/react";
import { beforeEach, describe, expect, it } from "vitest";

import { YouFace } from "./you-face";
import { useAuthStore } from "@/stores";
import type { User } from "@/types";

const reader = { id: "u-1", email: "ada@example.com", avatar_url: "u-1/a.png" } as User;

beforeEach(() => useAuthStore.setState({ user: null, avatarVersion: 0 }));

describe("the reader's face in a transcript", () => {
  it("draws the generated face until a picture has loaded, so a missing file is never a hole", () => {
    // jsdom never loads an image: what it renders is what a 404 renders.
    useAuthStore.setState({ user: reader });

    const { container } = render(<YouFace />);

    expect(container.querySelector("g.mo-root")).not.toBeNull();
    expect(container.querySelector("img")).toBeNull();
  });

  it("is a plain glyph for a reader who is not signed in", () => {
    const { container } = render(<YouFace />);

    expect(container.querySelector("svg.lucide-user")).not.toBeNull();
  });
});

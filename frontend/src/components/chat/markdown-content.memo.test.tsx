import { render, screen } from "@testing-library/react";
import type { ComponentProps } from "react";
import { expect, it, vi } from "vitest";
import type ReactMarkdown from "react-markdown";
import { MarkdownContent } from "./markdown-content.impl";

const parse = vi.hoisted(() => vi.fn());
vi.mock("react-markdown", async (load) => {
  const original = await load<typeof import("react-markdown")>();
  const Renderer = original.default;
  return {
    ...original,
    default: (props: ComponentProps<typeof ReactMarkdown>) => {
      parse(props);
      return <Renderer {...props} />;
    },
  };
});

it("does not reparse unchanged markdown and reuses plugin lists when another message streams", () => {
  const { rerender } = render(<MarkdownContent content="Saved answer" />);
  for (let n = 0; n < 20; n++) rerender(<MarkdownContent content="Saved answer" />);
  expect(parse).toHaveBeenCalledTimes(1);
  rerender(<MarkdownContent content="Updated answer" />);
  expect(screen.getByText("Updated answer")).toBeInTheDocument();
  expect(parse).toHaveBeenCalledTimes(2);
  expect(parse.mock.calls[0]![0].remarkPlugins).toBe(parse.mock.calls[1]![0].remarkPlugins);
  expect(parse.mock.calls[0]![0].rehypePlugins).toBe(parse.mock.calls[1]![0].rehypePlugins);
  rerender(<MarkdownContent content="Streaming answer" streaming />);
  rerender(<MarkdownContent content="Streaming answer grows" streaming />);
  expect(parse.mock.calls[2]![0].rehypePlugins).toBe(parse.mock.calls[3]![0].rehypePlugins);
});

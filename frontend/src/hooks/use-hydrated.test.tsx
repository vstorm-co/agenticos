import { render, screen } from "@testing-library/react";
import { renderToString } from "react-dom/server";
import { expect, it } from "vitest";

import { useHydrated } from "./use-hydrated";

function Probe() {
  return <p>{useHydrated() ? "client" : "server"}</p>;
}

it("is false while the server renders and true once the client has hydrated", () => {
  expect(renderToString(<Probe />)).toContain("server");
  render(<Probe />);
  expect(screen.getByText("client")).toBeInTheDocument();
});

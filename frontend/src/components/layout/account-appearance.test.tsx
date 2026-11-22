import { render } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { expect, it, vi } from "vitest";

import { AccountAppearance } from "./account-appearance";

const appearance = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-user-appearance", () => ({ useUserAppearance: appearance }));

it("renders nothing and adopts an acknowledged account appearance only for its owner", () => {
  appearance.mockReturnValue({ owner: null, epoch: undefined, preferences: undefined });
  const client = new QueryClient();
  const { container } = render(
    <QueryClientProvider client={client}>
      <AccountAppearance />
    </QueryClientProvider>,
  );
  expect(container).toBeEmptyDOMElement();
  expect(appearance).toHaveBeenCalled();
});

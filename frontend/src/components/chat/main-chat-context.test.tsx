import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { ChatScope } from "@/stores/chat-scope";
import { MainChatContext, useMainChat } from "./main-chat-context";

function Probe({ name }: { name: string }) {
  return <output aria-label={name}>{String(useMainChat())}</output>;
}

it("selects the main composer only inside the page and outside embedded chat scopes", () => {
  render(
    <>
      <Probe name="other page" />
      <MainChatContext.Provider value={true}>
        <Probe name="main chat" />
        <ChatScope agentId={null}>
          <Probe name="embedded chat" />
        </ChatScope>
      </MainChatContext.Provider>
    </>,
  );
  expect(screen.getByLabelText("other page")).toHaveTextContent("false");
  expect(screen.getByLabelText("main chat")).toHaveTextContent("true");
  expect(screen.getByLabelText("embedded chat")).toHaveTextContent("false");
});

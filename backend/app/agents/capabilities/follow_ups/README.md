# Follow-ups

One tool, `suggest_next_steps`: up to three short next steps, which the web chat,
the widget and the hosted page draw as buttons under the agent's answer. A click
sends the step as the person's next message.

## Why a tool and not a paragraph

An assistant that ends every answer with "Would you like me to..." is the habit
people complain about most, and a newcomer reads straight past it. Buttons cost
the person one click and leave the answer above them as the answer. They are
also the cheapest way to show someone a feature they did not know about - "Do
this every Monday" under a summary is how a routine gets discovered.

## What it deliberately does not do

- **Channels.** Slack, Telegram and Mattermost do not draw the buttons; the tool
  still answers there, and the agent's instructions do not depend on it.
- **Validation of intent.** A step is text the person may send; it grants
  nothing. What it asks for is checked the way any message is.
- **More than three.** A row of buttons is a choice; a column of them is a menu.

The starter agent (`general/agenticos`) binds it, so every new agent starts
with it; an FAQ bot's author switches it off in the Toolbox.

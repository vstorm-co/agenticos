# Web fetch

Exposes `web_fetch`, which reads one URL and returns it as Markdown. It is the
other half of `web_research`: search finds a page, this reads it. Before it
existed an agent cited pages it had only seen the snippet of (#51).

Scoped by `web:fetch` rather than sharing `web_research`'s `web:read`. Search
reaches one API this deployment picked; a fetch dereferences whatever URL the
model asks for, from inside the container, so the two are separate decisions and
an operator can allow searching without allowing that.

## What it deliberately does not do

**It does not fetch through code written here.** The request is Pydantic AI's
`web_fetch_tool`, over `pydantic_ai._ssrf.safe_download`. A URL chosen by a model
and dereferenced server-side is the SSRF case, and validating it up front the way
`app.core.sanitize.validate_webhook_url` does is not enough on its own: `httpx`
resolves the name again and follows redirects without asking, so a name that
answered publicly once can answer `169.254.169.254` a moment later, and a public
URL can redirect to one. `safe_download` pins the address it resolved into the
request and re-validates every hop. The reasoning, and what else it buys, is in
`_capability.py`.

**It does not offer `allow_local_urls`.** The library can be told to permit
private and loopback addresses. Nothing here exposes that, and a deployment that
wants an agent to read an internal wiki should put the wiki behind a hostname
that resolves publicly rather than turning the guard off for every URL a model
invents.

**The domain filters are not the security boundary.** `safe_download` is. They
are matched on the hostname only - exactly, with no wildcards - so they answer
"which sites may this agent read", not "can this agent reach our network".

**It does not summarise.** The page arrives as Markdown, truncated at
`max_content_chars`, and what to do with it is the model's problem. A summarising
fetch is two decisions in one tool, and the second one belongs to whoever wrote
the agent's instructions.

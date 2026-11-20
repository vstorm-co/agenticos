FROM node:24-bookworm-slim AS cli
ARG CLAUDE_CODE_VERSION=2.1.319
RUN npm install --global "@anthropic-ai/claude-code@${CLAUDE_CODE_VERSION}" \
    && claude --version
RUN node --input-type=module -e 'import fs from "node:fs/promises"; const response = await fetch(`https://raw.githubusercontent.com/nodejs/node/${process.version}/LICENSE`); if (!response.ok) throw new Error("Node licence download failed"); await fs.writeFile("/node-LICENSE", await response.text());'

FROM python:3.15-slim-bookworm
RUN apt-get update \
    && apt-get install --yes --no-install-recommends ca-certificates git iptables bsdutils \
    && rm -rf /var/lib/apt/lists/*
COPY --from=cli /usr/local/bin/node /usr/local/bin/node
COPY --from=cli /usr/local/lib/node_modules /usr/local/lib/node_modules
COPY --from=cli /node-LICENSE /licenses/node/LICENSE
RUN node -e 'const fs = require("node:fs"), path = require("node:path"), root = "/usr/local/lib/node_modules/@anthropic-ai/claude-code", manifest = require(root + "/package.json"); fs.symlinkSync(path.join(root, typeof manifest.bin === "string" ? manifest.bin : manifest.bin.claude), "/usr/local/bin/claude");' \
    && claude --version
WORKDIR /app
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY isolation.py schemas.py runtime.py server.py network_guard.py entrypoint.py ./
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
EXPOSE 8080
CMD ["python", "entrypoint.py"]

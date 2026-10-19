# The browser `browser_use` drives: a full Chromium, headful under a virtual
# display, so a site sees the browser a person runs rather than a headless shell.
#
# The headless shell this replaces announced itself - `HeadlessChrome` in its user
# agent, no window, no fonts - and sites that refuse bots refused it on sight
# (#2130). A real window under Xvfb, the fonts a desktop has and no automation
# flags remove what a page can read; `browser_use` covers the rest over CDP (its
# user agent, `navigator.webdriver`). Debian's Chromium rather than Google's
# Chrome because it is built for arm64 as well as amd64.
FROM debian:bookworm-slim

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        chromium \
        xvfb \
        socat \
        dumb-init \
        fonts-liberation \
        fonts-noto \
        fonts-noto-cjk \
        fonts-noto-color-emoji \
        ca-certificates \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && useradd --create-home --uid 1000 chrome

COPY entrypoint.sh /usr/local/bin/browser-entrypoint
RUN chmod 0755 /usr/local/bin/browser-entrypoint

USER chrome
WORKDIR /home/chrome

# What a site reads as where and in which language the browser is. An operator
# sets both for the deployment; `browser_use` can still override them per browse.
ENV TZ=UTC \
    BROWSER_LANG=en-US \
    SCREEN=1920x1080x24

EXPOSE 9222
ENTRYPOINT ["dumb-init", "--", "browser-entrypoint"]

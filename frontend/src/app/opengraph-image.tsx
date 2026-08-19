import { getTranslations } from "next-intl/server";
import { ImageResponse } from "next/og";

import { readBranding } from "@/lib/branding-server";
import { SITE } from "@/lib/seo";

export const alt = `${SITE.name} - ${SITE.tagline}`;

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Default Open Graph image - what a link to a deployment unfurls as. Black
 * background, oversized title with a lime highlight on a key word, plus the brand
 * mark and the tagline.
 *
 * No longer `force-static`: the name, tagline and description are the settings
 * row's, so a build-time render would freeze whatever they were when the image was
 * generated. `alt` stays on the built-in, because a route segment export is
 * evaluated at module load and has no request to read a row for.
 */
export default async function OpengraphImage() {
  const t = await getTranslations("pages.root");
  const { appName, tagline, description } = await readBranding();
  return new ImageResponse(
    <div
      style={{
        width: "100%",
        height: "100%",
        display: "flex",
        flexDirection: "column",
        justifyContent: "space-between",
        padding: "64px 80px",
        backgroundColor: "#0E0E0C",
        backgroundImage:
          "radial-gradient(ellipse 80% 60% at 80% 0%, rgba(197,249,74,0.18), transparent 60%)",
        color: "#F2F1EB",
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          <div
            style={{
              width: 14,
              height: 14,
              borderRadius: 9999,
              background: "#C5F94A",
            }}
          />
          <span style={{ fontSize: 26, fontWeight: 700, letterSpacing: "-0.01em" }}>{appName}</span>
        </div>
        <span
          style={{
            fontSize: 18,
            opacity: 0.6,
            fontFamily: "monospace",
            textTransform: "uppercase",
            letterSpacing: "0.1em",
          }}
        >
          {tagline}
        </span>
      </div>

      <div style={{ display: "flex", flexDirection: "column" }}>
        <div
          style={{
            fontSize: 110,
            fontWeight: 800,
            lineHeight: 1.0,
            letterSpacing: "-0.035em",
            display: "flex",
            flexWrap: "wrap",
          }}
        >
          {/* One message with two tags rather than a head and a tail: the lime
              underline falls on the last word, and which word that is changes with
              the language. The lead keeps its own span because Satori lays this out
              as a flex row - a bare string beside an element is not a box it can
              measure. */}
          {t.rich("ogHeadline", {
            lead: (chunks) => <span>{chunks}&#160;</span>,
            mark: (chunks) => (
              <span
                style={{
                  background:
                    "linear-gradient(transparent 50%, #C5F94A 50%, #C5F94A 90%, transparent 90%)",
                  paddingLeft: 8,
                  paddingRight: 8,
                }}
              >
                {chunks}
              </span>
            ),
          })}
        </div>
      </div>

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <span style={{ fontSize: 28, opacity: 0.7, maxWidth: 720, lineHeight: 1.4 }}>
          {description}
        </span>
        <div
          style={{
            fontSize: 22,
            fontWeight: 600,
            padding: "14px 28px",
            borderRadius: 9999,
            background: "#F2F1EB",
            color: "#0E0E0C",
            display: "flex",
            alignItems: "center",
            gap: 10,
          }}
        >
          {t("ogBadge")}
        </div>
      </div>
    </div>,
    { ...size },
  );
}

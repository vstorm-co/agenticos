import { getTranslations } from "next-intl/server";
import { ImageResponse } from "next/og";

import { LOGO_DATA_URI } from "@/lib/logo.generated";
import { readBranding } from "@/lib/branding-server";
import { SITE } from "@/lib/seo";

export const alt = `${SITE.name} - ${SITE.tagline}`;

export const size = { width: 1200, height: 630 };
export const contentType = "image/png";

/**
 * Default Open Graph image - what a link to a deployment unfurls as. The mark's
 * deep violet, an oversized title with its key word in the blob's own blue, the
 * mark beside it, and the tagline - the same card as the repository's
 * `docs/assets/social-preview.png`, so a link to the product and a link to a
 * deployment of it look like one thing.
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
        backgroundColor: "#100E18",
        backgroundImage:
          "radial-gradient(circle at 82% 50%, rgba(129,112,214,0.30), transparent 45%)",
        color: "#F4F2FB",
        fontFamily: "sans-serif",
      }}
    >
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div style={{ display: "flex", alignItems: "center", gap: 14 }}>
          {/* The same mark as the favicon and the sidebar, from the same data URI. */}
          <img src={LOGO_DATA_URI} alt="" width={44} height={44} />
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

      <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between" }}>
        <div
          style={{
            maxWidth: 760,
            fontSize: 110,
            fontWeight: 800,
            lineHeight: 1.0,
            letterSpacing: "-0.035em",
            display: "flex",
            flexWrap: "wrap",
          }}
        >
          {/* One message with two tags rather than a head and a tail: the blue
              falls on the last word, and which word that is changes with
              the language. The lead keeps its own span because Satori lays this out
              as a flex row - a bare string beside an element is not a box it can
              measure. */}
          {t.rich("ogHeadline", {
            lead: (chunks) => <span>{chunks}&#160;</span>,
            mark: (chunks) => <span style={{ color: "#BBD1FF" }}>{chunks}</span>,
          })}
        </div>
        {/* The mark, large: what the link is a link to, before anybody reads it. */}
        <img src={LOGO_DATA_URI} alt="" width={210} height={210} />
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
            background: "#BBD1FF",
            color: "#15121F",
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

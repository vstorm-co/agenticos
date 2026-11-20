"""Build the committed HTML/plain-text emails without application dependencies.

Run from any directory with Python 3.12+: python emails/build.py [--check].
The output keeps [[variable]] tokens for the backend's escaped renderer.
"""

import argparse
import html
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SANS = "Geist, Arial, Helvetica, sans-serif"
MONO = "'Geist Mono', 'Courier New', Courier, monospace"
INK = "#171717"
MUTED = "#666666"
LINE = "#e5e5e5"


@dataclass(frozen=True)
class Design:
    id: str
    family: str
    headline: str
    intro: str
    panel: str
    preview: str
    subject: str
    note: str = ""
    cta: str = ""
    url: str = ""


@dataclass(frozen=True)
class Section:
    markup: str
    text: str


def escape(value: str) -> str:
    return html.escape(value, quote=True)


def paragraph(value: str, style: str = "") -> str:
    return f'<p style="margin:0;font-family:{SANS};{style}">{escape(value)}</p>'


def rows(items: list[tuple[str, str, str]]) -> Section:
    rendered = []
    for label, value, color in items:
        rendered.append(
            '<tr><td class="detail-label" valign="top" width="42%" '
            f'style="padding:12px 12px 12px 0;border-bottom:1px solid {LINE};'
            f'font:400 13px/20px {SANS};color:{MUTED}">{escape(label)}</td>'
            '<td class="detail-value" valign="top" '
            f'style="padding:12px 0;border-bottom:1px solid {LINE};text-align:right;'
            f"font:400 15px/20px {SANS};color:{color};overflow-wrap:anywhere;"
            f'word-wrap:break-word">{escape(value)}</td></tr>'
        )
    return Section(
        '<table role="presentation" width="100%" cellpadding="0" cellspacing="0" '
        'border="0" style="table-layout:fixed;border-collapse:collapse">'
        + "".join(rendered)
        + "</table>",
        "\n".join(f"{label}: {value}" for label, value, _ in items),
    )


def metric(label: str, value: str) -> Section:
    return Section(
        f'<div style="border-top:1px solid {LINE};padding-top:20px">'
        + paragraph(label, f"font-size:12px;line-height:16px;color:{MUTED}")
        + paragraph(
            value,
            "margin-top:8px;font-size:40px;line-height:48px;font-weight:500;"
            f"font-variant-numeric:tabular-nums;color:{INK};overflow-wrap:anywhere",
        )
        + "</div>",
        f"{label}: {value}",
    )


def join_sections(*sections: Section) -> Section:
    return Section(
        "".join(section.markup for section in sections),
        "\n".join(section.text for section in sections),
    )


def panel(design: Design) -> Section:
    match design.panel:
        case "invitation":
            return Section(
                '<div style="background:#f7f7f7;border-radius:4px;padding:24px">'
                + paragraph("Workspace", f"font-size:12px;line-height:16px;color:{MUTED}")
                + paragraph(
                    "[[org_name]]",
                    f"margin-top:8px;font-size:28px;line-height:36px;font-weight:500;color:{INK}",
                )
                + paragraph(
                    "Invited by [[inviter_name]]", "margin-top:8px;font-size:14px;line-height:20px"
                )
                + "</div>",
                "Workspace: [[org_name]]\nInvited by [[inviter_name]]",
            )
        case "reset" | "expiry":
            return rows([("Link expires in", "[[expires_in]]", INK)])
        case "welcome":
            return rows(
                [
                    ("Knowledge", "Add the context your agents need", INK),
                    ("Agents", "Set a task and instructions", INK),
                    ("Results", "Review what the agent produces", INK),
                ]
            )
        case "new_email":
            return rows(
                [
                    ("Requested address", "[[new_email]]", INK),
                    ("Status", "Awaiting verification", "#894b00"),
                ]
            )
        case "admin":
            return rows(
                [("Administrator", "[[admin_email]]", INK), ("Session type", "Impersonation", INK)]
            )
        case "approval":
            agent = rows([("Agent", "[[agent_name]]", INK)])
            # asked_by already contains the complete attribution sentence from
            # NotificationService, and is empty on older queued notifications.
            return Section(
                '<div style="background:#f7f7f7;border-radius:4px;padding:12px 24px 24px">'
                + agent.markup
                + paragraph("[[asked_by]]", "font-size:13px;line-height:32px")
                + paragraph(
                    "Requested tools",
                    f"margin-top:20px;font-size:12px;line-height:16px;color:{MUTED}",
                )
                + f'<code class="tools" style="display:block;margin-top:8px;font:400 13px/24px {MONO};'
                f'color:{INK};white-space:pre-wrap;word-wrap:break-word;overflow-wrap:anywhere">[[tools]]</code></div>',
                "Agent: [[agent_name]]\n[[asked_by]]\nRequested tools:\n[[tools]]",
            )
        case "budget":
            return join_sections(
                metric("Spend at stop", "[[spent]]"),
                Section(
                    paragraph(
                        "[[reason]]",
                        "margin-top:16px;font-size:15px;line-height:24px;color:#894b00",
                    ),
                    "[[reason]]",
                ),
            )
        case "usage":
            return join_sections(
                metric("Total spend", "[[total]]"),
                rows([("Agent runs", "[[runs]]", INK), ("Agents", "[[agents]]", INK)]),
            )
        case "notification":
            return Section(
                '<div style="background:#f7f7f7;border-radius:4px;padding:24px;'
                f"font:400 20px/28px {SANS};color:{INK};white-space:pre-wrap;"
                'word-wrap:break-word;overflow-wrap:anywhere">[[summary]]</div>',
                "[[summary]]",
            )
        case "failure_learning":
            # The digest body is composed by the task: one line per new
            # pattern, already ordered. The panel only presents it.
            return Section(
                '<div style="background:#f7f7f7;border-radius:4px;padding:24px;'
                f"font:400 15px/24px {SANS};color:{INK};white-space:pre-wrap;"
                'word-wrap:break-word;overflow-wrap:anywhere">[[summary]]</div>',
                "[[summary]]",
            )
        case "workflow":
            return Section(
                f'<div style="border-top:1px solid {LINE};padding-top:24px;'
                f"font:400 16px/24px {SANS};color:{INK};white-space:pre-wrap;"
                'word-wrap:break-word;overflow-wrap:anywhere">[[body]]</div>',
                "[[body]]",
            )
        case "paid":
            return join_sections(
                metric("Amount paid", "[[amount]]"),
                rows([("Status", "Paid", "#166534"), ("Plan", "[[plan_name]]", INK)]),
            )
        case "failed":
            return join_sections(
                metric("Payment amount", "[[amount]]"),
                rows([("Status", "Unsuccessful", "#9f1239")]),
            )
        case "plan":
            return rows([("Previous plan", "[[old_plan]]", INK), ("New plan", "[[new_plan]]", INK)])
        case "canceled":
            return join_sections(
                metric("Access continues until", "[[access_until]]"),
                rows([("Plan", "[[plan_name]]", INK)]),
            )
        case "trial_ending":
            return metric("Time remaining", "[[days_left]] days")
        case "credits":
            return metric("Available balance", "[[balance]] credits")
        case "trial_expired" | "newsletter":
            return Section("", "")
        case _:
            raise ValueError(f"Unknown panel: {design.panel}")


def render(design: Design) -> tuple[str, str]:
    details = panel(design)
    action = fallback = ""
    if design.cta:
        url = f"[[{design.url}]]"
        action = f"""
        <table class="action" role="presentation" cellpadding="0" cellspacing="0" border="0" style="margin-top:32px">
          <tr><td align="center" bgcolor="#155dfc" style="border-radius:8px;mso-padding-alt:14px 24px">
            <a class="action-link" href="{url}" style="display:block;padding:14px 24px;border:0 solid #155dfc;border-radius:8px;font:500 15px/20px {SANS};color:#ffffff;text-decoration:none;text-align:center;mso-padding-alt:0">{escape(design.cta)}</a>
          </td></tr>
        </table>"""
        fallback = f"""
      <tr><td style="padding:20px 8px 24px;font:400 11px/16px {SANS};color:{MUTED};word-break:break-all;word-wrap:break-word;overflow-wrap:anywhere">
        If the button does not open, copy this link into your browser:<br>
        <a href="{url}" style="color:{MUTED};text-decoration:underline;word-break:break-all;word-wrap:break-word;overflow-wrap:anywhere">{url}</a>
      </td></tr>"""
    intro = paragraph(design.intro, "margin-bottom:24px") if design.intro else ""
    note = (
        paragraph(design.note, f"margin-top:24px;font-size:13px;line-height:20px;color:{MUTED}")
        if design.note
        else ""
    )
    markup = f"""<!DOCTYPE html>
<!-- Generated by emails/build.py; edit emails/content.json or the shared builder. -->
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="light">
  <meta name="supported-color-schemes" content="light">
  <title>{escape(design.subject)}</title>
  <!--[if !mso]><!-->
  <style>
    @font-face {{font-family:Geist;font-style:normal;font-weight:400;font-display:swap;src:url('[[email_font_base_url]]/Geist-Regular.woff2') format('woff2')}}
    @font-face {{font-family:Geist;font-style:normal;font-weight:500;font-display:swap;src:url('[[email_font_base_url]]/Geist-Medium.woff2') format('woff2')}}
    @font-face {{font-family:'Geist Mono';font-style:normal;font-weight:400;font-display:swap;src:url('[[email_font_base_url]]/GeistMono-Regular.woff2') format('woff2')}}
  </style>
  <!--<![endif]-->
  <style>
    body {{margin:0!important;padding:0!important;width:100%!important;-webkit-text-size-adjust:100%;-ms-text-size-adjust:100%}}
    table {{mso-table-lspace:0pt;mso-table-rspace:0pt}}
    @media only screen and (max-width:620px) {{
      .outer {{padding:12px!important}}
      .content {{padding:24px!important}}
      .headline {{font-size:28px!important;line-height:36px!important}}
      .action {{width:100%!important}}
      .action-link {{display:block!important}}
      .detail-label,.detail-value {{display:block!important;width:auto!important;text-align:left!important}}
      .detail-label {{padding:12px 0 4px!important;border-bottom:0!important}}
      .detail-value {{padding:0 0 12px!important}}
    }}
  </style>
  <!--[if mso]><style>body,table,td,p,a,h1,div,span{{font-family:Arial,Helvetica,sans-serif!important}}.tools{{font-family:'Courier New',Courier,monospace!important}}</style><![endif]-->
</head>
<body style="margin:0;padding:0;background:#f7f7f7;color:#525252;font:400 16px/24px {SANS}">
  <div style="display:none!important;visibility:hidden;mso-hide:all;max-height:0;max-width:0;opacity:0;overflow:hidden;font-size:1px;line-height:1px">{escape(design.preview)}</div>
  <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" bgcolor="#f7f7f7" style="table-layout:fixed">
    <tr><td class="outer" align="center" style="padding:24px">
      <!--[if mso]><table role="presentation" width="600" cellpadding="0" cellspacing="0" border="0"><tr><td><![endif]-->
      <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" align="center" style="width:100%;max-width:600px;table-layout:fixed">
      <tr><td class="content" bgcolor="#ffffff" style="border:1px solid {LINE};border-radius:16px;padding:32px;word-wrap:break-word;overflow-wrap:anywhere;font:400 16px/24px {SANS}">
        <table role="presentation" width="100%" cellpadding="0" cellspacing="0" border="0" style="table-layout:fixed;border-collapse:collapse">
          <tr>
            <td valign="top" width="60%" style="padding:0 12px 24px 0;border-bottom:1px solid {LINE};font:500 20px/24px {SANS};color:{INK};overflow-wrap:anywhere">[[app_name]]</td>
            <td valign="top" align="right" style="padding-bottom:24px;border-bottom:1px solid {LINE};font:400 12px/16px {SANS};color:{MUTED}">{escape(design.family)}</td>
          </tr>
        </table>
        <h1 class="headline" style="margin:24px 0 16px;font:500 32px/40px {SANS};color:{INK};overflow-wrap:anywhere">{escape(design.headline)}</h1>
        {intro}
        {details.markup}
        {action}
        {note}
      </td></tr>
      {fallback}
      </table>
      <!--[if mso]></td></tr></table><![endif]-->
    </td></tr>
  </table>
</body>
</html>
"""
    parts = [design.headline if design.panel != "workflow" else "", design.intro, details.text]
    if design.cta:
        parts.append(f"{design.cta}:\n[[{design.url}]]")
    parts.extend([design.note, "[[app_name]]" if design.panel != "workflow" else ""])
    text = f"Subject: {design.subject}\n\n" + "\n\n".join(part for part in parts if part) + "\n"
    return "\n".join(line.rstrip() for line in markup.splitlines()) + "\n", text


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check", action="store_true", help="Fail if compiled templates need rebuilding"
    )
    args = parser.parse_args()
    designs = [
        Design(**record)
        for record in json.loads((ROOT / "content.json").read_text(encoding="utf-8"))
    ]
    output = ROOT / "compiled"
    expected: dict[Path, str] = {}
    for design in designs:
        if not re.fullmatch(r"[a-z_]+", design.id) or bool(design.cta) != bool(design.url):
            raise ValueError(f"Invalid template id or action: {design.id}")
        for extension, content in zip(("html", "txt"), render(design), strict=True):
            path = output / f"{design.id}.{extension}"
            if path in expected:
                raise ValueError(f"Duplicate template: {design.id}")
            expected[path] = content
    if args.check:
        stale = [
            str(path.relative_to(ROOT))
            for path, content in expected.items()
            if not path.exists() or path.read_text(encoding="utf-8") != content
        ]
        stale.extend(
            str(path.relative_to(ROOT))
            for path in output.iterdir()
            if path.suffix in {".html", ".txt"} and path not in expected
        )
        if stale:
            sys.stderr.write(
                "Rebuild email templates with python emails/build.py: "
                + ", ".join(sorted(stale))
                + "\n"
            )
            return 1
        sys.stdout.write(f"All {len(designs)} HTML/plain-text template pairs are current.\n")
        return 0
    output.mkdir(parents=True, exist_ok=True)
    for path, content in expected.items():
        path.write_text(content, encoding="utf-8", newline="\n")
    sys.stdout.write(f"Built {len(designs)} HTML/plain-text template pairs.\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

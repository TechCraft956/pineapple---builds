"""Small, hand-rolled markdown/HTML rendering. Plumbing, not a product.

No templating engine, no external assets, no CDN -- the lab's dependency
list is deliberately short (see the repo's ground rules), and reports are
read by one person, not shipped to customers. This module gives every report
builder in :mod:`lab.reports` the same three primitives: a table, a section,
and a pass/fail verdict line, plus a way to turn the resulting markdown into
a self-contained HTML page.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Mapping, Sequence

import pandas as pd

__all__ = ["markdown_table", "section", "verdict_box", "to_html"]


def _fmt_cell(value: Any, fmt: str | None) -> str:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if isinstance(value, pd.Timestamp):
        return value.isoformat(sep=" ", timespec="seconds")
    if fmt is not None:
        try:
            return format(value, fmt)
        except (ValueError, TypeError):
            return str(value)
    if isinstance(value, bool):
        return "yes" if value else "no"
    if isinstance(value, float):
        return f"{value:,.2f}"
    if isinstance(value, int):
        return f"{value:,}"
    return str(value)


def markdown_table(
    df: pd.DataFrame,
    *,
    formats: Mapping[str, str] | None = None,
    index: bool = False,
    max_rows: int | None = None,
) -> str:
    """Render ``df`` as an aligned, pipe-delimited markdown table.

    ``formats`` maps column name to a Python format spec (e.g. ``{"pnl":
    ",.2f"}``); columns not listed get a sensible default (thousands-grouped
    floats/ints, ISO timestamps, ``yes``/``no`` for bools). Empty frames still
    render a header so a report never silently drops a section.
    """
    formats = formats or {}
    work = df.reset_index() if index else df
    if max_rows is not None and len(work) > max_rows:
        work = work.head(max_rows)
    columns = list(work.columns)
    if not columns:
        return "_(no columns)_"

    header = [str(c) for c in columns]
    body = [
        [_fmt_cell(row[c], formats.get(c)) for c in columns]
        for _, row in work.iterrows()
    ]

    widths = [len(h) for h in header]
    for r in body:
        for i, cell in enumerate(r):
            widths[i] = max(widths[i], len(cell))

    def _row(cells: Sequence[str]) -> str:
        return "| " + " | ".join(c.ljust(widths[i]) for i, c in enumerate(cells)) + " |"

    lines = [_row(header), "| " + " | ".join("-" * w for w in widths) + " |"]
    lines += [_row(r) for r in body]
    if not body:
        lines.append("| " + " | ".join("_(none)_".ljust(w) for w in widths) + " |")
    return "\n".join(lines)


def section(title: str, body: str, *, level: int = 2) -> str:
    """A markdown heading followed by ``body``, with the blank lines a renderer needs."""
    return f"{'#' * max(1, level)} {title}\n\n{body.strip()}\n"


def verdict_box(label: str, passed: bool, detail: str = "") -> str:
    """A one-line pass/fail callout, rendered as a markdown blockquote.

    Deliberately terse -- this is meant to be skimmed at the top of a report,
    not read as prose.
    """
    tag = "PASS" if passed else "FAIL"
    line = f"> **{tag}** -- {label}"
    if detail:
        line += f": {detail}"
    return line


# ---------------------------------------------------------------------------
# markdown -> self-contained HTML
# ---------------------------------------------------------------------------

_INLINE_BOLD = re.compile(r"\*\*(.+?)\*\*")
_INLINE_CODE = re.compile(r"`([^`]+)`")


def _inline(text: str) -> str:
    text = _html.escape(text)
    text = _INLINE_CODE.sub(r"<code>\1</code>", text)
    text = _INLINE_BOLD.sub(r"<strong>\1</strong>", text)
    return text


def _render_table_block(lines: list[str]) -> str:
    rows = [
        [c.strip() for c in ln.strip().strip("|").split("|")]
        for ln in lines
        if ln.strip()
    ]
    if len(rows) < 2:
        return ""
    header, _sep, *body = rows
    out = ["<table>", "<thead><tr>"]
    out += [f"<th>{_inline(c)}</th>" for c in header]
    out.append("</tr></thead><tbody>")
    for r in body:
        out.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
    out.append("</tbody></table>")
    return "".join(out)


def to_html(markdown_text: str, *, title: str = "Report") -> str:
    """Convert the markdown produced by this module into a self-contained page.

    Supports exactly what :mod:`lab.reports` builders emit: ``#``-headings,
    pipe tables, ``>`` blockquotes (including the verdict-box bold tag),
    ``-``/``*`` bullet lists, ``**bold**``/`` `code` ``, horizontal rules and
    plain paragraphs. No external stylesheet or script; theme follows the
    reader's OS preference.
    """
    lines = markdown_text.splitlines()
    html_parts: list[str] = []
    i, n = 0, len(lines)
    list_open = False

    def _close_list() -> None:
        nonlocal list_open
        if list_open:
            html_parts.append("</ul>")
            list_open = False

    while i < n:
        line = lines[i]
        stripped = line.strip()

        if not stripped:
            _close_list()
            i += 1
            continue

        heading = re.match(r"^(#{1,6})\s+(.*)$", stripped)
        if heading:
            _close_list()
            level = len(heading.group(1))
            html_parts.append(f"<h{level}>{_inline(heading.group(2))}</h{level}>")
            i += 1
            continue

        if stripped in ("---", "***", "___"):
            _close_list()
            html_parts.append("<hr>")
            i += 1
            continue

        if stripped.startswith("|"):
            _close_list()
            block = []
            while i < n and lines[i].strip().startswith("|"):
                block.append(lines[i])
                i += 1
            html_parts.append(_render_table_block(block))
            continue

        if stripped.startswith(">"):
            _close_list()
            quote_lines = []
            while i < n and lines[i].strip().startswith(">"):
                quote_lines.append(lines[i].strip().lstrip(">").strip())
                i += 1
            html_parts.append(f"<blockquote>{_inline(' '.join(quote_lines))}</blockquote>")
            continue

        if stripped.startswith(("- ", "* ")):
            if not list_open:
                html_parts.append("<ul>")
                list_open = True
            html_parts.append(f"<li>{_inline(stripped[2:])}</li>")
            i += 1
            continue

        _close_list()
        html_parts.append(f"<p>{_inline(stripped)}</p>")
        i += 1

    _close_list()
    body = "\n".join(html_parts)

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{_html.escape(title)}</title>
<style>
  :root {{ color-scheme: light dark; }}
  body {{
    font-family: ui-sans-serif, system-ui, -apple-system, "Segoe UI", Roboto, sans-serif;
    max-width: 62rem; margin: 2rem auto; padding: 0 1.25rem;
    line-height: 1.55; color: #1a1a1a; background: #fdfdfd;
  }}
  h1, h2, h3, h4 {{ line-height: 1.25; margin-top: 1.8em; }}
  h1 {{ border-bottom: 2px solid #ddd; padding-bottom: .3em; }}
  h2 {{ border-bottom: 1px solid #e2e2e2; padding-bottom: .25em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 1em 0; display: block; overflow-x: auto; }}
  th, td {{ border: 1px solid #d8d8d8; padding: .4em .7em; text-align: left; font-variant-numeric: tabular-nums; }}
  th {{ background: #f0f0f0; }}
  tr:nth-child(even) td {{ background: #f8f8f8; }}
  blockquote {{
    border-left: 4px solid #999; margin: 1em 0; padding: .4em 1em;
    background: #f4f4f4; border-radius: 0 4px 4px 0;
  }}
  code {{ background: #eee; padding: .1em .35em; border-radius: 3px; font-size: .92em; }}
  hr {{ border: none; border-top: 1px solid #ddd; margin: 2em 0; }}
  ul {{ padding-left: 1.4em; }}
  @media (prefers-color-scheme: dark) {{
    body {{ color: #e6e6e6; background: #14161a; }}
    h1 {{ border-color: #333; }}
    h2 {{ border-color: #2a2a2a; }}
    th, td {{ border-color: #333; }}
    th {{ background: #1f2126; }}
    tr:nth-child(even) td {{ background: #191b20; }}
    blockquote {{ background: #1c1f24; border-color: #666; }}
    code {{ background: #262a30; }}
    hr {{ border-top-color: #2a2a2a; }}
  }}
</style>
</head>
<body>
{body}
</body>
</html>
"""

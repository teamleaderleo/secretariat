"""Secret-free local reconciliation report rendering."""

from __future__ import annotations

import html
import json
import os
from pathlib import Path

from .reconcile import Group, ReconcileError, Report
from .reconciliation_plan import plan_block_reason, plan_template


_CLASS_ORDER = {"conflict": 0, "duplicate": 1, "single": 2}


def reconciliation_html(report: Report) -> str:
    counts = report.counts()
    groups = sorted(
        report.groups,
        key=lambda group: (_CLASS_ORDER.get(group.classification, 9), group.origin, group.username.casefold()),
    )
    rows = "\n".join(_group_row(group, group.origin in report.multi_account_origins) for group in groups)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Secretariat reconciliation report</title>
<style>
:root {{ color-scheme: light dark; font-family: ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }}
body {{ max-width: 1320px; margin: 0 auto; padding: 28px 20px 60px; line-height: 1.45; }}
h1 {{ margin-bottom: 4px; }}
.subtitle {{ opacity: .72; margin-top: 0; }}
.summary {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(140px, 1fr)); gap: 10px; margin: 24px 0; }}
.card {{ border: 1px solid color-mix(in srgb, currentColor 18%, transparent); border-radius: 12px; padding: 14px; }}
.card strong {{ display: block; font-size: 1.55rem; }}
.controls {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 18px 0; }}
button, input, select {{ font: inherit; padding: 8px 10px; border: 1px solid color-mix(in srgb, currentColor 24%, transparent); border-radius: 9px; background: transparent; color: inherit; }}
input[type="search"] {{ min-width: 260px; flex: 1; }}
input.alias {{ width: min(260px, 90vw); }}
select {{ max-width: 220px; }}
button[aria-pressed="true"] {{ font-weight: 700; outline: 2px solid currentColor; outline-offset: 1px; }}
button.primary {{ font-weight: 700; }}
table {{ width: 100%; border-collapse: collapse; font-size: .94rem; }}
th, td {{ text-align: left; vertical-align: top; padding: 11px 9px; border-bottom: 1px solid color-mix(in srgb, currentColor 14%, transparent); }}
th {{ position: sticky; top: 0; background: Canvas; z-index: 1; }}
.badge {{ display: inline-block; border: 1px solid currentColor; border-radius: 999px; padding: 2px 7px; font-size: .78rem; margin: 1px 3px 1px 0; }}
.classification {{ font-weight: 700; }}
.origin {{ word-break: break-word; }}
.muted {{ opacity: .68; }}
.callout {{ border-left: 4px solid currentColor; padding: 8px 12px; margin: 24px 0; background: color-mix(in srgb, currentColor 5%, transparent); }}
.plan-controls {{ display: grid; gap: 6px; min-width: 230px; }}
.plan-controls label {{ font-size: .78rem; opacity: .78; }}
.blocked {{ opacity: .7; }}
#plan-status {{ min-height: 1.4em; }}
@media (max-width: 900px) {{ th:nth-child(6), td:nth-child(6) {{ display: none; }} table {{ font-size: .86rem; }} }}
</style>
</head>
<body>
<h1>Secretariat reconciliation</h1>
<p class="subtitle">Secret-free comparison of {report.snapshot_count} snapshot(s), {report.observation_count} observed credential copy/copies.</p>
<section class="summary" aria-label="Summary">
  <div class="card"><strong>{counts['conflict']}</strong>conflicts</div>
  <div class="card"><strong>{counts['duplicate']}</strong>duplicates</div>
  <div class="card"><strong>{counts['single']}</strong>single copies</div>
  <div class="card"><strong>{counts['multi_account_origins']}</strong>multi-account sites</div>
</section>
<div class="callout"><strong>Review, then enroll:</strong> choose the rows you want in the Garden, edit each alias, and choose one home copy. Rows Secretariat cannot represent durably are visibly blocked instead of being coerced into a lossy Garden entry.</div>
<div class="controls">
  <button type="button" data-filter="all" aria-pressed="true">All</button>
  <button type="button" data-filter="conflict" aria-pressed="false">Conflicts</button>
  <button type="button" data-filter="duplicate" aria-pressed="false">Duplicates</button>
  <button type="button" data-filter="single" aria-pressed="false">Singles</button>
  <input id="search" type="search" placeholder="Filter site, username, source…" autocomplete="off">
  <button id="download-plan" class="primary" type="button">Download reviewed Garden plan</button>
</div>
<p id="plan-status" class="muted" role="status"></p>
<table>
<thead><tr><th>Enroll</th><th>Status</th><th>Site</th><th>Account</th><th>Decision</th><th>Copies / review</th></tr></thead>
<tbody id="groups">
{rows}
</tbody>
</table>
<p class="muted">This file and any downloaded plan contain private account metadata such as sites and usernames. They contain no password values, password-derived fingerprints, note contents, or OTP secrets.</p>
<script>
(() => {{
  const rows = [...document.querySelectorAll('#groups tr')];
  const buttons = [...document.querySelectorAll('[data-filter]')];
  const search = document.querySelector('#search');
  const status = document.querySelector('#plan-status');
  const download = document.querySelector('#download-plan');
  const aliasPattern = /^[A-Za-z0-9][A-Za-z0-9._-]{{0,95}}$/;
  let filter = 'all';

  const apply = () => {{
    const query = search.value.trim().toLocaleLowerCase();
    for (const row of rows) {{
      const classMatch = filter === 'all' || row.dataset.classification === filter;
      const textMatch = !query || row.textContent.toLocaleLowerCase().includes(query);
      row.hidden = !(classMatch && textMatch);
    }}
  }};

  const fail = (message) => {{ status.textContent = message; status.focus?.(); }};

  for (const button of buttons) button.addEventListener('click', () => {{
    filter = button.dataset.filter;
    for (const candidate of buttons) candidate.setAttribute('aria-pressed', String(candidate === button));
    apply();
  }});
  search.addEventListener('input', apply);

  download.addEventListener('click', () => {{
    const entries = [];
    const aliases = new Set();
    for (const row of rows) {{
      const include = row.querySelector('input.enroll');
      if (!include || !include.checked) continue;
      const alias = row.querySelector('input.alias').value.trim();
      const home = row.querySelector('select.home').value;
      if (!aliasPattern.test(alias)) {{
        fail(`Invalid Garden alias: ${{alias || '(empty)'}}`);
        return;
      }}
      if (aliases.has(alias)) {{
        fail(`Duplicate Garden alias: ${{alias}}`);
        return;
      }}
      if (!home) {{
        fail(`Choose a home copy for ${{alias}}.`);
        return;
      }}
      aliases.add(alias);
      const template = JSON.parse(row.dataset.plan);
      entries.push({{ ...template, alias, home }});
    }}
    if (entries.length === 0) {{
      fail('Select at least one reviewed row before downloading a plan.');
      return;
    }}
    const payload = JSON.stringify({{ schema_version: 1, entries }}, null, 2) + '\n';
    const url = URL.createObjectURL(new Blob([payload], {{ type: 'application/json' }}));
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = 'secretariat-garden-plan.json';
    anchor.click();
    setTimeout(() => URL.revokeObjectURL(url), 0);
    status.textContent = `Downloaded a reviewed plan with ${{entries.length}} entr${{entries.length === 1 ? 'y' : 'ies'}}.`;
  }});
}})();
</script>
</body>
</html>
"""


def write_reconciliation_html(report: Report, path: Path) -> None:
    target = path.expanduser()
    if target.exists() or target.is_symlink():
        raise ReconcileError("HTML report path already exists")
    parent = target.parent
    if not parent.exists() or not parent.is_dir():
        raise ReconcileError("HTML report parent directory is unavailable")
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except OSError as error:
        raise ReconcileError("HTML report could not be created") from error
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(reconciliation_html(report))
    except OSError as error:
        try:
            target.unlink()
        except OSError:
            pass
        raise ReconcileError("HTML report could not be written") from error


def _group_row(group: Group, multi_account: bool) -> str:
    source_badges = " ".join(
        f'<span class="badge">{html.escape(source)}{(" ×" + str(count)) if count > 1 else ""}</span>'
        for source, count in group.source_counts
    )
    extras = []
    if multi_account:
        extras.append('<span class="badge">multiple accounts</span>')
    if group.note_sources:
        extras.append('<span class="badge">notes in ' + html.escape(", ".join(group.note_sources)) + '</span>')
    if group.otp_sources:
        extras.append('<span class="badge">OTP in ' + html.escape(", ".join(group.otp_sources)) + '</span>')
    if group.ambiguous_sources:
        extras.append('<span class="badge">same-store conflict: ' + html.escape(", ".join(group.ambiguous_sources)) + '</span>')

    template = plan_template(group)
    encoded_plan = html.escape(
        json.dumps(
            {key: value for key, value in template.items() if key not in {"alias", "home"}},
            separators=(",", ":"),
        ),
        quote=True,
    )
    block_reason = plan_block_reason(group)
    blocked = block_reason is not None
    disabled = " disabled" if blocked else ""
    checked_home = template["home"]
    options = ['<option value="">Choose home…</option>']
    for copy in template["copies"]:
        selected = " selected" if copy["id"] == checked_home else ""
        options.append(
            f'<option value="{html.escape(copy["id"], quote=True)}"{selected}>{html.escape(copy["type"])}</option>'
        )

    review = block_reason or _review_text(group)
    searchable = " ".join((group.classification, group.origin, group.username, group.title, *group.sources))
    row_class = "blocked" if blocked else ""
    enrollment_title = block_reason or "Include this logical credential in the reviewed plan"
    return (
        f'<tr class="{row_class}" data-classification="{html.escape(group.classification)}" '
        f'data-search="{html.escape(searchable, quote=True)}" data-plan="{encoded_plan}">'
        f'<td><input class="enroll" type="checkbox" aria-label="Enroll {html.escape(group.title, quote=True)}" title="{html.escape(enrollment_title, quote=True)}"{disabled}></td>'
        f'<td class="classification">{html.escape(group.classification)}</td>'
        f'<td class="origin"><strong>{html.escape(group.title)}</strong><br><span class="muted">{html.escape(group.origin)}</span></td>'
        f'<td>{html.escape(group.username) or "<span class=\"muted\">empty username</span>"}</td>'
        '<td><div class="plan-controls">'
        f'<label>Garden alias<input class="alias" value="{html.escape(template["alias"], quote=True)}"{disabled}></label>'
        f'<label>Home copy<select class="home"{disabled}>{"".join(options)}</select></label>'
        '</div></td>'
        f'<td>{source_badges}<br>{" ".join(extras)}<br><span class="muted">{html.escape(review)}</span></td>'
        '</tr>'
    )


def _review_text(group: Group) -> str:
    if group.classification == "conflict":
        return "Choose the current credential's source as home before propagation."
    if group.classification == "duplicate":
        if group.note_sources or group.otp_sources:
            return "Password copies agree. Preserve the source carrying unique notes or OTP data during cleanup."
        return "Password copies agree. Choose a home and retire replicas you no longer want later."
    return "One observed source copy. Keep it, migrate it, or add replicas after enrollment."

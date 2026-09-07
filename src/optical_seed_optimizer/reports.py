from html import escape
from math import isfinite
from pathlib import Path
from typing import Optional

from .models import BackendResult, ProjectConfig


def _metric(value: Optional[float], digits: int, suffix: str = "") -> str:
    if value is None or not isfinite(float(value)):
        return "N/A"
    return ("%.*f" % (digits, value)) + suffix


def write_html_report(
    config: ProjectConfig, result: BackendResult, path: Path
) -> None:
    rows = []
    for snapshot in result.snapshots:
        requirement = "PASS" if snapshot.meets_requirements else "FAIL"
        decision = "ACCEPTED" if snapshot.accepted else "REJECTED"
        notes = "<br>".join(escape(note) for note in snapshot.notes) or "&mdash;"
        rows.append(
            "<tr>"
            "<td><strong>%s</strong></td>" % escape(snapshot.label)
            + "<td>%s</td>" % _metric(snapshot.merit_function, 4)
            + "<td>%s</td>" % _metric(snapshot.effective_focal_length_mm, 4, " mm")
            + "<td>%s</td>" % _metric(snapshot.efl_error_percent, 4, "%")
            + "<td>%s</td>" % _metric(snapshot.worst_rms_spot_um, 3, " &micro;m")
            + "<td>%s</td>" % _metric(snapshot.worst_mtf_at_target, 4)
            + '<td class="%s">%s</td>'
            % ("ok" if snapshot.meets_requirements else "bad", requirement)
            + '<td class="%s">%s</td>'
            % ("ok" if snapshot.accepted else "bad", decision)
            + "<td>%s</td>" % notes
            + "</tr>"
        )

    baseline = result.snapshots[0]
    final = result.snapshots[-1]
    merit_drop = 0.0
    if (
        isfinite(float(baseline.merit_function))
        and isfinite(float(final.merit_function))
        and baseline.merit_function
    ):
        merit_drop = 100.0 * (
            1.0 - final.merit_function / baseline.merit_function
        )
    evidence = (
        "ZOS-API physical calculation"
        if result.backend == "zosapi"
        else "Mock CI run - not physical evidence"
    )
    status_class = (
        "qualified" if result.status == "v0.1-qualified" else "rejected"
    )
    warnings = " ".join(result.warnings) or "No runtime warnings."
    checks = " ".join(
        "%s=%s" % (key, "PASS" if value else "FAIL")
        for key, value in result.qualification_checks.items()
    )
    unsupported = result.qualification_scope.get("unsupported_requirements", {})
    unsupported_text = (
        ", ".join(sorted(unsupported)) if unsupported else "None requested."
    )
    scope_name = str(result.qualification_scope.get("name", "unspecified"))
    html = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>{name} - OpticalSeedOptimizer</title>
<style>
:root{{--ink:#17231f;--muted:#66736d;--line:#dce5e0;--paper:#f6f9f7;--green:#17694e;--red:#a13b32}}
*{{box-sizing:border-box}}body{{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 Inter,system-ui,sans-serif}}
main{{max-width:1120px;margin:auto;padding:52px 24px 80px}}h1{{font-size:clamp(36px,6vw,64px);line-height:1;letter-spacing:-.045em;margin:8px 0 14px}}
p{{color:var(--muted)}}.badge{{display:inline-block;padding:6px 10px;border:1px solid var(--line);border-radius:999px;background:white}}
.status{{margin-left:8px;color:white;border:0}}.qualified{{background:var(--green)}}.rejected{{background:var(--red)}}
.grid{{display:grid;grid-template-columns:repeat(4,1fr);gap:1px;background:var(--line);border:1px solid var(--line);border-radius:18px;overflow:hidden;margin:28px 0}}
.grid div{{background:white;padding:20px}}.grid strong{{font-size:24px;display:block}}.grid span{{font-size:12px;color:var(--muted)}}
.table{{overflow:auto;background:white;border:1px solid var(--line);border-radius:18px}}table{{width:100%;border-collapse:collapse;min-width:920px}}th,td{{padding:15px;border-bottom:1px solid var(--line);text-align:left}}th{{font-size:11px;text-transform:uppercase;color:var(--muted)}}
.ok{{color:var(--green);font-weight:700}}.bad{{color:var(--red);font-weight:700}}.warning{{margin-top:20px;padding:16px;border-radius:14px;background:#fff6dc;border:1px solid #ead9a2}}code{{word-break:break-all}}@media(max-width:720px){{.grid{{grid-template-columns:1fr 1fr}}}}
</style></head><body><main>
<span class="badge">{evidence}</span><span class="badge status {status_class}">{status}</span>
<h1>{name}</h1><p>Seed-to-final staged optimization report. The source Seed was never overwritten.</p>
<div class="grid"><div><strong>{efl:.2f} mm</strong><span>target EFL</span></div><div><strong>F/{fno:.3f}</strong><span>target aperture</span></div><div><strong>{mtf}</strong><span>final worst MTF @ {frequency:g} lp/mm</span></div><div><strong>{drop:.1f}%</strong><span>merit reduction</span></div></div>
<div class="table"><table><thead><tr><th>Stage</th><th>Merit</th><th>Actual EFL</th><th>EFL error</th><th>Worst RMS spot</th><th>Worst MTF</th><th>Requirements</th><th>Stage decision</th><th>Notes</th></tr></thead><tbody>{rows}</tbody></table></div>
  <div class="warning"><strong>Qualification scope:</strong> {scope_name}. A V0.1 result is not a complete UV-lens qualification.<br><strong>Acceptance checks:</strong> {checks}<br><strong>Unsupported requested requirements:</strong> {unsupported}<br><strong>Evidence boundary:</strong> {warning}</div>
<p>Final artifact: <code>{artifact}</code></p>
</main></body></html>""".format(
        name=escape(config.name),
        evidence=escape(evidence),
        status_class=status_class,
        status=escape(result.status.upper()),
        efl=config.target.focal_length_mm,
        fno=config.target.f_number,
        mtf=_metric(final.worst_mtf_at_target, 4),
        frequency=config.analysis.mtf_frequency_lpmm,
        drop=merit_drop,
        rows="".join(rows),
        checks=escape(checks),
        scope_name=escape(scope_name),
        unsupported=escape(unsupported_text),
        warning=escape(warnings),
        artifact=escape(result.final_design_path),
    )
    path.write_text(html, encoding="utf-8")

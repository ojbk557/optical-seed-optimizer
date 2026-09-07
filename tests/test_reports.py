from pathlib import Path

from optical_seed_optimizer.config import load_config
from optical_seed_optimizer.models import BackendResult, MetricSnapshot
from optical_seed_optimizer.reports import write_html_report


def test_report_separates_requirements_from_stage_decision_and_shows_notes(
    tmp_path: Path,
):
    config = load_config("configs/large_aperture_60mm.yaml")
    rejected = MetricSnapshot(
        label="rejected_candidate",
        merit_function=1.0,
        worst_rms_spot_um=10.0,
        worst_mtf_at_target=0.5,
        effective_focal_length_mm=config.target.focal_length_mm,
        efl_error_percent=0.0,
        meets_requirements=True,
        accepted=False,
        notes=["Stage rejected; checkpoint restored <safely>."],
    )
    result = BackendResult(
        backend="zosapi",
        final_design_path="final.zos",
        snapshots=[rejected],
        artifacts={},
        status="rejected",
    )
    output = tmp_path / "report.html"

    write_html_report(config, result, output)
    html = output.read_text(encoding="utf-8")

    assert "<th>Requirements</th><th>Stage decision</th><th>Notes</th>" in html
    assert '<td class="ok">PASS</td>' in html
    assert '<td class="bad">REJECTED</td>' in html
    assert "checkpoint restored &lt;safely&gt;." in html

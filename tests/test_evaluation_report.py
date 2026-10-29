import shutil
from pathlib import Path

import pytest

from examples.build_evaluation_report import build_report


def test_report_rejects_missing_and_mixed_cohorts(tmp_path):
    submissions = Path(__file__).parents[1] / "leaderboard/submissions"
    with pytest.raises(ValueError, match="No submissions"):
        build_report(submissions, "not-a-submission", tmp_path)
    with pytest.raises(ValueError, match="one matching experimental cohort"):
        build_report(submissions, "", tmp_path)


@pytest.mark.skipif(not shutil.which("rsvg-convert"), reason="native PNG renderer not installed")
def test_report_builds_svg_png_and_evidence_table(tmp_path):
    submissions = Path(__file__).parents[1] / "leaderboard/submissions"
    build_report(submissions, "serial-s42", tmp_path)
    assert len(list(tmp_path.glob("*.svg"))) == len(list(tmp_path.glob("*.png"))) == 6
    assert all(p.read_bytes().startswith(b"\x89PNG\r\n\x1a\n") for p in tmp_path.glob("*.png"))
    text = (tmp_path / "README.md").read_text()
    assert "Clef-Flash" in text and "Completed / applied" in text
    assert "[submission]" in text

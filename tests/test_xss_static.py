"""Fix 6: the scheme name in scan.html must no longer be injected as raw HTML.

A static guard against regression — the render must go through textContent, not
innerHTML interpolation of out.scheme.name."""
import pathlib

SCAN_HTML = pathlib.Path(__file__).resolve().parent.parent / "app" / "web" / "scan.html"


def test_scheme_name_not_injected_as_html():
    src = SCAN_HTML.read_text()
    # The vulnerable pattern (innerHTML with an interpolated scheme name) is gone.
    assert "${out.scheme.name}" not in src
    # And the safe path is present.
    assert "tag.textContent = out.scheme.name" in src

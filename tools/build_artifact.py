"""Bundle web/ into one self-contained HTML body for publishing as a claude.ai Artifact.

The artifact host wraps the page in its own <!doctype>/<html>/<head>/<body> skeleton, so
the wrapper tags are stripped and the two scripts are inlined.

    python tools/build_artifact.py        ->  dist/hss_heat_treatment.html
"""

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def main():
    html = (ROOT / "web" / "index.html").read_text()
    for pattern in (r"<!doctype html>\s*", r"<html[^>]*>\s*", r"</html>\s*", r"<head>\s*", r"</head>\s*",
                    r"<body>\s*", r"</body>\s*", r'<meta charset="utf-8">\s*', r'<meta name="viewport"[^>]*>\s*'):
        html = re.sub(pattern, "", html, flags=re.IGNORECASE)
    for name in ("quench_data.js", "app.js"):
        code = (ROOT / "web" / name).read_text()
        assert "</script" not in code.lower(), name
        html = html.replace(f'<script src="{name}"></script>', f"<script>\n{code}\n</script>")
    out = ROOT / "dist" / "hss_heat_treatment.html"
    out.parent.mkdir(exist_ok=True)
    out.write_text(html)
    print(f"wrote {out} ({out.stat().st_size / 1e6:.2f} MB)")


if __name__ == "__main__":
    main()

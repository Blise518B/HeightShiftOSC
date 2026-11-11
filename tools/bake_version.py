"""Write _version_baked.py for a frozen build, so the exe / AppImage knows
its version without git.

    python tools/bake_version.py v2.0.27     # a release: the version IS the tag
    python tools/bake_version.py             # a local build: version.py (git)

The release workflow (.github/workflows/release.yml) passes the release's
tag, so the build reports exactly the version the updater compares against
the next tag. BUILD (the "b<n>" in the title) is the commit count of the
checkout, as version.py counts it. build.bat bakes its own the same way.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, text=True,
                             timeout=10)
        return out.stdout.strip() if out.returncode == 0 else ""
    except Exception:
        return ""


def main() -> None:
    tag = sys.argv[1].strip() if len(sys.argv) > 1 else ""
    if tag:
        version = tag[1:] if tag[:1] in "vV" else tag
    else:
        sys.path.insert(0, str(ROOT))
        from version import __version__ as version    # noqa: E402
    short_hash = _git("rev-parse", "--short", "HEAD")
    count = _git("rev-list", "--count", "HEAD")
    build = int(count) if count.isdigit() else 0
    (ROOT / "_version_baked.py").write_text(
        f"VERSION = {version!r}\nSHORT_HASH = {short_hash!r}\nBUILD = {build!r}\n",
        encoding="utf-8")
    print(f"Version {version} (b{build}, {short_hash or 'no git'})")


if __name__ == "__main__":
    main()

"""Repository checks: no secrets in tracked files, and every local link in the docs points to a real file."""

import re
import subprocess

import pytest
from conftest import ROOT

DOCS = ["README.md", "matcher/README.md", "showcase/index.html", "showcase/template.html", "index.html"]
KEY_PATTERNS = re.compile(r"AIza[0-9A-Za-z_-]{30,}|sk-ant-[0-9A-Za-z_-]{20,}")
LINK = re.compile(r"\]\(([^)\s]+)\)|(?:src|href)=\"([^\"]+)\"|\"src\": \"([^\"]+)\"")


def tracked_files():
    try:
        out = subprocess.run(["git", "ls-files"], cwd=ROOT, capture_output=True, text=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        pytest.skip("needs git to list tracked files")
    return [ROOT / line for line in out.splitlines()]


def test_no_api_keys_or_env_file_committed():
    files = tracked_files()
    assert ROOT / ".env" not in files
    for path in files:
        if path.suffix in {".png", ".pdf"}:
            continue
        assert not KEY_PATTERNS.search(path.read_text(encoding="utf-8")), f"possible API key in {path}"


@pytest.mark.parametrize("doc", DOCS)
def test_local_links_point_to_real_files(doc):
    path = ROOT / doc
    text = path.read_text(encoding="utf-8")
    links = [next(g for g in match.groups() if g) for match in LINK.finditer(text)]
    local = [link for link in links if not re.match(r"[a-z]+:|#|data:", link)]
    assert local or doc == "index.html", f"no local links found in {doc}"
    for link in local:
        target = (path.parent / link.split("#")[0]).resolve()
        assert target.exists(), f"{doc} links to missing {link}"

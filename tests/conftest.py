"""Shared test setup: make the scripts importable and run n8n Code node JavaScript."""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
for folder in ("scripts", "matcher"):
    sys.path.insert(0, str(ROOT / folder))

WORKFLOWS = {
    "screener_gemini": ROOT / "n8n" / "resume_screener_workflow.json",
    "screener_claude": ROOT / "n8n" / "resume_screener_workflow_claude.json",
    "matcher": ROOT / "n8n" / "smart_job_matcher_workflow.json",
}

# Stand-ins for the n8n globals a Code node uses: $input and $('Node name').
HARNESS = """
const ITEMS = __ITEMS__;
const REFS = __REFS__;
function nodeRef(i) {
  return function (name) {
    const r = REFS[name];
    if (!r) throw new Error('Code node referenced an unknown node: ' + name);
    return {
      item: { json: r[i] },
      first: () => ({ json: r[0] }),
      all: () => r.map(json => ({ json })),
      itemMatching: k => ({ json: r[k] }),
    };
  };
}
let results = [];
if (__MODE__ === 'runOnceForEachItem') {
  ITEMS.forEach((it, i) => {
    results.push((function ($input, $) { __CODE__ })({ item: { json: it } }, nodeRef(i)));
  });
} else {
  results = (function ($input, $) { __CODE__ })(
    { all: () => ITEMS.map(json => ({ json })), first: () => ({ json: ITEMS[0] }) }, nodeRef(0));
}
const out = JSON.stringify(results.map(r => r.json));
if (typeof process !== 'undefined' && process.stdout) process.stdout.write(out);
out;
"""


def js_command():
    """Node.js if installed; on macOS, JavaScriptCore through osascript also works."""
    if shutil.which("node"):
        return ["node"]
    if shutil.which("osascript"):
        return ["osascript", "-l", "JavaScript"]
    return None


@pytest.fixture(scope="session")
def workflows():
    return {key: json.loads(path.read_text(encoding="utf-8")) for key, path in WORKFLOWS.items()}


@pytest.fixture(scope="session")
def run_code_node():
    """Run a Code node from a workflow on test items and return its output items (json only)."""
    command = js_command()
    if command is None:
        pytest.skip("needs Node.js to run the n8n Code node JavaScript")

    def run(workflow: dict, node_name: str, items: list, refs: dict | None = None) -> list:
        node = next(n for n in workflow["nodes"] if n["name"] == node_name)
        params = node["parameters"]
        script = (HARNESS.replace("__ITEMS__", json.dumps(items))
                         .replace("__REFS__", json.dumps(refs or {}))
                         .replace("__MODE__", json.dumps(params.get("mode", "runOnceForAllItems")))
                         .replace("__CODE__", params["jsCode"]))
        with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8") as f:
            f.write(script)
        try:
            done = subprocess.run([*command, f.name], capture_output=True, text=True, timeout=60)
        finally:
            Path(f.name).unlink()
        assert done.returncode == 0, done.stderr
        return json.loads(done.stdout)

    return run

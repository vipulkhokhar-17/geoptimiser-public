"""The static (GitHub Pages) export of the UI. Needs neither FastAPI nor network."""

import json
import re
import shutil
import subprocess
from pathlib import Path

import pytest

from geoptimiser.app.static_export import UI_DIR, csp, export_site, main, render_index

ROOT = Path(__file__).parents[2]
API = "https://api.geoptimiser.me"


def test_export_contains_exactly_the_static_files(tmp_path):
    files = export_site(tmp_path / "site", api_base=API, domain="geoptimiser.me")
    assert files == [
        ".nojekyll",
        "CNAME",
        "FONTS-LICENSE.txt",
        "app.js",
        "config.js",
        "hanken-grotesk.woff2",
        "index.html",
        "jetbrains-mono.woff2",
        "style.css",
    ]
    assert (tmp_path / "site" / "CNAME").read_text() == "geoptimiser.me\n"


def test_assets_are_relative_so_the_site_works_at_the_domain_root_or_any_path(tmp_path):
    export_site(tmp_path / "site", api_base=API)
    page = (tmp_path / "site" / "index.html").read_text()
    refs = re.findall(r'(?:href|src)="([^"]+)"', page)
    # In-page routes (#/...) are fragment links, not assets.
    assets = [r for r in refs if not r.startswith("#")]
    assert assets == ["hanken-grotesk.woff2", "style.css", "config.js", "app.js"]
    assert all(r.startswith("#") for r in refs if r not in assets)
    assert '"/ui/' not in page and not any(r.startswith("/") for r in refs)
    for name in assets:
        assert (tmp_path / "site" / name).is_file()


def test_the_api_base_is_written_to_config_js_only(tmp_path):
    export_site(tmp_path / "site", api_base=API)
    config = (tmp_path / "site" / "config.js").read_text()
    assert config == f'window.GEOPTIMISER_CONFIG = {{"apiBase": "{API}"}};\n'
    for name in ("app.js", "style.css"):  # no backend URL is baked into the code
        assert "geoptimiser.me" not in (tmp_path / "site" / name).read_text()


def test_the_csp_allows_only_this_site_and_the_api_origin(tmp_path):
    export_site(tmp_path / "site", api_base=API)
    page = (tmp_path / "site" / "index.html").read_text()
    policy = re.search(r'Content-Security-Policy" content="([^"]+)"', page).group(1)
    assert policy == csp(API)
    assert "connect-src 'self' https://api.geoptimiser.me;" in policy
    assert (
        "script-src 'self'" in policy
        and "unsafe-inline" not in policy
        and "unsafe-eval" not in policy
    )
    assert "*" not in policy
    assert '<meta name="referrer" content="no-referrer">' in page


def test_same_origin_export_has_no_extra_connect_origin(tmp_path):
    export_site(tmp_path / "site", api_base="", domain=None)
    assert "connect-src 'self';" in (tmp_path / "site" / "index.html").read_text()
    assert (
        json.loads(
            (tmp_path / "site" / "config.js").read_text().split("= ")[1].rstrip(";\n")
        )["apiBase"]
        == ""
    )
    assert not (tmp_path / "site" / "CNAME").exists()


@pytest.mark.parametrize(
    "bad",
    ["*", "http://api.geoptimiser.me", "https://api.geoptimiser.me/v1", "https://u:p@api.geoptimiser.me",
     "javascript:alert(1)", "https://api.geoptimiser.me?x=1", "ftp://x.test", "https://", 'https://a.test"><script>'],
)  # fmt: skip
def test_unsafe_api_bases_are_refused(tmp_path, bad):
    with pytest.raises(ValueError):
        export_site(tmp_path / "site", api_base=bad)
    assert not (tmp_path / "site").exists()


def test_loopback_http_is_allowed_for_local_trials(tmp_path):
    export_site(tmp_path / "site", api_base="http://127.0.0.1:8000", domain=None)
    assert "http://127.0.0.1:8000" in (tmp_path / "site" / "config.js").read_text()


@pytest.mark.parametrize(
    "domain", ["", "bad domain", "http://geoptimiser.me", "evil.com/../x", "localhost"]
)
def test_domain_is_validated_when_given(tmp_path, domain):
    if not domain:
        export_site(tmp_path / "site", domain=None)
        return
    with pytest.raises(ValueError):
        export_site(tmp_path / "site", domain=domain)


def test_a_non_empty_output_directory_is_never_overwritten(tmp_path):
    out = tmp_path / "site"
    out.mkdir()
    (out / "keep.txt").write_text("x")
    with pytest.raises(FileExistsError):
        export_site(out)
    assert (out / "keep.txt").read_text() == "x"
    assert main(["--out", str(out)]) == 2
    assert main(["--out", str(out), "--force"]) == 0 and not (out / "keep.txt").exists()


def test_the_exported_scripts_are_the_same_files_the_backend_serves(tmp_path):
    export_site(tmp_path / "site", api_base=API)
    for name in ("app.js", "style.css", "hanken-grotesk.woff2", "jetbrains-mono.woff2"):
        assert (tmp_path / "site" / name).read_bytes() == (UI_DIR / name).read_bytes()


def test_the_source_page_has_no_hardcoded_backend_or_secret():
    for name in ("index.html", "app.js", "style.css"):
        text = (UI_DIR / name).read_text()
        assert "geoptimiser.me" not in text
        assert not re.search(r"sk-[A-Za-z0-9_-]{8,}|Bearer\s+\S{12,}", text)
    js = (UI_DIR / "app.js").read_text()
    assert "apiBase" in js and 'credentials: "omit"' in js
    assert not re.search(r"https?://", js)  # no absolute URL in the code
    assert not re.search(
        r"fetch\(\s*[\"'`]/", js
    )  # every request goes through apiUrl()


def test_render_index_rejects_unexpected_markup():
    with pytest.raises(ValueError):
        render_index("<html><body></body></html>", "")
    with pytest.raises(ValueError):
        render_index(
            '<meta name="viewport" content="x"><script src=\'/ui/x.js\'></script>', ""
        )


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_the_exported_app_sends_every_request_to_the_configured_api_without_credentials(
    tmp_path,
):
    export_site(tmp_path / "site", api_base=API)
    script = r"""
const fs = require('fs'), vm = require('vm');
const dir = process.argv[1];
const calls = [];
const stub = () => new Proxy(function () {}, {
  get: (t, p) => (p === 'then' ? undefined : p === Symbol.toPrimitive ? () => '' : p === 'value' ? '' : p === 'checked' ? false : stub()),
  apply: () => stub(), set: () => true,
});
global.window = { addEventListener: () => {}, scrollTo: () => {}, innerWidth: 1280 };
global.location = { hash: '' };
global.history = { replaceState: () => {} };
global.document = { getElementById: () => stub(), createElement: () => stub(), createTextNode: () => stub(),
  createDocumentFragment: () => stub(), querySelectorAll: () => [], addEventListener: () => {}, title: '' };
global.Node = function Node() {};
global.fetch = async (url, opt) => { calls.push({ url, credentials: opt && opt.credentials }); return { ok: true, json: async () => ({ status: 'ok', audits: [] }) }; };
global.setTimeout = () => 0; global.clearTimeout = () => 0;
vm.runInThisContext(fs.readFileSync(dir + '/config.js', 'utf8'));
vm.runInThisContext(fs.readFileSync(dir + '/app.js', 'utf8'));
setTimeout = undefined;
Promise.resolve().then(() => new Promise((r) => setImmediate(r))).then(() => { console.log(JSON.stringify(calls)); });
"""
    result = subprocess.run(
        ["node", "-e", script, str(tmp_path / "site")],
        capture_output=True,
        text=True,
        timeout=30,
    )
    assert result.returncode == 0, result.stderr
    calls = json.loads(result.stdout.strip().splitlines()[-1])
    assert calls, "the app made no requests on load"
    assert all(c["url"].startswith(API + "/api/v1/") for c in calls), calls
    assert all(c["credentials"] == "omit" for c in calls)
    urls = {c["url"] for c in calls}
    assert API + "/api/v1/health" in urls
    assert any(u.startswith(API + "/api/v1/audits?limit=") for u in urls), urls


@pytest.mark.skipif(shutil.which("node") is None, reason="node is not installed")
def test_ui_sources_have_valid_javascript_syntax():
    for name in ("app.js",):
        assert (
            subprocess.run(
                ["node", "--check", str(UI_DIR / name)], capture_output=True
            ).returncode
            == 0
        )


def _permissions(block: str, indent: int) -> dict[str, str]:
    """The ``permissions:`` mapping directly under a block, parsed without PyYAML."""
    pad = " " * indent
    found: dict[str, str] = {}
    lines = block.splitlines()
    for n, line in enumerate(lines):
        if line == f"{pad}permissions:":
            for entry in lines[n + 1 :]:
                match = re.match(rf"^{pad}  ([a-z-]+): (read|write|none)\s*$", entry)
                if not match:
                    break
                found[match.group(1)] = match.group(2)
            break
    return found


def _workflow_parts():
    text = (ROOT / ".github/workflows/pages.yml").read_text()
    head, jobs = text.split("\njobs:\n", 1)
    sections = re.split(r"^  ([a-z-]+):\n", jobs, flags=re.M)
    by_name = dict(zip(sections[1::2], sections[2::2], strict=True))
    return text, head, by_name


def test_the_pages_workflow_exists_and_is_least_privilege():
    text, head, jobs = _workflow_parts()
    assert "branches: [main]" in text and "pull_request" not in text
    assert "actions/deploy-pages" in text and "actions/upload-pages-artifact" in text
    assert "secrets." not in text and "GEOPTIMISER_API_BASE" in text
    assert "python -m geoptimiser.app.static_export" in text
    assert set(jobs) == {"build", "deploy"}


def test_pages_workflow_permission_scopes():
    _, head, jobs = _workflow_parts()
    # Workflow default: read-only contents, nothing else.
    assert _permissions(head, 0) == {"contents": "read"}
    # Build: configure-pages needs to read the Pages site (private repositories), and
    # nothing that writes.
    build = _permissions(jobs["build"], 4)
    assert build == {"contents": "read", "pages": "read"}
    assert "actions/configure-pages" in jobs["build"]
    assert "deploy-pages" not in jobs["build"]
    # Deploy: the only place with pages/id-token write.
    deploy = _permissions(jobs["deploy"], 4)
    assert deploy == {"pages": "write", "id-token": "write", "contents": "read"}
    assert "actions/deploy-pages" in jobs["deploy"]
    for name, scopes in (("build", build), ("deploy", deploy)):
        assert "write-all" not in jobs[name] and "read-all" not in jobs[name]
        assert scopes.get("contents") == "read"
    # No write scope outside the deploy job.
    assert "write" not in "".join(_permissions(head, 0).values())
    assert "write" not in "".join(build.values())
    assert "id-token" not in build and "id-token" not in _permissions(head, 0)

"""End-to-end browser check of the real product workflow (assignment Part 8).

Starts tests/e2e/e2e_server.py (the production API, pipeline, store and UI with the
crawler pointed at local synthetic fixture sites), drives Chromium through Playwright,
and asserts that what the UI shows agrees with what the backend returns. Expectations are
fixed in this file before it runs. No external network is used.

Run (Playwright for Python and Chromium must be installed; the backend runs in the
project's environment given by --python):

    python tests/e2e/browser_e2e.py --python .venv/bin/python --out /tmp/e2e-run

Exit status 0 means every check passed; each check is printed as PASS/FAIL.
"""

import argparse
import json
import os
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parents[2]
results: list[tuple[bool, str]] = []


def check(ok: bool, what: str) -> None:
    results.append((bool(ok), what))
    print(("PASS " if ok else "FAIL ") + what, flush=True)


def get(base: str, path: str) -> object:
    with urllib.request.urlopen(base + path, timeout=20) as res:
        return json.loads(res.read())


def wait_terminal(base: str, audit_id: str, seconds: float = 120) -> dict:
    end = time.time() + seconds
    while time.time() < end:
        audit = get(base, f"/api/v1/audits/{audit_id}")
        if audit["status"] in ("completed", "incomplete", "failed", "interrupted"):
            return audit
        time.sleep(0.5)
    raise TimeoutError(audit_id)


def submit_via_ui(page, base: str, url: str, posted: list) -> str:
    page.goto(base + "/#/")
    page.fill("#url", url)
    page.check("#authorized")
    page.click("button[type=submit]")
    page.wait_for_url("**/#/audits/aud_*", timeout=15000)
    return page.url.split("#/audits/")[1].split("/")[0]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="interpreter with the project and its api extra",
    )
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--port", type=int, default=8811)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    base, control = f"http://127.0.0.1:{args.port}", f"http://127.0.0.1:{args.port + 1}"
    env = {**os.environ, "PYTHONPATH": str(ROOT / "src") + os.pathsep + str(ROOT)}
    server = subprocess.Popen(
        [args.python, str(ROOT / "tests/e2e/e2e_server.py"), "--data-dir", str(args.out / "data"),
         "--port", str(args.port), "--control-port", str(args.port + 1)],
        env=env, stdout=subprocess.DEVNULL, stderr=open(args.out / "server.log", "w"),
    )  # fmt: skip
    try:
        for _ in range(60):
            try:
                get(base, "/api/v1/health")
                break
            except OSError:
                time.sleep(0.25)
        run_checks(base, control, args.out)
    finally:
        server.terminate()
        server.wait(10)
    failed = [w for ok, w in results if not ok]
    print(f"\n{len(results) - len(failed)}/{len(results)} checks passed")
    return 1 if failed else 0


def run_checks(base: str, control: str, out: Path) -> None:
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(viewport={"width": 1280, "height": 800})
        console, dialogs, posted = [], [], []
        page.on("console", lambda m: m.type == "error" and console.append(m.text))
        page.on("pageerror", lambda e: console.append(str(e)))
        page.on("dialog", lambda d: (dialogs.append(d.message), d.dismiss()))
        page.on(
            "request",
            lambda r: (
                r.method == "POST"
                and "/api/v1/audits" in r.url
                and posted.append(r.post_data)
            ),
        )

        # 1-3: open, enter a URL, and client-side validation without authorization.
        page.goto(base + "/#/")
        check(
            page.locator("h1").first.inner_text().startswith("Measure"),
            "1 the application opens on the New audit page",
        )
        page.fill("#url", "fixture.test")
        page.click("button[type=submit]")
        check(
            page.locator("#form-error").is_visible() and not posted,
            "3 an unauthorized submission is blocked in the browser and nothing is sent",
        )
        page.fill("#url", "ftp://fixture.test/")
        page.check("#authorized")
        page.click("button[type=submit]")
        check(
            "http" in page.locator("#form-error").inner_text() and not posted,
            "3 a non-http URL is rejected before submission",
        )

        # 4-9: submit, payload, start, live status, terminal state.
        page.fill("#url", "fixture.test")
        page.click("button[type=submit]")
        page.wait_for_url("**/#/audits/aud_*", timeout=15000)
        audit_id = page.url.split("#/audits/")[1].split("/")[0]
        body = json.loads(posted[-1]) if posted else {}
        check(body.get("url") == "fixture.test" and body.get("authorization_confirmed") is True
              and body.get("options") == {"max_pages": 10, "max_depth": 2, "retrieval": "lexical", "use_agent": False},
              "5 the backend receives exactly the submitted payload")  # fmt: skip
        check(
            len(posted) == 1, "4 one click creates one audit (no duplicate submission)"
        )
        audit = get(base, f"/api/v1/audits/{audit_id}")
        check(
            audit["status"] in ("queued", "running", "completed", "incomplete"),
            "6 the audit starts on the backend",
        )
        audit = wait_terminal(base, audit_id)
        page.wait_for_selector(".score-block", timeout=30000)
        check(
            audit["status"] == "completed",
            f"9 the audit reaches a terminal state ({audit['status']})",
        )
        stage_states = {s["name"]: s["status"] for s in audit["stages"]}
        dots = page.locator(".timeline li").evaluate_all(
            "els => els.map(e => e.dataset.s)"
        )
        check(
            dots and dots[-1] == "ok" and stage_states.get("report") == "ok",
            "8 the pipeline view shows the backend's stage results, including the report stage",
        )

        # 10-12: overview, score and reportability, categories.
        report = get(base, f"/api/v1/audits/{audit_id}/report")
        overall = report["scores"]["overall"]
        shown = page.locator(".score-block").inner_text()
        if overall["reported_score"] is None:
            check(
                "Score withheld" in shown,
                "11 a withheld score is shown as withheld, with the backend's reason",
            )
        else:
            check(
                str(round(overall["reported_score"] * 100)) in shown,
                "11 the score shown equals the backend's reported_score",
            )
        rows = page.locator("section[aria-labelledby=cat-title] tbody tr").count()
        check(
            rows == len(report["scores"]["categories"]),
            "12 one category row per backend category",
        )
        cells = page.locator(".ledger .cell").count()
        check(cells == 120, "10 the measurement ledger shows all 120 features")
        page.screenshot(path=str(out / "overview.png"), full_page=True)

        # 13: feature explorer agrees with /features.
        feats = get(base, f"/api/v1/audits/{audit_id}/features")["features"]
        f021 = next(f for f in feats if f["feature_id"] == "F021")
        page.goto(base + f"/#/audits/{audit_id}/features/F021")
        page.wait_for_selector(".detail h2")
        detail = page.locator(".detail").inner_text()
        check(
            "Title presence" in detail and f"{f021['passed']} passed" in detail,
            "13 the feature detail shows the backend's per-feature counts",
        )
        page.select_option("#f-impl", "PLANNED")
        listed = page.locator(".feature-list .row").count()
        planned = sum(1 for f in feats if f["implementation_status"] == "planned")
        check(
            listed == planned,
            f"13 the implementation filter lists the {planned} planned features",
        )

        # 14-15: findings and evidence.
        findings = get(base, f"/api/v1/audits/{audit_id}/findings")
        page.goto(base + f"/#/audits/{audit_id}/findings")
        page.wait_for_selector("#fd-q")
        check(
            page.locator("details.item").count() == findings["count"],
            "14 one finding per backend finding",
        )
        if findings["count"]:
            first = page.locator("details.item").first
            first.locator("summary").click()
            title = first.locator(".title").inner_text()
            backend = next(
                f for f in findings["findings"] if f["finding"]["title"] == title
            )
            snippet = backend["evidence"][0]["snippet"]
            check(
                snippet.strip()[:40] in first.inner_text(),
                "15 the evidence snippet shown is the backend's evidence text",
            )

        # 16: recommendations.
        recs = get(base, f"/api/v1/audits/{audit_id}/recommendations")
        page.goto(base + f"/#/audits/{audit_id}/recommendations")
        page.wait_for_selector("text=Recommendations come from fixed templates")
        check(
            page.locator("details.item").count() == recs["count"],
            "16 one recommendation per backend recommendation",
        )

        # 17-19: crawl, retrieval, agent.
        page.goto(base + f"/#/audits/{audit_id}/crawl")
        page.wait_for_selector("text=Pages audited")
        check(
            f"Pages audited ({len(report['pages'])})" in page.inner_text("body"),
            "17 crawl view shows the backend's page count",
        )
        page.goto(base + f"/#/audits/{audit_id}/retrieval")
        page.wait_for_selector("text=LLM agent")
        txt = page.inner_text("body")
        check(
            "lexical" in txt and "Not requested" in txt,
            "18-19 retrieval mode and agent state match the request",
        )

        # 20-21: report and download.
        with urllib.request.urlopen(
            base + f"/api/v1/audits/{audit_id}/report.html"
        ) as res:
            html = res.read().decode()
            check(
                "fixture.test" in html
                and "default-src 'none'" in res.headers["Content-Security-Policy"],
                "20 the HTML report is served with a script-free CSP",
            )
        with urllib.request.urlopen(
            base + f"/api/v1/audits/{audit_id}/report?download=true"
        ) as res:
            check(
                "attachment" in res.headers["Content-Disposition"]
                and json.loads(res.read())["audit"]["audit_id"] == audit_id,
                "21 the JSON report downloads as an attachment",
            )

        # 22: second audit of the same URL after the site changed, then compare.
        urllib.request.urlopen(control + "/use/clean_static")
        second = submit_via_ui(page, base, "fixture.test", posted)
        wait_terminal(base, second)
        page.goto(base + f"/#/audits/{second}/compare")
        page.wait_for_selector("button:has-text('Compare')")
        page.click("button:has-text('Compare')")
        page.wait_for_selector("text=Scores and coverage", timeout=15000)
        check(
            "do not show that" in page.inner_text("body")
            or "do not prove" in page.inner_text("body")
            or "They do not show" in page.inner_text("body"),
            "22 the comparison states that differences are not proof of causality",
        )
        page.screenshot(path=str(out / "compare.png"), full_page=True)

        # A failed audit: nothing auditable is served.
        urllib.request.urlopen(control + "/use/empty_failed_crawl")
        failed = submit_via_ui(page, base, "fixture.test", posted)
        audit = wait_terminal(base, failed)
        page.goto(base + f"/#/audits/{failed}")
        page.wait_for_selector(".callout")
        check(
            audit["status"] == "failed"
            and "This audit is failed" in page.inner_text("body"),
            "failed audits are labelled and explain why",
        )
        page.goto(base + f"/#/audits/{failed}/features")
        page.wait_for_selector("text=Not available for this audit")
        check(
            page.locator(".feature-list .row").count() == 0,
            "a failed audit shows no invented feature results",
        )

        check(
            not dialogs,
            "no script-triggered dialog fired while rendering site-derived content",
        )
        # The browser logs every non-2xx fetch; a 409 for the failed audit's feature
        # results is the API correctly refusing to invent them (checked above).
        unexpected = [c for c in console if "status of 409" not in c]
        check(
            not unexpected,
            "no unexpected browser console errors"
            + (f": {unexpected[:3]}" if unexpected else ""),
        )
        browser.close()


if __name__ == "__main__":
    raise SystemExit(main())

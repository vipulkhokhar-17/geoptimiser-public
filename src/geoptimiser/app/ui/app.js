"use strict";
/*
 * Geoptimiser UI. Plain JavaScript, no framework, no build step.
 *
 * Safety rules for this file:
 *  - Every value that comes from the API (and so possibly from an audited website or a
 *    model) is inserted as a text node through el(). No HTML-string API is used anywhere.
 *  - Links built from data are only created for http(s) URLs (safeHref).
 *  - Requests never send credentials (credentials: "omit").
 *  - Scores are never computed here: only the backend's reported_score is shown, and a
 *    withheld score shows the backend's reason.
 */

const API_BASE = String((window.GEOPTIMISER_CONFIG || {}).apiBase || "").replace(/\/+$/, "");
const apiUrl = (path) => API_BASE + path;
const $ = (id) => document.getElementById(id);
const TERMINAL = new Set(["completed", "incomplete", "failed", "interrupted"]);
const STAGE_LABELS = {
  validate: "Validate", crawl: "Crawl", extract: "Extract", features: "Features", chunk: "Chunk",
  retrieval: "Retrieval", diagnose: "Diagnose", recommend: "Recommend", agent: "Agent",
  validate_output: "Check output", report: "Report",
};
const STAGES = Object.keys(STAGE_LABELS);
const CATEGORY_NAMES = {}; // filled from the catalog
const GLYPH = { pass: "✓", fail: "✕", warning: "!", mixed: "±", not_measured: "?", not_applicable: "–", error: "⚠", planned: "·", unavailable: "∅", implemented: "●", partial: "◐" };
const RESULT_LABEL = {
  pass: "Pass", fail: "Fail", warning: "Warning", mixed: "Fails on some pages", not_measured: "Not measured",
  not_applicable: "Not applicable", error: "Error", planned: "Not implemented", unavailable: "Unavailable",
};

// --- DOM helpers ---------------------------------------------------------------------------

function el(tag, attrs, ...kids) {
  const node = document.createElement(tag);
  for (const [k, v] of Object.entries(attrs || {})) {
    if (v === false || v == null) continue;
    if (k === "class") node.className = v;
    else if (k === "dataset") Object.assign(node.dataset, v);
    else if (k.startsWith("on") && typeof v === "function") node.addEventListener(k.slice(2), v);
    else node.setAttribute(k, v === true ? "" : String(v));
  }
  for (const kid of kids.flat(Infinity)) {
    if (kid == null || kid === false) continue;
    node.append(kid instanceof Node ? kid : document.createTextNode(String(kid)));
  }
  return node;
}
const frag = (...kids) => { const f = document.createDocumentFragment(); for (const k of kids.flat(Infinity)) if (k != null && k !== false) f.append(k instanceof Node ? k : document.createTextNode(String(k))); return f; };
function safeHref(url) {
  const value = String(url || "").trim();
  return /^https?:\/\//i.test(value) ? value : null;
}
function extLink(url, text) {
  const href = safeHref(url);
  return href ? el("a", { href, target: "_blank", rel: "noopener noreferrer nofollow" }, text || url) : el("span", {}, text || url || "");
}
const fmtNum = (v, d = 2) => (v == null ? null : Number(v).toFixed(d));
const pct = (v) => (v == null ? "not measured" : Math.round(v * 100) + "%");
const when = (iso) => (iso ? iso.replace("T", " ").slice(0, 16) + " UTC" : "—");
function jsonText(v) {
  if (v == null) return "—";
  if (typeof v === "string") return v;
  try { return JSON.stringify(v); } catch (_) { return String(v); }
}
function pill(status, text) {
  return el("span", { class: "pill", "data-s": status }, el("span", { class: "glyph", "aria-hidden": "true" }, GLYPH[status] || "•"), text || RESULT_LABEL[status] || status.replace(/_/g, " "));
}
const sev = (s) => el("span", { class: "sev", "data-sev": s }, s);
function announce(text) { const n = $("announce"); if (n) n.textContent = text; }
function loading(text) { return el("div", { class: "loading" }, el("span", { class: "spin", "aria-hidden": "true" }), text || "Loading…"); }
function callout(tone, ...kids) { return el("div", { class: "callout", "data-tone": tone }, ...kids); }
function table(headers, rows, opts = {}) {
  return el("div", { class: "table-wrap" }, el("table", {},
    opts.caption ? el("caption", { class: "visually-hidden" }, opts.caption) : null,
    el("thead", {}, el("tr", {}, headers.map((h) => el("th", { scope: "col", class: h.num ? "num" : null }, h.label || h)))),
    el("tbody", {}, rows)));
}
function kv(pairs) {
  return el("dl", { class: "kv" }, pairs.filter((p) => p && p[1] != null && p[1] !== "").map(([k, v]) => [el("dt", {}, k), el("dd", {}, v)]));
}

// --- API -------------------------------------------------------------------------------------

class ApiError extends Error {}
async function api(path, options = {}) {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), options.timeout || 20000);
  let res;
  try {
    res = await fetch(apiUrl(path), { credentials: "omit", ...options, signal: controller.signal });
  } catch (_) {
    throw Object.assign(new ApiError("Cannot reach the Geoptimiser backend" + (API_BASE ? " at " + API_BASE : "") + ". Check that it is running."), { status: 0 });
  } finally { clearTimeout(timer); }
  let body = null;
  try { body = await res.json(); } catch (_) { /* not JSON */ }
  if (!res.ok) {
    const e = (body && body.error) || {};
    const err = new ApiError(e.message || "The request failed (HTTP " + res.status + ").");
    err.status = res.status; err.code = e.code; err.problems = e.problems || [];
    throw err;
  }
  return body;
}
const cache = { catalog: null, reports: new Map(), features: new Map() };
async function getCatalog() {
  if (!cache.catalog) {
    cache.catalog = api("/api/v1/catalog").then((c) => {
      for (const cat of c.categories || []) CATEGORY_NAMES[cat.code] = cat.name;
      c.byId = Object.fromEntries(c.features.map((f) => [f.feature_id, f]));
      return c;
    }).catch((e) => { cache.catalog = null; throw e; });
  }
  return cache.catalog;
}
async function getReport(id, terminal) {
  if (terminal && cache.reports.has(id)) return cache.reports.get(id);
  const p = api("/api/v1/audits/" + encodeURIComponent(id) + "/report");
  if (terminal) { cache.reports.set(id, p); p.catch(() => cache.reports.delete(id)); }
  return p;
}
async function getFeatures(id) {
  if (!cache.features.has(id)) {
    const p = api("/api/v1/audits/" + encodeURIComponent(id) + "/features");
    cache.features.set(id, p); p.catch(() => cache.features.delete(id));
  }
  return cache.features.get(id);
}

// --- routing ------------------------------------------------------------------------------------

let generation = 0; // increments on every navigation; stale async renders check it
let pollTimer = null;
function parseRoute() {
  const [path, query] = (location.hash.replace(/^#/, "") || "/").split("?");
  const parts = path.split("/").filter(Boolean).map(decodeURIComponent);
  const params = new URLSearchParams(query || "");
  if (!parts.length) return { view: "home", params };
  if (parts[0] === "audits" && parts[1]) return { view: "audit", id: parts[1], tab: parts[2] || "overview", sub: parts[3], params };
  if (parts[0] === "audits") return { view: "audits", params };
  if (parts[0] === "catalog") return { view: "catalog", sub: parts[1], params };
  if (parts[0] === "compare") return { view: "compare", params };
  return { view: "notfound", params };
}
function go(hash) { if (location.hash !== hash) location.hash = hash; else route(); }
function setNav(view) {
  const key = { home: "home", audits: "audits", audit: "audits", catalog: "catalog", compare: "compare" }[view];
  for (const a of document.querySelectorAll(".nav a")) {
    if (a.dataset.nav === key) a.setAttribute("aria-current", "page"); else a.removeAttribute("aria-current");
  }
}
async function route() {
  clearTimeout(pollTimer);
  const gen = ++generation;
  const r = parseRoute();
  setNav(r.view);
  closeMenu();
  const view = $("view");
  const mount = (node, title) => {
    if (gen !== generation) return false;
    view.replaceChildren(node);
    document.title = (title ? title + " — " : "") + "Geoptimiser";
    return true;
  };
  try {
    if (r.view === "home") await renderHome(mount, gen);
    else if (r.view === "audits") await renderAudits(mount, gen, r);
    else if (r.view === "audit") await renderAudit(mount, gen, r);
    else if (r.view === "catalog") await renderCatalog(mount, gen, r);
    else if (r.view === "compare") await renderCompare(mount, gen, r);
    else mount(el("div", { class: "empty" }, el("h1", {}, "Page not found"), el("p", {}, "This address does not match a page."), el("a", { class: "btn", href: "#/" }, "Go to New audit")), "Not found");
  } catch (e) {
    mount(errorView(e), "Error");
  }
}
function errorView(e) {
  return el("div", { class: "panel" }, el("h2", {}, e.status === 404 ? "Not found" : "Something went wrong"),
    el("p", {}, e.message || "The page could not be loaded."),
    e.status === 0 ? el("p", { class: "muted small" }, "Start the backend with: python -m geoptimiser.app serve") : null,
    el("div", { class: "actions" }, el("button", { class: "btn secondary", type: "button", onclick: () => route() }, "Try again")));
}

// --- home: intro + new audit ------------------------------------------------------------------

async function renderHome(mount, gen) {
  const intro = el("section", { class: "intro", "aria-labelledby": "home-title" },
    el("div", {},
      el("h1", { id: "home-title" }, "Measure what crawlers and answer engines can read on your site."),
      el("p", { class: "lede" }, "Geoptimiser crawls a website you are authorized to audit, runs a fixed catalog of 120 checks on the HTML it returns, and reports what it measured, what it could not measure, and what to change — with the evidence for every finding."),
      el("p", { class: "muted small" }, "Checks are deterministic. Scores are shown only when enough of them could be measured. Nothing here promises rankings or AI citations.")),
    el("div", { class: "panel" }, el("h2", {}, "How an audit runs"),
      el("ol", { class: "steps" },
        step("Crawl", "Fetches pages within your domain, respecting robots.txt, with size, time and address limits."),
        step("Extract", "Reads titles, headings, text, links, images and structured data from the returned HTML."),
        step("Measure", "Runs every implemented feature check and records pass, fail, or why it could not measure."),
        step("Diagnose", "Groups failures into findings with the evidence and passages that support them."),
        step("Recommend", "Writes rule-based changes, each with a way to verify it."),
        step("Report", "Produces an HTML and JSON report you can keep and compare later."))));
  const form = auditForm();
  const recent = el("div", {}, loading("Loading recent audits…"));
  if (!mount(el("div", {}, intro, el("div", { class: "grid-2" }, form, el("section", { class: "panel", "aria-labelledby": "recent-title" }, el("div", { class: "panel-head" }, el("h2", { id: "recent-title" }, "Recent audits"), el("a", { href: "#/audits", class: "small" }, "All audits")), recent))), "New audit")) return;
  $("url").focus({ preventScroll: true });
  try {
    const { audits } = await api("/api/v1/audits?limit=6");
    if (gen !== generation) return;
    recent.replaceChildren(audits.length ? auditTable(audits, true) : el("div", { class: "empty" }, el("p", {}, "No audits yet. Start one with the form.")));
  } catch (e) { if (gen === generation) recent.replaceChildren(callout("fail", el("p", {}, e.message))); }
}
function step(title, text) { return el("li", {}, el("div", {}, el("b", {}, title), el("span", {}, text))); }

function auditForm() {
  const error = el("p", { class: "form-error", id: "form-error", role: "alert", hidden: true });
  const submit = el("button", { class: "btn", type: "submit" }, "Start audit");
  const field = (id, label, input, hint) => el("div", { class: "field" }, el("label", { for: id }, label), input, hint ? el("span", { class: "hint", id: id + "-hint" }, hint) : null);
  const url = el("input", { id: "url", name: "url", type: "text", class: "url-input", inputmode: "url", autocomplete: "off", spellcheck: "false", required: true, maxlength: "2048", placeholder: "example.com", "aria-describedby": "url-hint" });
  const brand = el("input", { id: "brand", type: "text", maxlength: "100", autocomplete: "off" });
  const pages = el("input", { id: "max_pages", type: "number", min: "1", max: "100", value: "10", inputmode: "numeric" });
  const depth = el("input", { id: "max_depth", type: "number", min: "0", max: "5", value: "2", inputmode: "numeric" });
  const retrieval = el("select", { id: "retrieval" },
    el("option", { value: "lexical" }, "Lexical (BM25)"),
    el("option", { value: "semantic" }, "Semantic (needs the semantic extra)"),
    el("option", { value: "off" }, "Off"));
  const agent = el("input", { id: "use_agent", type: "checkbox" });
  const authorized = el("input", { id: "authorized", type: "checkbox", required: true });
  const form = el("form", { class: "panel form", id: "audit-form", novalidate: true, "aria-labelledby": "form-title" },
    el("h2", { id: "form-title" }, "Start an audit"),
    field("url", "Website URL", url, "A page on the site to start from. Only http and https on the default ports."),
    field("brand", "Brand name (optional)", brand),
    el("details", { class: "advanced" }, el("summary", {}, "Crawl and analysis options"),
      el("div", { class: "field-row" },
        field("max_pages", "Maximum pages", pages, "1–100; the server may cap it lower."),
        field("max_depth", "Link depth", depth, "0–5 links from the start page."),
        field("retrieval", "Passage retrieval", retrieval, "Used to attach supporting passages to findings.")),
      el("label", { class: "check" }, agent, el("span", {}, "Also run the optional LLM agent. It needs the agent extra and an OpenRouter key on the server; the deterministic audit does not depend on it."))),
    el("label", { class: "check" }, authorized, el("span", {}, "I own this site or am authorized to audit it.")),
    error,
    el("div", { class: "actions" }, submit));
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    if (submit.disabled) return; // a submission is already in flight
    error.hidden = true; url.removeAttribute("aria-invalid");
    const value = url.value.trim();
    const problems = [];
    if (!value) problems.push("Enter the website URL.");
    else if (/\s/.test(value)) problems.push("The URL cannot contain spaces.");
    else if (/^[a-z][a-z0-9+.-]*:/i.test(value) && !/^https?:\/\//i.test(value)) problems.push("Only http and https URLs can be audited.");
    const np = Number(pages.value), nd = Number(depth.value);
    if (!Number.isInteger(np) || np < 1 || np > 100) problems.push("Maximum pages must be a whole number from 1 to 100.");
    if (!Number.isInteger(nd) || nd < 0 || nd > 5) problems.push("Link depth must be a whole number from 0 to 5.");
    if (!authorized.checked) problems.push("Confirm that you own or are authorized to audit this site.");
    if (problems.length) {
      if (!value || /\s/.test(value)) url.setAttribute("aria-invalid", "true");
      error.textContent = problems.join(" "); error.hidden = false; return;
    }
    submit.disabled = true; submit.replaceChildren(el("span", { class: "spin", "aria-hidden": "true" }), "Starting…");
    try {
      const audit = await api("/api/v1/audits", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url: value, brand_name: brand.value.trim() || null, authorization_confirmed: true,
          options: { max_pages: np, max_depth: nd, retrieval: retrieval.value, use_agent: agent.checked } }),
      });
      announce("Audit started for " + audit.domain);
      go("#/audits/" + encodeURIComponent(audit.audit_id));
    } catch (e) {
      const detail = (e.problems || []).map((p) => (p.field ? p.field + ": " : "") + p.problem).join("; ");
      error.textContent = e.message + (detail ? " (" + detail + ")" : ""); error.hidden = false;
      if (e.code === "invalid_target") url.setAttribute("aria-invalid", "true");
      submit.disabled = false; submit.replaceChildren("Start audit");
    }
  });
  return form;
}

// --- audit list ------------------------------------------------------------------------------------

function scoreText(summary) {
  if (summary.overall_score != null && summary.score_reportable) return fmtNum(summary.overall_score, 2);
  if (summary.score_reportable === false) return "withheld";
  return "—";
}
function auditTable(audits, compact) {
  const rows = audits.map((a) => {
    const href = "#/audits/" + encodeURIComponent(a.audit_id);
    return el("tr", { class: "link-row", onclick: (e) => { if (e.target.tagName !== "A") go(href); } },
      el("td", {}, el("a", { class: "row-link", href }, a.domain), compact ? null : el("div", { class: "muted small mono" }, a.target_url)),
      el("td", {}, pill(a.status, a.status)),
      compact ? null : el("td", { class: "num" }, a.summary && a.summary.pages_ok != null ? a.summary.pages_ok : "—"),
      el("td", { class: "num mono" }, scoreText(a.summary || {})),
      el("td", { class: "small nowrap" }, when(a.created_at)));
  });
  const headers = compact
    ? ["Site", "Status", { label: "Score", num: true }, "Created"]
    : ["Site", "Status", { label: "Pages", num: true }, { label: "Score", num: true }, "Created"];
  return table(headers, rows, { caption: "Audits" });
}
async function renderAudits(mount, gen, r) {
  const status = r.params.get("status") || "";
  const { audits } = await api("/api/v1/audits?limit=100");
  const shown = status ? audits.filter((a) => a.status === status) : audits;
  const select = el("select", { id: "status-filter", onchange: (e) => go("#/audits" + (e.target.value ? "?status=" + e.target.value : "")) },
    el("option", { value: "" }, "All statuses"),
    ["completed", "incomplete", "failed", "interrupted", "running", "queued"].map((s) => el("option", { value: s, selected: s === status }, s)));
  mount(el("div", {},
    el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Audits"), el("p", {}, "Every audit stored by this backend, newest first. Scores show only where the backend reported one.")),
      el("a", { class: "btn", href: "#/" }, "New audit")),
    el("div", { class: "filters" }, el("div", { class: "field" }, el("label", { for: "status-filter" }, "Status"), select),
      el("span", { class: "result-count" }, shown.length + " of " + audits.length)),
    shown.length ? auditTable(shown, false) : el("div", { class: "panel empty" }, el("p", {}, audits.length ? "No audits have this status." : "No audits yet."), el("a", { class: "btn", href: "#/" }, "Start an audit"))), "Audits");
}

// --- one audit -------------------------------------------------------------------------------------

const TABS = [
  ["overview", "Overview"], ["features", "Features"], ["findings", "Findings"], ["recommendations", "Recommendations"],
  ["crawl", "Crawl and network"], ["retrieval", "Retrieval and agent"], ["report", "Report"], ["compare", "Compare"],
];
let pollDelay = 1500;
async function renderAudit(mount, gen, r) {
  const id = r.id;
  if (!/^aud_[0-9a-f]{20}$/.test(id)) throw Object.assign(new ApiError("This is not a valid audit id."), { status: 404 });
  const audit = await api("/api/v1/audits/" + encodeURIComponent(id));
  if (gen !== generation) return;
  if (!TERMINAL.has(audit.status)) {
    mount(runningView(audit), audit.domain);
    pollTimer = setTimeout(() => { if (gen === generation) { pollDelay = Math.min(pollDelay * 1.4, 8000); route(); } }, pollDelay);
    return;
  }
  pollDelay = 1500;
  const report = await getReport(id, true).catch((e) => ({ _error: e }));
  if (gen !== generation) return;
  const tab = TABS.some(([k]) => k === r.tab) ? r.tab : "overview";
  const body = el("div", {}, loading());
  mount(el("div", {}, auditHeader(audit, report), tabBar(audit, report, tab), statusNotice(audit, report), body), audit.domain);
  if (report._error) { body.replaceChildren(callout("fail", el("p", {}, "The report for this audit is not available: " + report._error.message))); return; }
  try {
    const node = await renderTab(tab, audit, report, r);
    if (gen === generation) body.replaceChildren(node);
  } catch (e) {
    if (gen !== generation) return;
    body.replaceChildren(e.status === 409 ? callout("info", el("p", {}, "Not available for this audit: " + e.message)) : callout("fail", el("p", {}, e.message)));
  }
}
function runningView(audit) {
  const stages = audit.stages || [];
  const current = audit.stage || (audit.status === "queued" ? "waiting in the queue" : "starting");
  return el("div", {},
    el("div", { class: "crumb" }, el("a", { href: "#/audits" }, "Audits"), " / ", audit.domain),
    el("div", { class: "page-head" }, el("div", {}, el("h1", {}, audit.domain), el("p", { class: "mono small" }, audit.target_url)), pill(audit.status, audit.status)),
    el("section", { class: "panel", "aria-labelledby": "progress-title" },
      el("div", { class: "panel-head" }, el("h2", { id: "progress-title" }, "Audit in progress"), el("span", { class: "small muted" }, el("span", { class: "spin", "aria-hidden": "true" }), " Current stage: ", STAGE_LABELS[current] || current)),
      timeline(stages, audit.stage),
      el("p", { class: "muted small" }, "Progress comes from the backend's stage records and refreshes automatically. Stage times appear as each stage finishes; nothing here is estimated.")));
}
function timeline(stages, running) {
  const by = Object.fromEntries((stages || []).map((s) => [s.name, s]));
  return el("ol", { class: "timeline", "aria-label": "Pipeline stages" }, STAGES.map((name) => {
    const s = by[name];
    const status = s ? s.status : (name === running ? "running" : "pending");
    const label = { ok: "done", failed: "failed", skipped: "skipped", running: "running", pending: "pending" }[status] || status;
    return el("li", { "data-s": status },
      el("span", { class: "dot", "aria-hidden": "true" }),
      el("span", { class: "name" }, STAGE_LABELS[name]),
      el("span", { class: "visually-hidden" }, ": " + label),
      el("span", { "aria-hidden": "true" }, label),
      s && s.duration_ms != null ? el("span", { class: "t" }, " " + (s.duration_ms >= 1000 ? (s.duration_ms / 1000).toFixed(1) + " s" : Math.round(s.duration_ms) + " ms")) : null);
  }));
}
// The only score the UI may show: the backend's reported_score (null when withheld).
// Reports written before reported_score existed use the same rule via `reportable`.
function shownScore(group) {
  if (!group) return null;
  return "reported_score" in group ? group.reported_score : (group.reportable ? group.score : null);
}
function scoreBlock(report) {
  const o = report && report.scores ? report.scores.overall : null;
  if (!o) return el("div", { class: "score-block" }, el("div", { class: "withheld" }, "No score"), el("div", { class: "caption" }, "Feature checks did not run."));
  const shown = shownScore(o);
  if (shown != null) {
    return el("div", { class: "score-block" }, el("div", { class: "value", "aria-label": "Overall score " + Math.round(shown * 100) + " out of 100" }, String(Math.round(shown * 100)), el("small", {}, "/100")),
      el("div", { class: "caption" }, "Share of measured, scored checks that passed. Feature coverage " + pct(o.feature_coverage) + "."));
  }
  return el("div", { class: "score-block" }, el("div", { class: "withheld" }, "Score withheld"),
    el("div", { class: "caption" }, (o.withheld_reason || "").replace(/^Score withheld:\s*/i, "") || ("Only " + o.measured_features + " of " + o.applicable_features + " applicable features were measured.")));
}
function auditHeader(audit, report) {
  return el("header", {},
    el("div", { class: "crumb" }, el("a", { href: "#/audits" }, "Audits"), " / ", audit.domain),
    el("div", { class: "audit-head" },
      el("div", {},
        el("h1", {}, audit.domain),
        el("dl", { class: "meta" },
          el("div", {}, el("dt", {}, "Status"), el("dd", {}, pill(audit.status, audit.status))),
          el("div", {}, el("dt", {}, "Start URL"), el("dd", { class: "mono small" }, extLink(audit.target_url))),
          audit.brand_name ? el("div", {}, el("dt", {}, "Brand"), el("dd", {}, audit.brand_name)) : null,
          el("div", {}, el("dt", {}, "Finished"), el("dd", {}, when(audit.finished_at))),
          el("div", {}, el("dt", {}, "Audit ID"), el("dd", { class: "mono small" }, audit.audit_id)))),
      scoreBlock(report && !report._error ? report : null)));
}
function tabBar(audit, report, active) {
  const base = "#/audits/" + encodeURIComponent(audit.audit_id) + "/";
  const counts = {
    findings: report && report.findings_available ? report.findings.length : null,
    recommendations: report && report.recommendations ? report.recommendations.recommendations.length : null,
  };
  return el("nav", { class: "tabs", "aria-label": "Audit sections" }, TABS.map(([key, label]) =>
    el("a", { href: base + key, "aria-current": key === active ? "page" : false }, label, counts[key] != null ? el("span", { class: "count" }, counts[key]) : null)));
}
function statusNotice(audit, report) {
  if (audit.status === "completed") return null;
  const tone = audit.status === "incomplete" ? "warn" : "fail";
  return callout(tone, el("p", {}, el("b", {}, "This audit is " + audit.status + ". "),
    audit.error_category ? "Reason: " + audit.error_category.replace(/_/g, " ") + (audit.error_message ? " — " + audit.error_message + ". " : ". ") : "",
    report && report.status_reason ? report.status_reason + ". " : "",
    "Only what was actually produced is shown."));
}
async function renderTab(tab, audit, report, r) {
  if (tab === "overview") return overviewTab(audit, report);
  if (tab === "features") return featuresTab(audit, report, r);
  if (tab === "findings") return findingsTab(audit, report, r);
  if (tab === "recommendations") return recommendationsTab(audit, report);
  if (tab === "crawl") return crawlTab(report);
  if (tab === "retrieval") return retrievalTab(audit, report);
  if (tab === "report") return reportTab(audit);
  return compareTab(audit);
}

// overview -------------------------------------------------------------------------------------------

function featureState(f) {
  if (f.implementation_status === "planned") return "planned";
  if (f.implementation_status === "unavailable") return "unavailable";
  if (f.failed > 0 && f.passed > 0) return "mixed";
  if (f.failed > 0) return "fail";
  if (f.warned > 0) return "warning";
  if (f.passed > 0) return "pass";
  if (f.errors > 0) return "error";
  if (f.not_applicable > 0 && !f.not_measured) return "not_applicable";
  return "not_measured";
}
function ledger(features, opts) {
  const byCat = {};
  for (const f of features) (byCat[f.category] = byCat[f.category] || []).push(f);
  const wrap = el("div", { class: "ledger", role: "group", "aria-label": opts.label });
  for (const code of Object.keys(byCat).sort()) {
    wrap.append(el("div", { class: "cat" }, el("b", {}, code), CATEGORY_NAMES[code] || ""));
    for (const f of byCat[code]) {
      const state = opts.state(f);
      const title = f.feature_id + " " + (f.name || "") + ": " + (opts.labels[state] || state);
      wrap.append(el("a", { class: "cell", "data-s": state, href: opts.href(f), title, "aria-label": title },
        el("span", {}, f.feature_id.slice(1)), el("span", { class: "g", "aria-hidden": "true" }, GLYPH[state] || "")));
    }
  }
  return wrap;
}
function legend(states, labels) {
  return el("div", { class: "legend", "aria-hidden": "true" }, states.map((s) => el("span", {}, el("i", { class: "cell", "data-s": s, style: false }), labels[s] || s)));
}
function overviewTab(audit, report) {
  const s = report.scores;
  const o = s ? s.overall : null;
  const base = "#/audits/" + encodeURIComponent(audit.audit_id) + "/features/";
  const facts = el("div", { class: "facts" },
    fact("Pages audited", String((report.pages || []).length), report.crawl && report.crawl.stop_reason ? "crawl stopped: " + report.crawl.stop_reason.replace(/_/g, " ") : ""),
    fact("Feature coverage", o ? pct(o.feature_coverage) : "—", o ? o.measured_features + " of " + o.applicable_features + " applicable features measured" : "no feature checks"),
    fact("Unit coverage", o ? pct(o.unit_coverage) : "—", "share of page-level checks that could conclude"),
    fact("Findings", report.findings_available ? String(report.findings.length) : "unavailable", report.recommendations ? report.recommendations.recommendations.length + " recommendations" : ""));
  const out = el("div", { class: "stack" }, facts);
  if (report.features && report.features.length) {
    const labels = RESULT_LABEL;
    out.append(el("section", { class: "panel", "aria-labelledby": "ledger-title" },
      el("div", { class: "panel-head" }, el("h2", { id: "ledger-title" }, "Measurement ledger"), el("span", { class: "small muted" }, "All 120 catalog features for this audit. Select one to see its evidence.")),
      ledger(report.features, { label: "Feature results for this audit", state: featureState, labels, href: (f) => base + f.feature_id }),
      legend(["pass", "fail", "mixed", "warning", "not_measured", "not_applicable", "error", "planned", "unavailable"], labels)));
  }
  if (s) {
    const rows = s.categories.map((c) => {
      const shown = shownScore(c);
      return el("tr", {},
        el("td", {}, el("b", { class: "mono" }, c.key + " "), c.name),
        el("td", {}, shown != null ? el("div", { class: "bar-cell" }, el("div", { class: "bar", role: "img", "aria-label": Math.round(shown * 100) + " percent" }, el("span", { style: false, dataset: { w: shown } })), el("span", { class: "mono" }, Math.round(shown * 100))) : el("span", { class: "muted small" }, c.score == null ? "not measured" : "withheld")),
        el("td", {}, el("div", { class: "bar-cell" }, el("div", { class: "bar", "data-kind": "coverage", role: "img", "aria-label": pct(c.feature_coverage) + " coverage" }, el("span", { dataset: { w: c.feature_coverage || 0 } })), el("span", { class: "mono" }, c.feature_coverage == null ? "—" : Math.round(c.feature_coverage * 100) + "%"))),
        el("td", { class: "num mono" }, c.measured_features + "/" + c.applicable_features),
        el("td", { class: "small muted" }, c.withheld_reason || ""));
    });
    const section = el("section", { class: "panel", "aria-labelledby": "cat-title" },
      el("h2", { id: "cat-title" }, "Categories"),
      table(["Category", "Score", "Feature coverage", { label: "Measured", num: true }, "Why withheld"], rows, { caption: "Category scores and coverage" }),
      el("p", { class: "muted small", style: false }, "A category score appears only when at least " + pct(s.min_reportable_coverage) + " of its applicable scored features were measured. Coverage says how much was measured, not how well the site performs."));
    out.append(section);
    applyBarWidths(section);
    const excluded = Object.entries(s.excluded_features || {});
    if (excluded.length) out.append(callout("info", el("p", {}, el("b", {}, "Not part of the aggregate score: "), excluded.map(([k, v], i) => [i ? "; " : "", el("span", { class: "mono" }, k), " " + v]))));
  } else {
    out.append(callout("warn", el("p", {}, "The feature checks did not run, so there are no scores.")));
  }
  // The stored report is written during the report stage, so its own stage list cannot
  // include that stage's result; the audit record's stage list (from the store) can.
  const stages = audit.stages && audit.stages.length ? audit.stages : report.stages || [];
  out.append(el("section", { class: "panel", "aria-labelledby": "stages-title" }, el("h2", { id: "stages-title" }, "Pipeline"), timeline(stages, null),
    stageErrors(stages)));
  const gaps = report.measurement_gaps || [];
  out.append(el("section", { class: "panel", "aria-labelledby": "limits-title" }, el("h2", { id: "limits-title" }, "Limitations"),
    el("ul", {}, (report.limitations || []).map((l) => el("li", {}, l))),
    gaps.length ? el("details", { class: "advanced" }, el("summary", {}, gaps.length + " checks could not conclude on a page"),
      el("p", { class: "muted small" }, "A limit of the measurement, not a finding about the page."),
      table(["Feature", "Page", "Reason"], gaps.map((g) => el("tr", {}, el("td", {}, el("a", { href: base + g.feature_id }, g.feature_id), " " + g.name), el("td", { class: "small mono" }, g.url || "(site)"), el("td", { class: "small" }, g.reason || ""))))) : null,
    el("p", { class: "muted small" }, report.disclaimer)));
  out.append(el("section", { class: "panel", "aria-labelledby": "meta-title" }, el("h2", { id: "meta-title" }, "Audit details"),
    kv([
      ["Requested options", el("span", { class: "mono small" }, jsonText(report.audit.options))],
      ["Pipeline version", el("span", { class: "mono small" }, report.pipeline.pipeline_version)],
      ["Catalog / scoring", el("span", { class: "mono small" }, "catalog v" + report.pipeline.catalog_version + ", scoring v" + report.pipeline.scoring_version)],
      ["Extraction", el("span", { class: "mono small" }, report.pipeline.extraction_version)],
      ["Crawler", el("span", { class: "mono small" }, jsonText(report.pipeline.crawl))],
      ["Generated", when(report.generated_at)],
    ])));
  return out;
}
function fact(k, v, n) { return el("div", { class: "fact" }, el("div", { class: "k" }, k), el("div", { class: "v" }, v), n ? el("div", { class: "n" }, n) : null); }
function applyBarWidths(root) {
  // Widths are set through the CSSOM (allowed by the style-src 'self' CSP), never markup.
  for (const span of root.querySelectorAll(".bar > span[data-w]")) span.style.width = Math.max(0, Math.min(1, Number(span.dataset.w))) * 100 + "%";
}
function stageErrors(stages) {
  const failed = stages.filter((s) => s.status === "failed" || s.status === "skipped");
  if (!failed.length) return null;
  return el("ul", { class: "small" }, failed.map((s) => el("li", {}, el("b", {}, STAGE_LABELS[s.name] || s.name), " " + s.status + ": ",
    s.status === "skipped" ? ((s.detail && s.detail.reason) || "") : (s.error_category || "") + (s.error_message ? " — " + s.error_message : ""))));
}

// features -------------------------------------------------------------------------------------------

async function featuresTab(audit, report, r) {
  const [catalog, data] = await Promise.all([getCatalog(), getFeatures(audit.audit_id)]);
  const merged = data.features.map((f) => ({ ...catalog.byId[f.feature_id], ...f, def: catalog.byId[f.feature_id] }));
  return explorer({
    items: merged,
    selected: r.sub,
    hrefFor: (id) => "#/audits/" + encodeURIComponent(audit.audit_id) + "/features/" + id,
    stateOf: featureState,
    stateLabel: RESULT_LABEL,
    filterKeys: ["result"],
    detail: (f) => featureDetail(f, true),
    intro: "Each feature's definition from the catalog next to what this audit measured. Results are per page unless the feature is site-wide.",
  });
}
function explorer(cfg) {
  const state = { q: "", cat: "", result: "", impl: "", level: "", sev: "" };
  const list = el("div", { class: "feature-list" });
  const detail = el("aside", { class: "panel detail", "aria-live": "polite", "aria-label": "Feature detail" });
  const count = el("span", { class: "result-count", role: "status" });
  const cats = [...new Set(cfg.items.map((f) => f.category))].sort();
  const sel = (id, label, options, key) => el("div", { class: "field" }, el("label", { for: id }, label),
    el("select", { id, onchange: (e) => { state[key] = e.target.value; draw(); } }, el("option", { value: "" }, "All"), options.map(([v, t]) => el("option", { value: v }, t))));
  const filters = el("div", { class: "filters" },
    el("div", { class: "field search" }, el("label", { for: "f-q" }, "Search"),
      el("input", { id: "f-q", type: "search", placeholder: "ID or name, for example F012 or canonical", oninput: (e) => { state.q = e.target.value.trim().toLowerCase(); draw(); } })),
    sel("f-cat", "Category", cats.map((c) => [c, c + " " + (CATEGORY_NAMES[c] || "")]), "cat"),
    cfg.filterKeys.includes("result") ? sel("f-res", "Result in this audit", Object.keys(RESULT_LABEL).map((k) => [k, RESULT_LABEL[k]]), "result") : null,
    sel("f-impl", "Implementation", [["IMPLEMENTED", "Implemented"], ["PARTIAL", "Partial"], ["PLANNED", "Planned"], ["UNAVAILABLE", "Unavailable"]], "impl"),
    sel("f-level", "Validation level", [["NOT_TESTED", "Not tested"], ["UNIT_TESTED", "Unit tested"], ["FIXTURE_VALIDATED", "Fixture validated"], ["PIPELINE_VALIDATED", "Pipeline validated"]], "level"),
    sel("f-sev", "Base severity", ["high", "medium", "low", "informational"].map((s) => [s, s]), "sev"),
    count);
  let current = cfg.selected && cfg.items.some((f) => f.feature_id === cfg.selected) ? cfg.selected : null;
  function matches(f) {
    const v = f.validation || (f.def && f.def.validation) || {};
    if (state.q && !(f.feature_id.toLowerCase().includes(state.q) || (f.name || "").toLowerCase().includes(state.q))) return false;
    if (state.cat && f.category !== state.cat) return false;
    if (state.result && cfg.stateOf(f) !== state.result) return false;
    if (state.impl && v.implementation_level !== state.impl) return false;
    if (state.level && v.validation_level !== state.level) return false;
    if (state.sev && f.base_severity !== state.sev) return false;
    return true;
  }
  function draw() {
    const shown = cfg.items.filter(matches);
    count.textContent = shown.length + " of " + cfg.items.length + " features";
    list.replaceChildren(...(shown.length ? shown.map((f) => {
      const st = cfg.stateOf(f);
      return el("button", { class: "row", type: "button", "aria-pressed": f.feature_id === current ? "true" : "false",
        onclick: () => { current = f.feature_id; history.replaceState(null, "", cfg.hrefFor(f.feature_id)); draw(); showDetail(); if (window.innerWidth < 1100) detail.scrollIntoView({ behavior: "smooth", block: "start" }); } },
        el("span", { class: "fid" }, f.feature_id),
        el("span", { class: "nm" }, f.name, el("span", { class: "sub" }, (CATEGORY_NAMES[f.category] || f.category))),
        el("span", { class: "badges" }, pill(st, cfg.stateLabel[st])));
    }) : [el("div", { class: "empty" }, el("p", {}, "No feature matches these filters."))]));
  }
  function showDetail() {
    const f = cfg.items.find((x) => x.feature_id === current);
    detail.replaceChildren(f ? cfg.detail(f) : el("div", { class: "empty" }, el("p", {}, "Select a feature to see its definition and evidence.")));
  }
  draw(); showDetail();
  return el("div", {}, el("p", { class: "muted small" }, cfg.intro), filters, el("div", { class: "explorer" }, list, detail));
}
function featureDetail(f, withResults) {
  const d = f.def || f;
  const v = d.validation || {};
  const node = el("div", {},
    el("div", { class: "fid" }, f.feature_id + " · " + (CATEGORY_NAMES[d.category] || d.category)),
    el("h2", {}, d.name),
    el("p", {}, d.description),
    el("p", { class: "muted small" }, d.rationale),
    el("div", { class: "linklist" },
      el("span", { class: "tag" }, "Implementation: " + (v.implementation_level || d.implementation_status)),
      el("span", { class: "tag" }, "Validation: " + (v.validation_level || "unknown").replace(/_/g, " ").toLowerCase()),
      v.disposition_code ? el("span", { class: "tag" }, "Disposition: " + v.disposition_code.replace(/_/g, " ").toLowerCase()) : null,
      el("span", { class: "tag" }, d.scored ? "Scored" : "Not scored"),
      d.is_heuristic ? el("span", { class: "tag" }, "Heuristic") : null,
      d.intent_dependent ? el("span", { class: "tag" }, "Owner setting (notice)") : null),
    kv([
      ["Measures", d.measurement],
      ["Method", d.method],
      ["Applies to", d.applicability],
      ["Scope", d.scope],
      ["Base severity", sev(d.base_severity)],
      ["Thresholds", Object.keys(d.config_defaults || {}).length ? el("span", { class: "mono small" }, Object.entries(d.config_defaults).map(([k, val]) => k + " = " + jsonText(val)).join("; ")) : "none"],
      ["Threshold basis", v.threshold_basis],
      ["Claim strength", v.claim_strength],
      ["Blocked by", (d.blocked_by || []).join(" ")],
    ]),
    (d.limitations || []).length ? el("div", {}, el("h4", {}, "Limitations"), el("ul", { class: "small" }, d.limitations.map((l) => el("li", {}, l)))) : null);
  if (withResults && f.result_count != null) {
    const contrib = f.scored ? (f.contributes ? "Counts toward the score" : "Excluded from the aggregate" + (f.exclusion_reason ? ": " + f.exclusion_reason : "")) : "Informational only (not scored)";
    node.append(el("hr"), el("h3", {}, "In this audit"),
      kv([
        ["Result", pill(featureState(f))],
        ["Units", f.passed + " passed, " + f.failed + " failed, " + f.warned + " warnings, " + f.not_measured + " not measured, " + f.not_applicable + " not applicable" + (f.errors ? ", " + f.errors + " errors" : "")],
        ["Pass rate", f.pass_rate == null ? "not measured" : pct(f.pass_rate)],
        ["Score contribution", contrib],
      ]));
    if (f.results && f.results.length) {
      node.append(table(["Page", "Result", "Observed", "Expected"], f.results.map((x) => el("tr", {},
        el("td", { class: "small mono" }, x.url ? extLink(x.url, x.url.replace(/^https?:\/\//, "")) : "(site)"),
        el("td", {}, pill(x.status), x.explanation ? el("div", { class: "small muted" }, x.explanation) : null),
        el("td", { class: "value-cell" }, jsonText(x.observed_value)),
        el("td", { class: "value-cell" }, jsonText(x.expected_value)))), { caption: "Results per page" }));
      const ev = f.results.flatMap((x) => x.evidence || []).slice(0, 8);
      if (ev.length) node.append(el("h4", {}, "Evidence"), evidenceList(ev));
      if (f.result_count > f.results.length) node.append(el("p", { class: "muted small" }, "Showing " + f.results.length + " of " + f.result_count + " results; the JSON report holds the rest."));
    } else if (d.implementation_status === "planned" || d.implementation_status === "unavailable") {
      node.append(callout("info", el("p", {}, "This feature is not implemented, so it was not measured. It never counts as a pass or a failure.")));
    }
  }
  if (d.remediation) node.append(el("h4", {}, "Typical remediation"), el("p", { class: "small" }, d.remediation));
  return node;
}
function evidenceList(items) {
  return el("ul", { class: "evidence-list" }, items.map((e) => el("li", {},
    el("div", { class: "src" }, extLink(e.source_url), " ", el("span", {}, "(" + e.source_type + (e.chunk_id ? ", chunk " + e.chunk_id + ", characters " + e.char_start + "–" + e.char_end : "") + ")")),
    el("blockquote", { class: "evidence" }, e.snippet))));
}

// findings -------------------------------------------------------------------------------------------

function findingsTab(audit, report, r) {
  if (!report.findings_available) return callout("info", el("p", {}, "Findings are not available for this audit: the stages that produce or validate them did not complete. See the Overview for stage results."));
  const all = report.findings;
  if (!all.length) return el("div", { class: "panel empty" }, el("p", {}, "No findings: every measured check passed or could not conclude. Check the Overview for what was not measured."));
  const want = r.params.get("ids") ? new Set(r.params.get("ids").split(",")) : null;
  const state = { sev: "", kind: "", scored: "", q: "" };
  const list = el("div", {});
  const count = el("span", { class: "result-count", role: "status" });
  const sel = (id, label, opts, key) => el("div", { class: "field" }, el("label", { for: id }, label), el("select", { id, onchange: (e) => { state[key] = e.target.value; draw(); } }, el("option", { value: "" }, "All"), opts.map(([v, t]) => el("option", { value: v }, t))));
  const order = { critical: 0, high: 1, medium: 2, low: 3, informational: 4 };
  const sorted = [...all].sort((a, b) => (order[a.finding.severity] - order[b.finding.severity]) || a.finding.title.localeCompare(b.finding.title));
  function draw() {
    const shown = sorted.filter((rf) => {
      const f = rf.finding;
      if (want && !want.has(f.finding_id)) return false;
      if (state.sev && f.severity !== state.sev) return false;
      if (state.kind && rf.kind !== state.kind) return false;
      if (state.scored === "yes" && !rf.contributes_to_score) return false;
      if (state.scored === "no" && rf.contributes_to_score) return false;
      if (state.q && !(f.title + " " + (f.feature_ids || []).join(" ")).toLowerCase().includes(state.q)) return false;
      return true;
    });
    count.textContent = shown.length + " of " + all.length + " findings";
    list.replaceChildren(...(shown.length ? shown.map(findingItem) : [el("div", { class: "panel empty" }, el("p", {}, "No finding matches these filters."))]));
  }
  draw();
  return el("div", {},
    want ? callout("info", el("p", {}, "Showing the findings linked to one recommendation. ", el("a", { href: "#/audits/" + encodeURIComponent(audit.audit_id) + "/findings" }, "Show all findings"))) : null,
    el("div", { class: "filters" },
      el("div", { class: "field search" }, el("label", { for: "fd-q" }, "Search"), el("input", { id: "fd-q", type: "search", placeholder: "Title or feature ID", oninput: (e) => { state.q = e.target.value.trim().toLowerCase(); draw(); } })),
      sel("fd-sev", "Severity", ["critical", "high", "medium", "low", "informational"].map((s) => [s, s]), "sev"),
      sel("fd-kind", "Type", [["defect", "Measured defect"], ["notice", "Owner setting to confirm"]], "kind"),
      sel("fd-scored", "Score", [["yes", "Counts toward the score"], ["no", "Does not count"]], "scored"),
      count),
    list);
}
function findingItem(rf) {
  const f = rf.finding;
  const basis = { measured: "Measured", heuristic: "Heuristic", model_judgement: "Model judgement" }[f.basis] || f.basis;
  return el("details", { class: "item", id: "finding-" + f.finding_id },
    el("summary", {}, sev(f.severity),
      el("span", {}, el("span", { class: "title" }, f.title), el("span", { class: "sub" }, (f.feature_ids || []).join(", ") + " · " + rf.affected_urls.length + " page" + (rf.affected_urls.length === 1 ? "" : "s"))),
      el("span", { class: "badges" }, rf.kind === "notice" ? pill("notice", "Confirm setting") : null, f.basis === "heuristic" ? el("span", { class: "tag" }, "Heuristic") : null)),
    el("div", { class: "body" },
      el("p", {}, f.description),
      kv([
        ["Basis", basis],
        ["Confidence", fmtNum(f.confidence, 2) + " (how sure the measurement is, not how serious the issue is)"],
        ["Method", f.measurement_method],
        ["Score", rf.contributes_to_score ? "Counts toward the score" : "Does not count toward the score"],
        rf.kind === "notice" ? ["Note", "This reflects a setting the site owner controls. Confirm it is intended before changing it."] : null,
      ]),
      rf.measurements.length ? table(["Page", "Result", "Observed", "Expected", "Why"], rf.measurements.map((m) => el("tr", {},
        el("td", { class: "small mono" }, m.url ? extLink(m.url, m.url.replace(/^https?:\/\//, "")) : "(site)"),
        el("td", {}, pill(m.status)), el("td", { class: "value-cell" }, jsonText(m.observed_value)), el("td", { class: "value-cell" }, jsonText(m.expected_value)),
        el("td", { class: "small" }, m.explanation || ""))), { caption: "Measurements" }) : null,
      rf.evidence.length ? el("div", {}, el("h4", {}, "Evidence"), evidenceList(rf.evidence)) : null,
      (f.verification_criteria || []).length ? el("div", {}, el("h4", {}, "How to verify"), el("ul", { class: "small" }, f.verification_criteria.map((x) => el("li", {}, x)))) : null,
      (f.limitations || []).length ? el("div", {}, el("h4", {}, "Limitations"), el("ul", { class: "small" }, f.limitations.map((x) => el("li", {}, x)))) : null));
}

// recommendations ------------------------------------------------------------------------------------

function recommendationsTab(audit, report) {
  if (!report.recommendations_validated || !report.recommendations) return callout("info", el("p", {}, "No validated recommendations exist for this audit. Recommendations appear only when the findings they rely on passed the output checks."));
  const recs = report.recommendations.recommendations;
  const rejected = report.recommendations.rejected || [];
  const base = "#/audits/" + encodeURIComponent(audit.audit_id) + "/findings?ids=";
  const impact = { positive: "Expected to help", neutral: "Neutral", negative: "Could hurt", uncertain: "Effect on AI visibility uncertain" };
  return el("div", {},
    el("p", { class: "muted small" }, "Recommendations come from fixed templates tied to measured findings. Priority and effort follow documented rules. None of them guarantees a ranking or a citation."),
    recs.length ? recs.map((r) => el("details", { class: "item" },
      el("summary", {}, el("span", {}, el("span", { class: "prio", "data-p": r.priority }, r.priority)),
        el("span", {}, el("span", { class: "title" }, r.title), el("span", { class: "sub" }, "Effort " + r.estimated_effort + " · " + (impact[r.expected_impact_direction] || r.expected_impact_direction))),
        el("span", { class: "badges" }, el("span", { class: "tag" }, r.finding_ids.length + " finding" + (r.finding_ids.length === 1 ? "" : "s")))),
      el("div", { class: "body" },
        el("h4", {}, "Proposed change"), el("p", {}, r.proposed_change),
        el("h4", {}, "Why"), el("p", { class: "small" }, r.rationale),
        kv([["Priority", r.priority], ["Effort", r.estimated_effort], ["Expected impact", impact[r.expected_impact_direction] || r.expected_impact_direction], ["Confidence", fmtNum(r.confidence, 2)],
          ["Related findings", el("a", { href: base + r.finding_ids.map(encodeURIComponent).join(",") }, "Open " + r.finding_ids.length + " linked finding" + (r.finding_ids.length === 1 ? "" : "s"))]]),
        el("h4", {}, "How to verify"), el("ul", { class: "small" }, r.verification_plan.map((v) => el("li", {}, v)))))) : el("div", { class: "panel empty" }, el("p", {}, "No recommendations were issued.")),
    rejected.length ? callout("warn", el("p", {}, rejected.length + " recommendation" + (rejected.length === 1 ? " was" : "s were") + " held back because claim validation found wording the evidence does not support.")) : null,
    (report.recommendations.notes || []).length ? el("ul", { class: "small muted" }, report.recommendations.notes.map((n) => el("li", {}, n))) : null);
}

// crawl and network ----------------------------------------------------------------------------------

function crawlTab(report) {
  const c = report.crawl || {};
  const n = report.network;
  const out = el("div", { class: "stack" });
  out.append(el("section", { class: "panel" }, el("h2", {}, "Crawl"),
    kv([
      ["Stop reason", (c.stop_reason || "—").replace(/_/g, " ")],
      ["Fetches", c.fetch_count],
      ["Skipped URLs", c.skipped_count],
      ["Blocked by robots.txt", c.robots_skipped],
      ["Truncated responses", c.truncated_bodies],
      ["Truncated documents", c.truncated_documents],
      ["Limits", c.max_pages != null ? c.max_pages + " pages, depth " + c.max_depth + (c.respect_robots ? ", robots.txt respected" : ", robots.txt not applied") : null],
      ["User agent", c.user_agent ? el("span", { class: "mono small" }, c.user_agent) : null],
    ]),
    el("p", { class: "muted small" }, "The crawler reads the HTML each URL returns. It does not run JavaScript, so content a script adds later is not seen.")));
  if (n) {
    out.append(el("section", { class: "panel" }, el("h2", {}, "Network"),
      kv([
        ["Fetches", n.fetches + " (" + n.fetches_ok + " successful)"],
        ["Redirect hops", n.redirects],
        ["Bytes stored", n.bytes_stored.toLocaleString("en")],
        ["HTTP status codes", Object.keys(n.status_codes).length ? Object.entries(n.status_codes).map(([k, v]) => k + " × " + v).join(", ") : "none"],
        ["Transport errors", Object.keys(n.errors_by_type).length ? Object.entries(n.errors_by_type).map(([k, v]) => k + " × " + v).join(", ") : "none"],
      ]),
      table(["Timing", { label: "Measured", num: true }, { label: "Not measured", num: true }, { label: "p50", num: true }, { label: "p95", num: true }, { label: "max", num: true }],
        Object.entries(n.timings).map(([k, t]) => el("tr", {}, el("td", { class: "mono small" }, k.replace(/_ms$/, "")), el("td", { class: "num" }, t.measured), el("td", { class: "num" }, t.not_measured),
          ...["p50_ms", "p95_ms", "max_ms"].map((q) => el("td", { class: "num mono small" }, t[q] == null ? "not measured" : t[q].toFixed(1) + " ms")))), { caption: "Fetch timings" }),
      el("p", { class: "muted small" }, n.note)));
  } else out.append(callout("info", el("p", {}, "No network measurements: nothing was fetched.")));
  const pages = report.pages || [];
  out.append(el("section", { class: "panel" }, el("h2", {}, "Pages audited (" + pages.length + ")"),
    pages.length ? el("ul", { class: "small mono" }, pages.map((p) => el("li", {}, extLink(p)))) : el("p", { class: "muted" }, "No page was fetched successfully.")));
  return out;
}

// retrieval and agent --------------------------------------------------------------------------------

function retrievalTab(audit, report) {
  const rt = report.retrieval || {};
  const ag = report.agent || {};
  const st = Object.fromEntries((report.stages || []).map((s) => [s.name, s]));
  const chunk = st.chunk && st.chunk.detail ? st.chunk.detail.chunks : null;
  const agentStatus = { not_requested: "Not requested", disabled: "Disabled on this server", unavailable: "Requested but unavailable", completed: "Ran and passed validation", incomplete: "Ran but did not finish", failed: "Ran and failed" };
  return el("div", { class: "grid-2" },
    el("section", { class: "panel" }, el("h2", {}, "Retrieval"),
      kv([
        ["Requested mode", rt.requested || audit.options.retrieval],
        ["Status", rt.status ? pill(rt.status === "ok" ? "ok" : rt.status === "skipped" ? "skipped" : "error", rt.status) : null],
        ["Mode used", rt.mode],
        ["Semantic embeddings", rt.semantic ? "yes" : "no"],
        ["Embedder", rt.embedder ? el("span", { class: "mono small" }, jsonText(rt.embedder)) : (rt.status === "ok" ? "none (lexical)" : null)],
        ["Chunks indexed", chunk],
        ["Stage note", st.retrieval && st.retrieval.status === "skipped" ? (st.retrieval.detail || {}).reason : (st.retrieval && st.retrieval.error_message)],
      ]),
      el("p", { class: "muted small" }, "Retrieval only attaches supporting passages to findings. A similarity score is not evidence that a page is correct, and lexical results are never substituted for a semantic request.")),
    el("section", { class: "panel" }, el("h2", {}, "LLM agent"),
      kv([
        ["Requested", audit.options.use_agent ? "yes" : "no"],
        ["Outcome", agentStatus[ag.status] || ag.status],
        ["Model", ag.model_id ? el("span", { class: "mono small" }, ag.model_id) : null],
        ["Iterations used", ag.iterations_used],
        ["Steps", ag.steps],
        ["Evidence valid", ag.evidence_valid == null ? null : (ag.evidence_valid ? "yes" : "no")],
        ["Output valid", ag.output_valid == null ? null : (ag.output_valid ? "yes" : "no")],
        ["Reason", ag.reason],
      ]),
      el("p", { class: "muted small" }, "The agent is optional and read-only. It can call six fixed tools over this audit's data. It cannot change measurements, findings, scores or the recommendations in this report, which come from the deterministic pipeline.")));
}

// report ------------------------------------------------------------------------------------------------

function reportTab(audit) {
  const id = encodeURIComponent(audit.audit_id);
  return el("section", { class: "panel" }, el("h2", {}, "Report"),
    el("p", {}, "The report is built from this audit's stored results: scores and coverage, pipeline stages, network measurements, findings with evidence, recommendations, what was not measured, and the limitations."),
    el("div", { class: "actions" },
      el("a", { class: "btn", href: apiUrl("/api/v1/audits/" + id + "/report.html"), target: "_blank", rel: "noopener" }, "Open HTML report"),
      el("a", { class: "btn secondary", href: apiUrl("/api/v1/audits/" + id + "/report.html?download=true") }, "Download HTML"),
      el("a", { class: "btn secondary", href: apiUrl("/api/v1/audits/" + id + "/report?download=true") }, "Download JSON")),
    el("p", { class: "muted small" }, "The JSON file is the complete machine-readable record, including every feature's score entry."));
}

// comparison ----------------------------------------------------------------------------------------------

async function compareTab(audit) {
  if (audit.status !== "completed") return callout("info", el("p", {}, "Only completed audits can be compared."));
  const { audits } = await api("/api/v1/audits?limit=100");
  const others = audits.filter((a) => a.normalized_url === audit.normalized_url && a.audit_id !== audit.audit_id && a.status === "completed");
  if (!others.length) return el("div", { class: "panel empty" }, el("p", {}, "A comparison needs another completed audit of the same URL. Run a new audit after changing the site."));
  return comparePicker([audit, ...others], audit.audit_id);
}
async function renderCompare(mount, gen) {
  const { audits } = await api("/api/v1/audits?limit=100");
  const groups = {};
  for (const a of audits) if (a.status === "completed") (groups[a.normalized_url] = groups[a.normalized_url] || []).push(a);
  const usable = Object.entries(groups).filter(([, list]) => list.length > 1);
  const head = el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Compare audits"), el("p", {}, "Compare two completed audits of the same URL. Differences are observations; they do not prove that a change to the site caused them.")));
  if (!usable.length) { mount(el("div", {}, head, el("div", { class: "panel empty" }, el("p", {}, "No URL has two completed audits yet."), el("a", { class: "btn", href: "#/" }, "Start an audit"))), "Compare"); return; }
  const target = el("div", {});
  const urlSel = el("select", { id: "cmp-url", onchange: () => target.replaceChildren(comparePicker(groups[urlSel.value], null)) }, usable.map(([u]) => el("option", { value: u }, u)));
  target.append(comparePicker(groups[usable[0][0]], null));
  mount(el("div", {}, head, el("div", { class: "panel" }, el("div", { class: "field" }, el("label", { for: "cmp-url" }, "URL"), urlSel)), target), "Compare");
}
function comparePicker(list, fixed) {
  const sorted = [...list].sort((a, b) => a.created_at.localeCompare(b.created_at));
  const label = (a) => when(a.created_at) + " — " + a.audit_id;
  const before = el("select", { id: "cmp-before" }, sorted.map((a, i) => el("option", { value: a.audit_id, selected: i === Math.max(0, sorted.length - 2) }, label(a))));
  const after = el("select", { id: "cmp-after" }, sorted.map((a, i) => el("option", { value: a.audit_id, selected: i === sorted.length - 1 }, label(a))));
  if (fixed) { for (const o of after.options) o.selected = o.value === fixed; const idx = sorted.findIndex((a) => a.audit_id === fixed); for (const o of before.options) o.selected = o.value === sorted[idx === 0 ? 1 : idx - 1].audit_id; }
  const result = el("div", {});
  const button = el("button", { class: "btn", type: "button" }, "Compare");
  button.addEventListener("click", async () => {
    if (before.value === after.value) { result.replaceChildren(callout("warn", el("p", {}, "Choose two different audits."))); return; }
    let [b, a] = [before.value, after.value];
    const t = Object.fromEntries(sorted.map((x) => [x.audit_id, x.created_at]));
    if (t[b] > t[a]) [b, a] = [a, b];
    button.disabled = true; result.replaceChildren(loading("Comparing…"));
    try {
      result.replaceChildren(comparisonView(await api("/api/v1/comparisons", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ before_audit_id: b, after_audit_id: a }) })));
    } catch (e) { result.replaceChildren(callout("fail", el("p", {}, e.message))); }
    finally { button.disabled = false; }
  });
  return el("div", { class: "stack" }, el("div", { class: "panel" }, el("div", { class: "field-row" },
    el("div", { class: "field" }, el("label", { for: "cmp-before" }, "Earlier audit"), before),
    el("div", { class: "field" }, el("label", { for: "cmp-after" }, "Later audit"), after),
    el("div", { class: "field" }, el("span", { class: "label", "aria-hidden": "true" }, " "), button))), result);
}
function deltaRow(d) {
  const show = (v) => (v == null ? "not reported" : Math.round(v * 100) + "");
  return el("tr", {}, el("td", {}, d.name), el("td", { class: "num mono" }, show(d.before)), el("td", { class: "num mono" }, show(d.after)),
    el("td", { class: "num mono" }, d.delta == null ? "—" : (d.delta > 0 ? "+" : "") + Math.round(d.delta * 100)), el("td", { class: "small muted" }, d.note || ""));
}
function comparisonView(c) {
  const findings = (title, items) => el("div", {}, el("h3", {}, title + " (" + items.length + ")"),
    items.length ? el("ul", { class: "small" }, items.map((f) => el("li", {}, f.title, " ", el("span", { class: "muted" }, "(" + (f.severity_after || f.severity_before || "") + ", " + f.affected_before + " → " + f.affected_after + " pages)")))) : el("p", { class: "muted small" }, "None."));
  const recStatus = { no_longer_failing: "No longer failing", still_failing: "Still failing", not_measured: "Not measured" };
  return el("div", { class: "stack" },
    callout(c.reliability === "comparable" ? "info" : "warn", el("p", {}, el("b", {}, c.reliability === "comparable" ? "Comparable. " : "Reduced reliability. "), c.statement),
      c.caveats.length ? el("ul", {}, c.caveats.map((x) => el("li", {}, x))) : null, c.notes.length ? el("p", { class: "small" }, c.notes.join(" ")) : null),
    el("section", { class: "panel" }, el("h2", {}, "Scores and coverage"),
      table(["", { label: "Earlier", num: true }, { label: "Later", num: true }, { label: "Change", num: true }, "Note"], [c.overall, ...c.categories, ...c.coverage].map(deltaRow), { caption: "Score and coverage changes (out of 100)" }),
      el("p", { class: "muted small" }, "Values are out of 100. A score that was withheld on either side has no change.")),
    c.features_changed.length ? el("section", { class: "panel" }, el("h2", {}, "Features whose results changed (" + c.features_changed.length + ")"),
      table(["Feature", { label: "Earlier pass rate", num: true }, { label: "Later pass rate", num: true }, { label: "Change", num: true }, "Note"], c.features_changed.map((d) => deltaRow({ ...d, name: d.key + " " + d.name })))) : null,
    el("section", { class: "panel grid-2" }, findings("New findings", c.findings_new), findings("Resolved findings", c.findings_resolved)),
    el("section", { class: "panel" }, findings("Findings in both audits", c.findings_persistent)),
    el("section", { class: "panel" }, el("h2", {}, "Earlier recommendations, checked in the later audit"),
      c.recommendations.length ? el("ul", { class: "small" }, c.recommendations.map((r) => el("li", {}, el("b", {}, recStatus[r.status] || r.status), " — " + r.title + ". " + r.detail))) : el("p", { class: "muted small" }, "None.")));
}

// --- catalog explorer -----------------------------------------------------------------------------------

async function renderCatalog(mount, gen, r) {
  const catalog = await getCatalog();
  const implState = (f) => ({ implemented: "implemented", partial: "partial", planned: "planned", unavailable: "unavailable" })[f.implementation_status];
  const labels = { implemented: "Implemented", partial: "Partially implemented", planned: "Planned (not measured)", unavailable: "Needs unavailable data" };
  const levels = {};
  for (const f of catalog.features) { const l = (f.validation || {}).validation_level || "unknown"; levels[l] = (levels[l] || 0) + 1; }
  const impl = {};
  for (const f of catalog.features) impl[f.implementation_status] = (impl[f.implementation_status] || 0) + 1;
  const ex = explorer({
    items: catalog.features, selected: r.sub,
    hrefFor: (id) => "#/catalog/" + id,
    stateOf: implState, stateLabel: labels, filterKeys: [],
    detail: (f) => featureDetail(f, false),
    intro: "The definition of every feature, independent of any audit. Validation levels come from the repository's validation matrix (docs/validation/feature_validation_matrix.csv).",
  });
  mount(el("div", {},
    el("div", { class: "page-head" }, el("div", {}, el("h1", {}, "Feature catalog"), el("p", {}, "120 features in 12 categories, catalog version " + catalog.version + ". What each one measures, how, and how far its implementation has been validated."))),
    el("div", { class: "facts" },
      fact("Implemented", String(impl.implemented || 0), "fully implemented checks"),
      fact("Partial", String(impl.partial || 0), "implemented with stated limits"),
      fact("Planned or unavailable", String((impl.planned || 0) + (impl.unavailable || 0)), "never measured, never scored"),
      fact("Pipeline validated", String(levels.PIPELINE_VALIDATED || 0), "fixture expectations met through the app and API")),
    el("section", { class: "panel section", "aria-labelledby": "cat-ledger" }, el("div", { class: "panel-head" }, el("h2", { id: "cat-ledger" }, "Implementation ledger"), el("span", { class: "small muted" }, "No feature has been validated on labelled real pages or shown to change AI-search outcomes.")),
      ledger(catalog.features, { label: "Implementation status of all features", state: implState, labels, href: (f) => "#/catalog/" + f.feature_id }),
      legend(["implemented", "partial", "planned", "unavailable"], labels)),
    el("section", { class: "section" }, el("h2", {}, "Explore features"), ex)), "Feature catalog");
}

// --- shell -------------------------------------------------------------------------------------------------

function closeMenu() { const rail = $("rail"); if (rail) rail.dataset.open = "false"; const t = $("menu-toggle"); if (t) t.setAttribute("aria-expanded", "false"); }
function setupShell() {
  const toggle = $("menu-toggle");
  toggle.addEventListener("click", () => {
    const open = $("rail").dataset.open !== "true";
    $("rail").dataset.open = String(open); toggle.setAttribute("aria-expanded", String(open));
    if (open) $("rail").querySelector("a").focus();
  });
  document.addEventListener("keydown", (e) => { if (e.key === "Escape") closeMenu(); });
  window.addEventListener("hashchange", () => { route(); $("main").focus({ preventScroll: true }); window.scrollTo(0, 0); });
}
async function checkBackend() {
  const tag = $("backend");
  try {
    await api("/api/v1/health", { timeout: 6000 });
    tag.dataset.state = "ok"; tag.textContent = API_BASE ? "Backend: " + API_BASE.replace(/^https?:\/\//, "") : "Backend connected";
  } catch (_) { tag.dataset.state = "down"; tag.textContent = "Backend unreachable"; }
}
setupShell();
checkBackend();
route();

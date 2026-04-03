#!/usr/bin/env python3
"""Export current session capture data into a standalone offline HTML."""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from html import escape
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import urlopen


def fetch_json(url: str) -> Any:
    try:
        with urlopen(url, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except HTTPError as exc:
        raise RuntimeError(f"HTTP error {exc.code} for {url}") from exc
    except URLError as exc:
        raise RuntimeError(f"Network error for {url}: {exc}") from exc


def build_payload(api_url: str, max_traces: int) -> dict[str, Any]:
    base = api_url.rstrip("/")
    timeline = fetch_json(f"{base}/api/timeline")
    if not isinstance(timeline, list):
        raise RuntimeError("invalid timeline payload")

    selected = timeline[: max(0, max_traces)]
    traces: dict[str, Any] = {}
    for item in selected:
        trace_id = str(item.get("trace_id", ""))
        if not trace_id:
            continue
        trace = fetch_json(f"{base}/api/trace/{trace_id}")
        traces[trace_id] = trace

    return {"timeline": selected, "traces": traces}


def load_web_assets() -> tuple[str, str]:
    script_dir = Path(__file__).resolve().parent
    web_dir = script_dir / "capture_tool" / "tools" / "context_capture" / "web"
    index_html = (web_dir / "index.html").read_text(encoding="utf-8")
    app_js = (web_dir / "app.js").read_text(encoding="utf-8")
    return index_html, app_js


def make_offline_app_js(app_js: str) -> str:
    fetch_json_src = """async function fetchJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}
"""
    fetch_json_offline = """async function fetchJson(url) {
  const data = window.__OFFLINE_CAPTURE_EXPORT__?.payload || { timeline: [], traces: {} };
  const parsed = new URL(url, window.location.href);
  const path = parsed.pathname;

  if (path === "/api/timeline") {
    return JSON.parse(JSON.stringify(data.timeline || []));
  }
  if (path.startsWith("/api/trace/")) {
    const traceId = decodeURIComponent(path.slice("/api/trace/".length));
    const trace = data.traces && Object.prototype.hasOwnProperty.call(data.traces, traceId)
      ? data.traces[traceId]
      : null;
    if (trace == null) throw new Error("404");
    return JSON.parse(JSON.stringify(trace));
  }

  throw new Error(`offline unsupported: ${path}`);
}
"""
    post_json_src = """async function postJson(url) {
  const r = await fetch(url, { method: "POST" });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}
"""
    post_json_offline = """async function postJson(url) {
  throw new Error(`offline read-only: ${url}`);
}
"""
    patched = app_js.replace(fetch_json_src, fetch_json_offline)
    patched = patched.replace(post_json_src, post_json_offline)
    init_src = "void loadTimelineAndSelect();"
    init_offline = """(() => {
  const payload = window.__OFFLINE_CAPTURE_EXPORT__?.payload || { timeline: [], traces: {} };
  state.timeline = Array.isArray(payload.timeline) ? JSON.parse(JSON.stringify(payload.timeline)) : [];
  const visible = buildVisibleTimeline(state.timeline);
  state.visibleTimeline = visible.list;
  state.filterNote = visible.note;
  state.traceCache = JSON.parse(JSON.stringify(payload.traces || {}));
  state.showAllMode = false;
  state.allTraces = [];
  if (state.visibleTimeline.length > 0) {
    state.selectedTraceId = String(state.visibleTimeline[0].trace_id);
    state.selectedTrace = state.traceCache[state.selectedTraceId] || null;
  } else {
    state.selectedTraceId = null;
    state.selectedTrace = null;
  }
  setHidden("error-state", true);
  renderAll();
})();"""
    patched = patched.replace(init_src, init_offline)
    return patched


def html_template(title: str, payload: dict[str, Any]) -> str:
    index_html, app_js = load_web_assets()
    app_js = make_offline_app_js(app_js)
    safe_title = escape(title)
    exported_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    data_json = json.dumps(payload, ensure_ascii=False)

    offline_bootstrap = f"""
    <script>
      window.__OFFLINE_CAPTURE_EXPORT__ = {{
        title: {json.dumps(title, ensure_ascii=False)},
        exportedAt: {json.dumps(exported_at, ensure_ascii=False)},
        payload: {data_json}
      }};
    </script>
    <script>
{app_js}
    </script>
    <script>
      document.addEventListener("DOMContentLoaded", () => {{
        document.title = window.__OFFLINE_CAPTURE_EXPORT__.title;
        const h1 = document.querySelector(".toolbar h1");
        if (h1) h1.textContent = window.__OFFLINE_CAPTURE_EXPORT__.title;
        const lastRefresh = document.getElementById("last-refresh-time");
        if (lastRefresh) lastRefresh.textContent = "离线导出: " + window.__OFFLINE_CAPTURE_EXPORT__.exportedAt;
        const clearBtn = document.getElementById("clear-capture-button");
        if (clearBtn) {{
          clearBtn.disabled = true;
          clearBtn.title = "离线导出为只读视图";
        }}
        const refreshBtn = document.getElementById("refresh-button");
        if (refreshBtn) {{
          refreshBtn.textContent = "离线视图";
          refreshBtn.title = "当前页面已内嵌全部数据";
        }}
      }});
    </script>
"""

    html = index_html.replace("<title>OpenClaw 会话抓包分析</title>", f"<title>{safe_title}</title>")
    html = html.replace('<script src="/web/app.js"></script>', offline_bootstrap)
    return html


def main() -> int:
    parser = argparse.ArgumentParser(description="Export session capture into offline HTML")
    parser.add_argument("--api-url", default="http://127.0.0.1:8000", help="Capture API base URL")
    parser.add_argument("--output", required=True, help="Output HTML file path")
    parser.add_argument("--title", default="OpenClaw Session Capture Offline Report", help="Report title")
    parser.add_argument("--max-traces", type=int, default=200, help="Max traces to include")
    args = parser.parse_args()

    payload = build_payload(args.api_url, args.max_traces)
    html = html_template(args.title, payload)
    output_path = Path(args.output)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(html, encoding="utf-8")
    print(str(output_path))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

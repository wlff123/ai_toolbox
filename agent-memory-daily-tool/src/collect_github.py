import json
import os
import urllib.parse
import urllib.request
from datetime import date
from typing import Any

from src.time_window import ReportWindow


GITHUB_API = "https://api.github.com"


def build_search_query(repo_full_name: str, target_date: date) -> str:
    day = target_date.isoformat()
    return f"repo:{repo_full_name} is:pr is:merged merged:{day}..{day}"


def build_window_search_query(repo_full_name: str, window: ReportWindow) -> str:
    start_day = window.start_utc.date().isoformat()
    end_day = window.end_utc.date().isoformat()
    return f"repo:{repo_full_name} is:pr is:merged merged:{start_day}..{end_day}"


def _github_request(url: str, token: str | None = None) -> dict[str, Any] | list[Any]:
    request = urllib.request.Request(url)
    request.add_header("Accept", "application/vnd.github+json")
    request.add_header("X-GitHub-Api-Version", "2022-11-28")
    request.add_header("User-Agent", "agent-memory-daily/0.1")
    if token:
        request.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.loads(response.read().decode("utf-8"))


def search_merged_prs(repo_full_name: str, target_date: date, token: str | None = None) -> list[dict[str, Any]]:
    query = urllib.parse.quote(build_search_query(repo_full_name, target_date))
    url = f"{GITHUB_API}/search/issues?q={query}&per_page=50"
    payload = _github_request(url, token or os.getenv("GITHUB_TOKEN"))
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub search response was not an object")
    return parse_github_search_result(repo_full_name, payload)


def search_merged_prs_for_window(
    repo_full_name: str,
    window: ReportWindow,
    token: str | None = None,
) -> list[dict[str, Any]]:
    query = urllib.parse.quote(build_window_search_query(repo_full_name, window))
    url = f"{GITHUB_API}/search/issues?q={query}&per_page=50"
    payload = _github_request(url, token or os.getenv("GITHUB_TOKEN"))
    if not isinstance(payload, dict):
        raise RuntimeError("GitHub search response was not an object")
    prs = parse_github_search_result(repo_full_name, payload)
    return [pr for pr in prs if _within_window(pr.get("merged_at", ""), window)]


def fetch_pr_files(repo_full_name: str, number: int, token: str | None = None) -> list[str]:
    url = f"{GITHUB_API}/repos/{repo_full_name}/pulls/{number}/files?per_page=100"
    payload = _github_request(url, token or os.getenv("GITHUB_TOKEN"))
    if not isinstance(payload, list):
        raise RuntimeError("GitHub pull files response was not a list")
    return [item.get("filename", "") for item in payload if item.get("filename")]


def parse_github_search_result(repo_full_name: str, payload: dict[str, Any]) -> list[dict[str, Any]]:
    prs = []
    for item in payload.get("items", []):
        prs.append(
            {
                "repo": repo_full_name,
                "number": item.get("number"),
                "title": item.get("title", ""),
                "url": item.get("html_url", ""),
                "author": (item.get("user") or {}).get("login", ""),
                "merged_at": item.get("closed_at", ""),
                "body": item.get("body") or "",
                "labels": [label.get("name", "") for label in item.get("labels", [])],
                "changed_files": [],
            }
        )
    return prs


def collect_for_repos(repo_full_names: list[str], target_date: date, token: str | None = None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for repo in repo_full_names:
        prs = search_merged_prs(repo, target_date, token)
        for pr in prs:
            if pr.get("number"):
                try:
                    pr["changed_files"] = fetch_pr_files(repo, int(pr["number"]), token)
                except Exception as exc:
                    pr["changed_files"] = []
                    pr["file_fetch_error"] = str(exc)
            collected.append(pr)
    return collected


def collect_for_repos_window(repo_full_names: list[str], window: ReportWindow, token: str | None = None) -> list[dict[str, Any]]:
    collected: list[dict[str, Any]] = []
    for repo in repo_full_names:
        prs = search_merged_prs_for_window(repo, window, token)
        for pr in prs:
            if pr.get("number"):
                try:
                    pr["changed_files"] = fetch_pr_files(repo, int(pr["number"]), token)
                except Exception as exc:
                    pr["changed_files"] = []
                    pr["file_fetch_error"] = str(exc)
            collected.append(pr)
    return collected


def _within_window(merged_at: str, window: ReportWindow) -> bool:
    if not merged_at:
        return False
    from datetime import datetime

    merged = datetime.fromisoformat(merged_at.replace("Z", "+00:00"))
    return window.start_utc <= merged <= window.end_utc

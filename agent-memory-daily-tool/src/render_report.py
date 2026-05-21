from collections import defaultdict
from datetime import date
import re
from typing import Any


def render_markdown_report(
    target_date: date,
    ranked_prs: list[dict[str, Any]],
    repos: list[str],
    max_focus_prs: int = 12,
) -> str:
    all_important = [pr for pr in ranked_prs if pr.get("relevance") in ("high", "medium")]
    important = _select_focus_prs(all_important, max_focus_prs)
    lines = [
        f"# Agent 记忆系统日报 · {target_date.isoformat()}",
        "",
        "## 昨日概览",
    ]
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pr in ranked_prs:
        grouped[pr.get("repo", "")].append(pr)
    for repo in repos:
        items = grouped.get(repo, [])
        if not items:
            lines.append(f"- `{repo}`：昨日无 merged PR。")
            continue
        high_count = sum(1 for item in items if item.get("relevance") in ("high", "medium"))
        lines.append(f"- `{repo}`：{len(items)} 个 merged PR，{high_count} 个上下文/记忆相关。")

    lines.extend(["", "## 重点 PR"])
    lines.extend(_render_grouped_prs(important, repos, ranked_prs))

    lines.append("")
    return "\n".join(lines)


def _render_pr(pr: dict[str, Any], heading_level: int = 4) -> list[str]:
    title = pr.get("title", "").strip() or "Untitled"
    summary = pr.get("summary") or _fallback_summary(pr)
    heading = "#" * heading_level
    return [
        "",
        f"{heading} {_record_label(pr)} {title}",
        "",
        f"- PR 链接：{pr.get('url', '')}",
        f"- 合入时间：{pr.get('merged_at', '')}",
        f"- 作者：{pr.get('author', '')}",
        f"- 变更摘要：{summary}",
    ]


def _render_grouped_prs(
    prs: list[dict[str, Any]],
    repos: list[str],
    all_prs: list[dict[str, Any]],
) -> list[str]:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for pr in prs:
        repo = pr.get("repo", "")
        grouped[repo].append(pr)

    lines: list[str] = []
    for index, repo in enumerate(repos, start=1):
        lines.extend(["", f"### {index}. {repo}"])
        if repo == "openclaw/openclaw":
            lines.extend(_render_openclaw_prs(index, grouped.get(repo, []), all_prs))
            continue
        if not grouped.get(repo):
            lines.append("- 昨日无重点 PR。")
            continue
        for pr in grouped[repo]:
            lines.extend(_render_pr(pr))
    return lines


def _render_openclaw_prs(
    index: int,
    focus_prs: list[dict[str, Any]],
    all_prs: list[dict[str, Any]],
) -> list[str]:
    context_hook_prs = [
        pr
        for pr in all_prs
        if pr.get("repo") == "openclaw/openclaw" and _is_contextengine_hook_pr(pr)
    ]
    context_keys = {_record_key(pr) for pr in context_hook_prs}
    other_focus_prs = [pr for pr in focus_prs if _record_key(pr) not in context_keys]

    lines: list[str] = ["", f"#### {index}.1 ContextEngine 与 hook 接口改动"]
    if context_hook_prs:
        for pr in context_hook_prs:
            lines.extend(_render_pr(pr, heading_level=5))
    else:
        lines.append("- 昨日无 ContextEngine 或 hook 接口相关 PR。")

    lines.extend(["", f"#### {index}.2 其他重点 PR"])
    if other_focus_prs:
        for pr in other_focus_prs:
            lines.extend(_render_pr(pr, heading_level=5))
    else:
        lines.append("- 昨日无其他重点 PR。")
    return lines


def _select_focus_prs(prs: list[dict[str, Any]], max_focus_prs: int) -> list[dict[str, Any]]:
    selected: list[dict[str, Any]] = []
    selected_ids: set[tuple[str, object]] = set()

    for pr in prs:
        repo = pr.get("repo", "")
        if any(item.get("repo", "") == repo for item in selected):
            continue
        selected.append(pr)
        selected_ids.add((repo, pr.get("number") or pr.get("commit") or pr.get("url")))
        if len(selected) >= max_focus_prs:
            return selected

    for pr in prs:
        key = (pr.get("repo", ""), pr.get("number") or pr.get("commit") or pr.get("url"))
        if key in selected_ids:
            continue
        selected.append(pr)
        selected_ids.add(key)
        if len(selected) >= max_focus_prs:
            break
    return selected


def _is_contextengine_hook_pr(pr: dict[str, Any]) -> bool:
    fields: list[str] = [
        str(pr.get("title", "")),
        str(pr.get("body", "")),
        " ".join(str(item) for item in pr.get("changed_files", [])),
        " ".join(str(item) for item in pr.get("matched_keywords", [])),
    ]
    haystack = " ".join(fields).lower().replace("_", "").replace("-", "")
    contextengine_hit = "contextengine" in haystack or "context engine" in haystack
    hook_hit = "hook" in haystack or "hooks" in haystack
    return contextengine_hit or hook_hit


def _record_key(pr: dict[str, Any]) -> tuple[str, object]:
    return (pr.get("repo", ""), pr.get("number") or pr.get("commit") or pr.get("url"))


def _record_label(pr: dict[str, Any]) -> str:
    repo = pr.get("repo", "")
    number = pr.get("number")
    if number:
        return f"{repo}#{number}"
    commit = pr.get("commit", "")
    if commit:
        return f"{repo}@{commit[:7]}"
    return f"{repo}@unknown"


def _fallback_summary(pr: dict[str, Any]) -> str:
    title = _clean_title(str(pr.get("title") or ""))
    files = pr.get("changed_files", [])
    action = _title_action_summary(title)
    areas = _file_area_summary([str(item) for item in files])

    if action and areas:
        return f"{action}，主要改动 {areas}。"
    if action:
        return f"{action}。"
    if title and areas:
        return f"该 PR 处理“{title}”对应的实现，主要改动 {areas}。"
    if areas:
        return f"该 PR 主要改动 {areas}，覆盖对应实现链路。"
    if title:
        return f"该 PR 处理“{title}”对应的实现。"
    return "该 PR 调整了实现细节。"


def _clean_title(title: str) -> str:
    cleaned = " ".join(title.split())
    cleaned = re.sub(r"\s*\(#\d+\)\s*$", "", cleaned)
    cleaned = re.sub(r"^\[AI-assisted\]\s*", "", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(
        r"^(feat|fix|refactor|chore|docs|test|tests|perf|ci)(\([^)]+\))?:\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    )
    return cleaned.strip()


def _title_action_summary(title: str) -> str:
    lowered = title.lower()
    rules = [
        (
            ["revert", "install codex plugin on openai model selection"],
            "回滚 OpenAI 模型选择时自动安装 Codex 插件的改动",
        ),
        (
            ["route openai agents through codex"],
            "将 OpenAI agents 默认路由到 Codex，并同步调整模型选择和运行时链路",
        ),
        (
            ["install codex plugin on openai model selection"],
            "在 OpenAI 模型选择流程中加入 Codex 插件安装",
        ),
        (
            ["clean subagent fallback scaffolding"],
            "清理 subagent fallback 脚手架和相关测试残留",
        ),
        (
            ["invalidate context engine cache"],
            "修复工具结果上下文保护里的 ContextEngine 缓存失效逻辑",
        ),
        (
            ["clamp compaction max_tokens"],
            "将 compaction 的 max_tokens 限制到模型输出上限内",
        ),
        (
            ["require admin scope for global toggles"],
            "为 active-memory 全局开关增加 admin scope 权限要求",
        ),
        (
            ["repeated codex native approval prompts", "allow-always"],
            "修复 allow-always 后 Codex native 审批提示重复弹出的问题",
        ),
        (
            ["honor archiveafterminutes for session-mode reaping"],
            "让 session-mode 清理流程遵循 archiveAfterMinutes 配置",
        ),
        (
            ["fail fast on session lock fallback"],
            "在 session lock fallback 失败时快速中断，避免继续进入不可靠的会话状态",
        ),
        (
            ["hand mem0 search decisions to the agent"],
            "把 mem0 搜索决策交给 agent，由 agent 决定是否触发记忆检索",
        ),
        (
            ["drain cold-cache deferred compaction debt"],
            "修复 cold-cache 场景下 deferred compaction debt 的清理流程",
        ),
        (
            ["make suites safe without isolation"],
            "调整测试套件，使扩展、插件和网关相关测试在无隔离环境下安全运行",
        ),
    ]
    for keywords, summary in rules:
        if all(keyword in lowered for keyword in keywords):
            return summary

    if not title:
        return ""
    return f"该 PR 处理“{title}”指向的实现问题"


def _file_area_summary(files: list[str]) -> str:
    if not files:
        return ""

    area_rules = [
        ("active-memory", "active-memory 扩展"),
        ("contextengine", "ContextEngine"),
        ("context-engine", "ContextEngine"),
        ("tool-result-context-guard", "工具结果上下文保护"),
        ("/context/", "上下文管理"),
        ("/hooks/", "hook 配置"),
        ("hooks/", "hook 配置"),
        ("codex-hooks", "hook 配置"),
        ("on_user_prompt", "prompt hook 脚本"),
        ("compaction", "compaction 压缩逻辑"),
        ("subagent", "subagent 管理"),
        ("session", "会话状态"),
        ("gateway", "网关协议"),
        ("gatewaymodels", "网关协议"),
        ("openclawprotocol", "网关协议"),
        ("model", "模型/运行时/认证链路"),
        ("runtime", "模型/运行时/认证链路"),
        ("provider", "模型/运行时/认证链路"),
        ("auth", "模型/运行时/认证链路"),
        ("doctor", "模型/运行时/认证链路"),
        ("docs/", "文档"),
        ("test", "测试覆盖"),
    ]

    areas: list[str] = []
    for path in files:
        normalized = path.replace("\\", "/").lower()
        compact = normalized.replace("_", "").replace("-", "")
        for needle, label in area_rules:
            haystack = compact if needle in ("contextengine", "gatewaymodels", "openclawprotocol") else normalized
            if needle in haystack and label not in areas:
                areas.append(label)

    if not areas:
        shown = "、".join(files[:3])
        return f"{shown} 等文件"
    return "、".join(areas[:4])

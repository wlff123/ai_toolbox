import json
import subprocess
from datetime import date
from typing import Any


def build_summary_prompt(
    target_date: date,
    ranked_prs: list[dict[str, Any]],
    repos: list[str] | None = None,
) -> str:
    payload = json.dumps(ranked_prs, ensure_ascii=False, indent=2)
    repo_payload = json.dumps(repos or [], ensure_ascii=False, indent=2)
    return f"""你是 Agent 记忆系统日报编辑。请基于下面 JSON 生成中文 Markdown 日报。

硬性规则：
- 只允许使用 JSON 中出现的信息，不要编造外部事实。
- 标题必须是：# Agent 记忆系统日报 · {target_date.isoformat()}
- 结构必须包含：昨日概览、重点 PR。
- 不要输出额外结论小节。
- 不要输出旧版概览小节标题。
- 昨日概览必须放在重点 PR 前面，并按配置仓库顺序概述每个仓库的 PR 数量与重点 PR 情况。
- 昨日概览不要写“本报重点展开”“建议优先”这类套话。
- 不要输出旧的同日口径概览小节标题。
- 重点 PR 必须按“配置仓库顺序”分组，例如 `### 1. openclaw/openclaw`、`### 2. yoloshii/ClawMem`。
- 配置仓库都必须在“重点 PR”下出现；没有重点 PR 的仓库写 `- 昨日无重点 PR。`。
- `openclaw/openclaw` 章节必须拆成两个小节：`#### 1.1 ContextEngine 与 hook 接口改动` 和 `#### 1.2 其他重点 PR`。
- `1.1 ContextEngine 与 hook 接口改动` 只列前一天 openclaw/openclaw PR 中修改 ContextEngine、Context Engine、hook、hooks 或 hook 相关接口/文件的 PR；每条格式和 1.2 相同。
- 已经列入 1.1 的 PR 不要再列入 1.2。
- 如果 1.1 没有匹配 PR，写 `- 昨日无 ContextEngine 或 hook 接口相关 PR。`。
- 重点 PR 每条只包含：PR 链接、合入时间、作者、变更摘要。
- 每个 PR 条目的第一行必须严格写成：`- PR 链接：<url>`。
- 变更摘要必须用中文一句话讲清楚 PR 做了什么，字数可以适当加长。
- 变更摘要必须结合 title、body、changed_files，说明具体改动了哪个模块、接口、行为或测试场景。
- 禁止使用“用于更新相关功能或测试覆盖”“相关功能”“进行变更”这类泛化描述。
- 可以提到文件路径反映出的模块，但不要只罗列文件名。
- 不要输出独立的链接汇总小节。
- 不要增加解释 PR 入选原因的额外栏目。
- 如果没有重点 PR，明确写“无重点 PR”。
- 输出必须包裹在 <REPORT> 和 </REPORT> 之间。

配置仓库顺序：
{repo_payload}

PR JSON：
{payload}
"""


def run_codex_summary(prompt: str, timeout_seconds: int = 600) -> str:
    result = subprocess.run(
        build_codex_command(prompt),
        check=False,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr or result.stdout or "codex summary failed")
    return parse_codex_report(result.stdout)


def build_codex_command(prompt: str) -> list[str]:
    return [
        "codex",
        "exec",
        "--sandbox",
        "workspace-write",
        "--skip-git-repo-check",
        prompt,
    ]


def parse_codex_report(output: str) -> str:
    start = output.find("<REPORT>")
    end = output.find("</REPORT>")
    if start == -1 or end == -1 or end < start:
        return output.strip()
    return output[start + len("<REPORT>") : end].strip()

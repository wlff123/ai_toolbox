import json
import os
import tempfile
import unittest
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

from src.collect_github import (
    build_search_query,
    build_window_search_query,
    collect_for_repos_window,
    parse_github_search_result,
)
from src.config import load_config
from src.feishu_cli import build_lark_command
from src.git_collect import extract_pr_number, parse_git_log_records, repo_dir_name, ensure_local_repo
from src.rank_prs import rank_pr
from src.render_report import render_markdown_report
from src.schedule import next_beijing_run, should_run_daily
from src.summarize import build_codex_command, build_summary_prompt, parse_codex_report
from src.time_window import beijing_previous_day_window


class DailyReportTests(unittest.TestCase):
    def test_beijing_previous_day_window_uses_beijing_calendar_day(self):
        now = datetime(2026, 5, 8, 23, 45, tzinfo=timezone.utc)

        window = beijing_previous_day_window(now)

        self.assertEqual(window.target_date, date(2026, 5, 8))
        self.assertEqual(window.start_utc.isoformat(), "2026-05-07T16:00:00+00:00")
        self.assertEqual(window.end_utc.isoformat(), "2026-05-08T15:59:59+00:00")

    def test_next_beijing_run_targets_today_when_before_0730_beijing(self):
        now = datetime(2026, 5, 7, 22, 0, tzinfo=timezone.utc)

        next_run = next_beijing_run(now)

        self.assertEqual(next_run.isoformat(), "2026-05-07T23:30:00+00:00")

    def test_next_beijing_run_targets_tomorrow_when_after_0730_beijing(self):
        now = datetime(2026, 5, 8, 0, 0, tzinfo=timezone.utc)

        next_run = next_beijing_run(now)

        self.assertEqual(next_run.isoformat(), "2026-05-08T23:30:00+00:00")

    def test_should_run_daily_triggers_after_0730_beijing_once_per_day(self):
        before_target = datetime(2026, 5, 10, 23, 20, tzinfo=timezone.utc)
        first_poll_after_target = datetime(2026, 5, 10, 23, 35, tzinfo=timezone.utc)

        self.assertFalse(should_run_daily(before_target, None))
        self.assertTrue(should_run_daily(first_poll_after_target, None))
        self.assertFalse(should_run_daily(first_poll_after_target, "2026-05-11"))

    def test_build_search_query_targets_merged_prs_for_one_repo_and_date(self):
        query = build_search_query("mem0ai/mem0", date(2026, 5, 7))

        self.assertEqual(
            query,
            "repo:mem0ai/mem0 is:pr is:merged merged:2026-05-07..2026-05-07",
        )

    def test_build_window_search_query_covers_utc_dates_for_beijing_day(self):
        window = beijing_previous_day_window(datetime(2026, 5, 8, 23, 45, tzinfo=timezone.utc))

        query = build_window_search_query("mem0ai/mem0", window)

        self.assertEqual(
            query,
            "repo:mem0ai/mem0 is:pr is:merged merged:2026-05-07..2026-05-08",
        )

    def test_parse_github_search_result_extracts_report_fields(self):
        payload = {
            "items": [
                {
                    "number": 123,
                    "title": "Improve memory retrieval cache",
                    "html_url": "https://github.com/mem0ai/mem0/pull/123",
                    "user": {"login": "alice"},
                    "closed_at": "2026-05-07T13:20:00Z",
                    "body": "Adds cache invalidation for memory retrieval.",
                    "labels": [{"name": "enhancement"}],
                }
            ]
        }

        prs = parse_github_search_result("mem0ai/mem0", payload)

        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]["repo"], "mem0ai/mem0")
        self.assertEqual(prs[0]["number"], 123)
        self.assertEqual(prs[0]["author"], "alice")
        self.assertEqual(prs[0]["merged_at"], "2026-05-07T13:20:00Z")

    def test_collect_for_repos_window_keeps_pr_when_file_fetch_hits_rate_limit(self):
        window = beijing_previous_day_window(datetime(2026, 5, 8, 23, 45, tzinfo=timezone.utc))
        pr = {
            "repo": "mem0ai/mem0",
            "number": 123,
            "title": "Improve memory retrieval cache",
            "merged_at": "2026-05-07T13:20:00Z",
            "changed_files": [],
        }

        with patch("src.collect_github.search_merged_prs_for_window", return_value=[pr]):
            with patch("src.collect_github.fetch_pr_files", side_effect=RuntimeError("rate limit exceeded")):
                prs = collect_for_repos_window(["mem0ai/mem0"], window)

        self.assertEqual(len(prs), 1)
        self.assertEqual(prs[0]["changed_files"], [])
        self.assertIn("rate limit exceeded", prs[0]["file_fetch_error"])

    def test_repo_dir_name_is_stable_for_owner_repo(self):
        self.assertEqual(repo_dir_name("mem0ai/mem0"), "mem0ai__mem0")

    def test_extract_pr_number_supports_merge_and_squash_subjects(self):
        self.assertEqual(extract_pr_number("Merge pull request #123 from feature"), 123)
        self.assertEqual(extract_pr_number("fix memory cache (#456)"), 456)
        self.assertEqual(extract_pr_number('Revert "old change (#111)" (#222)'), 222)
        self.assertIsNone(extract_pr_number("direct commit without pull request"))

    def test_parse_git_log_records_builds_pr_and_commit_urls(self):
        raw = (
            "abc123\x1f2026-05-07T13:20:00+00:00\x1fAlice\x1ffix memory cache (#456)\x1e"
            "def456\x1f2026-05-07T14:20:00+00:00\x1fBob\x1fdirect docs update"
        )

        records = parse_git_log_records("mem0ai/mem0", raw)

        self.assertEqual(records[0]["number"], 456)
        self.assertEqual(records[0]["url"], "https://github.com/mem0ai/mem0/pull/456")
        self.assertEqual(records[1]["number"], None)
        self.assertEqual(records[1]["url"], "https://github.com/mem0ai/mem0/commit/def456")

    def test_ensure_local_repo_uses_existing_copy_when_pull_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            repos_dir = Path(tmp)
            local_dir = repos_dir / "mem0ai__mem0"
            local_dir.mkdir()

            with patch("src.git_collect._run_git", side_effect=RuntimeError("network")):
                result = ensure_local_repo("mem0ai/mem0", repos_dir)

        self.assertEqual(result, local_dir)

    def test_rank_pr_flags_memory_context_relevance_without_reason_field(self):
        pr = {
            "title": "Add persistent context compaction cache",
            "body": "Stores compacted session memory for recall.",
            "changed_files": ["src/memory/store.py", "docs/context.md"],
        }
        ranked = rank_pr(pr, ["memory", "context", "recall", "compaction"])

        self.assertEqual(ranked["relevance"], "high")
        self.assertGreaterEqual(ranked["score"], 4)
        self.assertNotIn("reason", ranked)

    def test_render_report_has_requested_sections_and_no_why_related_label(self):
        ranked_prs = [
            {
                "repo": "mem0ai/mem0",
                "number": 123,
                "title": "Improve memory retrieval cache",
                "url": "https://github.com/mem0ai/mem0/pull/123",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "summary": "该 PR 改进记忆检索缓存失效流程，降低旧记忆被错误召回的概率。",
                "relevance": "high",
                "score": 5,
            }
        ]

        report = render_markdown_report(date(2026, 5, 7), ranked_prs, ["mem0ai/mem0"])

        self.assertIn("# Agent 记忆系统日报 · 2026-05-07", report)
        self.assertIn("## 昨日概览", report)
        self.assertIn("## 重点 PR", report)
        self.assertIn("### 1. mem0ai/mem0", report)
        self.assertNotIn("## 今日核心结论", report)
        self.assertNotIn("## 今日概览", report)
        self.assertNotIn("## 仓库概览", report)
        self.assertLess(report.index("## 昨日概览"), report.index("## 重点 PR"))
        self.assertNotIn("为什么和记忆", report)
        self.assertNotIn("本报重点展开", report)
        self.assertNotIn("建议优先", report)
        self.assertNotIn("影响判断", report)
        self.assertNotIn("## 值得跟踪", report)
        self.assertNotIn("## 原始链接", report)
        self.assertIn("变更摘要：该 PR 改进记忆检索缓存失效流程", report)
        self.assertLess(report.index("PR 链接：https://github.com/mem0ai/mem0/pull/123"), report.index("合入时间："))

    def test_render_report_fallback_summary_describes_specific_pr_change(self):
        ranked_prs = [
            {
                "repo": "openclaw/openclaw",
                "number": 78899,
                "title": "Route OpenAI agents through Codex by default",
                "url": "https://github.com/openclaw/openclaw/pull/78899",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "changed_files": [
                    "src/agents/openai-runtime.ts",
                    "src/auth/openai.ts",
                    "docs/cli/models.md",
                ],
                "relevance": "high",
                "score": 10,
            },
            {
                "repo": "mem0ai/mem0",
                "number": 4992,
                "title": "refactor(plugin): hand mem0 search decisions to the agent",
                "url": "https://github.com/mem0ai/mem0/pull/4992",
                "author": "bob",
                "merged_at": "2026-05-07T14:20:00Z",
                "changed_files": [
                    "mem0-plugin/hooks/codex-hooks.json",
                    "mem0-plugin/scripts/on_user_prompt.sh",
                ],
                "relevance": "high",
                "score": 9,
            },
        ]

        report = render_markdown_report(
            date(2026, 5, 7),
            ranked_prs,
            ["openclaw/openclaw", "mem0ai/mem0"],
        )

        self.assertNotIn("用于更新相关功能", report)
        self.assertNotIn("更新相关功能或测试覆盖", report)
        self.assertNotIn("进行变更", report)
        self.assertNotIn("对应的功能或行为调整", report)
        self.assertIn("OpenAI agents 默认路由到 Codex", report)
        self.assertIn("模型/运行时/认证链路", report)
        self.assertIn("把 mem0 搜索决策交给 agent", report)
        self.assertIn("hook 配置", report)

    def test_render_report_fallback_summary_handles_revert_before_original_change(self):
        ranked_prs = [
            {
                "repo": "openclaw/openclaw",
                "number": 78878,
                "title": 'Revert "Install Codex plugin on OpenAI model selection (#78799)"',
                "url": "https://github.com/openclaw/openclaw/pull/78878",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "changed_files": [
                    "packages/core/src/provider/OpenAIProvider.ts",
                    "docs/cli/models.md",
                ],
                "relevance": "high",
                "score": 10,
            }
        ]

        report = render_markdown_report(date(2026, 5, 7), ranked_prs, ["openclaw/openclaw"])

        self.assertIn("回滚 OpenAI 模型选择时自动安装 Codex 插件的改动", report)
        self.assertNotIn("在 OpenAI 模型选择流程中加入 Codex 插件安装，主要改动", report)

    def test_render_report_fallback_summary_avoids_generic_unknown_wording(self):
        ranked_prs = [
            {
                "repo": "openclaw/openclaw",
                "number": 78263,
                "title": "fix(subagents): honor archiveAfterMinutes for session-mode reaping",
                "url": "https://github.com/openclaw/openclaw/pull/78263",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "changed_files": [
                    "packages/subagents/src/session-mode-reaper.ts",
                    "packages/subagents/test/session-mode-reaper.test.ts",
                ],
                "relevance": "high",
                "score": 10,
            }
        ]

        report = render_markdown_report(date(2026, 5, 7), ranked_prs, ["openclaw/openclaw"])

        self.assertIn("让 session-mode 清理流程遵循 archiveAfterMinutes 配置", report)
        self.assertNotIn("对应的功能或行为调整", report)

    def test_render_report_limits_focus_prs_for_concise_daily(self):
        ranked_prs = []
        for index in range(20):
            ranked_prs.append(
                {
                    "repo": "openclaw/openclaw",
                    "number": index + 1,
                    "title": f"Memory change {index + 1}",
                    "url": f"https://example.com/{index + 1}",
                    "author": "alice",
                    "merged_at": "2026-05-07T13:20:00Z",
                    "summary": "summary",
                    "relevance": "high",
                    "score": 10 - index,
                }
            )

        report = render_markdown_report(date(2026, 5, 7), ranked_prs, ["openclaw/openclaw"])

        self.assertIn("### 1. openclaw/openclaw", report)
        self.assertEqual(report.count("#### openclaw/openclaw#"), 12)

    def test_render_report_keeps_at_least_one_focus_pr_per_relevant_repo(self):
        ranked_prs = []
        for index in range(12):
            ranked_prs.append(
                {
                    "repo": "openclaw/openclaw",
                    "number": index + 1,
                    "title": f"OpenClaw change {index + 1}",
                    "url": f"https://example.com/openclaw/{index + 1}",
                    "author": "alice",
                    "merged_at": "2026-05-07T13:20:00Z",
                    "summary": "summary",
                    "relevance": "high",
                    "score": 100 - index,
                }
            )
        ranked_prs.append(
            {
                "repo": "Martian-Engineering/lossless-claw",
                "number": 622,
                "title": "Drain cold-cache deferred compaction debt",
                "url": "https://example.com/lossless/622",
                "author": "bob",
                "merged_at": "2026-05-07T13:20:00Z",
                "summary": "summary",
                "relevance": "medium",
                "score": 1,
            }
        )

        report = render_markdown_report(
            date(2026, 5, 7),
            ranked_prs,
            ["openclaw/openclaw", "Martian-Engineering/lossless-claw"],
        )

        self.assertIn("### 2. Martian-Engineering/lossless-claw", report)
        self.assertIn("#### Martian-Engineering/lossless-claw#622", report)

    def test_render_report_splits_openclaw_contextengine_hook_prs(self):
        ranked_prs = [
            {
                "repo": "openclaw/openclaw",
                "number": 10,
                "title": "Update ContextEngine hook API",
                "url": "https://example.com/openclaw/10",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "summary": "该 PR 调整 ContextEngine hook 接口。",
                "changed_files": ["src/context/ContextEngine.ts", "src/hooks/context-hook.ts"],
                "relevance": "high",
                "score": 10,
            },
            {
                "repo": "openclaw/openclaw",
                "number": 11,
                "title": "Improve session cache",
                "url": "https://example.com/openclaw/11",
                "author": "bob",
                "merged_at": "2026-05-07T14:20:00Z",
                "summary": "该 PR 改进 session cache。",
                "changed_files": ["src/session/cache.ts"],
                "relevance": "high",
                "score": 9,
            },
        ]

        report = render_markdown_report(date(2026, 5, 7), ranked_prs, ["openclaw/openclaw"])

        self.assertIn("#### 1.1 ContextEngine 与 hook 接口改动", report)
        self.assertIn("#### 1.2 其他重点 PR", report)
        self.assertIn("##### openclaw/openclaw#10 Update ContextEngine hook API", report)
        self.assertIn("##### openclaw/openclaw#11 Improve session cache", report)
        self.assertLess(
            report.index("##### openclaw/openclaw#10 Update ContextEngine hook API"),
            report.index("#### 1.2 其他重点 PR"),
        )
        self.assertGreater(
            report.index("##### openclaw/openclaw#11 Improve session cache"),
            report.index("#### 1.2 其他重点 PR"),
        )
        self.assertEqual(report.count("openclaw/openclaw#10"), 1)

    def test_render_report_lists_configured_repos_without_focus_prs(self):
        ranked_prs = [
            {
                "repo": "openclaw/openclaw",
                "number": 78834,
                "title": "Update agent tests",
                "url": "https://github.com/openclaw/openclaw/pull/78834",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "summary": "该 PR 更新 Agent 相关测试覆盖。",
                "relevance": "high",
                "score": 10,
            }
        ]

        report = render_markdown_report(
            date(2026, 5, 7),
            ranked_prs,
            ["openclaw/openclaw", "yoloshii/ClawMem", "mem9-ai/mem9"],
        )

        self.assertIn("### 1. openclaw/openclaw", report)
        self.assertIn("### 2. yoloshii/ClawMem", report)
        self.assertIn("### 3. mem9-ai/mem9", report)
        self.assertIn("- 昨日无重点 PR。", report)

    def test_render_report_labels_direct_commits_without_none_pr_number(self):
        ranked_prs = [
            {
                "repo": "openclaw/openclaw",
                "number": None,
                "commit": "abcdef123456",
                "title": "direct memory commit",
                "url": "https://example.com/commit/abcdef123456",
                "author": "alice",
                "merged_at": "2026-05-07T13:20:00Z",
                "summary": "该提交更新了记忆相关逻辑。",
                "relevance": "high",
                "score": 10,
            }
        ]

        report = render_markdown_report(date(2026, 5, 7), ranked_prs, ["openclaw/openclaw"])

        self.assertIn("#### openclaw/openclaw@abcdef1 direct memory commit", report)
        self.assertNotIn("#None", report)

    def test_build_lark_command_uses_markdown_dry_run_by_default(self):
        command = build_lark_command(
            chat_id="CHAT_ID_TEST",
            markdown="## Agent 记忆系统日报\n\n- test",
            identity="bot",
            profile="PROFILE_NAME",
            dry_run=True,
        )

        self.assertEqual(command[:5], ["lark-cli", "--profile", "PROFILE_NAME", "im", "+messages-send"])
        self.assertIn("--chat-id", command)
        self.assertIn("CHAT_ID_TEST", command)
        self.assertIn("--markdown", command)
        self.assertIn("## Agent 记忆系统日报\n\n- test", command)
        self.assertIn("--dry-run", command)
        self.assertIn("--as", command)
        self.assertIn("bot", command)

    def test_load_config_reads_repos_and_keywords(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "config.json"
            path.write_text(
                json.dumps(
                    {
                        "timezone": "Asia/Shanghai",
                        "repos": [{"name": "mem0", "full_name": "mem0ai/mem0"}],
                        "keywords": ["memory", "context"],
                        "feishu": {
                            "targets": [
                                {
                                    "name": "target-a",
                                    "chat_id": "CHAT_ID_BOT",
                                    "identity": "bot",
                                    "profile": "PROFILE_NAME",
                                },
                                {
                                    "name": "target-b",
                                    "chat_id": "CHAT_ID_USER",
                                    "identity": "user",
                                },
                            ]
                        },
                    }
                ),
                encoding="utf-8",
            )

            config = load_config(path)

        self.assertEqual(config.timezone, "Asia/Shanghai")
        self.assertEqual(config.repo_full_names(), ["mem0ai/mem0"])
        self.assertEqual(config.keywords, ["memory", "context"])
        targets = config.feishu.delivery_targets()
        self.assertEqual(len(targets), 2)
        self.assertEqual(targets[0].chat_id, "CHAT_ID_BOT")
        self.assertEqual(targets[0].identity, "bot")
        self.assertEqual(targets[0].profile, "PROFILE_NAME")
        self.assertEqual(targets[1].chat_id, "CHAT_ID_USER")
        self.assertEqual(targets[1].identity, "user")

    def test_build_summary_prompt_forbids_unbacked_facts_and_omits_why_related(self):
        prompt = build_summary_prompt(
            target_date=date(2026, 5, 7),
            ranked_prs=[
                {
                    "repo": "mem0ai/mem0",
                    "number": 123,
                    "title": "Improve memory retrieval cache",
                    "url": "https://github.com/mem0ai/mem0/pull/123",
                    "score": 5,
                }
            ],
            repos=["mem0ai/mem0", "mem9-ai/mem9"],
        )

        self.assertIn("只允许使用 JSON 中出现的信息", prompt)
        self.assertIn("Agent 记忆系统日报 · 2026-05-07", prompt)
        self.assertNotIn("为什么和记忆", prompt)
        self.assertIn("昨日概览", prompt)
        self.assertNotIn("今日概览", prompt)
        self.assertNotIn("今日核心结论", prompt)
        self.assertNotIn("仓库概览", prompt)
        self.assertIn("openclaw/openclaw", prompt)
        self.assertIn("1.1 ContextEngine 与 hook 接口改动", prompt)
        self.assertIn("1.2 其他重点 PR", prompt)
        self.assertIn("变更摘要", prompt)
        self.assertIn("PR 链接", prompt)
        self.assertIn("配置仓库顺序", prompt)
        self.assertIn("mem9-ai/mem9", prompt)
        self.assertNotIn("影响判断", prompt)
        self.assertNotIn("值得跟踪", prompt)
        self.assertNotIn("原始链接", prompt)
        self.assertIn("重点 PR 必须按“配置仓库顺序”分组", prompt)
        self.assertIn("必须结合 title、body、changed_files", prompt)
        self.assertIn("禁止使用“用于更新相关功能或测试覆盖”", prompt)

    def test_build_codex_command_skips_git_repo_check_for_workspace_task(self):
        command = build_codex_command("prompt")

        self.assertEqual(command[:2], ["codex", "exec"])
        self.assertIn("--skip-git-repo-check", command)
        self.assertIn("--sandbox", command)
        self.assertIn("workspace-write", command)

    def test_parse_codex_report_extracts_markdown_between_markers(self):
        output = "logs\n<REPORT>\n# Agent 记忆系统日报\n\n内容\n</REPORT>\nmore logs"

        report = parse_codex_report(output)

        self.assertEqual(report, "# Agent 记忆系统日报\n\n内容")


if __name__ == "__main__":
    unittest.main()

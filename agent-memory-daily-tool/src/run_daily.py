import argparse
import json
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

from src.config import Config, FeishuTarget, load_config
from src.feishu_cli import send_markdown_file
from src.git_collect import sync_and_collect_repos
from src.rank_prs import rank_all
from src.render_report import render_markdown_report
from src.summarize import build_summary_prompt, run_codex_summary
from src.time_window import beijing_date_window, beijing_previous_day_window


ROOT = Path(__file__).resolve().parent.parent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Generate Agent memory system daily report.")
    parser.add_argument("--config", type=Path, default=ROOT / "config" / "config.json")
    parser.add_argument("--date", help="Beijing target date, YYYY-MM-DD. Default: previous Beijing day.")
    parser.add_argument("--sample", action="store_true", help="Use local sample PR data instead of GitHub.")
    parser.add_argument("--no-codex", action="store_true", help="Use deterministic renderer instead of Codex.")
    parser.add_argument("--send", action="store_true", help="Actually send to Feishu through lark-cli.")
    parser.add_argument("--skip-feishu", action="store_true", help="Do not call lark-cli even in dry-run.")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    window = _resolve_window(args.date)

    dirs = _ensure_dirs()
    log_file = dirs["logs"] / f"{window.target_date.isoformat()}.log"
    _log(log_file, f"start target_date={window.target_date.isoformat()} send={args.send} sample={args.sample}")

    raw_prs = (
        _load_sample_prs()
        if args.sample
        else sync_and_collect_repos(config.repo_full_names(), ROOT / "repos", window)
    )
    if not config.include_direct_commits:
        raw_prs = [item for item in raw_prs if item.get("number")]
    ranked = rank_all(raw_prs, config.keywords)
    _write_json(dirs["raw"] / f"{window.target_date.isoformat()}-prs.json", ranked)

    report = _build_report(config, window.target_date, ranked, args.no_codex, log_file)
    report_path = dirs["reports"] / f"{window.target_date.isoformat()}.md"
    report_path.write_text(report, encoding="utf-8")
    _log(log_file, f"report={report_path}")

    if not args.skip_feishu:
        _maybe_send_feishu(config, report_path, send=args.send, log_file=log_file)

    print(str(report_path))
    return 0


def _resolve_window(value: str | None):
    if value:
        return beijing_date_window(date.fromisoformat(value))
    return beijing_previous_day_window(datetime.now(timezone.utc))


def _ensure_dirs() -> dict[str, Path]:
    dirs = {
        "reports": ROOT / "reports",
        "raw": ROOT / "data" / "raw",
        "logs": ROOT / "logs",
    }
    for path in dirs.values():
        path.mkdir(parents=True, exist_ok=True)
    return dirs


def _load_sample_prs() -> list[dict]:
    path = ROOT / "data" / "sample_prs.json"
    return json.loads(path.read_text(encoding="utf-8"))


def _build_report(
    config: Config,
    target_date: date,
    ranked: list[dict],
    no_codex: bool,
    log_file: Path,
) -> str:
    if config.codex_enabled and not no_codex and ranked:
        prompt = build_summary_prompt(target_date, ranked, config.repo_full_names())
        try:
            return run_codex_summary(prompt)
        except Exception as exc:
            _log(log_file, f"codex_failed fallback=deterministic error={exc}")
    return render_markdown_report(target_date, ranked, config.repo_full_names())


def _maybe_send_feishu(config: Config, report_path: Path, send: bool, log_file: Path) -> None:
    targets = config.feishu.delivery_targets()
    env_chat_id = os.getenv("FEISHU_CHAT_ID")
    if env_chat_id and not targets:
        targets = [
            FeishuTarget(
                chat_id=env_chat_id,
                identity=config.feishu.identity,
                profile=config.feishu.profile,
                name="env",
            )
        ]
    if not targets:
        _log(log_file, "feishu_skipped reason=missing_chat_id")
        return
    for target in targets:
        result = send_markdown_file(
            chat_id=target.chat_id,
            markdown_path=report_path,
            identity=target.identity,
            profile=target.profile,
            dry_run=not send,
        )
        label = target.name or target.chat_id
        _log(log_file, f"feishu_target={label} feishu_exit={result.returncode} dry_run={not send}")
        if result.stdout:
            _log(log_file, f"feishu_target={label} feishu_stdout={result.stdout.strip()[:1000]}")
        if result.stderr:
            _log(log_file, f"feishu_target={label} feishu_stderr={result.stderr.strip()[:1000]}")
        if send and result.returncode != 0:
            raise RuntimeError(f"lark-cli send failed for {label}: {result.stderr or result.stdout}")


def _write_json(path: Path, payload) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _log(path: Path, message: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    now = datetime.now(timezone.utc).isoformat()
    with path.open("a", encoding="utf-8") as handle:
        handle.write(f"[{now}] {message}\n")


if __name__ == "__main__":
    sys.exit(main())

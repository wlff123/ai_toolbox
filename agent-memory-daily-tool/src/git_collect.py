import re
import subprocess
from pathlib import Path
from typing import Any

from src.time_window import ReportWindow


FIELD_SEP = "\x1f"
RECORD_SEP = "\x1e"


def repo_dir_name(repo_full_name: str) -> str:
    return repo_full_name.replace("/", "__")


def extract_pr_number(subject: str) -> int | None:
    parenthetical = re.findall(r"\(#(\d+)\)", subject)
    if parenthetical:
        return int(parenthetical[-1])

    patterns = [
        r"Merge pull request #(\d+)",
        r"#(\d+)",
    ]
    for pattern in patterns:
        match = re.search(pattern, subject)
        if match:
            return int(match.group(1))
    return None


def sync_and_collect_repos(
    repo_full_names: list[str],
    repos_dir: Path,
    window: ReportWindow,
    clone_depth: int = 1000,
) -> list[dict[str, Any]]:
    repos_dir.mkdir(parents=True, exist_ok=True)
    collected: list[dict[str, Any]] = []
    for repo_full_name in repo_full_names:
        local_dir = ensure_local_repo(repo_full_name, repos_dir, clone_depth=clone_depth)
        collected.extend(collect_repo_commits(repo_full_name, local_dir, window))
    return collected


def ensure_local_repo(repo_full_name: str, repos_dir: Path, clone_depth: int = 1000) -> Path:
    local_dir = repos_dir / repo_dir_name(repo_full_name)
    if not local_dir.exists():
        url = f"https://github.com/{repo_full_name}.git"
        _run_git(
            [
                "git",
                "clone",
                "--filter=blob:none",
                f"--depth={clone_depth}",
                url,
                str(local_dir),
            ],
            cwd=repos_dir,
        )
        return local_dir

    try:
        _run_git(["git", "fetch", "--prune", "origin"], cwd=local_dir)
        _run_git(["git", "pull", "--ff-only"], cwd=local_dir)
    except RuntimeError:
        return local_dir
    return local_dir


def collect_repo_commits(repo_full_name: str, local_dir: Path, window: ReportWindow) -> list[dict[str, Any]]:
    pretty = f"%H{FIELD_SEP}%cI{FIELD_SEP}%an{FIELD_SEP}%s{RECORD_SEP}"
    result = _run_git(
        [
            "git",
            "log",
            "--first-parent",
            f"--since={window.start_utc.isoformat()}",
            f"--until={window.end_utc.isoformat()}",
            f"--pretty=format:{pretty}",
        ],
        cwd=local_dir,
    )
    records = parse_git_log_records(repo_full_name, result.stdout)
    for record in records:
        record["changed_files"] = changed_files_for_commit(local_dir, record["commit"])
    return records


def parse_git_log_records(repo_full_name: str, raw: str) -> list[dict[str, Any]]:
    records: list[dict[str, Any]] = []
    for chunk in raw.strip(RECORD_SEP).split(RECORD_SEP):
        if not chunk.strip():
            continue
        fields = chunk.strip().split(FIELD_SEP)
        if len(fields) != 4:
            continue
        commit, merged_at, author, subject = fields
        pr_number = extract_pr_number(subject)
        url = (
            f"https://github.com/{repo_full_name}/pull/{pr_number}"
            if pr_number
            else f"https://github.com/{repo_full_name}/commit/{commit}"
        )
        records.append(
            {
                "repo": repo_full_name,
                "number": pr_number,
                "title": subject,
                "url": url,
                "author": author,
                "merged_at": merged_at,
                "body": subject,
                "labels": [],
                "changed_files": [],
                "commit": commit,
            }
        )
    return records


def changed_files_for_commit(local_dir: Path, commit: str) -> list[str]:
    result = _run_git(["git", "show", "--name-only", "--format=", commit], cwd=local_dir)
    return [line.strip() for line in result.stdout.splitlines() if line.strip()]


def _run_git(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(args, cwd=cwd, text=True, capture_output=True, check=False)
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or result.stdout.strip() or "git command failed")
    return result

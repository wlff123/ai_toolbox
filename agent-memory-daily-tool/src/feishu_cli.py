import subprocess
from pathlib import Path


def build_lark_command(
    chat_id: str,
    markdown: str,
    identity: str = "bot",
    profile: str = "",
    dry_run: bool = True,
) -> list[str]:
    command = ["lark-cli"]
    if profile:
        command.extend(["--profile", profile])
    command.extend([
        "im",
        "+messages-send",
        "--chat-id",
        chat_id,
        "--markdown",
        markdown,
        "--as",
        identity,
    ])
    if dry_run:
        command.append("--dry-run")
    return command


def send_markdown_file(
    chat_id: str,
    markdown_path: Path,
    identity: str = "bot",
    profile: str = "",
    dry_run: bool = True,
) -> subprocess.CompletedProcess[str]:
    markdown = markdown_path.read_text(encoding="utf-8")
    command = build_lark_command(chat_id, markdown, identity=identity, profile=profile, dry_run=dry_run)
    return subprocess.run(command, check=False, text=True, capture_output=True)

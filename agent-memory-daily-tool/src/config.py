import json
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RepoConfig:
    name: str
    full_name: str


@dataclass(frozen=True)
class FeishuTarget:
    chat_id: str
    identity: str = "bot"
    profile: str = ""
    name: str = ""


@dataclass(frozen=True)
class FeishuConfig:
    chat_id: str
    identity: str = "bot"
    profile: str = ""
    targets: list[FeishuTarget] | None = None

    def delivery_targets(self) -> list[FeishuTarget]:
        if self.targets:
            return self.targets
        if not self.chat_id:
            return []
        return [
            FeishuTarget(
                chat_id=self.chat_id,
                identity=self.identity,
                profile=self.profile,
                name="default",
            )
        ]


@dataclass(frozen=True)
class Config:
    timezone: str
    repos: list[RepoConfig]
    keywords: list[str]
    feishu: FeishuConfig
    codex_enabled: bool = True
    include_direct_commits: bool = False

    def repo_full_names(self) -> list[str]:
        return [repo.full_name for repo in self.repos]


def load_config(path: Path) -> Config:
    payload = json.loads(path.read_text(encoding="utf-8"))
    repos = [
        RepoConfig(name=item["name"], full_name=item["full_name"])
        for item in payload.get("repos", [])
    ]
    feishu_payload = payload.get("feishu", {})
    targets = [
        FeishuTarget(
            chat_id=item.get("chat_id", ""),
            identity=item.get("identity", "bot"),
            profile=item.get("profile", ""),
            name=item.get("name", ""),
        )
        for item in feishu_payload.get("targets", [])
        if item.get("chat_id")
    ]
    feishu = FeishuConfig(
        chat_id=feishu_payload.get("chat_id", ""),
        identity=feishu_payload.get("identity", "bot"),
        profile=feishu_payload.get("profile", ""),
        targets=targets,
    )
    return Config(
        timezone=payload.get("timezone", "Asia/Shanghai"),
        repos=repos,
        keywords=payload.get("keywords", []),
        feishu=feishu,
        codex_enabled=payload.get("codex_enabled", True),
        include_direct_commits=payload.get("include_direct_commits", False),
    )

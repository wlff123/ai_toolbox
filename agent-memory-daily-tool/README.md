# Agent Memory Daily

每天北京时间 07:30 同步本地 GitHub 仓库副本，分析前一天 first-parent 合入记录，筛选上下文和记忆相关变更，生成结构化中文日报，并按配置发送到飞书群。

## 功能

- 按北京时间计算“前一天”的日报窗口。
- 首次运行会把 `config/config.json` 中的仓库 clone 到 `repos/`。
- 后续运行会对每个本地仓库执行 `git fetch --prune origin` 和 `git pull --ff-only`。
- 默认只统计能从 merge/squash 提交标题解析出 PR 号的记录。
- 支持 Codex 摘要；失败时回退到确定性 Markdown 渲染。
- 支持多个飞书发送目标，每个目标可指定 `chat_id`、发送身份和 `lark-cli` profile。
- 内置项目级后台 scheduler，在没有 cron/systemd 的环境中也可定时运行。

## 目录

- `config/config.json`：仓库、关键词、飞书目标模板。上传前保持占位符，不要提交真实群 ID、profile、密钥或用户信息。
- `src/`：采集、排序、摘要、渲染、发送和定时计算代码。
- `scripts/run.sh`：单次运行入口。
- `scripts/daily_scheduler.sh`：常驻定时循环。
- `scripts/start_daily_scheduler.sh`：后台启动定时任务。
- `scripts/status_daily_scheduler.sh`：检查定时任务状态。
- `tests/`：单元测试。
- `data/sample_prs.json`：本地样例数据。

## 配置

编辑 `config/config.json`：

```json
"feishu": {
  "targets": [
    {
      "name": "YOUR_GROUP_NAME",
      "chat_id": "YOUR_CHAT_ID",
      "identity": "bot",
      "profile": "YOUR_LARK_CLI_PROFILE"
    }
  ]
}
```

注意：

- 不要把真实 `chat_id`、open_id、app id、profile 名、token、secret、用户名提交到 Git。
- `profile` 需要先在本机通过 `lark-cli profile add` 或 `lark-cli config bind` 配好。
- 真实 App ID、Secret、Token 等敏感值由部署环境维护，不放进仓库。

## 手动运行

生成报告但不调用飞书：

```bash
./scripts/run.sh --skip-feishu
```

使用确定性渲染，不调用 Codex：

```bash
./scripts/run.sh --no-codex --skip-feishu
```

指定日期：

```bash
./scripts/run.sh --date 2026-05-07 --skip-feishu
```

样例数据：

```bash
./scripts/run.sh --sample --no-codex --skip-feishu
```

真实发送：

```bash
./scripts/run.sh --send
```

## 定时任务

启动项目级后台 scheduler：

```bash
./scripts/start_daily_scheduler.sh
```

查看状态：

```bash
./scripts/status_daily_scheduler.sh
```

运行日志：

- `logs/scheduler.log`
- `logs/cron.log`

注意：项目级 scheduler 是普通后台进程。机器或容器重启后，需要重新执行 `scripts/start_daily_scheduler.sh`，或接入你自己的进程管理系统。

## 测试

```bash
python3 -m unittest discover -s tests -v
python3 -m compileall -q src
bash -n scripts/*.sh
```

## 不应提交的内容

`.gitignore` 已排除：

- `repos/`
- `reports/`
- `logs/`
- `data/raw/`
- `runtime/`
- Python 缓存文件

提交前建议用你的仓库密钥扫描工具再检查一遍，重点确认没有真实飞书群 ID、用户 ID、消息 ID、App ID、Token、Secret、profile 名和用户名。

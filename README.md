# medical-health-ai-jobs-insight

医药健康 + AI 岗位洞察：一个**会自己跑**的数据项目。后台流水线按你设定的时间采集岗位、
调用 LLM 规范化与分析，产出 JSON，前端可视化看板直接读这些 JSON。

## 当前版本

| 能力 | 状态 |
| --- | --- |
| 自定义调度 | 支持每天定点、cron、固定间隔、手动运行及 GitHub Actions |
| LLM | 支持 OpenAI 兼容接口、Anthropic、Ollama 和离线 mock，失败自动回退规则解析 |
| 数据采集 | 支持本地 JSON、JSON API、网页 + LLM，以及需要授权会话的 Playwright 浏览器 |
| 发布安全 | 必需来源、最低采集量、相关度过滤和质量分均可作为发布门禁 |
| 可观测性 | 提供数据版本、来源健康、质量、新鲜度、运行历史和 `doctor` 诊断 |
| 前端降级 | 实时 API 优先，后端不可用时自动读取静态数据快照 |

> 仓库默认启用的是 fixture 示例数据和 mock LLM，目的是无需账号即可验证完整流程。
> 若要持续获取真实招聘数据，请按“数据源”章节配置有权访问的接口或浏览器账号，并遵守平台条款。

```
                 ┌──────────── 你设定的运行时间 ────────────┐
                 │  每天定点 / cron / 固定间隔 / 仅手动      │
                 └───────────────────┬──────────────────────┘
                                     ▼
  数据源                     automation/ (jobsinsight)                     web/
┌──────────┐        ┌──────────────────────────────────────┐        ┌──────────────┐
│ 本地 JSON│        │ 采集 → LLM 富化 → 统计聚合 → 原子落盘│        │ React 看板   │
│ JSON 接口│ ─────▶ │        ↑                             │ ─────▶ │ 图表 + 洞察  │
│ 网页+LLM │        │   规则兜底（缺 Key/超时也能产出）    │        │ 自动化面板   │
└──────────┘        └──────────────────────────────────────┘        └──────────────┘
                                     │
                          HTTP 控制接口（可选）
                    查看状态 / 改运行时间 / 立即运行 / 调 LLM
```

## 快速开始

后端核心零依赖，只需要 Python 3.11+（浏览器采集才需要可选 Playwright）。

```bash
# 1. 跑一次流水线（默认离线 mock provider，不需要 API Key）
cd automation
python -m jobsinsight doctor  # 先检查配置、来源、目录和已有数据
python -m jobsinsight run

# 2. 看看下一次什么时候跑
python -m jobsinsight next-runs

# 3. 常驻运行：到点自动执行
python -m jobsinsight schedule

# 4. 或者带上 HTTP 接口一起启动（同时托管构建好的前端）
python -m jobsinsight serve      # http://127.0.0.1:8787/api/status
```

前端：

```bash
cd web
npm install
npm run dev      # http://localhost:5173
npm run build    # 产物在 web/dist
```

Docker（调度器 + 接口 + 前端一起跑）：

```bash
LLM_PROVIDER=deepseek LLM_MODEL=deepseek-chat LLM_API_KEY=sk-xxx docker compose up -d
```

## 自定义运行时间

运行时间写在 `automation/config.toml` 的 `[schedule]` 里，四种模式：

| mode | 用到的字段 | 例子 | 说明 |
| --- | --- | --- | --- |
| `daily` | `daily_times` | `["00:00", "12:30"]` | 每天定点，可以配多个时刻 |
| `cron` | `cron` | `"30 */6 * * 1-5"` | 标准 5 字段 cron，支持 `*/n`、区间、列表、星期名与 `@daily` 等宏 |
| `interval` | `interval_minutes` | `360` | 每 N 分钟跑一次，从上次运行开始算 |
| `manual` | — | — | 不自动运行，只接受手动或接口触发 |

配套字段：`timezone`（默认 `Asia/Shanghai`）、`jitter_seconds`（触发时随机延迟，避开整点拥塞）、
`catch_up`（进程重启后补跑错过的窗口）、`run_on_start`（启动即跑一次）、`enabled`。

三种改法，效果相同：

```bash
# 改配置文件
vim automation/config.toml

# 用命令行改（写入 automation/state/overrides.json，覆盖配置文件）
python -m jobsinsight set-schedule --at 08:30,20:30
python -m jobsinsight set-schedule --cron "30 */6 * * 1-5"
python -m jobsinsight set-schedule --every 90
python -m jobsinsight set-schedule --disable

# 运行中通过接口改，立即生效（前端「自动化运行」面板里也能改）
curl -X PUT localhost:8787/api/schedule \
     -H 'Content-Type: application/json' \
     -d '{"mode":"daily","daily_times":["08:30","20:30"]}'
```

GitHub Actions 的 cron 只能写死在 YAML 里而且是 UTC，所以工作流用一个较粗的触发频率，
真正「是否该跑」交给 `run --if-due` 按你的配置判断。改完运行时间后执行
`python -m jobsinsight sync-cron`，会把 workflow 里的 cron 同步成对应的 UTC 时刻。

## LLM 调用接口

配置换一下 `provider` / `model` / `api_key` 就能切换厂商：

```toml
[llm]
provider = "deepseek"        # 或 openai / moonshot / dashscope / zhipu / siliconflow / groq / ollama / anthropic / mock
model = "deepseek-chat"
api_key = "${DEEPSEEK_API_KEY}"
```

- **OpenAI 兼容协议**：OpenAI、DeepSeek、Kimi/Moonshot、通义千问、智谱 GLM、SiliconFlow、
  Groq、vLLM、Ollama、LM Studio……自建网关填 `base_url` 即可。
- **Anthropic Messages API**：`provider = "anthropic"`。
- **`mock`**：内置离线实现，不联网、不需要 Key，用来先把流程跑通和跑测试。

调用层统一提供：可重试的指数退避（含抖动）、限流最小间隔、JSON 模式与一次自动修复、
token 用量统计。**任何一步 LLM 失败都不会让运行失败**——会退回 `heuristics.py` 的规则解析，
照样产出完整数据，并把原因记进运行报告。

LLM 在流水线里做三件事：规范化岗位字段（薪资、经验、学历、级别、技能、方向、相关度、
一句话摘要）、生成每日洞察、以及 `html_llm` 数据源里的网页岗位抽取。

自定义厂商：

```python
from jobsinsight.llm import register_provider, LLMProvider

class MyProvider(LLMProvider):
    name = "my-gateway"
    def complete(self, request): ...

register_provider("my-gateway", lambda options: MyProvider(**options))
```

## 数据源

`[[sources]]` 可以配多个，单个来源失败不影响整次运行：

| type | 用途 |
| --- | --- |
| `fixture` | 读本地 JSON（默认，离线可用；也用来回放已保存的抓取结果） |
| `json_api` | 任意 JSON 接口，字段通过 `options.field_map` 映射，支持分页与 Cookie |
| `html_llm` | 抓网页转成纯文本，交给 LLM 抽取结构化岗位 |
| `browser` | 可选 Playwright；使用你授权的账号或已保存会话读取动态页面 |

51job / Boss直聘 / 猎聘 的搜索接口地址、参数与 Cookie 因账号而异且会变，
所以**不写死在代码里**，而是放在配置中（`automation/config.toml` 里有注释掉的示例）。
仓库默认使用 `automation/data/seed_postings.json` 作为示例数据源，开箱即可跑通。

需要登录的网站可复制 `automation/config/accounts.example.toml` 为
`accounts.toml`，账号密码通过环境变量传入，再执行
`python -m jobsinsight browser-login <账号名>` 人工完成首次登录。私密配置和浏览器
Cookie 均被 Git 忽略。该采集器不会规避验证码、风控或平台访问限制；请遵守平台条款。

生产来源建议设置 `required = true` 和合理的 `min_collected`。必需来源失败、采集量
异常或数据质量低于 `output.min_quality_score` 时，流水线会保留上一版有效数据，
并把连续失败次数写入 `automation/state/sources_health.json`。

## HTTP 控制接口

`python -m jobsinsight serve` 之后：

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/health` | 健康检查 |
| GET | `/api/doctor` | 配置、来源、数据质量与新鲜度诊断 |
| GET | `/api/status` | 调度状态、LLM 配置、数据源、最近一次运行 |
| GET | `/api/config` | 脱敏后的完整配置 |
| GET | `/api/schedule` | 当前运行时间与未来 5 次触发时刻 |
| PUT | `/api/schedule` | 修改运行时间，立即生效并持久化 |
| GET | `/api/runs` · `/api/runs/latest` | 运行历史 |
| POST | `/api/runs` | 立即触发一次运行（`dry_run`、`limit`、`async`） |
| POST | `/api/llm/chat` | 透传调用 LLM（`prompt` 或 `messages`） |
| POST | `/api/llm/ask` | 基于当前数据问答 |
| GET | `/api/data/<name>.json` | 读取产出的数据文件 |

配置了 `server.auth_token` 后，写操作需要 `Authorization: Bearer <token>`；读接口保持开放，
方便前端轮询状态。

## 产出的数据

写入 `web/public/data/`，原子写入，前端直接 fetch：

- `jobs.json` —— 规范化后的岗位列表
- `stats.json` —— 平台/城市/技能/经验/学历/级别/方向/薪资分布等聚合结果，含今日新增、更新、下架
- `insights.json` —— 每日洞察（模型撰写或统计规则生成）+ 运行时间与上次运行信息
- `manifest.json` —— 本轮 run ID、数据版本、有效条数、来源与文件清单

`manifest.json` 同时包含 `quality`（0–100 分、缺失字段与警告）和 `freshness`
（最新/最旧发布日期、中位数据年龄、过期数量）。前端状态条会显示这些信息；
`/api/health`、`/api/status` 和 `/api/doctor` 可供监控系统读取。

运行状态在 `automation/state/`（不入库）：`state.json`（上次运行时间）、`runs.json`（运行历史）、
`jobs_snapshot.json`（用于算增量）、`sources_health.json`（来源健康历史）和
`overrides.json`（运行时改过的配置）。

## 配置的优先级

后面的覆盖前面的：内置默认值 → 配置文件（`config.toml` / `.json` / `.yaml`）→
环境变量（`JOBSINSIGHT_*`，以及字符串里的 `${VAR}` / `${VAR:-默认值}`）→
运行时覆盖（`automation/state/overrides.json`，由 CLI 或接口写入）。

常用环境变量：`JOBSINSIGHT_LLM_API_KEY`、`JOBSINSIGHT_LLM_PROVIDER`、`JOBSINSIGHT_LLM_MODEL`、
`JOBSINSIGHT_SCHEDULE_MODE`、`JOBSINSIGHT_SCHEDULE_DAILY_TIMES`、`JOBSINSIGHT_SCHEDULE_CRON`、
`JOBSINSIGHT_SERVER_PORT`、`JOBSINSIGHT_SERVER_AUTH_TOKEN`。API Key 不要写进仓库。

## 生产部署检查

1. 对真实来源设置 `required = true` 和合理的 `min_collected`，避免登录过期时发布空数据。
2. 设置 `output.min_quality_score`（建议先观察实际质量分，再逐步提高门槛）。
3. 把 API Key、账号密码和 `server.auth_token` 放入 Secret 或环境变量，不提交到 Git。
4. 首次部署运行 `python -m jobsinsight run`，确认 `manifest.json` 和来源健康记录已生成。
5. 执行 `python -m jobsinsight doctor --strict`；生产环境应处理完全部警告。
6. 通过 `/api/health` 监控数据年龄和最近运行状态，通过 `/api/doctor` 查看具体故障。

## 开发

```bash
cd automation
python -m pytest          # 单元测试
python -m ruff check .     # lint
python -m ruff format .    # 格式化
python -m jobsinsight run --dry-run   # 跑完整流程但不写文件

cd ../web
npm run lint && npm run build
```

更多后端细节见 [automation/README.md](automation/README.md)，前端说明见 [web/README.md](web/README.md)。

## 目录结构

```
automation/                 自动化后端（Python，零依赖）
├── config.toml             运行时间、LLM、数据源、产出、接口配置
├── config/                 私密账号配置示例（真实 accounts.toml 不入库）
├── data/                   示例数据源
├── jobsinsight/
│   ├── cli.py              命令行入口
│   ├── config.py           配置加载与校验
│   ├── cron.py             5 字段 cron 解析
│   ├── scheduler.py        运行时间计算与调度守护
│   ├── collectors/         数据源（fixture / json_api / html_llm / browser）
│   ├── llm/                统一 LLM 调用接口
│   ├── diagnostics.py      doctor 预检与故障定位
│   ├── quality.py          数据质量和岗位新鲜度
│   ├── enrich.py           LLM 富化 + 洞察
│   ├── heuristics.py       规则兜底
│   ├── analysis.py         统计聚合
│   ├── pipeline.py         完整流水线
│   ├── server.py           HTTP 控制接口
│   └── workflow.py         同步 GitHub Actions cron
└── tests/                  pytest

web/                        前端看板（React + TypeScript + Vite）
├── public/data/            流水线产出的 JSON
└── src/
    ├── App.tsx             看板主体
    ├── components/AutomationPanel.tsx   自动化状态与洞察面板
    ├── components/DataStatusBar.tsx     数据版本、质量与来源状态
    ├── hooks/useAutomation.ts
    └── lib/automation.ts   自动化接口客户端
```

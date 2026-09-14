# 医药健康+AI岗位洞察平台

[![React](https://img.shields.io/badge/React-19-61DAFB?logo=react)](https://react.dev/)
[![TypeScript](https://img.shields.io/badge/TypeScript-5.9-3178C6?logo=typescript)](https://www.typescriptlang.org/)
[![Vite](https://img.shields.io/badge/Vite-7-646CFF?logo=vite)](https://vite.dev/)
[![Tailwind CSS](https://img.shields.io/badge/Tailwind%20CSS-3.4-06B6D4?logo=tailwindcss)](https://tailwindcss.com/)

> 聚合 51job、Boss直聘、猎聘网数据，解码医药健康+AI行业人才趋势

看板本身不做采集：`public/data/*.json` 全部由仓库根目录的
[`automation/`](../automation/README.md) 流水线按设定时间自动产出。

## 🌟 功能特性

### 📊 数据可视化
- **平台生态概览** - 三大招聘平台数据对比
- **薪资分布洞察** - 行业薪资水平与分布分析
- **地域机会分布** - 各城市岗位数量与薪资对比
- **核心技能图谱** - 热门技能需求排行
- **经验要求分析** - 不同经验段的岗位分布

### 🔍 智能筛选与排序
- **多维度筛选** - 工作年限、学历、岗位等级、城市、平台
- **关键词搜索** - 岗位名称、技能、概述搜索
- **智能排序** - 发布时间、薪资、公司体量、岗位等级
- **自动去重** - 同一公司相同岗位只保留最新发布

### 🔄 自动化运行面板
- 展示后台流水线的运行时间与下一次触发时刻
- 展示上次运行结果：状态、耗时、今日新增 / 更新 / 下架
- 展示每日洞察（LLM 撰写，或未配置 LLM 时由统计规则生成）
- 控制接口在线时可直接触发运行、切换运行时间（每天定点 / cron / 固定间隔 / 仅手动）
- 接口不可用时自动降级为只读，页面其余部分不受影响

### 👔 猎头资源
- **专业猎头顾问** - 点击头像进入招聘网站主页
- **知名猎头机构** - 点击机构访问官网
- 覆盖医药健康+AI领域专业猎头

## 🛠 技术栈

- **前端框架**: React 18 + TypeScript
- **构建工具**: Vite 5
- **样式方案**: Tailwind CSS 3.4
- **UI组件**: shadcn/ui
- **数据可视化**: Recharts
- **动画效果**: Framer Motion
- **图标库**: Lucide React

## 📁 项目结构

```
web/
├── public/
│   └── data/                   # 由 automation/ 流水线产出
│       ├── jobs.json           # 岗位数据
│       ├── stats.json          # 统计数据
│       ├── insights.json       # 每日洞察 + 运行时间与上次运行信息
│       ├── headhunters.json    # 猎头数据
│       └── agencies.json       # 猎头机构数据
├── src/
│   ├── App.tsx                 # 主应用组件
│   ├── components/
│   │   ├── AutomationPanel.tsx # 自动化状态与洞察面板
│   │   └── ui/                 # shadcn/ui 组件（按上游原样保留）
│   ├── hooks/
│   │   └── useAutomation.ts    # 汇总静态洞察 + 实时接口状态
│   ├── lib/
│   │   └── automation.ts       # 自动化接口客户端与类型
│   ├── App.css                 # 全局样式
│   ├── index.css               # 入口样式
│   └── main.tsx                # 入口文件
├── index.html
├── package.json
├── tsconfig.json
├── tailwind.config.js
└── vite.config.ts
```

## 🚀 快速开始

### 环境要求
- Node.js >= 18.0.0
- npm >= 9.0.0

### 安装依赖

```bash
npm install
```

### 开发模式

```bash
npm run dev
```

### 生产构建

```bash
npm run build
```

### 预览生产构建

```bash
npm run preview
```

### 连接自动化接口

岗位、统计和洞察会优先读取实时 `/api/data/*.json`；后端不可用时自动回退到
`BASE_URL/data/*.json` 静态快照，因此部署在 GitHub Pages 子路径时也能正确加载。
关键数据失败会显示具体错误和重试入口，猎头/机构等可选文件失败不会让页面永久 Loading。
自动化面板再请求 `/api/status`，接口在线时才显示「立即运行」与运行时间编辑器。

页面顶部的数据状态条读取 `manifest.json`，持续展示 API/静态来源、数据版本、
产出时间、有效条数和质量分。超过 48 小时、流水线部分失败或来源异常时会显示黄色警告。

- `python -m jobsinsight serve` 会同时托管 `web/dist` 与 `/api/*`，同源，无需额外配置。
- `npm run dev` 已将 `/api` 代理到 `127.0.0.1:8787`；不同地址时用环境变量覆盖：

```bash
# web/.env.local
VITE_AUTOMATION_API=http://127.0.0.1:8787
VITE_AUTOMATION_TOKEN=   # 后端配置了 server.auth_token 时填
```

## 📊 数据结构

### 岗位数据 (Job)

```typescript
interface Job {
  id: number
  platform: string           // 招聘平台
  title: string              // 岗位名称
  company: string            // 公司名称
  company_scale_value: number // 公司体量评分
  company_scale: string      // 公司规模
  company_level: string      // 公司级别
  city: string               // 城市
  salary_min: number         // 最低薪资(K)
  salary_max: number         // 最高薪资(K)
  experience: string         // 工作经验
  education: string          // 学历要求
  job_level: string          // 岗位等级
  summary: string            // 岗位概述
  skills: string[]           // 技能要求
  publish_date: string       // 发布日期
  update_date: string        // 更新日期
  status: 'active' | 'deleted' | 'updated'
  // 以下为流水线附加的元信息
  url: string                // 原始岗位链接
  category: string           // 岗位方向，如 AI药物研发 / 医学影像AI
  relevance: number          // 与「医药健康 + AI」的相关度 0-100
  enriched_by: 'llm' | 'heuristic'  // 字段由模型规范化还是规则解析
}
```

### 洞察数据 (Insights)

```typescript
interface AutomationInsights {
  generated_at: string       // 产出时间
  provider: string           // LLM provider，未启用时为 disabled
  model: string
  source: 'llm' | 'rules'    // 模型撰写 / 统计规则生成
  schedule: {                // 运行时间
    mode: 'daily' | 'cron' | 'interval' | 'manual'
    description: string      // 如「每天 00:00 (Asia/Shanghai)」
    timezone: string
    next_run: string
  }
  run: { total_jobs: number; new_jobs: number; updated_jobs: number; deleted_jobs: number }
  headline: string
  summary: string
  highlights: string[]       // 数据发现
  hot_skills: string[]       // 值得投入的技能
  advice: string[]           // 求职建议
}
```

### 猎头数据 (Headhunter)

```typescript
interface Headhunter {
  id: number
  name: string               // 猎头姓名
  avatar: string             // 头像URL
  company: string            // 所属公司
  company_url: string        // 公司URL
  profile_url: string        // 个人主页URL
  platform: string           // 所在平台
  specialty: string          // 专业领域
  experience: string         // 从业经验
}
```

### 猎头机构数据 (Agency)

```typescript
interface Agency {
  id: number
  name: string               // 机构名称
  logo: string               // Logo URL
  website: string            // 官网URL
  description: string        // 机构描述
  platforms: string[]        // 覆盖平台
}
```

## 🎨 设计特色

- **深色科技风** - 深蓝底色搭配科技蓝渐变
- **流畅动画** - Framer Motion实现滚动触发动画
- **玻璃拟态** - 半透明卡片与模糊背景效果
- **响应式设计** - 完美适配桌面与移动设备

## 📝 更新日志

### v2.0.0
- ✨ 新增「自动化运行」面板：运行时间、上次运行结果、每日洞察
- ✨ 面板可直接触发后台流水线运行、在线修改运行时间
- 🔧 数据改为由 `automation/` 流水线自动产出，不再手工维护
- 🔧 Hero 的「每日自动更新」按钮改为真正触发一次流水线运行

### v1.1.0 (2024-02-19)
- ✨ 新增猎头资源板块
- ✨ 新增薪资区间分布详情Tooltip
- ✨ 新增每日更新按钮交互
- 🔧 将"公司实力"改为"公司体量"

### v1.0.0 (2024-02-19)
- 🎉 项目初始发布
- ✨ 岗位数据可视化
- ✨ 智能筛选与排序
- ✨ 每日自动更新

## 📄 许可证

MIT License © 2024 医药健康AI人才洞察平台

## 🤝 贡献

欢迎提交Issue和Pull Request！

---

> 💡 **提示**: 仓库自带的 `public/data/*.json` 由 `automation/` 流水线从示例数据源产出，用于演示。接上真实招聘接口或 LLM 后，重新跑一次流水线即可替换。

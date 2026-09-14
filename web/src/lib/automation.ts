/**
 * 自动化后端（automation/ 里的 jobsinsight）的前端客户端。
 *
 * 数据文件（insights.json）是静态产出，任何部署方式下都能读到；
 * /api/* 只有在跑了 `python -m jobsinsight serve` 时才存在，
 * 所以这里把两者分开：读不到接口时页面依然完整，只是不显示控制按钮。
 *
 * 接口地址默认同源，可用 VITE_AUTOMATION_API 指向别处，
 * 写操作的令牌用 VITE_AUTOMATION_TOKEN 提供（对应 server.auth_token）。
 */

export type ScheduleMode = 'daily' | 'cron' | 'interval' | 'manual'

export interface RunDiff {
  new_jobs: number
  updated_jobs: number
  deleted_jobs: number
  unchanged_jobs: number
}

export interface AutomationInsights {
  generated_at: string
  provider: string
  model: string
  schedule: {
    mode: ScheduleMode
    description: string
    timezone: string
    next_run: string
  }
  run: { total_jobs: number } & Partial<RunDiff>
  /** llm = 模型撰写；rules = 由统计规则生成（未配置 LLM 或调用失败时） */
  source?: 'llm' | 'rules'
  headline?: string
  summary?: string
  highlights?: string[]
  hot_skills?: string[]
  advice?: string[]
}

export type DataOrigin = 'api' | 'static'

export interface ManifestSource {
  name: string
  type: string
  required?: boolean
  status: 'ok' | 'error'
  collected: number
  items_before_dedupe?: number
  duration_ms?: number
  error?: string
}

export interface DataManifest {
  schema_version: number
  run_id: string
  data_version: string
  generated_at: string
  status: 'success' | 'partial' | 'failed' | 'skipped'
  counts: { raw: number; valid: number; dropped: number }
  sources: ManifestSource[]
  quality?: {
    score: number
    warnings: string[]
    missing_company: number
    missing_salary: number
    missing_url: number
    missing_publish_date: number
    duplicate_fingerprints: number
  }
  freshness?: {
    newest_publish_date: string
    oldest_publish_date: string
    median_age_days: number | null
    stale_over_30d: number
    future_dated: number
    missing_publish_date: number
  }
  files: string[]
}

export interface DataResult<T> {
  data: T
  origin: DataOrigin
}

export interface ScheduleInfo {
  enabled: boolean
  mode: ScheduleMode
  timezone: string
  daily_times: string[]
  cron: string
  interval_minutes: number
  description: string
  cron_equivalent: string
  next_runs: string[]
}

export interface RunReport {
  run_id: string
  trigger: string
  started_at: string
  finished_at: string
  duration_seconds: number
  status: 'success' | 'partial' | 'failed' | 'skipped'
  collected: number
  kept: number
  dropped_low_relevance: number
  diff: Partial<RunDiff>
  insights_generated: boolean
  published?: boolean
  quality?: DataManifest['quality']
  freshness?: DataManifest['freshness']
  dry_run: boolean
  errors: string[]
}

export interface AutomationStatus {
  now: string
  running: boolean
  current_run_id?: string | null
  scheduler_active: boolean
  schedule: ScheduleInfo
  llm: {
    enabled: boolean
    provider: string
    model: string
    api_key_configured: boolean
    enrich_jobs: boolean
    generate_insights: boolean
  }
  sources: Array<{ name: string; type: string; enabled: boolean }>
  last_run: RunReport | null
  data?: {
    status: 'ok' | 'degraded' | 'unavailable'
    age_hours: number | null
    manifest: DataManifest | null
  }
  sources_health?: {
    schema_version: number
    updated_at: string
    sources: Record<
      string,
      {
        type: string
        required: boolean
        last_status: 'ok' | 'error'
        last_collected: number
        last_success_at?: string
        last_error?: string
        consecutive_failures: number
      }
    >
  }
}

export type ScheduleUpdate = Partial<
  Pick<ScheduleInfo, 'enabled' | 'mode' | 'timezone' | 'daily_times' | 'cron' | 'interval_minutes'>
>

const API_BASE = (import.meta.env.VITE_AUTOMATION_API ?? '').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_AUTOMATION_TOKEN ?? ''
const STATIC_BASE = import.meta.env.BASE_URL || './'

export class AutomationApiError extends Error {}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const headers = new Headers(init?.headers)
  if (init?.body) headers.set('Content-Type', 'application/json')
  if (API_TOKEN) headers.set('Authorization', `Bearer ${API_TOKEN}`)

  const response = await fetch(`${API_BASE}${path}`, { ...init, headers })
  const text = await response.text()
  let payload: unknown = null
  try {
    payload = text ? JSON.parse(text) : null
  } catch {
    throw new AutomationApiError(`${path} 返回的不是 JSON（HTTP ${response.status}）`)
  }

  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload && 'error' in payload
        ? String(payload.error)
        : `请求失败（HTTP ${response.status}）`
    throw new AutomationApiError(message)
  }
  return payload as T
}

/**
 * 优先读实时 API；本项目部署为纯静态站点时，回退到 Vite BASE_URL 下的
 * data 快照。不能使用 `/data/...`，否则 GitHub Pages 子目录会 404。
 */
export async function fetchDataFileWithMeta<T>(name: string): Promise<DataResult<T>> {
  const errors: string[] = []
  try {
    return { data: await request<T>(`/api/data/${name}.json`), origin: 'api' }
  } catch (cause) {
    errors.push(cause instanceof Error ? cause.message : String(cause))
  }

  const staticUrl = `${STATIC_BASE}data/${name}.json`
  try {
    const response = await fetch(staticUrl, { cache: 'no-store' })
    if (!response.ok) throw new Error(`HTTP ${response.status}`)
    const type = response.headers.get('content-type') ?? ''
    if (type && !type.includes('json')) throw new Error(`返回类型是 ${type}，不是 JSON`)
    return { data: (await response.json()) as T, origin: 'static' }
  } catch (cause) {
    errors.push(`${staticUrl}: ${cause instanceof Error ? cause.message : String(cause)}`)
  }
  throw new AutomationApiError(`无法加载 ${name}.json：${errors.join('；')}`)
}

export async function fetchDataFile<T>(name: string): Promise<T> {
  return (await fetchDataFileWithMeta<T>(name)).data
}

export async function fetchManifest(): Promise<DataResult<DataManifest> | null> {
  try {
    return await fetchDataFileWithMeta<DataManifest>('manifest')
  } catch {
    return null
  }
}

/** 静态/实时洞察均不可用时返回 null，不影响岗位主数据。 */
export async function fetchInsights(): Promise<AutomationInsights | null> {
  try {
    return await fetchDataFile<AutomationInsights>('insights')
  } catch {
    return null
  }
}

export const fetchStatus = () => request<AutomationStatus>('/api/status')

export const triggerRun = (options: { trigger?: string; limit?: number } = {}) =>
  request<RunReport>('/api/runs', {
    method: 'POST',
    body: JSON.stringify({ trigger: 'web', ...options }),
  })

export const updateSchedule = (updates: ScheduleUpdate) =>
  request<ScheduleInfo>('/api/schedule', { method: 'PUT', body: JSON.stringify(updates) })

export const askLLM = (question: string) =>
  request<{ question: string; answer: string }>('/api/llm/ask', {
    method: 'POST',
    body: JSON.stringify({ question }),
  })

/** 把 ISO 时间显示成本地可读格式；拿不到就原样返回。 */
export function formatMoment(value: string | undefined | null): string {
  if (!value) return '—'
  const parsed = new Date(value)
  if (Number.isNaN(parsed.getTime())) return value
  return parsed.toLocaleString('zh-CN', {
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

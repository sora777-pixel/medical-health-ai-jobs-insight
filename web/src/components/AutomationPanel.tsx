import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import {
  AlertCircle,
  Bot,
  CalendarClock,
  CheckCircle2,
  Clock,
  Database,
  Lightbulb,
  Play,
  Save,
  Sparkles,
  TrendingUp,
} from 'lucide-react'

import { formatMoment, type DataManifest, type ScheduleMode, type ScheduleUpdate } from '@/lib/automation'
import type { UseAutomation } from '@/hooks/useAutomation'

const MODE_LABELS: Record<ScheduleMode, string> = {
  daily: '每天定点',
  cron: 'cron 表达式',
  interval: '固定间隔',
  manual: '仅手动触发',
}

const RUN_STATUS_STYLES: Record<string, { label: string; className: string }> = {
  success: { label: '成功', className: 'text-[#00B578]' },
  partial: { label: '部分成功', className: 'text-[#F5B935]' },
  failed: { label: '失败', className: 'text-[#FF6B6B]' },
  skipped: { label: '已跳过', className: 'text-white/60' },
}

interface Props {
  automation: UseAutomation
  manifest?: DataManifest | null
}

/**
 * 自动化面板：展示运行时间、上一次运行结果与 LLM 洞察，
 * 在控制接口可用时还能直接触发运行、修改运行时间。
 */
export function AutomationPanel({ automation, manifest }: Props) {
  const { insights, status, online, running, error, lastRun, runNow, changeSchedule } = automation
  const schedule = status?.schedule
  const scheduleText = schedule?.description ?? insights?.schedule?.description ?? '未配置'
  const nextRun = schedule?.next_runs?.[0] ?? insights?.schedule?.next_run
  const sourceRuns = status?.data?.manifest?.sources ?? manifest?.sources ?? []
  const failedSources = sourceRuns.filter((source) => source.status === 'error')
  const collected = sourceRuns.reduce((total, source) => total + source.collected, 0)

  if (!insights && !online) return null

  return (
    <section className="py-20 px-4 bg-white/5">
      <div className="max-w-7xl mx-auto">
        <motion.div
          initial={{ opacity: 0, x: -50 }}
          whileInView={{ opacity: 1, x: 0 }}
          viewport={{ once: true }}
          className="mb-12"
        >
          <div className="flex items-center gap-3 mb-4">
            <h2 className="text-3xl md:text-4xl font-bold">自动化运行</h2>
            <span
              className={`px-3 py-1 rounded-full text-xs border ${
                online
                  ? 'bg-[#00B578]/20 border-[#00B578]/40 text-[#00B578]'
                  : 'bg-white/5 border-white/20 text-white/50'
              }`}
            >
              {online ? '接口在线' : '只读模式'}
            </span>
          </div>
          <p className="text-white/60">
            数据由后台流水线定时采集、LLM 规范化后产出，运行时间可以自己设定
          </p>
        </motion.div>

        <div className="grid lg:grid-cols-2 gap-6">
          <motion.div
            initial={{ opacity: 0, y: 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="rounded-2xl bg-white/5 border border-white/10 p-6 space-y-5"
          >
            <div className="flex items-start justify-between gap-4">
              <div>
                <div className="flex items-center gap-2 text-white/60 text-sm mb-1">
                  <CalendarClock className="w-4 h-4" />
                  运行时间
                </div>
                <div className="text-xl font-semibold">{scheduleText}</div>
                <div className="text-sm text-white/50 mt-1">
                  下一次：{formatMoment(nextRun)}
                </div>
              </div>
              {online && (
                <button
                  onClick={() => void runNow()}
                  disabled={running}
                  className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#1B45F4] hover:bg-[#4D6CFA] disabled:opacity-50 disabled:cursor-not-allowed transition-colors shrink-0"
                >
                  <Play className="w-4 h-4" />
                  <span className="text-sm font-medium">{running ? '运行中…' : '立即运行'}</span>
                </button>
              )}
            </div>

            <div className="grid sm:grid-cols-2 gap-3">
              <InfoTile
                icon={<Clock className="w-4 h-4" />}
                label="上次运行"
                value={formatMoment(lastRun?.finished_at ?? insights?.generated_at)}
                hint={
                  lastRun
                    ? `${RUN_STATUS_STYLES[lastRun.status]?.label ?? lastRun.status} · ${lastRun.duration_seconds}s`
                    : undefined
                }
                hintClassName={lastRun ? RUN_STATUS_STYLES[lastRun.status]?.className : undefined}
              />
              <InfoTile
                icon={<TrendingUp className="w-4 h-4" />}
                label="上次产出"
                value={`${lastRun?.kept ?? insights?.run?.total_jobs ?? 0} 个岗位`}
                hint={
                  lastRun
                    ? `新增 ${lastRun.diff?.new_jobs ?? 0} · 更新 ${lastRun.diff?.updated_jobs ?? 0} · 下架 ${lastRun.diff?.deleted_jobs ?? 0}`
                    : undefined
                }
              />
              <InfoTile
                icon={<Bot className="w-4 h-4" />}
                label="LLM"
                value={
                  status?.llm?.enabled === false
                    ? '未启用（规则解析）'
                    : `${status?.llm?.provider ?? insights?.provider ?? '—'}`
                }
                hint={status?.llm?.model ?? insights?.model ?? undefined}
              />
              <InfoTile
                icon={<Database className="w-4 h-4" />}
                label="数据源"
                value={
                  sourceRuns.length
                    ? `${sourceRuns.length - failedSources.length} 正常 / ${failedSources.length} 失败`
                    : status
                    ? `${status.sources.filter((source) => source.enabled).length} / ${status.sources.length} 启用`
                    : '按配置采集'
                }
                hint={sourceRuns.length ? `本轮采集 ${collected} 条` : status?.sources.map((source) => source.name).join('、')}
              />
            </div>

            {lastRun?.errors?.length ? (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-[#F5B935]/10 border border-[#F5B935]/30 text-sm text-[#F5B935]">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="space-y-1">
                  {lastRun.errors.slice(0, 3).map((message) => (
                    <div key={message}>{message}</div>
                  ))}
                </div>
              </div>
            ) : null}

            {!lastRun?.errors?.length && failedSources.length > 0 ? (
              <div className="flex items-start gap-2 p-3 rounded-lg bg-[#F5B935]/10 border border-[#F5B935]/30 text-sm text-[#F5B935]">
                <AlertCircle className="w-4 h-4 mt-0.5 shrink-0" />
                <div className="space-y-1">
                  {failedSources.slice(0, 3).map((source) => (
                    <div key={source.name}>{source.error || `${source.name} 采集失败`}</div>
                  ))}
                </div>
              </div>
            ) : null}

            {error && (
              <div className="flex items-center gap-2 p-3 rounded-lg bg-[#FF6B6B]/10 border border-[#FF6B6B]/30 text-sm text-[#FF6B6B]">
                <AlertCircle className="w-4 h-4 shrink-0" />
                {error}
              </div>
            )}

            {online && schedule && <ScheduleEditor schedule={schedule} onSave={changeSchedule} />}
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 40 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            transition={{ delay: 0.1 }}
            className="rounded-2xl bg-gradient-to-br from-[#1B45F4]/20 to-transparent border border-white/10 p-6"
          >
            <div className="flex items-center gap-2 text-white/60 text-sm mb-3">
              <Sparkles className="w-4 h-4 text-[#F5B935]" />
              {insights?.source === 'rules' ? '每日洞察（统计规则）' : 'LLM 每日洞察'}
            </div>

            {insights?.headline ? (
              <>
                <h3 className="text-2xl font-bold mb-3 leading-snug">{insights.headline}</h3>
                {insights.summary && (
                  <p className="text-white/70 leading-relaxed mb-5">{insights.summary}</p>
                )}

                {insights.highlights?.length ? (
                  <ul className="space-y-2 mb-5">
                    {insights.highlights.map((item) => (
                      <li key={item} className="flex items-start gap-2 text-sm text-white/80">
                        <CheckCircle2 className="w-4 h-4 text-[#00B578] mt-0.5 shrink-0" />
                        {item}
                      </li>
                    ))}
                  </ul>
                ) : null}

                {insights.hot_skills?.length ? (
                  <div className="flex flex-wrap gap-2 mb-5">
                    {insights.hot_skills.map((skill) => (
                      <span
                        key={skill}
                        className="px-3 py-1 rounded-full text-xs bg-white/10 border border-white/10"
                      >
                        {skill}
                      </span>
                    ))}
                  </div>
                ) : null}

                {insights.advice?.length ? (
                  <div className="space-y-2 pt-4 border-t border-white/10">
                    {insights.advice.map((item) => (
                      <div key={item} className="flex items-start gap-2 text-sm text-white/70">
                        <Lightbulb className="w-4 h-4 text-[#F5B935] mt-0.5 shrink-0" />
                        {item}
                      </div>
                    ))}
                  </div>
                ) : null}
              </>
            ) : (
              <p className="text-white/60 text-sm leading-relaxed">
                还没有 LLM 洞察。在 <code className="text-white/80">automation/config.toml</code> 里把{' '}
                <code className="text-white/80">[llm]</code> 换成真实的 provider 与 API Key，
                下一次运行就会生成。
              </p>
            )}

            {insights?.generated_at && (
              <div className="text-xs text-white/40 mt-5">
                生成于 {formatMoment(insights.generated_at)} ·{' '}
                {insights.source === 'llm' ? `${insights.provider} / ${insights.model}` : '统计规则'}
              </div>
            )}
          </motion.div>
        </div>
      </div>
    </section>
  )
}

interface InfoTileProps {
  icon: React.ReactNode
  label: string
  value: string
  hint?: string
  hintClassName?: string
}

function InfoTile({ icon, label, value, hint, hintClassName }: InfoTileProps) {
  return (
    <div className="rounded-xl bg-white/5 border border-white/10 p-4">
      <div className="flex items-center gap-2 text-white/50 text-xs mb-2">
        {icon}
        {label}
      </div>
      <div className="font-semibold truncate" title={value}>
        {value}
      </div>
      {hint && (
        <div className={`text-xs mt-1 truncate ${hintClassName ?? 'text-white/40'}`} title={hint}>
          {hint}
        </div>
      )}
    </div>
  )
}

interface EditorProps {
  schedule: NonNullable<UseAutomation['status']>['schedule']
  onSave: (updates: ScheduleUpdate) => Promise<boolean>
}

/** 运行时间编辑器：改完立即生效并写入 state/overrides.json。 */
function ScheduleEditor({ schedule, onSave }: EditorProps) {
  const [mode, setMode] = useState<ScheduleMode>(schedule.mode)
  const [times, setTimes] = useState(schedule.daily_times.join(', '))
  const [cron, setCron] = useState(schedule.cron)
  const [interval, setInterval] = useState(String(schedule.interval_minutes))
  const [saving, setSaving] = useState(false)
  const [saved, setSaved] = useState(false)

  useEffect(() => {
    setMode(schedule.mode)
    setTimes(schedule.daily_times.join(', '))
    setCron(schedule.cron)
    setInterval(String(schedule.interval_minutes))
  }, [schedule])

  const save = async () => {
    setSaving(true)
    setSaved(false)
    const updates: ScheduleUpdate = { mode, enabled: true }
    if (mode === 'daily') {
      updates.daily_times = times
        .split(/[,，]/)
        .map((item) => item.trim())
        .filter(Boolean)
    } else if (mode === 'cron') {
      updates.cron = cron.trim()
    } else if (mode === 'interval') {
      updates.interval_minutes = Number(interval) || 0
    }

    const ok = await onSave(updates)
    setSaving(false)
    setSaved(ok)
    if (ok) window.setTimeout(() => setSaved(false), 3000)
  }

  return (
    <div className="pt-5 border-t border-white/10 space-y-3">
      <div className="text-sm text-white/60">修改运行时间</div>

      <div className="flex flex-wrap gap-2">
        {(Object.keys(MODE_LABELS) as ScheduleMode[]).map((option) => (
          <button
            key={option}
            onClick={() => setMode(option)}
            className={`px-3 py-1.5 rounded-lg text-sm transition-colors ${
              mode === option ? 'bg-[#1B45F4] text-white' : 'bg-white/10 text-white/70 hover:bg-white/20'
            }`}
          >
            {MODE_LABELS[option]}
          </button>
        ))}
      </div>

      <div className="flex flex-wrap items-center gap-3">
        {mode === 'daily' && (
          <LabelledInput
            label="每天"
            value={times}
            onChange={setTimes}
            placeholder="00:00, 12:30"
            hint={`时区 ${schedule.timezone}`}
          />
        )}
        {mode === 'cron' && (
          <LabelledInput
            label="cron"
            value={cron}
            onChange={setCron}
            placeholder="30 */6 * * 1-5"
            hint="分 时 日 月 周"
          />
        )}
        {mode === 'interval' && (
          <LabelledInput
            label="每"
            value={interval}
            onChange={setInterval}
            placeholder="360"
            hint="分钟"
            type="number"
          />
        )}
        {mode === 'manual' && <div className="text-sm text-white/50">不再自动运行，只能手动触发。</div>}

        <button
          onClick={() => void save()}
          disabled={saving}
          className="flex items-center gap-2 px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 disabled:opacity-50 transition-colors text-sm"
        >
          <Save className="w-4 h-4" />
          {saving ? '保存中…' : '保存'}
        </button>

        {saved && <span className="text-sm text-[#00B578]">已保存，立即生效</span>}
      </div>
    </div>
  )
}

interface LabelledInputProps {
  label: string
  value: string
  onChange: (value: string) => void
  placeholder?: string
  hint?: string
  type?: string
}

function LabelledInput({ label, value, onChange, placeholder, hint, type = 'text' }: LabelledInputProps) {
  return (
    <label className="flex items-center gap-2 text-sm">
      <span className="text-white/50">{label}</span>
      <input
        type={type}
        value={value}
        placeholder={placeholder}
        onChange={(event) => onChange(event.target.value)}
        className="px-3 py-2 rounded-lg bg-[#0A1628] border border-white/20 focus:border-[#4D6CFA] outline-none w-44"
      />
      {hint && <span className="text-white/40 text-xs">{hint}</span>}
    </label>
  )
}

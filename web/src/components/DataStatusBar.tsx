import { AlertTriangle, CheckCircle2, Clock3, Database, GitCommitHorizontal } from 'lucide-react'
import { useState } from 'react'

import { formatMoment, type DataManifest, type DataOrigin } from '@/lib/automation'

interface Props {
  manifest: DataManifest | null
  origin: DataOrigin | null
}

const STATUS = {
  success: { label: '发布成功', className: 'text-[#00B578]', icon: CheckCircle2 },
  partial: { label: '部分来源失败', className: 'text-[#F5B935]', icon: AlertTriangle },
  failed: { label: '发布失败', className: 'text-[#FF6B6B]', icon: AlertTriangle },
  skipped: { label: '未发布', className: 'text-white/50', icon: Clock3 },
}

export function DataStatusBar({ manifest, origin }: Props) {
  const [renderedAt] = useState(() => Date.now())
  if (!manifest) return null

  const ageHours = Math.max(0, (renderedAt - new Date(manifest.generated_at).getTime()) / 3_600_000)
  const stale = Number.isFinite(ageHours) && ageHours > 48
  const status = STATUS[manifest.status] ?? STATUS.failed
  const StatusIcon = status.icon
  const failedSources = manifest.sources.filter((source) => source.status === 'error')

  return (
    <section className="px-4 -mt-8 relative z-20">
      <div className="max-w-7xl mx-auto rounded-2xl bg-[#101F38]/95 backdrop-blur border border-white/10 px-5 py-4 shadow-xl">
        <div className="flex flex-wrap items-center gap-x-6 gap-y-3 text-sm">
          <StatusIcon className={`w-4 h-4 ${status.className}`} />
          <span className={status.className}>{status.label}</span>
          <StatusItem
            icon={<Database className="w-4 h-4" />}
            label={origin === 'api' ? '实时 API' : '静态快照'}
          />
          <StatusItem icon={<Clock3 className="w-4 h-4" />} label={formatMoment(manifest.generated_at)} />
          <StatusItem
            icon={<GitCommitHorizontal className="w-4 h-4" />}
            label={`版本 ${manifest.data_version.slice(0, 8)}`}
            title={manifest.data_version}
          />
          <span className="text-white/50">
            质量 {manifest.quality?.score ?? '—'}/100 · 有效 {manifest.counts.valid} 条
          </span>
        </div>

        {(stale || failedSources.length > 0 || manifest.quality?.warnings?.length) && (
          <div className="mt-3 pt-3 border-t border-white/10 text-xs text-[#F5B935] flex flex-wrap gap-x-5 gap-y-1">
            {stale && <span>数据已超过 48 小时，请检查自动任务</span>}
            {failedSources.map((source) => (
              <span key={source.name}>
                {source.name}：{source.error || '采集失败'}
              </span>
            ))}
            {manifest.quality?.warnings?.slice(0, 2).map((warning) => <span key={warning}>{warning}</span>)}
          </div>
        )}
      </div>
    </section>
  )
}

function StatusItem({ icon, label, title }: { icon: React.ReactNode; label: string; title?: string }) {
  return (
    <span className="inline-flex items-center gap-1.5 text-white/60" title={title}>
      {icon}
      {label}
    </span>
  )
}

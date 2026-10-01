import { useEffect, useState } from 'react'

interface SourceRow {
  source: string
  status: string
  jobs_valid?: number
  valid?: number
  discovered?: number
  last_error?: string
  fallback?: string
}

interface ProviderRow {
  name: string
  configured: boolean
  healthy: boolean | string
}

const STYLE: Record<string, string> = {
  healthy: 'text-[#00B578]',
  degraded: 'text-[#F5B935]',
  blocked: 'text-[#F5B935]',
  auth_required: 'text-[#F5B935]',
  security_challenge: 'text-[#F5B935]',
  unavailable: 'text-white/50',
  disabled: 'text-white/40',
}

export function SourceHealthPanel() {
  const [rows, setRows] = useState<SourceRow[]>([])
  const [providers, setProviders] = useState<ProviderRow[]>([])
  const [offline, setOffline] = useState(false)

  useEffect(() => {
    let active = true
    void Promise.all([
      fetch('/api/sources/health').then((response) => (response.ok ? response.json() : Promise.reject(response.status))),
      fetch('/api/search/providers').then((response) => (response.ok ? response.json() : Promise.reject(response.status))),
    ])
      .then(([health, search]) => {
        if (!active) return
        const sources = (health as { sources?: Record<string, SourceRow> }).sources ?? {}
        setRows(Object.values(sources))
        setProviders((search as { providers?: ProviderRow[] }).providers ?? [])
      })
      .catch(() => {
        if (active) setOffline(true)
      })
    return () => {
      active = false
    }
  }, [])

  if (offline) return null

  return (
    <section className="px-4 pt-6">
      <div className="max-w-7xl mx-auto rounded-2xl border border-white/10 bg-white/5 px-5 py-4">
        <h2 className="text-lg font-semibold mb-3">Data Sources</h2>
        <div className="grid md:grid-cols-2 gap-4 text-sm">
          <div>
            <div className="text-white/40 mb-2">Search</div>
            {providers.map((provider) => (
              <div key={provider.name} className="flex justify-between gap-3 py-1">
                <span>{provider.name === 'ddgs' ? 'DuckDuckGo fallback' : provider.name}</span>
                <span className={provider.healthy === true ? 'text-[#00B578]' : 'text-[#F5B935]'}>
                  {provider.configured ? String(provider.healthy) : 'Not configured'}
                </span>
              </div>
            ))}
            {providers.length === 0 && <p className="text-white/40">搜索提供方状态会在接口在线后显示</p>}
          </div>
          <div>
            <div className="text-white/40 mb-2">Recruitment / Company Careers</div>
            {rows.length === 0 && <p className="text-white/40">还没有探测记录。可运行 python -m jobsinsight sources test --all</p>}
            {rows.map((row) => {
              const jobs = row.jobs_valid ?? row.valid ?? 0
              return (
                <div key={row.source} className="py-1">
                  <div className="flex justify-between gap-3">
                    <span>{row.source}</span>
                    <span className={STYLE[row.status] ?? 'text-white/60'}>
                      {row.status} · {jobs} jobs
                    </span>
                  </div>
                  {row.fallback && <p className="text-white/40">fallback: {row.fallback}</p>}
                  {row.last_error && <p className="text-white/40">原因: {row.last_error}</p>}
                </div>
              )
            })}
          </div>
        </div>
      </div>
    </section>
  )
}

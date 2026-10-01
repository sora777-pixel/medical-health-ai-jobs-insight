import { useEffect, useState } from 'react'
import { motion } from 'framer-motion'
import { Briefcase, MapPin, Sparkles, Target } from 'lucide-react'

import {
  EXAMPLE_PROFILE,
  fetchMatches,
  fetchProfile,
  matchCandidate,
  parseProfile,
  type CandidateProfile,
  type MatchBreakdown,
  type MatchResponse,
  type SkillGap,
} from '@/lib/career'

const STORAGE_KEY = 'healthcare-career-candidate-id'

const BREAKDOWN_LABELS: Array<[keyof MatchBreakdown, string]> = [
  ['skill', 'Skill'],
  ['experience', 'Experience'],
  ['education', 'Education'],
  ['domain', 'Domain'],
  ['location', 'Location'],
  ['salary', 'Salary'],
  ['role', 'Role'],
]

const PRIORITY_STYLE: Record<string, string> = {
  high: 'bg-[#FF6B6B]/20 text-[#FF6B6B] border-[#FF6B6B]/40',
  medium: 'bg-[#F5B935]/20 text-[#F5B935] border-[#F5B935]/40',
  low: 'bg-white/10 text-white/70 border-white/20',
}

interface Props {
  onViewJob?: (title: string) => void
}

export function CareerPanel({ onViewJob }: Props) {
  const [text, setText] = useState(EXAMPLE_PROFILE)
  const [profile, setProfile] = useState<CandidateProfile | null>(null)
  const [matches, setMatches] = useState<MatchResponse | null>(null)
  const [busy, setBusy] = useState<'parse' | 'match' | null>(null)
  const [error, setError] = useState('')
  const [highlight, setHighlight] = useState('')

  useEffect(() => {
    const saved = window.localStorage.getItem(STORAGE_KEY)
    if (!saved) return
    let active = true
    void (async () => {
      try {
        const loaded = await fetchProfile(saved)
        if (!active) return
        setProfile(loaded.profile)
        if (loaded.profile.profile_text) setText(loaded.profile.profile_text)
        const cached = await fetchMatches(saved)
        if (active) setMatches(cached)
      } catch {
        window.localStorage.removeItem(STORAGE_KEY)
      }
    })()
    return () => {
      active = false
    }
  }, [])

  const analyze = async () => {
    setBusy('parse')
    setError('')
    setMatches(null)
    try {
      const result = await parseProfile(text)
      setProfile(result.profile)
      window.localStorage.setItem(STORAGE_KEY, result.profile.candidate_id)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '画像解析失败')
    } finally {
      setBusy(null)
    }
  }

  const match = async () => {
    if (!profile) return
    setBusy('match')
    setError('')
    try {
      const result = await matchCandidate(profile.candidate_id, 20)
      setMatches(result)
    } catch (cause) {
      setError(cause instanceof Error ? cause.message : '匹配失败')
    } finally {
      setBusy(null)
    }
  }

  const focusGap = (skill: string) => {
    setHighlight(skill)
    document.getElementById('skill-gaps')?.scrollIntoView({ behavior: 'smooth', block: 'start' })
  }

  return (
    <section className="px-4 py-12">
      <div className="max-w-7xl mx-auto">
        <div className="mb-8">
          <h2 className="text-3xl md:text-4xl font-bold mb-3">My Career</h2>
          <p className="text-white/60 max-w-3xl">
            用一段职业背景生成候选人画像，再对当前岗位库做可解释匹配。分数由规则计算，画像只保存在本地 API，不会写入公开数据文件。
          </p>
        </div>

        <div className="grid lg:grid-cols-2 gap-6 mb-8">
          <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
            <label htmlFor="career-profile" className="block text-sm text-white/70 mb-3">
              职业背景
            </label>
            <textarea
              id="career-profile"
              value={text}
              onChange={(event) => setText(event.target.value)}
              rows={10}
              className="w-full rounded-xl bg-[#0A1628] border border-white/10 px-4 py-3 text-sm leading-6 outline-none focus:border-[#4D6CFA]"
            />
            <div className="mt-4 flex flex-wrap gap-3">
              <button
                type="button"
                onClick={() => void analyze()}
                disabled={busy !== null || !text.trim()}
                className="px-4 py-2 rounded-lg bg-[#1B45F4] hover:bg-[#4D6CFA] disabled:opacity-50"
              >
                {busy === 'parse' ? '解析中...' : 'Analyze Profile'}
              </button>
              <button
                type="button"
                onClick={() => setText(EXAMPLE_PROFILE)}
                className="px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20"
              >
                填入示例
              </button>
              <button
                type="button"
                onClick={() => void match()}
                disabled={busy !== null || !profile}
                className="px-4 py-2 rounded-lg bg-[#00B578] hover:bg-[#00D68F] disabled:opacity-50"
              >
                {busy === 'match' ? '匹配中...' : 'Match Jobs'}
              </button>
            </div>
            {error && <p className="mt-4 text-sm text-[#FF6B6B]">{error}。请确认已启动 python -m jobsinsight serve。</p>}
          </div>

          <ProfileSummary profile={profile} />
        </div>

        {matches && (
          <div className="space-y-6">
            <div className="flex items-end justify-between gap-4">
              <h3 className="text-2xl font-semibold">Top matching jobs</h3>
              <span className="text-sm text-white/50">{matches.results.length} 个岗位</span>
            </div>
            {matches.results.length === 0 && (
              <p className="text-white/60">当前岗位库为空，或没有可比较的在招岗位。</p>
            )}
            <div className="grid xl:grid-cols-2 gap-5">
              {matches.results.map((result) => (
                <motion.article
                  key={result.job_id}
                  initial={{ opacity: 0, y: 12 }}
                  animate={{ opacity: 1, y: 0 }}
                  className="rounded-2xl border border-white/10 bg-white/5 p-5"
                >
                  <div className="flex items-start justify-between gap-4">
                    <div>
                      <h4 className="text-xl font-semibold">{result.job?.title ?? `岗位 ${result.job_id}`}</h4>
                      <p className="text-white/60 mt-1">{result.job?.company ?? '未知公司'}</p>
                      <div className="mt-2 flex flex-wrap gap-3 text-sm text-white/70">
                        <span className="inline-flex items-center gap-1">
                          <MapPin className="w-3.5 h-3.5" />
                          {result.job?.city || '城市未知'}
                        </span>
                        <span>{formatSalary(result.job?.salary_min, result.job?.salary_max)}</span>
                      </div>
                    </div>
                    <div className="text-right">
                      <div className="text-3xl font-bold text-[#F5B935]">{Math.round(result.overall_score)}</div>
                      <div className="text-xs text-white/50">Overall Match</div>
                    </div>
                  </div>

                  <div className="mt-4 grid grid-cols-2 gap-2">
                    {BREAKDOWN_LABELS.map(([key, label]) => (
                      <ScoreLine key={key} label={label} value={result.breakdown?.[key] ?? null} />
                    ))}
                  </div>

                  <ChipRow title="Matched skills" items={result.matched_skills} tone="match" />
                  <ChipRow title="Missing skills" items={result.missing_skills} tone="miss" />
                  {result.nice_to_have.length > 0 && (
                    <ChipRow title="Nice-to-have" items={result.nice_to_have} tone="extra" />
                  )}

                  <div className="mt-4 rounded-xl bg-[#0A1628]/60 p-3">
                    <div className="text-xs text-white/40 mb-1">Why matched</div>
                    <p className="text-sm text-white/80">{result.explanation?.summary || result.reasons[0] || '暂无说明'}</p>
                    {result.reasons.length > 0 && (
                      <ul className="mt-2 space-y-1 text-sm text-white/60">
                        {result.reasons.slice(0, 4).map((reason) => (
                          <li key={reason}>{reason}</li>
                        ))}
                      </ul>
                    )}
                  </div>

                  <div className="mt-4 flex flex-wrap gap-2">
                    <button
                      type="button"
                      className="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm inline-flex items-center gap-1"
                      onClick={() => {
                        if (result.job?.url) {
                          window.open(result.job.url, '_blank', 'noopener,noreferrer')
                          return
                        }
                        if (result.job?.title) onViewJob?.(result.job.title)
                      }}
                    >
                      <Briefcase className="w-3.5 h-3.5" />
                      View Job
                    </button>
                    <button
                      type="button"
                      className="px-3 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm inline-flex items-center gap-1"
                      onClick={() => focusGap(result.missing_skills[0] ?? '')}
                    >
                      <Target className="w-3.5 h-3.5" />
                      View Skill Gap
                    </button>
                  </div>
                </motion.article>
              ))}
            </div>

            <div id="skill-gaps" className="rounded-2xl border border-white/10 bg-white/5 p-5">
              <div className="flex items-center gap-2 mb-4">
                <Sparkles className="w-4 h-4 text-[#F5B935]" />
                <h3 className="text-xl font-semibold">Skill Gap priority</h3>
              </div>
              {matches.skill_gaps.length === 0 && <p className="text-white/60">当前 Top 岗位没有汇总出缺失技能。</p>}
              <div className="space-y-3">
                {matches.skill_gaps.map((gap) => (
                  <GapRow key={gap.skill} gap={gap} active={highlight === gap.skill} />
                ))}
              </div>
            </div>
          </div>
        )}
      </div>
    </section>
  )
}

function ProfileSummary({ profile }: { profile: CandidateProfile | null }) {
  if (!profile) {
    return (
      <div className="rounded-2xl border border-dashed border-white/15 p-5 text-white/50">
        解析后会在这里显示年限、学历、技能、目标岗位、城市和薪资。
      </div>
    )
  }
  const salary =
    profile.salary_min && profile.salary_max
      ? `${profile.salary_min}-${profile.salary_max}K`
      : profile.salary_min
        ? `${profile.salary_min}K+`
        : '未提供'
  return (
    <div className="rounded-2xl border border-white/10 bg-white/5 p-5">
      <h3 className="text-lg font-semibold mb-2">Parsed Profile</h3>
      <p className="text-sm text-white/70 mb-4">{profile.profile_summary || profile.headline || '已提取结构化画像'}</p>
      <dl className="grid grid-cols-2 gap-3 text-sm">
        <Fact label="经验" value={profile.years_experience ? `${profile.years_experience} 年` : '未提供'} />
        <Fact label="学历" value={[profile.education, profile.education_field].filter(Boolean).join(' · ') || '未提供'} />
        <Fact label="目标城市" value={profile.target_cities.join('、') || '不限'} />
        <Fact label="薪资" value={salary} />
      </dl>
      <ChipRow title="Skills" items={profile.skills.map((skill) => skill.canonical_name)} tone="match" />
      <ChipRow title="Target roles" items={profile.target_roles} tone="extra" />
      <ChipRow title="Domains" items={profile.domains} tone="extra" />
    </div>
  )
}

function Fact({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <dt className="text-white/40">{label}</dt>
      <dd className="text-white/90">{value}</dd>
    </div>
  )
}

function ScoreLine({ label, value }: { label: string; value: number | null }) {
  const score = value === null || value === undefined ? null : Math.max(0, Math.min(100, value))
  return (
    <div>
      <div className="flex justify-between text-xs text-white/50 mb-1">
        <span>{label}</span>
        <span>{score === null ? '未提供' : Math.round(score)}</span>
      </div>
      <div className="h-1.5 rounded-full bg-white/10 overflow-hidden">
        <div className="h-full bg-[#4D6CFA]" style={{ width: score === null ? '0%' : `${score}%` }} />
      </div>
    </div>
  )
}

function ChipRow({ title, items, tone }: { title: string; items: string[]; tone: 'match' | 'miss' | 'extra' }) {
  if (!items.length) return null
  const toneClass =
    tone === 'match'
      ? 'bg-[#00B578]/15 text-[#7DFFC3]'
      : tone === 'miss'
        ? 'bg-[#FF6B6B]/15 text-[#FFB4B4]'
        : 'bg-[#4D6CFA]/15 text-[#C9D4FF]'
  return (
    <div className="mt-3">
      <div className="text-xs text-white/40 mb-1">{title}</div>
      <div className="flex flex-wrap gap-2">
        {items.map((item) => (
          <span key={`${title}-${item}`} className={`px-2 py-1 rounded-full text-xs ${toneClass}`}>
            {item}
          </span>
        ))}
      </div>
    </div>
  )
}

function GapRow({ gap, active }: { gap: SkillGap; active: boolean }) {
  return (
    <div className={`rounded-xl border px-4 py-3 ${active ? 'border-[#F5B935]' : 'border-white/10'}`}>
      <div className="flex items-center justify-between gap-3">
        <span className="font-medium">{gap.skill}</span>
        <span className={`text-xs px-2 py-0.5 rounded-full border ${PRIORITY_STYLE[gap.priority] ?? PRIORITY_STYLE.low}`}>
          {gap.priority} · {gap.frequency}
        </span>
      </div>
      <p className="text-sm text-white/60 mt-1">{gap.reason}</p>
    </div>
  )
}

function formatSalary(min?: number, max?: number) {
  if (!min && !max) return '薪资未知'
  if (min && max) return `${min}-${max}K`
  return `${min || max}K`
}

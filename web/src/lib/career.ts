/**
 * Career copilot client. Profiles stay on the API; they are never read from public/data.
 */

export interface CandidateSkill {
  name: string
  canonical_name: string
  level: string
  years: number
  evidence: string
}

export interface CandidateProfile {
  candidate_id: string
  name: string
  headline: string
  years_experience: number
  education: string
  education_field: string
  current_city: string
  target_cities: string[]
  current_role: string
  target_roles: string[]
  target_categories: string[]
  salary_min: number
  salary_max: number
  employment_type: string
  domains: string[]
  skills: CandidateSkill[]
  target_skills: CandidateSkill[]
  profile_text: string
  profile_summary: string
  created_at: string
  updated_at: string
}

export interface MatchBreakdown {
  skill: number | null
  experience: number | null
  education: number | null
  domain: number | null
  location: number | null
  salary: number | null
  role: number | null
}

export interface SkillGap {
  skill: string
  priority: 'high' | 'medium' | 'low' | string
  reason: string
  related_jobs: number[]
  frequency: number
}

export interface MatchExplanation {
  reasons: string[]
  strengths: string[]
  gaps: string[]
  summary: string
}

export interface MatchJob {
  id: number
  title: string
  company: string
  city: string
  salary_min: number
  salary_max: number
  experience: string
  education: string
  category: string
  url: string
  summary: string
  skills: string[]
  platform: string
}

export interface MatchResult {
  job_id: number
  overall_score: number
  confidence: number
  breakdown: MatchBreakdown
  matched_skills: string[]
  missing_skills: string[]
  nice_to_have: string[]
  reasons: string[]
  skill_gap_priority: SkillGap[]
  available_weight: number
  explanation: MatchExplanation
  job?: MatchJob
}

export interface MatchResponse {
  candidate_id: string
  top_k?: number
  results: MatchResult[]
  skill_gaps: SkillGap[]
  generated_at?: string
}

const API_BASE = (import.meta.env.VITE_AUTOMATION_API ?? '').replace(/\/$/, '')
const API_TOKEN = import.meta.env.VITE_AUTOMATION_TOKEN ?? ''

export class CareerApiError extends Error {}

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
    throw new CareerApiError(`${path} 返回的不是 JSON（HTTP ${response.status}）`)
  }
  if (!response.ok) {
    const message =
      typeof payload === 'object' && payload && 'error' in payload
        ? String((payload as { error: unknown }).error)
        : `请求失败（HTTP ${response.status}）`
    throw new CareerApiError(message)
  }
  return payload as T
}

export const parseProfile = (text: string) =>
  request<{ profile: CandidateProfile }>('/api/candidates/parse', {
    method: 'POST',
    body: JSON.stringify({ text }),
  })

export const fetchProfile = (candidateId: string) =>
  request<{ profile: CandidateProfile }>(`/api/candidates/${candidateId}`)

export const matchCandidate = (candidateId: string, topK = 20) =>
  request<MatchResponse>('/api/matches', {
    method: 'POST',
    body: JSON.stringify({ candidate_id: candidateId, top_k: topK }),
  })

export const fetchMatches = (candidateId: string) => request<MatchResponse>(`/api/matches/${candidateId}`)

export const fetchSkillGaps = (candidateId: string) =>
  request<{ candidate_id: string; skill_gaps: SkillGap[] }>(
    `/api/skills/gaps?candidate_id=${encodeURIComponent(candidateId)}`,
  )

export const EXAMPLE_PROFILE = `我有3年生物信息学经验，硕士学历。
熟悉 Python、PyTorch、Docker、Linux、scRNA-seq。
做过单细胞数据分析和深度学习项目。
想转医疗AI或AI药物研发。
希望上海或杭州，薪资25K以上。`

import { useState, useEffect, useMemo, useCallback } from 'react'
import { motion, AnimatePresence } from 'framer-motion'
import { 
  BarChart, Bar, XAxis, YAxis, CartesianGrid, Tooltip, ResponsiveContainer, 
  PieChart, Pie, Cell, Legend, AreaChart, Area
} from 'recharts'
import { 
  Briefcase, MapPin, DollarSign, Building2, 
  GraduationCap, Code, Activity, ChevronDown, ChevronUp,
  Filter, Clock, TrendingUp, Award, RefreshCw, Calendar,
  Search, X, AlertCircle, ExternalLink
} from 'lucide-react'
import { AutomationPanel } from '@/components/AutomationPanel'
import { DataStatusBar } from '@/components/DataStatusBar'
import { useAutomation } from '@/hooks/useAutomation'
import {
  fetchDataFile,
  fetchDataFileWithMeta,
  fetchManifest,
  type DataManifest,
  type DataOrigin,
} from '@/lib/automation'
import './App.css'

// 类型定义
interface Job {
  id: number
  platform: string
  title: string
  company: string
  company_scale_value: number
  company_scale: string
  company_level: string
  city: string
  salary_min: number
  salary_max: number
  experience: string
  education: string
  job_level: string
  summary: string
  skills: string[]
  publish_date: string
  update_date: string
  status: 'active' | 'deleted' | 'updated'
}

interface Headhunter {
  id: number
  name: string
  avatar: string
  company: string
  company_url: string
  profile_url: string
  platform: string
  specialty: string
  experience: string
}

interface Agency {
  id: number
  name: string
  logo: string
  website: string
  description: string
  platforms: string[]
}

interface SalaryRangeDetail {
  count: number
  top_city: string
  top_city_count: number
  top_title: string
  top_title_count: number
}

interface Stats {
  total_jobs: number
  platform_stats: Record<string, { count: number; avg_salary: number }>
  city_stats: Record<string, { count: number; avg_salary: number }>
  skill_stats: Record<string, number>
  experience_stats: Record<string, { count: number; avg_salary: number }>
  salary_distribution: Record<string, number>
  salary_distribution_detail: Record<string, SalaryRangeDetail>
  last_update: string
  new_jobs_today: number
  updated_jobs_today: number
  deleted_jobs_today: number
}

// 颜色配置
const COLORS = {
  primary: '#1B45F4',
  secondary: '#4D6CFA',
  accent: '#F5B935',
  light: '#E9EFFD',
  dark: '#0A1628',
  white: '#FFFFFF',
  gradient: ['#1B45F4', '#4D6CFA', '#6B8BFF', '#8BA5FF', '#ABBEFF']
}

const PLATFORM_COLORS: Record<string, string> = {
  '51job': '#1B45F4',
  'Boss直聘': '#00B578',
  '猎聘网': '#FF6B6B'
}

const JOB_LEVEL_ORDER = ['初级', '中级', '高级', '专家', '资深专家']
const EXPERIENCE_ORDER = ['应届', '1-3年', '3-5年', '5-10年', '10年以上']

// 自定义饼图Tooltip组件
interface PieTooltipProps {
  active?: boolean
  payload?: Array<{
    name: string
    value: number
    payload: {
      name: string
      value: number
    }
  }>
  salaryDetail?: Record<string, SalaryRangeDetail>
}

const CustomPieTooltip = ({ active, payload, salaryDetail }: PieTooltipProps) => {
  if (active && payload && payload.length && salaryDetail) {
    const data = payload[0]
    const rangeName = data.payload.name
    const detail = salaryDetail[rangeName]
    
    if (detail) {
      return (
        <div className="bg-[#0A1628] border border-white/20 rounded-xl p-4 shadow-2xl max-w-xs">
          <div className="text-lg font-bold mb-3 text-white">{rangeName}</div>
          <div className="space-y-2 text-sm">
            <div className="flex items-center justify-between">
              <span className="text-white/60">岗位总数:</span>
              <span className="font-semibold text-[#4D6CFA]">{detail.count} 个</span>
            </div>
            <div className="border-t border-white/10 pt-2 mt-2">
              <div className="text-white/40 text-xs mb-1">热门城市</div>
              <div className="flex items-center justify-between">
                <span className="text-white/80">{detail.top_city}</span>
                <span className="text-[#00B578]">{detail.top_city_count} 个岗位</span>
              </div>
            </div>
            <div className="border-t border-white/10 pt-2 mt-2">
              <div className="text-white/40 text-xs mb-1">热门岗位</div>
              <div className="flex items-center justify-between">
                <span className="text-white/80 truncate max-w-[120px]">{detail.top_title}</span>
                <span className="text-[#F5B935]">{detail.top_title_count} 个</span>
              </div>
            </div>
          </div>
        </div>
      )
    }
  }
  return null
}

function App() {
  const [jobs, setJobs] = useState<Job[]>([])
  const [stats, setStats] = useState<Stats | null>(null)
  const [headhunters, setHeadhunters] = useState<Headhunter[]>([])
  const [agencies, setAgencies] = useState<Agency[]>([])
  const [loading, setLoading] = useState(true)
  const [loadError, setLoadError] = useState('')
  const [manifest, setManifest] = useState<DataManifest | null>(null)
  const [dataOrigin, setDataOrigin] = useState<DataOrigin | null>(null)
  const [isUpdating, setIsUpdating] = useState(false)
  
  // 筛选状态
  const [selectedPlatform, setSelectedPlatform] = useState<string>('all')
  const [selectedCity, setSelectedCity] = useState<string>('all')
  const [selectedExperience, setSelectedExperience] = useState<string>('all')
  const [selectedEducation, setSelectedEducation] = useState<string>('all')
  const [selectedJobLevel, setSelectedJobLevel] = useState<string>('all')
  const [searchSummary, setSearchSummary] = useState<string>('')
  
  // 排序状态
  const [sortBy, setSortBy] = useState<string>('publish_date')
  const [sortOrder, setSortOrder] = useState<'asc' | 'desc'>('desc')
  
  const [showAllJobs, setShowAllJobs] = useState(false)
  const [showFilters, setShowFilters] = useState(false)
  const [updateResult, setUpdateResult] = useState<string>('')

  // 自动化后端状态（运行时间、上次运行、LLM 洞察）
  const automation = useAutomation()

  const loadData = useCallback(async () => {
    const [jobsResult, statsResult, manifestResult] = await Promise.all([
      fetchDataFileWithMeta<Job[]>('jobs'),
      fetchDataFileWithMeta<Stats>('stats'),
      fetchManifest(),
    ])
    setJobs(jobsResult.data)
    setStats(statsResult.data)
    setManifest(manifestResult?.data ?? null)
    setDataOrigin(jobsResult.origin)
    return { jobs: jobsResult.data, stats: statsResult.data }
  }, [])

  // 更新按钮：接口在线时触发后台流水线跑一次，否则只重新拉取已产出的数据
  const handleDailyUpdate = async () => {
    setIsUpdating(true)
    setUpdateResult('')

    try {
      if (automation.online) {
        const report = await automation.runNow()
        if (!report) throw new Error(automation.error ?? '运行失败')
        if (report.published === false || report.status === 'failed') {
          throw new Error(report.errors?.[0] ?? '数据未通过发布门禁，已保留上一版数据')
        }
        await loadData()
        setUpdateResult(
          `${report.status === 'partial' ? '部分来源失败，已发布可用数据。' : '更新完成！'}新增 ${report.diff?.new_jobs ?? 0} 个岗位，更新 ${report.diff?.updated_jobs ?? 0} 个，下架 ${report.diff?.deleted_jobs ?? 0} 个`
        )
      } else {
        const { stats: latest } = await loadData()
        setUpdateResult(
          `已同步最新数据（${latest.last_update}）：新增 ${latest.new_jobs_today} 个岗位，更新 ${latest.updated_jobs_today} 个`
        )
      }
      setTimeout(() => setUpdateResult(''), 4000)
    } catch (error) {
      setUpdateResult(error instanceof Error ? `更新失败：${error.message}` : '更新失败，请稍后重试')
      setTimeout(() => setUpdateResult(''), 4000)
    } finally {
      setIsUpdating(false)
    }
  }

  useEffect(() => {
    let active = true
    const initialize = async () => {
      setLoading(true)
      setLoadError('')
      try {
        await loadData()
        // 猎头与机构是非关键内容，失败不能阻塞整个岗位看板。
        const [headhuntersResult, agenciesResult] = await Promise.allSettled([
          fetchDataFile<Headhunter[]>('headhunters'),
          fetchDataFile<Agency[]>('agencies')
        ])
        if (!active) return
        if (headhuntersResult.status === 'fulfilled') setHeadhunters(headhuntersResult.value)
        if (agenciesResult.status === 'fulfilled') setAgencies(agenciesResult.value)
      } catch (error) {
        if (active) setLoadError(error instanceof Error ? error.message : '数据加载失败')
      } finally {
        if (active) setLoading(false)
      }
    }
    void initialize()
    return () => {
      active = false
    }
  }, [loadData])

  // 去重函数：同一公司相同岗位只保留最新发布的
  const deduplicateJobs = (jobs: Job[]): Job[] => {
    const jobMap = new Map<string, Job>()
    
    jobs.forEach(job => {
      const key = `${job.company}-${job.title}`
      const existing = jobMap.get(key)
      
      if (!existing || new Date(job.publish_date) > new Date(existing.publish_date)) {
        jobMap.set(key, job)
      }
    })
    
    return Array.from(jobMap.values())
  }

  // 过滤和排序后的岗位数据
  const processedJobs = useMemo(() => {
    // 1. 先过滤掉已删除的岗位
    let filtered = jobs.filter(job => job.status !== 'deleted')
    
    // 2. 去重
    filtered = deduplicateJobs(filtered)
    
    // 3. 应用筛选条件
    if (selectedPlatform !== 'all') {
      filtered = filtered.filter(job => job.platform === selectedPlatform)
    }
    if (selectedCity !== 'all') {
      filtered = filtered.filter(job => job.city === selectedCity)
    }
    if (selectedExperience !== 'all') {
      filtered = filtered.filter(job => job.experience === selectedExperience)
    }
    if (selectedEducation !== 'all') {
      filtered = filtered.filter(job => job.education === selectedEducation)
    }
    if (selectedJobLevel !== 'all') {
      filtered = filtered.filter(job => job.job_level === selectedJobLevel)
    }
    if (searchSummary.trim()) {
      const keyword = searchSummary.toLowerCase()
      filtered = filtered.filter(job => 
        job.summary.toLowerCase().includes(keyword) ||
        job.title.toLowerCase().includes(keyword) ||
        job.skills.some(s => s.toLowerCase().includes(keyword))
      )
    }
    
    // 4. 排序
    filtered.sort((a, b) => {
      let comparison = 0
      
      switch (sortBy) {
        case 'publish_date':
          comparison = new Date(a.publish_date).getTime() - new Date(b.publish_date).getTime()
          break
        case 'salary': {
          const avgA = (a.salary_min + a.salary_max) / 2
          const avgB = (b.salary_min + b.salary_max) / 2
          comparison = avgA - avgB
          break
        }
        case 'company_scale_value':
          comparison = a.company_scale_value - b.company_scale_value
          break
        case 'job_level': {
          const levelA = JOB_LEVEL_ORDER.indexOf(a.job_level)
          const levelB = JOB_LEVEL_ORDER.indexOf(b.job_level)
          comparison = levelA - levelB
          break
        }
        default:
          comparison = 0
      }
      
      return sortOrder === 'asc' ? comparison : -comparison
    })
    
    return filtered
  }, [jobs, selectedPlatform, selectedCity, selectedExperience, selectedEducation, selectedJobLevel, searchSummary, sortBy, sortOrder])

  if (loading) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0A1628] to-[#1B45F4]">
        <motion.div 
          animate={{ rotate: 360 }}
          transition={{ duration: 2, repeat: Infinity, ease: 'linear' }}
          className="w-16 h-16 border-4 border-white border-t-transparent rounded-full"
        />
      </div>
    )
  }

  if (loadError || !stats) {
    return (
      <div className="min-h-screen flex items-center justify-center bg-gradient-to-br from-[#0A1628] to-[#1B45F4] px-4 text-white">
        <div className="max-w-xl w-full rounded-2xl bg-[#0A1628]/80 border border-white/20 p-8 text-center shadow-2xl">
          <AlertCircle className="w-12 h-12 text-[#FF6B6B] mx-auto mb-4" />
          <h1 className="text-2xl font-bold mb-3">岗位数据加载失败</h1>
          <p className="text-white/70 text-sm break-words mb-6">{loadError || 'stats.json 不存在或格式无效'}</p>
          <button
            onClick={() => window.location.reload()}
            className="px-5 py-2.5 rounded-lg bg-[#1B45F4] hover:bg-[#4D6CFA] transition-colors"
          >
            重新加载
          </button>
          <p className="text-white/40 text-xs mt-4">
            可在 automation 目录执行 python -m jobsinsight doctor 查看具体原因
          </p>
        </div>
      </div>
    )
  }

  // 平台对比数据
  const platformData = Object.entries(stats.platform_stats).map(([name, data]) => ({
    name,
    岗位数: data.count,
    平均薪资: data.avg_salary
  }))

  // 城市数据
  const cityData = Object.entries(stats.city_stats)
    .sort((a, b) => b[1].count - a[1].count)
    .slice(0, 8)
    .map(([name, data]) => ({
      name,
      岗位数: data.count,
      平均薪资: data.avg_salary
    }))

  // 薪资分布数据
  const salaryData = Object.entries(stats.salary_distribution).map(([range, count]) => ({
    name: range,
    value: count
  }))

  // 技能数据
  const skillData = Object.entries(stats.skill_stats)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 12)
    .map(([name, count]) => ({
      name,
      count,
      percentage: Math.round((count / stats.total_jobs) * 100)
    }))

  // 经验数据
  const experienceData = Object.entries(stats.experience_stats).map(([name, data]) => ({
    name,
    岗位数: data.count,
    平均薪资: data.avg_salary
  }))

  const displayedJobs = showAllJobs ? processedJobs.slice(0, 20) : processedJobs.slice(0, 6)
  
  // 城市列表
  const cities = ['北京', '上海', '广州', '深圳', '杭州', '成都', '南京', '武汉', '西安', '苏州']

  // 获取排序按钮样式
  const getSortButtonStyle = (key: string) => {
    if (sortBy === key) {
      return 'bg-[#1B45F4] text-white'
    }
    return 'bg-white/10 text-white/70 hover:bg-white/20'
  }

  // 清除所有筛选
  const clearFilters = () => {
    setSelectedPlatform('all')
    setSelectedCity('all')
    setSelectedExperience('all')
    setSelectedEducation('all')
    setSelectedJobLevel('all')
    setSearchSummary('')
  }

  return (
    <div className="min-h-screen bg-[#0A1628] text-white overflow-x-hidden">
      {/* Hero Section */}
      <section className="relative min-h-screen flex items-center justify-center overflow-hidden">
        {/* 动态背景 */}
        <div className="absolute inset-0">
          <motion.div 
            animate={{ 
              background: [
                'radial-gradient(ellipse at 20% 30%, #1B45F4 0%, transparent 50%)',
                'radial-gradient(ellipse at 80% 70%, #4D6CFA 0%, transparent 50%)',
                'radial-gradient(ellipse at 50% 50%, #1B45F4 0%, transparent 50%)',
                'radial-gradient(ellipse at 20% 30%, #1B45F4 0%, transparent 50%)'
              ]
            }}
            transition={{ duration: 10, repeat: Infinity, ease: 'linear' }}
            className="absolute inset-0 opacity-40"
          />
          <div className="absolute inset-0 bg-gradient-to-b from-transparent via-[#0A1628]/50 to-[#0A1628]" />
        </div>

        {/* 粒子效果 */}
        <div className="absolute inset-0 overflow-hidden">
          {[...Array(20)].map((_, i) => (
            <motion.div
              key={i}
              className="absolute w-1 h-1 bg-white/30 rounded-full"
              style={{
                left: `${Math.random() * 100}%`,
                top: `${Math.random() * 100}%`
              }}
              animate={{
                y: [0, -100, 0],
                opacity: [0, 1, 0]
              }}
              transition={{
                duration: 5 + Math.random() * 5,
                repeat: Infinity,
                delay: Math.random() * 5
              }}
            />
          ))}
        </div>

        {/* 内容 */}
        <div className="relative z-10 text-center px-4 max-w-5xl mx-auto">
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8 }}
            className="inline-flex items-center gap-2 px-4 py-2 rounded-full bg-white/10 backdrop-blur-sm border border-white/20 mb-6"
          >
            <Activity className="w-4 h-4 text-[#F5B935]" />
            <span className="text-sm">{dataOrigin === 'api' ? '实时 API 数据' : '定时更新数据快照'}</span>
          </motion.div>

          <motion.h1
            initial={{ opacity: 0, y: 50 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 1, delay: 0.2 }}
            className="text-5xl md:text-7xl font-bold mb-6 leading-tight"
          >
            <span className="bg-gradient-to-r from-white via-[#E9EFFD] to-[#4D6CFA] bg-clip-text text-transparent">
              医药健康+AI
            </span>
            <br />
            <span className="text-white">岗位洞察平台</span>
          </motion.h1>

          <motion.p
            initial={{ opacity: 0, y: 30 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.8, delay: 0.4 }}
            className="text-xl text-white/70 mb-8 max-w-2xl mx-auto"
          >
            实时聚合51job、Boss直聘、猎聘网数据，解码行业人才趋势
          </motion.p>

          <motion.div
            initial={{ opacity: 0, scale: 0.9 }}
            animate={{ opacity: 1, scale: 1 }}
            transition={{ duration: 0.6, delay: 0.6 }}
            className="flex flex-wrap justify-center gap-4"
          >
            <div className="px-6 py-3 rounded-xl bg-white/5 backdrop-blur-sm border border-white/10">
              <div className="text-3xl font-bold text-[#F5B935]">{processedJobs.length}+</div>
              <div className="text-sm text-white/60">在招岗位</div>
            </div>
            <div className="px-6 py-3 rounded-xl bg-white/5 backdrop-blur-sm border border-white/10">
              <div className="text-3xl font-bold text-[#4D6CFA]">3</div>
              <div className="text-sm text-white/60">招聘平台</div>
            </div>
            <div className="px-6 py-3 rounded-xl bg-white/5 backdrop-blur-sm border border-white/10">
              <div className="text-3xl font-bold text-[#00B578]">10+</div>
              <div className="text-sm text-white/60">覆盖城市</div>
            </div>
          </motion.div>
          
          {/* 每日更新提示 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.8 }}
            className="mt-8 inline-flex flex-wrap items-center justify-center gap-4 px-6 py-3 rounded-xl bg-gradient-to-r from-[#1B45F4]/30 to-[#4D6CFA]/30 backdrop-blur-sm border border-white/20"
          >
            <button
              onClick={handleDailyUpdate}
              disabled={isUpdating}
              className="flex items-center gap-2 px-4 py-2 rounded-lg bg-[#00B578] hover:bg-[#00D68F] disabled:opacity-50 disabled:cursor-not-allowed transition-colors"
            >
              <motion.div
                animate={isUpdating ? { rotate: 360 } : { rotate: 0 }}
                transition={isUpdating ? { duration: 1, repeat: Infinity, ease: 'linear' } : {}}
              >
                <RefreshCw className="w-4 h-4" />
              </motion.div>
              <span className="text-sm font-medium">
                {isUpdating ? '更新中...' : '每日自动更新'}
              </span>
            </button>
            <div className="w-px h-4 bg-white/20 hidden sm:block" />
            <div className="flex items-center gap-2">
              <span className="text-sm text-white/60">今日新增:</span>
              <span className="text-sm font-semibold text-[#00B578]">+{stats.new_jobs_today}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-white/60">更新:</span>
              <span className="text-sm font-semibold text-[#F5B935]">{stats.updated_jobs_today}</span>
            </div>
            <div className="flex items-center gap-2">
              <span className="text-sm text-white/60">下线:</span>
              <span className="text-sm font-semibold text-[#FF6B6B]">{stats.deleted_jobs_today}</span>
            </div>
          </motion.div>
          
          {/* 更新结果提示 */}
          <AnimatePresence>
            {updateResult && (
              <motion.div
                initial={{ opacity: 0, y: -10 }}
                animate={{ opacity: 1, y: 0 }}
                exit={{ opacity: 0, y: -10 }}
                className="mt-4 px-4 py-2 rounded-lg bg-[#00B578]/20 border border-[#00B578]/30 text-sm"
              >
                {updateResult}
              </motion.div>
            )}
          </AnimatePresence>
        </div>

        {/* 滚动提示 */}
        <motion.div
          animate={{ y: [0, 10, 0] }}
          transition={{ duration: 2, repeat: Infinity }}
          className="absolute bottom-8 left-1/2 -translate-x-1/2"
        >
          <ChevronDown className="w-8 h-8 text-white/40" />
        </motion.div>
      </section>

      <DataStatusBar manifest={manifest} origin={dataOrigin} />

      {/* 自动化运行状态与 LLM 洞察 */}
      <AutomationPanel automation={automation} manifest={manifest} />

      {/* 平台生态概览 */}
      <section className="py-20 px-4">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">平台生态概览</h2>
            <p className="text-white/60">三大招聘平台数据对比分析</p>
          </motion.div>

          <div className="grid md:grid-cols-3 gap-6">
            {Object.entries(stats.platform_stats).map(([platform, data], index) => (
              <motion.div
                key={platform}
                initial={{ opacity: 0, y: 50 }}
                whileInView={{ opacity: 1, y: 0 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.1 }}
                whileHover={{ y: -10, scale: 1.02 }}
                className="relative p-6 rounded-2xl bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-sm border border-white/10 overflow-hidden group"
              >
                <div 
                  className="absolute inset-0 opacity-0 group-hover:opacity-100 transition-opacity duration-500"
                  style={{
                    background: `radial-gradient(circle at 50% 0%, ${PLATFORM_COLORS[platform]}40, transparent 70%)`
                  }}
                />
                <div className="relative z-10">
                  <div className="flex items-center justify-between mb-4">
                    <h3 className="text-xl font-semibold">{platform}</h3>
                    <div 
                      className="w-3 h-3 rounded-full"
                      style={{ backgroundColor: PLATFORM_COLORS[platform] }}
                    />
                  </div>
                  <div className="space-y-4">
                    <div>
                      <div className="text-4xl font-bold mb-1">{data.count}</div>
                      <div className="text-sm text-white/60">在招岗位</div>
                    </div>
                    <div className="pt-4 border-t border-white/10">
                      <div className="flex items-center gap-2">
                        <DollarSign className="w-4 h-4 text-[#F5B935]" />
                        <span className="text-2xl font-bold">{data.avg_salary}K</span>
                      </div>
                      <div className="text-sm text-white/60">平均月薪</div>
                    </div>
                  </div>
                </div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* 薪资分布 */}
      <section className="py-20 px-4 bg-white/5">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">薪资分布洞察</h2>
            <p className="text-white/60">行业薪资水平与分布情况</p>
          </motion.div>

          <div className="grid lg:grid-cols-2 gap-8">
            {/* 平台薪资对比 */}
            <motion.div
              initial={{ opacity: 0, x: -30 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              className="p-6 rounded-2xl bg-white/5 backdrop-blur-sm border border-white/10"
            >
              <h3 className="text-lg font-semibold mb-6 flex items-center gap-2">
                <BarChart className="w-5 h-5 text-[#4D6CFA]" />
                平台平均薪资对比
              </h3>
              <ResponsiveContainer width="100%" height={300}>
                <BarChart data={platformData}>
                  <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                  <XAxis dataKey="name" stroke="#ffffff60" />
                  <YAxis stroke="#ffffff60" />
                  <Tooltip 
                    contentStyle={{ 
                      backgroundColor: '#0A1628', 
                      border: '1px solid #ffffff20',
                      borderRadius: '8px'
                    }}
                  />
                  <Bar dataKey="平均薪资" fill="#1B45F4" radius={[8, 8, 0, 0]} />
                </BarChart>
              </ResponsiveContainer>
            </motion.div>

            {/* 薪资分布饼图 */}
            <motion.div
              initial={{ opacity: 0, x: 30 }}
              whileInView={{ opacity: 1, x: 0 }}
              viewport={{ once: true }}
              className="p-6 rounded-2xl bg-white/5 backdrop-blur-sm border border-white/10"
            >
              <h3 className="text-lg font-semibold mb-2 flex items-center gap-2">
                <PieChart className="w-5 h-5 text-[#F5B935]" />
                薪资区间分布
              </h3>
              <p className="text-xs text-white/40 mb-4">悬停查看各区间热门城市和岗位</p>
              <ResponsiveContainer width="100%" height={300}>
                <PieChart>
                  <Pie
                    data={salaryData}
                    cx="50%"
                    cy="50%"
                    innerRadius={60}
                    outerRadius={100}
                    paddingAngle={5}
                    dataKey="value"
                  >
                    {salaryData.map((_entry, index) => (
                      <Cell key={`cell-${index}`} fill={COLORS.gradient[index % COLORS.gradient.length]} />
                    ))}
                  </Pie>
                  <Tooltip content={<CustomPieTooltip salaryDetail={stats.salary_distribution_detail} />} />
                  <Legend />
                </PieChart>
              </ResponsiveContainer>
            </motion.div>
          </div>
        </div>
      </section>

      {/* 城市分布 */}
      <section className="py-20 px-4">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">地域机会分布</h2>
            <p className="text-white/60">各城市岗位数量与薪资水平</p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="p-6 rounded-2xl bg-white/5 backdrop-blur-sm border border-white/10"
          >
            <ResponsiveContainer width="100%" height={400}>
              <AreaChart data={cityData}>
                <defs>
                  <linearGradient id="colorJobs" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#1B45F4" stopOpacity={0.8}/>
                    <stop offset="95%" stopColor="#1B45F4" stopOpacity={0}/>
                  </linearGradient>
                  <linearGradient id="colorSalary" x1="0" y1="0" x2="0" y2="1">
                    <stop offset="5%" stopColor="#F5B935" stopOpacity={0.8}/>
                    <stop offset="95%" stopColor="#F5B935" stopOpacity={0}/>
                  </linearGradient>
                </defs>
                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                <XAxis dataKey="name" stroke="#ffffff60" />
                <YAxis yAxisId="left" stroke="#ffffff60" />
                <YAxis yAxisId="right" orientation="right" stroke="#F5B935" />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: '#0A1628', 
                    border: '1px solid #ffffff20',
                    borderRadius: '8px'
                  }}
                />
                <Legend />
                <Area 
                  yAxisId="left"
                  type="monotone" 
                  dataKey="岗位数" 
                  stroke="#1B45F4" 
                  fillOpacity={1} 
                  fill="url(#colorJobs)" 
                />
                <Area 
                  yAxisId="right"
                  type="monotone" 
                  dataKey="平均薪资" 
                  stroke="#F5B935" 
                  fillOpacity={1} 
                  fill="url(#colorSalary)" 
                />
              </AreaChart>
            </ResponsiveContainer>
          </motion.div>
        </div>
      </section>

      {/* 技能图谱 */}
      <section className="py-20 px-4 bg-white/5">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">核心技能图谱</h2>
            <p className="text-white/60">热门技能需求排行</p>
          </motion.div>

          <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-4">
            {skillData.map((skill, index) => (
              <motion.div
                key={skill.name}
                initial={{ opacity: 0, scale: 0.9 }}
                whileInView={{ opacity: 1, scale: 1 }}
                viewport={{ once: true }}
                transition={{ delay: index * 0.05 }}
                whileHover={{ scale: 1.05 }}
                className="p-4 rounded-xl bg-gradient-to-r from-white/10 to-white/5 backdrop-blur-sm border border-white/10"
              >
                <div className="flex items-center justify-between mb-2">
                  <div className="flex items-center gap-3">
                    <div className="w-8 h-8 rounded-lg bg-[#1B45F4]/30 flex items-center justify-center">
                      <Code className="w-4 h-4 text-[#4D6CFA]" />
                    </div>
                    <span className="font-semibold">{skill.name}</span>
                  </div>
                  <span className="text-[#F5B935] font-bold">{skill.percentage}%</span>
                </div>
                <div className="w-full h-2 bg-white/10 rounded-full overflow-hidden">
                  <motion.div
                    initial={{ width: 0 }}
                    whileInView={{ width: `${skill.percentage}%` }}
                    viewport={{ once: true }}
                    transition={{ duration: 1, delay: 0.3 }}
                    className="h-full bg-gradient-to-r from-[#1B45F4] to-[#4D6CFA] rounded-full"
                  />
                </div>
                <div className="mt-2 text-sm text-white/60">{skill.count} 个岗位需求</div>
              </motion.div>
            ))}
          </div>
        </div>
      </section>

      {/* 经验要求 */}
      <section className="py-20 px-4">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">经验要求分析</h2>
            <p className="text-white/60">不同经验段的岗位分布与薪资</p>
          </motion.div>

          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="p-6 rounded-2xl bg-white/5 backdrop-blur-sm border border-white/10"
          >
            <ResponsiveContainer width="100%" height={350}>
              <BarChart data={experienceData} layout="vertical">
                <CartesianGrid strokeDasharray="3 3" stroke="#ffffff10" />
                <XAxis type="number" stroke="#ffffff60" />
                <YAxis dataKey="name" type="category" stroke="#ffffff60" width={80} />
                <Tooltip 
                  contentStyle={{ 
                    backgroundColor: '#0A1628', 
                    border: '1px solid #ffffff20',
                    borderRadius: '8px'
                  }}
                />
                <Legend />
                <Bar dataKey="岗位数" fill="#1B45F4" radius={[0, 8, 8, 0]} />
                <Bar dataKey="平均薪资" fill="#F5B935" radius={[0, 8, 8, 0]} />
              </BarChart>
            </ResponsiveContainer>
          </motion.div>
        </div>
      </section>

      {/* 岗位列表 */}
      <section className="py-20 px-4 bg-white/5">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-8"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">精选岗位推荐</h2>
            <p className="text-white/60">实时更新的热门职位（已自动去重，展示最新发布）</p>
          </motion.div>

          {/* 筛选和排序栏 */}
          <motion.div
            initial={{ opacity: 0, y: 20 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-6"
          >
            {/* 排序选项 */}
            <div className="flex flex-wrap items-center gap-3 mb-4">
              <span className="text-sm text-white/60 flex items-center gap-1">
                <TrendingUp className="w-4 h-4" />
                排序：
              </span>
              <button
                onClick={() => {
                  if (sortBy === 'publish_date') {
                    setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
                  } else {
                    setSortBy('publish_date')
                    setSortOrder('desc')
                  }
                }}
                className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1 transition-colors ${getSortButtonStyle('publish_date')}`}
              >
                <Calendar className="w-3 h-3" />
                发布时间
                {sortBy === 'publish_date' && (
                  sortOrder === 'desc' ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />
                )}
              </button>
              <button
                onClick={() => {
                  if (sortBy === 'salary') {
                    setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
                  } else {
                    setSortBy('salary')
                    setSortOrder('desc')
                  }
                }}
                className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1 transition-colors ${getSortButtonStyle('salary')}`}
              >
                <DollarSign className="w-3 h-3" />
                薪资
                {sortBy === 'salary' && (
                  sortOrder === 'desc' ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />
                )}
              </button>
              <button
                onClick={() => {
                  if (sortBy === 'company_scale_value') {
                    setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
                  } else {
                    setSortBy('company_scale_value')
                    setSortOrder('desc')
                  }
                }}
                className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1 transition-colors ${getSortButtonStyle('company_scale_value')}`}
              >
                <Building2 className="w-3 h-3" />
                公司体量
                {sortBy === 'company_scale_value' && (
                  sortOrder === 'desc' ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />
                )}
              </button>
              <button
                onClick={() => {
                  if (sortBy === 'job_level') {
                    setSortOrder(sortOrder === 'asc' ? 'desc' : 'asc')
                  } else {
                    setSortBy('job_level')
                    setSortOrder('desc')
                  }
                }}
                className={`px-3 py-1.5 rounded-lg text-sm flex items-center gap-1 transition-colors ${getSortButtonStyle('job_level')}`}
              >
                <Award className="w-3 h-3" />
                岗位等级
                {sortBy === 'job_level' && (
                  sortOrder === 'desc' ? <ChevronDown className="w-3 h-3" /> : <ChevronUp className="w-3 h-3" />
                )}
              </button>
              
              <div className="flex-1" />
              
              <button
                onClick={() => setShowFilters(!showFilters)}
                className="px-4 py-1.5 rounded-lg bg-white/10 hover:bg-white/20 text-sm flex items-center gap-2 transition-colors"
              >
                <Filter className="w-4 h-4" />
                {showFilters ? '收起筛选' : '更多筛选'}
              </button>
            </div>
            
            {/* 展开的高级筛选 */}
            <AnimatePresence>
              {showFilters && (
                <motion.div
                  initial={{ opacity: 0, height: 0 }}
                  animate={{ opacity: 1, height: 'auto' }}
                  exit={{ opacity: 0, height: 0 }}
                  className="overflow-hidden"
                >
                  <div className="p-4 rounded-xl bg-white/5 border border-white/10 space-y-4">
                    {/* 岗位概述搜索 */}
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-sm text-white/60 flex items-center gap-1">
                        <Search className="w-4 h-4" />
                        岗位概述：
                      </span>
                      <div className="relative flex-1 max-w-md">
                        <input
                          type="text"
                          value={searchSummary}
                          onChange={(e) => setSearchSummary(e.target.value)}
                          placeholder="搜索岗位名称、技能或概述..."
                          className="w-full px-4 py-2 pr-10 rounded-lg bg-white/10 border border-white/20 text-sm focus:outline-none focus:border-[#4D6CFA] placeholder:text-white/30"
                        />
                        {searchSummary && (
                          <button
                            onClick={() => setSearchSummary('')}
                            className="absolute right-3 top-1/2 -translate-y-1/2 text-white/40 hover:text-white"
                          >
                            <X className="w-4 h-4" />
                          </button>
                        )}
                      </div>
                    </div>
                    
                    {/* 筛选器行 */}
                    <div className="flex flex-wrap items-center gap-3">
                      <span className="text-sm text-white/60 flex items-center gap-1">
                        <Briefcase className="w-4 h-4" />
                        工作年限：
                      </span>
                      <select 
                        value={selectedExperience}
                        onChange={(e) => setSelectedExperience(e.target.value)}
                        className="px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-sm focus:outline-none focus:border-[#4D6CFA]"
                      >
                        <option value="all">全部</option>
                        {EXPERIENCE_ORDER.map(exp => (
                          <option key={exp} value={exp}>{exp}</option>
                        ))}
                      </select>
                      
                      <span className="text-sm text-white/60 flex items-center gap-1 ml-4">
                        <GraduationCap className="w-4 h-4" />
                        学历：
                      </span>
                      <select 
                        value={selectedEducation}
                        onChange={(e) => setSelectedEducation(e.target.value)}
                        className="px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-sm focus:outline-none focus:border-[#4D6CFA]"
                      >
                        <option value="all">全部</option>
                        <option value="本科">本科</option>
                        <option value="硕士">硕士</option>
                        <option value="博士">博士</option>
                      </select>
                      
                      <span className="text-sm text-white/60 flex items-center gap-1 ml-4">
                        <Award className="w-4 h-4" />
                        岗位等级：
                      </span>
                      <select 
                        value={selectedJobLevel}
                        onChange={(e) => setSelectedJobLevel(e.target.value)}
                        className="px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-sm focus:outline-none focus:border-[#4D6CFA]"
                      >
                        <option value="all">全部</option>
                        {JOB_LEVEL_ORDER.map(level => (
                          <option key={level} value={level}>{level}</option>
                        ))}
                      </select>
                      
                      <span className="text-sm text-white/60 flex items-center gap-1 ml-4">
                        <MapPin className="w-4 h-4" />
                        城市：
                      </span>
                      <select 
                        value={selectedCity}
                        onChange={(e) => setSelectedCity(e.target.value)}
                        className="px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-sm focus:outline-none focus:border-[#4D6CFA]"
                      >
                        <option value="all">全部</option>
                        {cities.map(city => (
                          <option key={city} value={city}>{city}</option>
                        ))}
                      </select>
                      
                      <span className="text-sm text-white/60 flex items-center gap-1 ml-4">
                        平台：
                      </span>
                      <select 
                        value={selectedPlatform}
                        onChange={(e) => setSelectedPlatform(e.target.value)}
                        className="px-3 py-2 rounded-lg bg-white/10 border border-white/20 text-sm focus:outline-none focus:border-[#4D6CFA]"
                      >
                        <option value="all">全部</option>
                        <option value="51job">51job</option>
                        <option value="Boss直聘">Boss直聘</option>
                        <option value="猎聘网">猎聘网</option>
                      </select>
                    </div>
                    
                    {/* 清除筛选 */}
                    <div className="flex justify-end pt-2 border-t border-white/10">
                      <button
                        onClick={clearFilters}
                        className="px-4 py-2 rounded-lg text-sm text-white/60 hover:text-white hover:bg-white/10 transition-colors flex items-center gap-2"
                      >
                        <X className="w-4 h-4" />
                        清除所有筛选
                      </button>
                    </div>
                  </div>
                </motion.div>
              )}
            </AnimatePresence>
            
            {/* 结果统计 */}
            <div className="mt-4 flex items-center gap-4 text-sm text-white/60">
              <span>共找到 <span className="text-white font-semibold">{processedJobs.length}</span> 个岗位</span>
              {(selectedPlatform !== 'all' || selectedCity !== 'all' || selectedExperience !== 'all' || selectedEducation !== 'all' || selectedJobLevel !== 'all' || searchSummary) && (
                <span className="flex items-center gap-1 text-[#F5B935]">
                  <AlertCircle className="w-3 h-3" />
                  已应用筛选
                </span>
              )}
            </div>
          </motion.div>

          {/* 岗位卡片 */}
          <div className="space-y-4">
            <AnimatePresence mode="popLayout">
              {displayedJobs.map((job, index) => (
                <motion.div
                  key={job.id}
                  layout
                  initial={{ opacity: 0, y: 30 }}
                  animate={{ opacity: 1, y: 0 }}
                  exit={{ opacity: 0, scale: 0.95 }}
                  transition={{ delay: index * 0.03 }}
                  whileHover={{ scale: 1.01 }}
                  className="p-6 rounded-xl bg-gradient-to-r from-white/10 to-white/5 backdrop-blur-sm border border-white/10 hover:border-[#4D6CFA]/50 transition-colors group"
                >
                  <div className="flex flex-wrap items-start justify-between gap-4">
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-3 mb-2 flex-wrap">
                        <h3 className="text-lg font-semibold group-hover:text-[#4D6CFA] transition-colors">
                          {job.title}
                        </h3>
                        <span 
                          className="px-2 py-1 text-xs rounded-full"
                          style={{ 
                            backgroundColor: `${PLATFORM_COLORS[job.platform]}30`,
                            color: PLATFORM_COLORS[job.platform]
                          }}
                        >
                          {job.platform}
                        </span>
                        <span className="px-2 py-1 text-xs rounded-full bg-[#F5B935]/20 text-[#F5B935]">
                          {job.job_level}
                        </span>
                        {/* 今日新发布标签 */}
                        {job.publish_date === new Date().toISOString().split('T')[0] && (
                          <span className="px-2 py-1 text-xs rounded-full bg-[#00B578]/20 text-[#00B578] flex items-center gap-1">
                            <span className="w-1.5 h-1.5 bg-[#00B578] rounded-full animate-pulse" />
                            今日新发布
                          </span>
                        )}
                        {/* 今日更新标签 */}
                        {job.update_date === new Date().toISOString().split('T')[0] && job.publish_date !== job.update_date && (
                          <span className="px-2 py-1 text-xs rounded-full bg-[#F5B935]/20 text-[#F5B935]">
                            今日更新
                          </span>
                        )}
                      </div>
                      
                      {/* 岗位概述 */}
                      <p className="text-sm text-white/60 mb-3 line-clamp-2">
                        {job.summary}
                      </p>
                      
                      <div className="flex flex-wrap items-center gap-4 text-sm text-white/60 mb-3">
                        <span className="flex items-center gap-1" title={`公司体量评分: ${job.company_scale_value}`}>
                          <Building2 className="w-4 h-4" />
                          {job.company}
                          <span className="px-1.5 py-0.5 text-xs rounded bg-white/10 text-white/40">
                            {job.company_level}
                          </span>
                        </span>
                        <span className="flex items-center gap-1">
                          <MapPin className="w-4 h-4" />
                          {job.city}
                        </span>
                        <span className="flex items-center gap-1">
                          <GraduationCap className="w-4 h-4" />
                          {job.education}
                        </span>
                        <span className="flex items-center gap-1">
                          <Briefcase className="w-4 h-4" />
                          {job.experience}
                        </span>
                      </div>
                      <div className="flex flex-wrap gap-2">
                        {job.skills.map(skill => (
                          <span 
                            key={skill}
                            className="px-2 py-1 text-xs rounded-md bg-white/10 text-white/70"
                          >
                            {skill}
                          </span>
                        ))}
                      </div>
                    </div>
                    <div className="text-right flex-shrink-0">
                      <div className="text-xl font-bold text-[#F5B935]">
                        {job.salary_min}-{job.salary_max}K
                      </div>
                      <div className="text-sm text-white/60 flex items-center gap-1 justify-end">
                        <Clock className="w-3 h-3" />
                        {job.publish_date}
                      </div>
                    </div>
                  </div>
                </motion.div>
              ))}
            </AnimatePresence>
          </div>

          {/* 加载更多 */}
          {processedJobs.length > 6 && (
            <motion.div
              initial={{ opacity: 0 }}
              whileInView={{ opacity: 1 }}
              viewport={{ once: true }}
              className="mt-8 text-center"
            >
              <button
                onClick={() => setShowAllJobs(!showAllJobs)}
                className="px-6 py-3 rounded-lg bg-[#1B45F4] hover:bg-[#4D6CFA] transition-colors flex items-center gap-2 mx-auto"
              >
                {showAllJobs ? (
                  <>
                    收起 <ChevronUp className="w-4 h-4" />
                  </>
                ) : (
                  <>
                    查看更多 ({processedJobs.length - 6}个) <ChevronDown className="w-4 h-4" />
                  </>
                )}
              </button>
            </motion.div>
          )}
          
          {/* 无结果提示 */}
          {processedJobs.length === 0 && (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="text-center py-12"
            >
              <div className="text-white/40 mb-4">
                <Search className="w-16 h-16 mx-auto" />
              </div>
              <p className="text-white/60">没有找到符合条件的岗位</p>
              <button
                onClick={clearFilters}
                className="mt-4 px-4 py-2 rounded-lg bg-white/10 hover:bg-white/20 text-sm transition-colors"
              >
                清除筛选条件
              </button>
            </motion.div>
          )}
        </div>
      </section>

      {/* 猎头资源 */}
      <section className="py-20 px-4 bg-gradient-to-b from-white/5 to-transparent">
        <div className="max-w-7xl mx-auto">
          <motion.div
            initial={{ opacity: 0, x: -50 }}
            whileInView={{ opacity: 1, x: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h2 className="text-3xl md:text-4xl font-bold mb-4">猎头资源</h2>
            <p className="text-white/60">专业猎头顾问与机构，助力职业发展</p>
          </motion.div>

          {/* 猎头顾问 */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
            className="mb-12"
          >
            <h3 className="text-xl font-semibold mb-6 flex items-center gap-2">
              <Briefcase className="w-5 h-5 text-[#4D6CFA]" />
              专业猎头顾问
            </h3>
            <div className="grid md:grid-cols-2 lg:grid-cols-3 gap-6">
              {headhunters.map((headhunter, index) => (
                <motion.a
                  key={headhunter.id}
                  href={headhunter.profile_url}
                  target="_blank"
                  rel="noopener noreferrer"
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.1 }}
                  whileHover={{ y: -5, scale: 1.02 }}
                  className="p-5 rounded-xl bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-sm border border-white/10 hover:border-[#4D6CFA]/50 transition-all cursor-pointer group"
                >
                  <div className="flex items-start gap-4">
                    <div className="relative">
                      <img
                        src={headhunter.avatar}
                        alt={headhunter.name}
                        className="w-16 h-16 rounded-full bg-white/10 object-cover"
                      />
                      <div 
                        className="absolute -bottom-1 -right-1 w-5 h-5 rounded-full border-2 border-[#0A1628]"
                        style={{ backgroundColor: PLATFORM_COLORS[headhunter.platform] }}
                        title={headhunter.platform}
                      />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2 mb-1">
                        <h4 className="font-semibold text-lg group-hover:text-[#4D6CFA] transition-colors">
                          {headhunter.name}
                        </h4>
                        <span className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/60">
                          {headhunter.platform}
                        </span>
                      </div>
                      <p className="text-sm text-white/60 mb-1">{headhunter.company}</p>
                      <p className="text-xs text-[#F5B935]">{headhunter.experience}</p>
                      <div className="mt-2 flex flex-wrap gap-1">
                        <span className="text-xs px-2 py-1 rounded-md bg-[#1B45F4]/20 text-[#4D6CFA]">
                          {headhunter.specialty}
                        </span>
                      </div>
                    </div>
                  </div>
                  <div className="mt-4 pt-3 border-t border-white/10 flex items-center justify-between">
                    <span className="text-xs text-white/40">点击查看主页</span>
                    <ExternalLink className="w-4 h-4 text-white/40 group-hover:text-[#4D6CFA] transition-colors" />
                  </div>
                </motion.a>
              ))}
            </div>
          </motion.div>

          {/* 猎头机构 */}
          <motion.div
            initial={{ opacity: 0, y: 30 }}
            whileInView={{ opacity: 1, y: 0 }}
            viewport={{ once: true }}
          >
            <h3 className="text-xl font-semibold mb-6 flex items-center gap-2">
              <Building2 className="w-5 h-5 text-[#F5B935]" />
              知名猎头机构
            </h3>
            <div className="grid md:grid-cols-2 lg:grid-cols-4 gap-6">
              {agencies.map((agency, index) => (
                <motion.a
                  key={agency.id}
                  href={agency.website}
                  target="_blank"
                  rel="noopener noreferrer"
                  initial={{ opacity: 0, y: 20 }}
                  whileInView={{ opacity: 1, y: 0 }}
                  viewport={{ once: true }}
                  transition={{ delay: index * 0.1 }}
                  whileHover={{ y: -5, scale: 1.02 }}
                  className="p-5 rounded-xl bg-gradient-to-br from-white/10 to-white/5 backdrop-blur-sm border border-white/10 hover:border-[#F5B935]/50 transition-all cursor-pointer group text-center"
                >
                  <div className="w-16 h-16 mx-auto mb-4 rounded-xl bg-gradient-to-br from-[#1B45F4] to-[#4D6CFA] flex items-center justify-center text-white font-bold text-xl">
                    {agency.name.slice(0, 2)}
                  </div>
                  <h4 className="font-semibold text-lg mb-2 group-hover:text-[#F5B935] transition-colors">
                    {agency.name}
                  </h4>
                  <p className="text-sm text-white/60 mb-3 line-clamp-2">{agency.description}</p>
                  <div className="flex flex-wrap justify-center gap-1 mb-3">
                    {agency.platforms.map(platform => (
                      <span
                        key={platform}
                        className="text-xs px-2 py-0.5 rounded-full bg-white/10 text-white/50"
                        style={{ color: PLATFORM_COLORS[platform] }}
                      >
                        {platform}
                      </span>
                    ))}
                  </div>
                  <div className="pt-3 border-t border-white/10 flex items-center justify-center gap-2 text-xs text-white/40">
                    <span>访问官网</span>
                    <ExternalLink className="w-3 h-3" />
                  </div>
                </motion.a>
              ))}
            </div>
          </motion.div>
        </div>
      </section>

      {/* Footer */}
      <footer className="py-12 px-4 border-t border-white/10">
        <div className="max-w-7xl mx-auto text-center">
          <motion.div
            initial={{ opacity: 0 }}
            whileInView={{ opacity: 1 }}
            viewport={{ once: true }}
          >
            <div className="flex items-center justify-center gap-2 mb-4 text-white/40">
              <RefreshCw className="w-4 h-4" />
              <span className="text-sm">最后更新: {stats.last_update}</span>
            </div>
            <p className="text-xl font-light mb-4">
              数据驱动决策，洞察引领未来
            </p>
            <p className="text-sm text-white/40">
              © 2024 医药健康AI人才洞察平台 | 数据来源：51job、Boss直聘、猎聘网
            </p>
          </motion.div>
        </div>
      </footer>
    </div>
  )
}

export default App

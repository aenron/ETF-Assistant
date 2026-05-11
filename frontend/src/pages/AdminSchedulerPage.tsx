import { useEffect, useMemo, useState } from 'react'
import { CalendarClock, Loader2, Play, RefreshCw, ShieldCheck } from 'lucide-react'

import { schedulerApi, type SchedulerJob } from '@/services/api'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Switch } from '@/components/ui/switch'
import { formatBeijingTime } from '@/utils/time'

function describeJob(job: SchedulerJob) {
  if (job.id === 'daily_analysis') return '工作日收盘后为所有活跃用户生成持仓分析，并按用户通知配置推送。'
  if (job.id === 'weekly_account_analysis') return '每周五收盘后为所有活跃用户生成账户级分析，并推送摘要。'
  if (job.id === 'market_refresh' || job.id.startsWith('market_refresh_')) return 'A股交易时段刷新活跃用户持仓 ETF 的行情缓存。'
  if (job.id === 'etf_profile_refresh') return '交易日 09:15 和 13:15 刷新活跃用户持仓 ETF 的资料快照、资产配置、公告和基金持仓。'
  return '后台调度任务'
}

function jobTone(job: SchedulerJob) {
  if (job.id === 'daily_analysis') return 'border-blue-200 bg-blue-50 text-blue-700'
  if (job.id === 'weekly_account_analysis') return 'border-violet-200 bg-violet-50 text-violet-700'
  if (job.id === 'market_refresh' || job.id.startsWith('market_refresh_')) return 'border-emerald-200 bg-emerald-50 text-emerald-700'
  if (job.id === 'etf_profile_refresh') return 'border-amber-200 bg-amber-50 text-amber-700'
  return 'border-slate-200 bg-slate-50 text-slate-700'
}

export function AdminSchedulerPage() {
  const [running, setRunning] = useState(false)
  const [jobs, setJobs] = useState<SchedulerJob[]>([])
  const [loading, setLoading] = useState(true)
  const [busyJobId, setBusyJobId] = useState<string | null>(null)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error' | 'neutral'>('neutral')

  const loadJobs = async (options?: { silent?: boolean }) => {
    if (!options?.silent) setLoading(true)
    setMessage(null)
    try {
      const res = await schedulerApi.listJobs()
      setRunning(res.data.running)
      setJobs(res.data.jobs)
    } catch (error: any) {
      console.error('Failed to load scheduler jobs:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '加载定时任务失败')
    } finally {
      if (!options?.silent) setLoading(false)
    }
  }

  const runJob = async (job: SchedulerJob) => {
    setBusyJobId(job.id)
    setMessage(null)
    try {
      const res = await schedulerApi.runJob(job.id)
      setMessageTone('success')
      setMessage(res.data.message || '任务已开始执行')
      await loadJobs({ silent: true })
    } catch (error: any) {
      console.error('Failed to run scheduler job:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '手动执行任务失败')
    } finally {
      setBusyJobId(null)
    }
  }

  const toggleJob = async (job: SchedulerJob, enabled: boolean) => {
    setBusyJobId(job.id)
    setMessage(null)
    try {
      const res = enabled
        ? await schedulerApi.resumeJob(job.id)
        : await schedulerApi.pauseJob(job.id)
      setMessageTone('success')
      setMessage(res.data.message || (enabled ? '任务已恢复' : '任务已暂停'))
      await loadJobs({ silent: true })
    } catch (error: any) {
      console.error('Failed to toggle scheduler job:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '更新任务状态失败')
    } finally {
      setBusyJobId(null)
    }
  }

  useEffect(() => {
    loadJobs()
  }, [])

  const stats = useMemo(() => {
    const enabledCount = jobs.filter((job) => job.enabled).length
    return {
      total: jobs.length,
      enabled: enabledCount,
      paused: jobs.length - enabledCount,
    }
  }, [jobs])

  const bannerClassName =
    messageTone === 'success'
      ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
      : messageTone === 'error'
        ? 'border-red-200 bg-red-50 text-red-700'
        : 'border-slate-200 bg-slate-50 text-slate-700'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">定时任务</h1>
          <p className="mt-1 text-sm text-muted-foreground">查看后台 APScheduler 任务，并手动执行或暂停单个任务。</p>
        </div>
        <Button variant="outline" onClick={() => loadJobs()} disabled={loading} className="w-full sm:w-auto">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {message && (
        <div className={`rounded-xl border px-4 py-3 text-sm ${bannerClassName}`}>
          {message}
        </div>
      )}

      <div className="grid gap-4 sm:grid-cols-4">
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">调度器</CardTitle>
          </CardHeader>
          <CardContent>
            <Badge variant="outline" className={running ? 'border-emerald-300 bg-emerald-50 text-emerald-700' : 'border-red-300 bg-red-50 text-red-700'}>
              {running ? '运行中' : '未运行'}
            </Badge>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">任务总数</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.total}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">启用</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.enabled}</div>
          </CardContent>
        </Card>
        <Card>
          <CardHeader className="pb-2">
            <CardTitle className="text-sm font-medium text-muted-foreground">暂停</CardTitle>
          </CardHeader>
          <CardContent>
            <div className="text-2xl font-bold">{stats.paused}</div>
          </CardContent>
        </Card>
      </div>

      <Card>
        <CardHeader className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <CardTitle className="flex items-center gap-2">
            <CalendarClock className="h-5 w-5 text-primary" />
            任务列表
          </CardTitle>
          <div className="inline-flex items-center gap-1.5 text-xs text-muted-foreground">
            <ShieldCheck className="h-3.5 w-3.5" />
            仅管理员可操作
          </div>
        </CardHeader>
        <CardContent>
          {loading ? (
            <div className="flex items-center justify-center py-12 text-sm text-muted-foreground">
              <Loader2 className="mr-2 h-4 w-4 animate-spin" />
              加载任务中...
            </div>
          ) : (
            <div className="space-y-3">
              {jobs.map((job) => {
                const busy = busyJobId === job.id
                return (
                  <div key={job.id} className="rounded-xl border bg-background p-4 shadow-sm">
                    <div className="grid gap-4 xl:grid-cols-[minmax(0,1fr)_220px_220px] xl:items-center">
                      <div className="min-w-0 space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="font-medium">{job.name}</div>
                          <Badge variant="outline" className={jobTone(job)}>
                            {job.enabled ? '已启用' : '已暂停'}
                          </Badge>
                          <span className="font-mono text-xs text-muted-foreground">{job.id}</span>
                        </div>
                        <p className="text-sm text-muted-foreground">{describeJob(job)}</p>
                        <div className="rounded-lg border bg-muted/30 px-3 py-2 font-mono text-xs text-muted-foreground">
                          {job.trigger}
                        </div>
                      </div>

                      <div className="rounded-lg border bg-slate-50 px-3 py-2">
                        <div className="text-xs text-muted-foreground">下次执行</div>
                        <div className="mt-1 text-sm font-medium">{formatBeijingTime(job.next_run_time, {}, '已暂停')}</div>
                      </div>

                      <div className="flex flex-col gap-2 sm:flex-row xl:justify-end">
                        <Button variant="outline" onClick={() => runJob(job)} disabled={busy || !running} className="w-full sm:w-auto">
                          {busy ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                          手动执行
                        </Button>
                        <label className="flex min-h-10 items-center justify-between gap-3 rounded-lg border px-3 py-2">
                          <span className="text-sm">{job.enabled ? '启用' : '暂停'}</span>
                          <Switch
                            checked={job.enabled}
                            disabled={busy}
                            onCheckedChange={(checked) => toggleJob(job, checked)}
                          />
                        </label>
                      </div>
                    </div>
                  </div>
                )
              })}
              {jobs.length === 0 && (
                <div className="rounded-xl border border-dashed py-12 text-center text-sm text-muted-foreground">
                  暂无已注册定时任务
                </div>
              )}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  )
}

import { useEffect, useState } from 'react'
import { Loader2, RefreshCw, Save } from 'lucide-react'

import { adminApi, type DcaSignalConfig } from '@/services/api'
import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'

const fields: Array<{ key: keyof DcaSignalConfig; label: string; step?: string; group: string }> = [
  { key: 'valuation_deep_green_percentile', label: '深绿分位', step: '0.1', group: '估值轨' },
  { key: 'valuation_green_percentile', label: '绿灯分位', step: '0.1', group: '估值轨' },
  { key: 'valuation_red_percentile', label: '红灯分位', step: '0.1', group: '估值轨' },
  { key: 'valuation_min_sample_size', label: '估值最小样本', group: '估值轨' },
  { key: 'trend_short_ma_days', label: '短期均线', group: '趋势轨' },
  { key: 'trend_medium_ma_days', label: '中期均线', group: '趋势轨' },
  { key: 'trend_long_ma_days', label: '长期均线', group: '趋势轨' },
  { key: 'trend_history_days', label: 'K线读取天数', group: '趋势轨' },
  { key: 'trend_slope_shift_days', label: '斜率间隔天数', group: '趋势轨' },
  { key: 'trend_volume_ma_days', label: '成交量均线', group: '量能确认' },
  { key: 'trend_volume_confirm_ratio', label: '量能确认倍数', step: '0.01', group: '量能确认' },
  { key: 'trend_volume_expand_ratio', label: '放量加分倍数', step: '0.01', group: '量能确认' },
  { key: 'trend_atr_days', label: 'ATR周期', group: '波动过滤' },
  { key: 'trend_atr_base_multiplier', label: '常规ATR倍数', step: '0.1', group: '波动过滤' },
  { key: 'trend_atr_mid_multiplier', label: '中高波动ATR倍数', step: '0.1', group: '波动过滤' },
  { key: 'trend_atr_high_multiplier', label: '高波动ATR倍数', step: '0.1', group: '波动过滤' },
  { key: 'trend_atr_mid_volatility_pct', label: '中高波动阈值%', step: '0.1', group: '波动过滤' },
  { key: 'trend_atr_high_volatility_pct', label: '高波动阈值%', step: '0.1', group: '波动过滤' },
  { key: 'light_confirm_count', label: '灯色确认次数', group: '状态确认' },
]

const groups = Array.from(new Set(fields.map((field) => field.group)))

type FormState = Record<string, string>

export function AdminDcaSignalConfigPage() {
  const [form, setForm] = useState<FormState>({})
  const [loading, setLoading] = useState(true)
  const [saving, setSaving] = useState(false)
  const [message, setMessage] = useState<string | null>(null)
  const [messageTone, setMessageTone] = useState<'success' | 'error'>('success')

  const loadConfig = async () => {
    setLoading(true)
    setMessage(null)
    try {
      const res = await adminApi.getDcaSignalConfig()
      const next: FormState = {}
      fields.forEach((field) => {
        next[field.key] = String(res.data[field.key] ?? '')
      })
      setForm(next)
    } catch (error: any) {
      console.error('Failed to load DCA signal config:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '加载红绿灯参数失败')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    loadConfig()
  }, [])

  const saveConfig = async () => {
    setSaving(true)
    setMessage(null)
    try {
      const payload: Record<string, number> = {}
      fields.forEach((field) => {
        const value = Number(form[field.key])
        if (!Number.isNaN(value)) payload[field.key] = value
      })
      const res = await adminApi.updateDcaSignalConfig(payload)
      const next: FormState = {}
      fields.forEach((field) => {
        next[field.key] = String(res.data[field.key] ?? '')
      })
      setForm(next)
      setMessageTone('success')
      setMessage('红绿灯参数已保存')
    } catch (error: any) {
      console.error('Failed to update DCA signal config:', error)
      setMessageTone('error')
      setMessage(error.response?.data?.detail || '保存红绿灯参数失败')
    } finally {
      setSaving(false)
    }
  }

  const messageClassName = messageTone === 'success'
    ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
    : 'border-red-200 bg-red-50 text-red-700'

  return (
    <div className="space-y-6">
      <div className="flex flex-col gap-4 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-2xl font-bold sm:text-3xl">红绿灯参数</h1>
          <p className="mt-1 text-sm text-muted-foreground">配置定投红绿灯的估值阈值、趋势均线、量能确认、ATR过滤和灯色确认次数。</p>
        </div>
        <Button variant="outline" onClick={loadConfig} disabled={loading} className="w-full sm:w-auto">
          <RefreshCw className={`mr-2 h-4 w-4 ${loading ? 'animate-spin' : ''}`} />
          刷新
        </Button>
      </div>

      {message && <div className={`rounded-xl border px-4 py-3 text-sm ${messageClassName}`}>{message}</div>}

      {loading ? (
        <Card><CardContent className="flex items-center justify-center py-12 text-sm text-muted-foreground"><Loader2 className="mr-2 h-4 w-4 animate-spin" />加载参数中...</CardContent></Card>
      ) : (
        <div className="space-y-4">
          {groups.map((group) => (
            <Card key={group}>
              <CardHeader><CardTitle>{group}</CardTitle></CardHeader>
              <CardContent>
                <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
                  {fields.filter((field) => field.group === group).map((field) => (
                    <label key={field.key} className="space-y-1.5">
                      <span className="text-sm font-medium">{field.label}</span>
                      <Input
                        type="number"
                        step={field.step || '1'}
                        value={form[field.key] || ''}
                        onChange={(event) => setForm((prev) => ({ ...prev, [field.key]: event.target.value }))}
                      />
                    </label>
                  ))}
                </div>
              </CardContent>
            </Card>
          ))}
          <div className="flex justify-end">
            <Button onClick={saveConfig} disabled={saving} className="w-full sm:w-auto">
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
              保存参数
            </Button>
          </div>
        </div>
      )}
    </div>
  )
}

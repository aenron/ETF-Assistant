import { useEffect, useState } from 'react'
import { llmApi, type LLMConfigResponse } from '@/services/api'
import { Button } from '@/components/ui/button'
import { RadioGroup, RadioGroupItem } from '@/components/ui/radio-group'
import { Label } from '@/components/ui/label'
import { Badge } from '@/components/ui/badge'
import { Sparkles, Check, Search } from 'lucide-react'
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'

export function LLMSelector() {
  const [config, setConfig] = useState<LLMConfigResponse | null>(null)
  const [selected, setSelected] = useState<string>('')
  const [loading, setLoading] = useState(false)
  const [open, setOpen] = useState(false)

  useEffect(() => {
    if (open) {
      fetchConfig()
    }
  }, [open])

  const fetchConfig = async () => {
    try {
      const res = await llmApi.getProviders()
      setConfig(res.data)
      setSelected(res.data.current_provider)
    } catch (error) {
      console.error('Failed to fetch LLM config:', error)
    }
  }

  const handleSwitch = async () => {
    if (!selected || selected === config?.current_provider) {
      setOpen(false)
      return
    }

    setLoading(true)
    try {
      const res = await llmApi.switchProvider(selected)
      if (res.data.success) {
        if (config) {
          setConfig({ ...config, current_provider: selected })
        }
        setOpen(false)
      } else {
        alert(res.data.message || '切换失败')
      }
    } catch (error) {
      console.error('Failed to switch LLM:', error)
      alert('切换失败')
    } finally {
      setLoading(false)
    }
  }

  const currentProvider = config?.providers.find(p => p.id === config.current_provider)

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className="gap-2">
          <Sparkles className="h-4 w-4" />
          {currentProvider?.name || '选择模型'}
        </Button>
      </DialogTrigger>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>选择AI模型</DialogTitle>
        </DialogHeader>
        <div className="py-4">
          {config ? (
            <>
              <RadioGroup value={selected} onValueChange={setSelected} className="space-y-3">
                {config.providers.map((provider) => (
                  <div
                    key={provider.id}
                    className={`flex items-center space-x-3 rounded-lg border p-3 ${
                      provider.enabled
                        ? 'cursor-pointer hover:bg-accent'
                        : 'cursor-not-allowed opacity-50'
                    } ${selected === provider.id ? 'border-primary bg-accent' : ''}`}
                    onClick={() => provider.enabled && setSelected(provider.id)}
                  >
                    <RadioGroupItem value={provider.id} disabled={!provider.enabled} />
                    <div className="flex-1">
                      <div className="flex items-center gap-2">
                        <Label className="font-medium">{provider.name}</Label>
                        {provider.enabled ? (
                          <Badge variant="secondary" className="text-xs">
                            可用
                          </Badge>
                        ) : (
                          <Badge variant="outline" className="text-xs">
                            未配置
                          </Badge>
                        )}
                        {provider.supports_search && (
                          <Badge variant="default" className="text-xs gap-1">
                            <Search className="h-3 w-3" />
                            联网搜索
                          </Badge>
                        )}
                      </div>
                      <p className="text-sm text-muted-foreground">{provider.description}</p>
                    </div>
                    {config.current_provider === provider.id && (
                      <Check className="h-4 w-4 text-primary" />
                    )}
                  </div>
                ))}
              </RadioGroup>
              <div className="mt-4 flex justify-end gap-2">
                <Button variant="outline" onClick={() => setOpen(false)}>
                  取消
                </Button>
                <Button onClick={handleSwitch} disabled={loading || selected === config.current_provider}>
                  {loading ? '切换中...' : '确认切换'}
                </Button>
              </div>
            </>
          ) : (
            <div className="text-center text-muted-foreground">加载中...</div>
          )}
        </div>
      </DialogContent>
    </Dialog>
  )
}

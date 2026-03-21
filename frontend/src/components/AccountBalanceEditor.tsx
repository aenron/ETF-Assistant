import { useEffect, useState } from 'react'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { authApi } from '@/services/authApi'
import { Pencil, Save } from 'lucide-react'

interface AccountBalanceEditorProps {
  balance?: number | null
  onBalanceChange?: (balance: number) => void
  triggerClassName?: string
}

export function AccountBalanceEditor({
  balance: balanceProp,
  onBalanceChange,
  triggerClassName,
}: AccountBalanceEditorProps) {
  const [open, setOpen] = useState(false)
  const [balance, setBalance] = useState<string>('')
  const [loading, setLoading] = useState(balanceProp === undefined)
  const [saving, setSaving] = useState(false)

  useEffect(() => {
    if (balanceProp !== undefined) {
      setBalance(balanceProp === null ? '' : balanceProp.toString())
      setLoading(false)
      return
    }

    fetchBalance()
  }, [balanceProp])

  const fetchBalance = async () => {
    setLoading(true)
    try {
      const res = await authApi.getAccountBalance()
      if (res.account_balance !== null) {
        setBalance(res.account_balance.toString())
      }
    } catch (error) {
      console.error('Failed to fetch account balance:', error)
    } finally {
      setLoading(false)
    }
  }

  const handleSave = async () => {
    const numBalance = parseFloat(balance)
    if (isNaN(numBalance) || numBalance <= 0) {
      alert('请输入有效的账户金额')
      return
    }

    setSaving(true)
    try {
      const res = await authApi.updateAccountBalance(numBalance)
      setBalance(res.account_balance.toString())
      onBalanceChange?.(res.account_balance)
      alert('账户金额已更新')
      setOpen(false)
    } catch (error) {
      console.error('Failed to update account balance:', error)
      alert('更新失败')
    } finally {
      setSaving(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button variant="outline" size="sm" className={triggerClassName}>
          <Pencil className="h-4 w-4 mr-2" />
          编辑
        </Button>
      </DialogTrigger>
      <DialogContent>
        <DialogHeader>
          <DialogTitle>编辑账户金额</DialogTitle>
          <DialogDescription>
            更新账户可用资金后，建议仓位会基于新的金额重新计算。
          </DialogDescription>
        </DialogHeader>
        <div className="space-y-2">
          <Label htmlFor="account-balance">当前账户金额（元）</Label>
          <Input
            id="account-balance"
            type="number"
            value={balance}
            onChange={(e) => setBalance(e.target.value)}
            placeholder="请输入账户金额"
            min="0"
            step="0.01"
            disabled={loading || saving}
          />
        </div>
        <DialogFooter>
          <Button onClick={handleSave} disabled={saving || loading}>
            <Save className="h-4 w-4 mr-2" />
            {saving ? '保存中...' : '保存'}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

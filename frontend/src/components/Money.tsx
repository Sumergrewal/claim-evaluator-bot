import { formatMoney } from '../utils/format'

type MoneyProps = {
  value: string | number | null | undefined
  className?: string
}

export function Money({ value, className }: MoneyProps) {
  return <span className={className ?? 'money'}>{formatMoney(value)}</span>
}

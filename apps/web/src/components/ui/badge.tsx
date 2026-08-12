import type { HTMLAttributes } from 'react'
import { cn } from '../../lib/utils'

type BadgeTone = 'fixture' | 'success' | 'warning' | 'neutral' | 'heat'

const tones: Record<BadgeTone, string> = {
  fixture: 'border-[#8d4f09]/30 bg-[#fff3d4] text-[#704006]',
  success: 'border-[#16665d]/25 bg-[#dff4ee] text-[#0b554e]',
  warning: 'border-[#a7422e]/25 bg-[#fff0e9] text-[#8e3423]',
  neutral: 'border-line bg-panel-raised text-muted-ink',
  heat: 'border-[#ba3c28]/25 bg-[#fff0e9] text-[#9d2f20]',
}

interface BadgeProps extends HTMLAttributes<HTMLSpanElement> {
  tone?: BadgeTone
}

export function Badge({ className, tone = 'neutral', ...props }: BadgeProps) {
  return (
    <span
      className={cn(
        'inline-flex min-h-6 items-center gap-1.5 rounded-full border px-2.5 py-0.5 text-[0.6875rem] font-bold uppercase tracking-[0.12em]',
        tones[tone],
        className,
      )}
      {...props}
    />
  )
}

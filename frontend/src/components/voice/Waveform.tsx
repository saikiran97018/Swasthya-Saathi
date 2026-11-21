import { useEffect, useRef } from 'react'
import { cn } from '@/lib/format'

interface Props {
  /** Live audio source (mic or playback). Without one, a calm idle animation is drawn. */
  analyser: AnalyserNode | null
  active: boolean
  className?: string
  bars?: number
}

/** Frequency-bar visualiser drawn on a canvas; respects reduced-motion by drawing static bars. */
export function Waveform({ analyser, active, className, bars = 28 }: Props) {
  const canvas = useRef<HTMLCanvasElement>(null)

  useEffect(() => {
    const el = canvas.current
    if (!el) return
    const ctx = el.getContext('2d')
    if (!ctx) return
    const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches
    const color = getComputedStyle(el).getPropertyValue('--accent').trim() || '#0f766e'
    const accent2 = getComputedStyle(el).getPropertyValue('--saffron').trim() || '#f59e0b'
    const data = analyser ? new Uint8Array(analyser.frequencyBinCount) : null
    let raf = 0
    let t = 0

    const resize = () => {
      const dpr = window.devicePixelRatio || 1
      const { width, height } = el.getBoundingClientRect()
      el.width = Math.round(width * dpr)
      el.height = Math.round(height * dpr)
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
    }
    resize()
    const ro = new ResizeObserver(resize)
    ro.observe(el)

    const draw = () => {
      const { width, height } = el.getBoundingClientRect()
      ctx.clearRect(0, 0, width, height)
      const gap = 4
      const w = Math.max(2, (width - gap * (bars - 1)) / bars)
      if (analyser && data && active) analyser.getByteFrequencyData(data)

      for (let i = 0; i < bars; i++) {
        let amp: number
        if (analyser && data && active) {
          // Voice energy sits in the low-mid bins; spread the bars across the first ~60 %.
          const bin = Math.floor((i / bars) * data.length * 0.6)
          amp = (data[bin] ?? 0) / 255
        } else {
          amp = reduce ? 0.12 : 0.1 + 0.07 * Math.sin(t * 2 + i * 0.5)
        }
        // Shape: taller in the middle so it reads as a voice, not a spectrum.
        const envelope = 0.55 + 0.45 * Math.sin((Math.PI * (i + 0.5)) / bars)
        const h = Math.max(4, amp * envelope * height * 1.05)
        const x = i * (w + gap)
        ctx.fillStyle = i % 5 === 0 ? accent2 : color
        ctx.globalAlpha = 0.55 + amp * 0.45
        ctx.beginPath()
        ctx.roundRect(x, (height - h) / 2, w, h, w / 2)
        ctx.fill()
      }
      ctx.globalAlpha = 1
      t += 0.03
      if (!reduce || (analyser && active)) raf = requestAnimationFrame(draw)
    }
    draw()
    return () => {
      cancelAnimationFrame(raf)
      ro.disconnect()
    }
  }, [analyser, active, bars])

  return <canvas ref={canvas} className={cn('h-16 w-full', className)} role="img" aria-label={active ? 'Live audio waveform' : 'Audio waveform, idle'} />
}

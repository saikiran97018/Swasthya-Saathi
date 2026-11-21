import { cn } from '@/lib/format'

/**
 * Friendly illustrated woman doctor with a floating heart-pulse badge. Drawn as inline SVG (no photo, no network),
 * used in the Triage hero. Decorative: hidden from assistive technology.
 */
export function DoctorIllustration({ className }: { className?: string }) {
  return (
    <svg viewBox="0 0 240 210" className={cn('h-auto', className)} aria-hidden focusable="false">
      {/* soft leaf shapes behind her */}
      <path d="M20 190c-8-40 4-80 40-100 4 38-8 78-40 100z" fill="#bfe6dd" opacity=".75" />
      <path d="M232 170c8-38-2-72-34-92-6 34 4 70 34 92z" fill="#a9ddd2" opacity=".7" />
      <path d="M205 40c-18 4-30 18-32 36 18-4 30-18 32-36z" fill="#cfeee6" />

      {/* floating heart-pulse badge */}
      <g>
        <rect x="26" y="26" width="52" height="52" rx="16" fill="#fff" />
        <rect x="26" y="26" width="52" height="52" rx="16" fill="none" stroke="#cde7e1" />
        <path d="M52 66C40 58 34 52 34 45.5 34 40.5 38 37 42.5 37c3.4 0 6.2 1.8 9.5 5.4 3.3-3.6 6.1-5.4 9.5-5.4 4.5 0 8.5 3.5 8.5 8.5C70 52 64 58 52 66z" fill="#17a597" />
        <path d="M33 52h9l3-7 5 12 4-9 2.5 4H71" fill="none" stroke="#fff" strokeWidth="2.6" strokeLinecap="round" strokeLinejoin="round" />
      </g>

      {/* hair behind: ponytail */}
      <path d="M150 62c14 4 22 20 20 40-2 16-8 26-16 32 2-16 0-30-6-42z" fill="#1d2640" />
      <path d="M92 66c-6 20-2 44 10 58l30-4c6-20 4-44-8-58z" fill="#1d2640" />

      {/* body: white coat */}
      <path d="M56 210c0-44 24-72 70-72s70 28 70 72z" fill="#fff" />
      <path d="M56 210c0-44 24-72 70-72s70 28 70 72" fill="none" stroke="#d3e6e1" strokeWidth="2" />
      {/* blue top */}
      <path d="M104 142l22 38 22-38c-8-5-36-5-44 0z" fill="#3b82c4" />
      {/* lapels */}
      <path d="M104 142l-14 12 24 56h12z" fill="#f2f8f7" stroke="#d3e6e1" strokeWidth="1.5" />
      <path d="M148 142l14 12-24 56h-12z" fill="#f2f8f7" stroke="#d3e6e1" strokeWidth="1.5" />

      {/* neck */}
      <path d="M116 118h20v26c-6 6-14 6-20 0z" fill="#efc09a" />
      {/* head */}
      <ellipse cx="126" cy="96" rx="27" ry="31" fill="#f6cfaa" />
      {/* fringe and top hair */}
      <path d="M99 94c-4-34 18-50 38-46 18 4 28 24 22 48-4-16-12-26-26-28-14 0-24 10-34 26z" fill="#1d2640" />
      {/* bun */}
      <circle cx="146" cy="48" r="13" fill="#1d2640" />
      {/* face */}
      <circle cx="116" cy="100" r="2.6" fill="#1d2640" />
      <circle cx="137" cy="100" r="2.6" fill="#1d2640" />
      <path d="M118 112c4 5 12 5 17 0" fill="none" stroke="#b5503f" strokeWidth="2.4" strokeLinecap="round" />
      <circle cx="109" cy="110" r="4.5" fill="#f19b8c" opacity=".45" />
      <circle cx="144" cy="110" r="4.5" fill="#f19b8c" opacity=".45" />

      {/* stethoscope */}
      <path d="M108 140c-6 18-2 34 12 40" fill="none" stroke="#33485a" strokeWidth="3.4" strokeLinecap="round" />
      <path d="M144 140c6 16 2 30-10 38" fill="none" stroke="#33485a" strokeWidth="3.4" strokeLinecap="round" />
      <circle cx="124" cy="184" r="6.5" fill="#dfe8ec" stroke="#33485a" strokeWidth="2.6" />

      {/* raised hand (viewer's left) */}
      <path d="M72 176c-12-10-18-26-16-44" fill="none" stroke="#f6cfaa" strokeWidth="15" strokeLinecap="round" />
      <ellipse cx="54" cy="124" rx="10" ry="13" fill="#f6cfaa" transform="rotate(-14 54 124)" />
      <path d="M46 114l-4-8M52 111l-1-9M58 112l3-8" stroke="#f6cfaa" strokeWidth="5" strokeLinecap="round" />
      {/* sleeve */}
      <path d="M72 190c-8-6-12-14-14-22l22 2z" fill="#fff" stroke="#d3e6e1" strokeWidth="1.5" />
    </svg>
  )
}

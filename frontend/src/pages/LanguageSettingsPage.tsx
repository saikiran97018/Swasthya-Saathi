import { Link } from 'react-router-dom'
import { ArrowLeft, Check, Headphones, Mic } from 'lucide-react'
import { usePrefs, useUpdatePrefs } from '@/api/hooks'
import { Badge, Button, PageHeader, Skeleton, Toggle } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { useLanguage } from '@/hooks/LanguageProvider'
import { cn } from '@/lib/format'

export default function LanguageSettingsPage() {
  const toast = useToast()
  const { languages } = useLanguage()
  const { data: prefs, isLoading, isError, refetch } = usePrefs()
  const update = useUpdatePrefs()

  const save = (patch: Parameters<typeof update.mutate>[0]) =>
    update.mutate(patch, { onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not save your language settings') })

  const setPrimary = (code: string) => {
    if (!prefs || prefs.primary_language === code) return
    save({ primary_language: code, secondary_languages: prefs.secondary_languages.filter((c) => c !== code) })
  }
  const toggleSecondary = (code: string) => {
    if (!prefs || prefs.primary_language === code) return
    const has = prefs.secondary_languages.includes(code)
    save({ secondary_languages: has ? prefs.secondary_languages.filter((c) => c !== code) : [...prefs.secondary_languages, code] })
  }

  return (
    <div className="mx-auto w-full max-w-4xl p-4 md:p-8">
      <Link to="/settings" className="mb-3 inline-flex items-center gap-1.5 text-sm font-medium text-muted hover:text-fg">
        <ArrowLeft className="size-4" aria-hidden /> Settings
      </Link>
      <PageHeader title="Languages" description="Choose the language you speak most. Saathi answers in it, and understands mixed speech like Hinglish." />

      {isError ? (
        <div role="alert" className="card flex items-center justify-between gap-3 p-4">
          <span className="text-sm text-danger">Could not load your language settings.</span>
          <Button size="sm" onClick={() => void refetch()}>Retry</Button>
        </div>
      ) : isLoading || !prefs ? (
        <Skeleton className="h-64" />
      ) : (
        <>
          <div className="card mb-6 px-5 divide-y divide-line">
            <Toggle
              checked={prefs.auto_detect_language}
              onChange={(v) => save({ auto_detect_language: v })}
              label="Detect my language automatically"
              description="If you switch to another script, for example type in Tamil, the reply follows. Turn off to always keep the conversation language."
            />
          </div>

          <ul className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3" aria-label="Languages">
            {languages.map((l) => {
              const primary = prefs.primary_language === l.code
              const secondary = prefs.secondary_languages.includes(l.code)
              return (
                <li key={l.code} className={cn('card flex flex-col gap-3 p-4 transition', primary && 'border-accent ring-2 ring-accent/25')}>
                  <div className="flex items-start justify-between gap-2">
                    <div className="min-w-0">
                      <div className="truncate text-xl font-semibold" lang={l.code}>{l.native_name}</div>
                      {l.native_name !== l.name && <div className="text-sm text-muted">{l.name}</div>}
                    </div>
                    {primary && <Badge tone="accent"><Check className="size-3" aria-hidden /> Primary</Badge>}
                  </div>
                  <div className="flex flex-wrap gap-1.5">
                    <Badge tone={l.asr ? 'ok' : 'neutral'} title={l.asr ? 'You can speak in this language' : 'Speaking is not available'}><Mic className="size-3" aria-hidden /> {l.asr ? 'Speak' : 'No voice input'}</Badge>
                    <Badge tone={l.tts ? 'ok' : 'neutral'} title={l.tts ? 'Replies can be read aloud' : 'Replies are text only'}><Headphones className="size-3" aria-hidden /> {l.tts ? 'Hear replies' : 'Text replies only'}</Badge>
                  </div>
                  <div className="mt-auto flex gap-2">
                    <button
                      onClick={() => setPrimary(l.code)}
                      aria-pressed={primary}
                      className={cn('h-9 flex-1 rounded-lg text-sm font-medium transition', primary ? 'bg-accent text-accent-fg' : 'bg-soft hover:bg-line')}
                    >
                      {primary ? 'Primary language' : 'Make primary'}
                    </button>
                    <button
                      onClick={() => toggleSecondary(l.code)}
                      disabled={primary}
                      aria-pressed={secondary}
                      className={cn('h-9 rounded-lg px-3 text-sm font-medium transition disabled:opacity-40', secondary ? 'bg-accent-soft text-accent-text' : 'bg-soft hover:bg-line')}
                    >
                      {secondary ? 'Also using' : 'Also use'}
                    </button>
                  </div>
                </li>
              )
            })}
          </ul>
        </>
      )}
    </div>
  )
}

import { useEffect, useState, type ReactNode } from 'react'
import { Link } from 'react-router-dom'
import { ChevronRight, Languages, Monitor, Moon, Sun, Users } from 'lucide-react'
import { useMe, usePrefs, useUpdateMe, useUpdatePrefs } from '@/api/hooks'
import type { Preferences } from '@/api/types'
import { PhoneNotifications } from '@/components/health/PhoneNotifications'
import { Badge, Button, PageHeader, Segmented, Skeleton, Toggle } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { useTheme } from '@/hooks/ThemeProvider'
import { languageLabel } from '@/lib/language'
import { useLanguage } from '@/hooks/LanguageProvider'

function Section({ title, description, children }: { title: string; description?: string; children: ReactNode }) {
  return (
    <section className="card mb-5 p-5" aria-label={title}>
      <h2 className="font-semibold">{title}</h2>
      {description && <p className="mt-0.5 text-sm text-muted">{description}</p>}
      <div className="mt-2 divide-y divide-line">{children}</div>
    </section>
  )
}

export default function SettingsPage() {
  const toast = useToast()
  const { theme, setTheme } = useTheme()
  const { languages } = useLanguage()
  const { data: me } = useMe()
  const { data: prefs, isLoading, isError: prefsError, refetch: refetchPrefs } = usePrefs()
  const updateMe = useUpdateMe()
  const update = useUpdatePrefs()

  const [name, setName] = useState('')
  useEffect(() => setName(me?.display_name ?? ''), [me?.display_name])

  const save = (patch: Partial<Preferences>) => update.mutate(patch, { onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not save that setting') })

  return (
    <div className="mx-auto w-full max-w-2xl p-4 md:p-8">
      <PageHeader title="Settings" description="Make Swasthya Saathi work the way you like." />

      <Section title="Profile">
        <form
          className="flex flex-wrap items-end gap-3 py-3"
          onSubmit={(e) => {
            e.preventDefault()
            const next = name.trim()
            if (next && next !== me?.display_name) updateMe.mutate(next, { onSuccess: () => toast.success('Name saved'), onError: (err) => toast.error(err instanceof Error ? err.message : 'Could not save your name') })
          }}
        >
          <div className="min-w-48 flex-1">
            <label htmlFor="display-name" className="mb-1.5 block text-sm font-medium">Your name</label>
            <input id="display-name" value={name} maxLength={120} onChange={(e) => setName(e.target.value)} className="h-10 w-full rounded-xl border border-line bg-bg px-3 text-[15px] outline-none focus:border-accent focus:ring-2 focus:ring-accent/25" />
          </div>
          <Button type="submit" variant="primary" loading={updateMe.isPending} disabled={!name.trim() || name.trim() === me?.display_name}>Save</Button>
        </form>
        {me?.is_guest && <p className="py-3 text-sm text-muted"><Badge>Guest</Badge> <span className="ml-1.5">Your conversations are saved to this browser's guest account.</span></p>}
      </Section>

      <Section title="Family" description="The people you book doctor visits for.">
        <Link to="/family" className="flex items-center gap-3 py-3.5 transition hover:text-accent-text">
          <Users className="size-5 text-accent-text" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">Family profiles</span>
            <span className="block text-sm text-muted">Add, edit or remove family members</span>
          </span>
          <ChevronRight className="size-4 text-muted" aria-hidden />
        </Link>
      </Section>

      <Section title="Appearance">
        <div className="flex items-center justify-between gap-4 py-3">
          <span className="text-sm font-medium">Theme</span>
          <Segmented<Preferences['theme']>
            label="Theme"
            value={theme}
            onChange={setTheme}
            options={[
              { value: 'light', label: <span className="inline-flex items-center gap-1.5"><Sun className="size-4" aria-hidden />Light</span> },
              { value: 'dark', label: <span className="inline-flex items-center gap-1.5"><Moon className="size-4" aria-hidden />Dark</span> },
              { value: 'system', label: <span className="inline-flex items-center gap-1.5"><Monitor className="size-4" aria-hidden />Auto</span> },
            ]}
          />
        </div>
      </Section>

      <Section title="Voice" description="How speaking and listening work.">
        {prefsError ? (
          <div role="alert" className="flex items-center justify-between gap-3 py-3">
            <span className="text-sm text-danger">Could not load your voice settings.</span>
            <Button size="sm" onClick={() => void refetchPrefs()}>Retry</Button>
          </div>
        ) : isLoading || !prefs ? (
          <Skeleton className="my-3 h-40" />
        ) : (
          <>
            <Toggle checked={prefs.voice_output_enabled} onChange={(v) => save({ voice_output_enabled: v })} label="Read replies aloud" description="Turn off to only see text answers." />
            <Toggle checked={prefs.auto_play_responses} disabled={!prefs.voice_output_enabled} onChange={(v) => save({ auto_play_responses: v })} label="Start speaking automatically" description="On the voice screen, replies begin playing as soon as they are ready." />
            <Toggle checked={prefs.auto_send_voice} onChange={(v) => save({ auto_send_voice: v })} label="Send what I say automatically" description="Skip the check step. When off, you can correct the text before it is sent." />
            <div className="flex items-center justify-between gap-4 py-3">
              <span className="text-sm font-medium">Voice of the replies</span>
              <Segmented<Preferences['tts_gender']> label="Voice" value={prefs.tts_gender} onChange={(v) => save({ tts_gender: v })} options={[{ value: 'female', label: 'Female' }, { value: 'male', label: 'Male' }]} />
            </div>
            <div className="py-3">
              <div className="mb-2 flex items-center justify-between">
                <label htmlFor="silence" className="text-sm font-medium">Wait after I stop talking</label>
                <span className="text-sm text-muted tabular-nums">{(prefs.silence_timeout_ms / 1000).toFixed(1)} s</span>
              </div>
              <input
                id="silence"
                type="range"
                min={500}
                max={5000}
                step={250}
                value={prefs.silence_timeout_ms}
                onChange={(e) => update.mutate({ silence_timeout_ms: Number(e.target.value) })}
                className="w-full accent-[var(--accent)]"
                aria-valuetext={`${(prefs.silence_timeout_ms / 1000).toFixed(1)} seconds`}
              />
              <p className="mt-1 text-xs text-muted">How long a pause before Saathi decides you are done. Increase if you speak slowly.</p>
            </div>
          </>
        )}
      </Section>

      <Section title="Reminders" description="How you hear about upcoming visits.">
        <PhoneNotifications />
        {prefs && <Toggle checked={prefs.symptom_checkins} onChange={(v) => save({ symptom_checkins: v })} label="Check on me the next day" description="After you tell Saathi how you feel, get a message the next day asking how you are now." />}
        {prefs?.sms_available && (
          <Toggle
            checked={prefs.sms_reminders}
            onChange={(v) => save({ sms_reminders: v })}
            label="Also text my reminders"
            description="A text message goes to the mobile number you gave for the visit. Standard SMS rates may apply."
          />
        )}
      </Section>

      <Section title="Chat">
        {prefs && <Toggle checked={prefs.show_tool_details} onChange={(v) => save({ show_tool_details: v })} label="Show action details" description="Let me expand each action Saathi takes to see what was sent and received." />}
        <Link to="/settings/language" className="flex items-center gap-3 py-3.5 transition hover:text-accent-text">
          <Languages className="size-5 text-accent-text" aria-hidden />
          <span className="min-w-0 flex-1">
            <span className="block text-sm font-medium">Languages</span>
            <span className="block text-sm text-muted">Primary: {prefs ? languageLabel(prefs.primary_language, languages) : '…'}</span>
          </span>
          <ChevronRight className="size-4 text-muted" aria-hidden />
        </Link>
      </Section>
    </div>
  )
}

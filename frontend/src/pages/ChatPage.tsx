import { useEffect, useRef } from 'react'
import { Link, useLocation, useNavigate } from 'react-router-dom'
import { Phone, Stethoscope } from 'lucide-react'
import { Composer } from '@/components/chat/Composer'
import { SuggestedPrompts } from '@/components/chat/SuggestedPrompts'
import { ThreadView } from '@/components/chat/ThreadView'
import { Badge } from '@/components/ui/primitives'
import { useChat } from '@/hooks/ChatProvider'
import { useLanguage } from '@/hooks/LanguageProvider'
import { useRouteConversation } from '@/hooks/useRouteConversation'
import { languageLabel } from '@/lib/language'

export default function ChatPage() {
  const { routeId } = useRouteConversation('/chat')
  const chat = useChat()
  const { languages } = useLanguage()
  const location = useLocation()
  const navigate = useNavigate()
  const { state } = chat

  // A prompt handed over from the dashboard ("Check my symptoms"): send it once.
  const handled = useRef<string | null>(null)
  useEffect(() => {
    const prompt = (location.state as { prompt?: string; lang?: string } | null)?.prompt
    const key = location.key
    if (prompt && handled.current !== key && !routeId) {
      handled.current = key
      chat.sendMessage(prompt, { language: (location.state as { lang?: string }).lang })
      navigate(location.pathname, { replace: true, state: null })
    }
  }, [location, routeId, chat, navigate])

  const lang = state.language ?? state.conversation?.language

  return (
    <div className="page-glow flex h-full flex-col">
      <div className="flex items-center gap-3 border-b border-line/70 px-4 py-2.5 md:px-6">
        <div className="min-w-0 flex-1">
          <h1 className="truncate text-[15px] font-semibold">{state.conversation?.title ?? 'New conversation'}</h1>
        </div>
        {lang && <Badge tone="accent">{languageLabel(lang, languages)}</Badge>}
        <Link to="/call" className="inline-flex h-9 items-center gap-1.5 rounded-xl bg-soft px-3 text-sm font-medium text-muted transition hover:text-fg" aria-label="Start a live voice call">
          <Phone className="size-4" aria-hidden /> Live call
        </Link>
      </div>

      <ThreadView>
        <div className="flex flex-col items-center pt-6 text-center md:pt-14">
          <div className="mb-5 grid size-16 place-items-center rounded-3xl bg-brand text-white shadow-[var(--shadow-pop)]">
            <Stethoscope className="size-8" aria-hidden />
          </div>
          <h2 className="text-2xl font-semibold tracking-tight md:text-3xl">How are you feeling today?</h2>
          <p className="mt-2 max-w-md text-muted">Describe your symptoms, find a doctor near you, or manage an appointment, in the language you are most comfortable with.</p>
          <div className="mt-8 w-full max-w-2xl text-left">
            <SuggestedPrompts onPick={(p) => chat.sendMessage(p.text, { language: p.lang })} />
          </div>
          <p className="mt-6 max-w-md text-xs text-muted">Swasthya Saathi gives general guidance, not a diagnosis. In an emergency call 112 or 108.</p>
        </div>
      </ThreadView>

      <Composer autoFocus />
    </div>
  )
}

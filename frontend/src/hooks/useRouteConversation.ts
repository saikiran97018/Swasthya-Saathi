import { useEffect } from 'react'
import { useNavigate, useParams } from 'react-router-dom'
import { useChat } from './ChatProvider'

/**
 * Keeps the URL (`/chat/:id`, `/voice/:id`) and the live conversation in sync:
 *  - opening a URL with an id loads that conversation;
 *  - a brand-new conversation (created by the first message) puts its id into the URL;
 *  - Chat and Voice share one thread, so switching between them keeps the conversation.
 */
export function useRouteConversation(base: '/chat' | '/voice') {
  const { id } = useParams<{ id: string }>()
  const navigate = useNavigate()
  const { state, openConversation } = useChat()
  const current = state.conversationId

  useEffect(() => {
    if (id) {
      if (current !== id) void openConversation(id)
    } else if (current) {
      navigate(`${base}/${current}`, { replace: true })
    }
  }, [id, current, base, navigate, openConversation])

  return { routeId: id }
}

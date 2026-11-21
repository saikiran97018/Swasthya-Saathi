import { useEffect, useRef, useState } from 'react'
import { Link, useLocation } from 'react-router-dom'
import { Check, MessageSquare, Mic, Pencil, Search, Trash2, X } from 'lucide-react'
import { flattenPages, useConversations, useDeleteConversation, useRenameConversation } from '@/api/hooks'
import type { Conversation } from '@/api/types'
import { Button, Dialog, EmptyState, IconButton, PageHeader, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { useChat } from '@/hooks/ChatProvider'
import { dateTime, relativeTime } from '@/lib/format'
import { nativeName } from '@/lib/language'

function useDebounced<T>(value: T, ms: number): T {
  const [v, setV] = useState(value)
  useEffect(() => {
    const t = window.setTimeout(() => setV(value), ms)
    return () => window.clearTimeout(t)
  }, [value, ms])
  return v
}

export default function HistoryPage() {
  const location = useLocation()
  const toast = useToast()
  const chat = useChat()
  const [query, setQuery] = useState('')
  const q = useDebounced(query.trim(), 300)
  const search = useRef<HTMLInputElement>(null)

  const { data, isLoading, isError, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage, isFetching } = useConversations(q)
  const rename = useRenameConversation()
  const remove = useDeleteConversation()
  const items = flattenPages(data)
  const total = data?.pages[0]?.total ?? 0

  const [editing, setEditing] = useState<string | null>(null)
  const [draft, setDraft] = useState('')
  const [deleting, setDeleting] = useState<Conversation | null>(null)

  // Ctrl/Cmd+K lands here with focusSearch set.
  const focusToken = (location.state as { focusSearch?: number } | null)?.focusSearch
  useEffect(() => {
    search.current?.focus()
    search.current?.select()
  }, [focusToken])

  const startRename = (c: Conversation) => {
    setEditing(c.id)
    setDraft(c.title)
  }
  const commitRename = (c: Conversation) => {
    const title = draft.trim()
    setEditing(null)
    if (title && title !== c.title) rename.mutate({ id: c.id, title }, { onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not rename the conversation') })
  }
  const confirmDelete = () => {
    if (!deleting) return
    const c = deleting
    setDeleting(null)
    if (chat.state.conversationId === c.id) chat.startNew()
    remove.mutate(c.id, {
      onSuccess: () => toast.success('Conversation deleted'),
      onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not delete the conversation'),
    })
  }

  return (
    <div className="mx-auto w-full max-w-3xl p-4 md:p-8">
      <PageHeader title="History" description="Everything you have talked about, saved on this device's account." />

      <div className="relative mb-4">
        <Search className="pointer-events-none absolute top-1/2 left-3.5 size-4 -translate-y-1/2 text-muted" aria-hidden />
        <input
          ref={search}
          type="search"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          placeholder="Search conversations (Ctrl+K)"
          aria-label="Search conversations"
          className="h-11 w-full rounded-xl border border-line bg-elev pr-10 pl-10 text-[15px] outline-none placeholder:text-muted focus:border-accent focus:ring-2 focus:ring-accent/25"
        />
        {query && (
          <button aria-label="Clear search" onClick={() => setQuery('')} className="absolute top-1/2 right-2.5 -translate-y-1/2 rounded-md p-1 text-muted hover:text-fg">
            <X className="size-4" />
          </button>
        )}
      </div>

      {isError ? (
        <div role="alert" className="card flex items-center justify-between gap-3 p-4">
          <span className="text-sm text-danger">{error instanceof Error ? error.message : 'Could not load conversations.'}</span>
          <Button size="sm" onClick={() => void refetch()}>Retry</Button>
        </div>
      ) : isLoading ? (
        <div className="space-y-3">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : items.length === 0 ? (
        <div className="card">
          <EmptyState
            icon={<MessageSquare className="size-6" />}
            title={q ? 'No matching conversations' : 'No conversations yet'}
            action={!q && <Link to="/chat"><Button variant="primary"><MessageSquare className="size-4" aria-hidden /> Start a chat</Button></Link>}
          >
            {q ? `Nothing matches “${q}”. Try another word.` : 'Your conversations will be saved here.'}
          </EmptyState>
        </div>
      ) : (
        <>
          <p className="mb-2 px-1 text-sm text-muted" aria-live="polite">{total} conversation{total === 1 ? '' : 's'}{isFetching && !isFetchingNextPage ? ' · updating…' : ''}</p>
          <ul className="space-y-2.5">
            {items.map((c) => (
              <li key={c.id} className="card flex items-center gap-3 p-3.5">
                <span className="grid size-10 shrink-0 place-items-center rounded-xl bg-soft text-muted">{c.voice_message_count > 0 ? <Mic className="size-[18px]" /> : <MessageSquare className="size-[18px]" />}</span>
                <div className="min-w-0 flex-1">
                  {editing === c.id ? (
                    <form onSubmit={(e) => { e.preventDefault(); commitRename(c) }} className="flex items-center gap-1.5">
                      <input
                        autoFocus
                        value={draft}
                        maxLength={200}
                        aria-label="Conversation title"
                        onChange={(e) => setDraft(e.target.value)}
                        onKeyDown={(e) => e.key === 'Escape' && setEditing(null)}
                        className="h-9 min-w-0 flex-1 rounded-lg border border-accent bg-bg px-2.5 text-sm outline-none ring-2 ring-accent/25"
                      />
                      <IconButton label="Save title" size="sm" variant="primary" type="submit"><Check className="size-4" /></IconButton>
                      <IconButton label="Cancel rename" size="sm" type="button" onClick={() => setEditing(null)}><X className="size-4" /></IconButton>
                    </form>
                  ) : (
                    <Link to={`/chat/${c.id}`} className="block rounded-md">
                      <span className="block truncate font-medium">{c.title}</span>
                      <span className="text-xs text-muted" title={dateTime(c.last_message_at)}>
                        {relativeTime(c.last_message_at)} · {nativeName(c.language)} · {c.message_count} message{c.message_count === 1 ? '' : 's'}
                        {c.voice_message_count > 0 && ` · ${c.voice_message_count} spoken`}
                      </span>
                    </Link>
                  )}
                </div>
                {editing !== c.id && (
                  <div className="flex shrink-0 items-center">
                    <IconButton label={`Rename “${c.title}”`} size="sm" className="size-9" onClick={() => startRename(c)}><Pencil className="size-4" /></IconButton>
                    <IconButton label={`Delete “${c.title}”`} size="sm" className="size-9 hover:text-danger" onClick={() => setDeleting(c)}><Trash2 className="size-4" /></IconButton>
                  </div>
                )}
              </li>
            ))}
          </ul>
          {hasNextPage && (
            <div className="mt-5 flex justify-center">
              <Button onClick={() => void fetchNextPage()} loading={isFetchingNextPage}>Load more</Button>
            </div>
          )}
        </>
      )}

      <Dialog
        open={!!deleting}
        onClose={() => setDeleting(null)}
        title="Delete this conversation?"
        footer={
          <>
            <Button data-autofocus onClick={() => setDeleting(null)}>Keep it</Button>
            <Button variant="danger" onClick={confirmDelete}><Trash2 className="size-4" aria-hidden /> Delete</Button>
          </>
        }
      >
        “{deleting?.title}” and its messages will be permanently removed. This cannot be undone.
      </Dialog>
    </div>
  )
}

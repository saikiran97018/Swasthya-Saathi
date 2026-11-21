import { useState } from 'react'
import { Link } from 'react-router-dom'
import { Activity, ClipboardList, Check, ShieldCheck, Wrench } from 'lucide-react'
import { flattenPages, useAgents, useExecutions, useTasks, useUpdateTask } from '@/api/hooks'
import type { Execution, Task } from '@/api/types'
import { ToolCard, toolIcon } from '@/components/chat/ToolCard'
import { Badge, Button, EmptyState, PageHeader, Segmented, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { usePrefs } from '@/api/hooks'
import { dateTime, durationMs, humanize, relativeTime } from '@/lib/format'

type Tab = 'runs' | 'tasks' | 'tools'

const RUN_TONE: Record<string, 'ok' | 'danger' | 'warn' | 'neutral'> = { completed: 'ok', failed: 'danger', awaiting_confirmation: 'warn' }

export default function ActivityPage() {
  const [tab, setTab] = useState<Tab>('runs')
  return (
    <div className="mx-auto w-full max-w-4xl p-4 md:p-8">
      <PageHeader
        title="Agent activity"
        description="What Swasthya Saathi did on your behalf: each step, the tools it used, and what is waiting for you."
        actions={
          <Segmented<Tab>
            label="Activity sections"
            value={tab}
            onChange={setTab}
            options={[
              { value: 'runs', label: 'Runs' },
              { value: 'tasks', label: 'Tasks & requests' },
              { value: 'tools', label: 'Tools' },
            ]}
          />
        }
      />
      {tab === 'runs' && <Runs />}
      {tab === 'tasks' && <Tasks />}
      {tab === 'tools' && <Tools />}
    </div>
  )
}

function Runs() {
  const { data: prefs } = usePrefs()
  const { data, isLoading, isError, error, refetch, hasNextPage, fetchNextPage, isFetchingNextPage } = useExecutions()
  const runs = flattenPages(data)

  if (isLoading) return <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-32" />)}</div>
  if (isError) return <ErrorRow message={error instanceof Error ? error.message : 'Could not load activity.'} onRetry={() => void refetch()} />
  if (runs.length === 0)
    return (
      <div className="card">
        <EmptyState icon={<Activity className="size-6" />} title="No activity yet">When Saathi looks something up, books or reminds on your behalf, each step will be listed here.</EmptyState>
      </div>
    )

  return (
    <>
      <ol className="relative space-y-4 border-l border-line pl-5 md:pl-6">
        {runs.map((r: Execution) => (
          <li key={r.id} className="relative">
            <span aria-hidden className="absolute top-5 -left-[1.72rem] size-3 rounded-full border-2 border-bg bg-accent md:-left-[1.97rem]" />
            <article className="card p-4">
              <header className="flex flex-wrap items-center gap-2">
                <Badge tone={RUN_TONE[r.status] ?? 'neutral'}>{humanize(r.status)}</Badge>
                <h3 className="text-[15px] font-semibold">{r.intent ? humanize(r.intent) : 'Conversation'}</h3>
                <span className="ml-auto text-xs text-muted" title={dateTime(r.started_at)}>{relativeTime(r.started_at)}</span>
              </header>
              <p className="mt-1 text-xs text-muted">
                <Link to={`/chat/${r.conversation_id}`} className="font-medium text-accent-text hover:underline">{r.conversation_title ?? 'Conversation'}</Link>
                {' · '}{r.steps} step{r.steps === 1 ? '' : 's'}
                {r.latency_ms !== null && ` · ${durationMs(r.latency_ms)}`}
                {r.model && ` · ${r.model}`}
              </p>
              {r.error && <p className="mt-2 rounded-lg bg-danger-soft px-3 py-2 text-sm text-danger">{r.error}</p>}
              {r.tool_executions.length > 0 && (
                <div className="mt-3 space-y-1.5">
                  {r.tool_executions.map((t) => <ToolCard key={t.id} tool={t} showDetails={prefs?.show_tool_details ?? true} compact rich={false} />)}
                </div>
              )}
            </article>
          </li>
        ))}
      </ol>
      {hasNextPage && <div className="mt-6 flex justify-center"><Button onClick={() => void fetchNextPage()} loading={isFetchingNextPage}>Load more</Button></div>}
    </>
  )
}

const TASK_FILTERS = [
  { value: '', label: 'All' },
  { value: 'open', label: 'Open' },
  { value: 'submitted', label: 'Submitted' },
  { value: 'done', label: 'Done' },
] as const

function Tasks() {
  const toast = useToast()
  const [filter, setFilter] = useState<string>('')
  const { data, isLoading, isError, error, refetch } = useTasks(filter)
  const update = useUpdateTask()
  const items = data?.items ?? []

  return (
    <div>
      <div className="mb-4"><Segmented label="Filter tasks" value={filter} onChange={setFilter} options={TASK_FILTERS.map((f) => ({ value: f.value, label: f.label }))} /></div>
      {isLoading ? (
        <div className="space-y-3">{[0, 1, 2].map((i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : isError ? (
        <ErrorRow message={error instanceof Error ? error.message : 'Could not load tasks.'} onRetry={() => void refetch()} />
      ) : items.length === 0 ? (
        <div className="card"><EmptyState icon={<ClipboardList className="size-6" />} title="Nothing here yet">Tasks, reminders and requests created by Saathi appear here with a reference code.</EmptyState></div>
      ) : (
        <ul className="space-y-2.5">
          {items.map((t: Task) => (
            <li key={t.id} className="card flex flex-wrap items-center gap-3 p-4">
              <code className="rounded-md bg-soft px-2 py-1 font-mono text-xs font-semibold">{t.ref}</code>
              <div className="min-w-0 flex-1">
                <div className="truncate font-medium">{t.title}</div>
                <div className="text-xs text-muted">
                  {t.kind === 'service_request' ? 'Request' : 'Task'}
                  {t.due_at && ` · due ${new Date(t.due_at).toLocaleDateString('en-IN', { day: 'numeric', month: 'short' })}`} · {relativeTime(t.created_at)}
                </div>
              </div>
              <Badge tone={t.status === 'done' ? 'ok' : t.status === 'cancelled' ? 'neutral' : t.status === 'submitted' ? 'accent' : 'saffron'}>{humanize(t.status)}</Badge>
              {t.kind === 'task' && (t.status === 'open' || t.status === 'in_progress') && (
                <Button size="sm" loading={update.isPending && update.variables?.id === t.id} onClick={() => update.mutate({ id: t.id, status: 'done' }, { onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not update the task') })}>
                  <Check className="size-4" aria-hidden /> Mark done
                </Button>
              )}
            </li>
          ))}
        </ul>
      )}
    </div>
  )
}

function Tools() {
  const { data, isLoading, isError, error, refetch } = useAgents()
  const agent = data?.[0]
  if (isLoading) return <div className="grid gap-3 sm:grid-cols-2">{[0, 1, 2, 3].map((i) => <Skeleton key={i} className="h-28" />)}</div>
  if (isError || !agent) return <ErrorRow message={error instanceof Error ? error.message : 'Could not load the tool list.'} onRetry={() => void refetch()} />
  return (
    <div>
      <p className="mb-4 text-sm text-muted">{agent.description} <span className="whitespace-nowrap">Model: <strong className="font-medium text-fg">{agent.model}</strong></span></p>
      <ul className="grid gap-3 sm:grid-cols-2">
        {agent.tools.map((t) => {
          const Icon = toolIcon(t.name)
          return (
            <li key={t.name} className={`card p-4 ${t.enabled ? '' : 'opacity-70'}`}>
              <div className="mb-1.5 flex items-center gap-2.5">
                <span className="grid size-8 shrink-0 place-items-center rounded-lg bg-accent-soft text-accent-text"><Icon className="size-4" aria-hidden /></span>
                <h3 className="min-w-0 flex-1 truncate font-medium">{humanize(t.name)}</h3>
              </div>
              <p className="text-sm text-muted">{t.description}</p>
              <div className="mt-3 flex flex-wrap gap-1.5">
                <Badge>{humanize(t.category)}</Badge>
                {t.requires_confirmation && <Badge tone="saffron"><ShieldCheck className="size-3" aria-hidden /> Asks you first</Badge>}
                {!t.enabled && <Badge tone="warn"><Wrench className="size-3" aria-hidden /> Not set up</Badge>}
              </div>
            </li>
          )
        })}
      </ul>
    </div>
  )
}

function ErrorRow({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div role="alert" className="card flex items-center justify-between gap-3 p-4">
      <span className="text-sm text-danger">{message}</span>
      <Button size="sm" onClick={onRetry}>Retry</Button>
    </div>
  )
}

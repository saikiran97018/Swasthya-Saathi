import { useState } from 'react'
import { Link } from 'react-router-dom'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { Check, Sparkles } from 'lucide-react'
import { api } from '@/api/endpoints'
import type { BillingPlan, BillingStatus } from '@/api/types'
import { Badge, Button, Dialog, PageHeader, ProgressBar, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { renewalLine, usageFraction, usageLine } from '@/lib/billing'
import { openSubscriptionCheckout } from '@/lib/razorpay'

const KEY = { plans: ['billing', 'plans'], status: ['billing', 'status'] } as const

export default function PlansPage() {
  const toast = useToast()
  const qc = useQueryClient()
  const plans = useQuery({ queryKey: KEY.plans, queryFn: api.billingPlans, staleTime: 5 * 60_000 })
  const status = useQuery({ queryKey: KEY.status, queryFn: api.billingStatus, staleTime: 10_000 })
  const [busy, setBusy] = useState<string | null>(null)
  const [confirmCancel, setConfirmCancel] = useState(false)

  const setStatus = (s: BillingStatus) => qc.setQueryData(KEY.status, s)

  const subscribe = async (plan: BillingPlan, keyId: string) => {
    setBusy(plan.id)
    try {
      const created = await api.billingSubscribe(plan.id)
      await openSubscriptionCheckout({
        keyId: created.key_id || keyId,
        subscriptionId: created.subscription_id,
        description: plan.name,
        onDismiss: () => setBusy(null),
        onSuccess: (r) => {
          api.billingVerify(r)
            .then((s) => {
              setStatus(s)
              toast.success(s.plan === 'plus' ? 'Welcome to Saathi Plus!' : 'Payment received. Your plan will update in a moment.')
            })
            .catch((e) => toast.error(e instanceof Error ? e.message : 'We could not confirm the payment. If money was taken it will be matched shortly.'))
            .finally(() => {
              setBusy(null)
              void qc.invalidateQueries({ queryKey: KEY.status })
            })
        },
      })
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not start the payment')
      setBusy(null)
    }
  }

  const cancel = async () => {
    setBusy('cancel')
    try {
      setStatus(await api.billingCancel())
      toast.success('Done. Saathi Plus will not renew.')
      setConfirmCancel(false)
    } catch (e) {
      toast.error(e instanceof Error ? e.message : 'Could not cancel')
    } finally {
      setBusy(null)
    }
  }

  const s = status.data
  const p = plans.data
  const renew = s ? renewalLine(s) : null

  return (
    <div className="mx-auto w-full max-w-2xl p-4 md:p-8">
      <PageHeader title="Saathi Plus" description="Talk to Saathi as much as you need." />

      {status.isLoading || plans.isLoading ? (
        <Skeleton className="h-48" />
      ) : status.isError || plans.isError || !s || !p ? (
        <div role="alert" className="card flex items-center justify-between gap-3 p-5">
          <span className="text-sm text-danger">Could not load your plan.</span>
          <Button size="sm" onClick={() => { void status.refetch(); void plans.refetch() }}>Retry</Button>
        </div>
      ) : (
        <>
          <section className="card mb-5 p-5" aria-label="Your plan">
            <div className="flex items-center justify-between gap-3">
              <h2 className="font-semibold">Your plan</h2>
              <Badge>{s.plan === 'plus' ? 'Saathi Plus' : 'Free'}</Badge>
            </div>
            {renew && <p className="mt-1 text-sm text-muted">{renew}</p>}
            <div className="mt-4 space-y-4">
              <div>
                <div className="mb-1.5 text-sm">{usageLine(s.messages_today, s.messages_limit, 'messages')}</div>
                {s.messages_limit !== null && <ProgressBar value={usageFraction(s.messages_today, s.messages_limit) * 100} label="Messages used today" />}
              </div>
              <div>
                <div className="mb-1.5 text-sm">{usageLine(s.calls_today, s.calls_limit, 'live calls')}</div>
                {s.calls_limit !== null && <ProgressBar value={usageFraction(s.calls_today, s.calls_limit) * 100} label="Live calls used today" />}
              </div>
            </div>
            <p className="mt-4 text-xs text-muted">SOS, emergency numbers and your reminders are always free, on every plan.</p>
            {s.plan === 'plus' && !s.cancel_at_cycle_end && (
              <div className="mt-4"><Button size="sm" onClick={() => setConfirmCancel(true)}>Cancel subscription</Button></div>
            )}
          </section>

          {s.plan === 'free' && (
            !p.enabled ? (
              <section className="card p-5" aria-label="Plans"><p className="text-sm text-muted">Paid plans are not available yet.</p></section>
            ) : (
              <section aria-label="Plans" className="space-y-4">
                <ul className="card space-y-2 p-5">
                  {p.features.map((f) => (
                    <li key={f} className="flex items-start gap-2 text-sm"><Check className="mt-0.5 size-4 shrink-0 text-accent-text" aria-hidden />{f}</li>
                  ))}
                </ul>
                <div className="grid gap-3 sm:grid-cols-2">
                  {p.plans.map((plan) => (
                    <div key={plan.id} className="card flex flex-col p-5">
                      <div className="flex items-center gap-2 text-sm font-medium"><Sparkles className="size-4 text-accent-text" aria-hidden />{plan.name}</div>
                      <div className="mt-2 text-3xl font-semibold">₹{plan.price_inr}<span className="text-base font-normal text-muted"> / {plan.period}</span></div>
                      {plan.note && <div className="mt-1 text-sm text-accent-text">{plan.note}</div>}
                      <Button className="mt-4" variant="primary" loading={busy === plan.id} disabled={busy !== null} onClick={() => void subscribe(plan, p.key_id ?? '')}>Subscribe</Button>
                    </div>
                  ))}
                </div>
                <p className="text-xs text-muted">You pay on Razorpay's secure page with UPI, card or net banking. You can cancel any time; Plus then stays until the period you paid for ends.</p>
              </section>
            )
          )}
        </>
      )}

      <nav aria-label="Legal pages" className="mt-6 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        <Link to="/legal/terms" className="hover:text-fg">Terms</Link>
        <Link to="/legal/privacy" className="hover:text-fg">Privacy</Link>
        <Link to="/legal/refunds" className="hover:text-fg">Cancellation and refunds</Link>
        <Link to="/legal/contact" className="hover:text-fg">Contact</Link>
      </nav>

      <Dialog
        open={confirmCancel}
        onClose={() => setConfirmCancel(false)}
        title="Cancel Saathi Plus?"
        footer={
          <>
            <Button onClick={() => setConfirmCancel(false)}>Keep Plus</Button>
            <Button variant="danger" loading={busy === 'cancel'} onClick={() => void cancel()}>Cancel subscription</Button>
          </>
        }
      >
        <p className="text-sm text-muted">It will not renew. You keep Plus until the end of the period you already paid for.</p>
      </Dialog>
    </div>
  )
}

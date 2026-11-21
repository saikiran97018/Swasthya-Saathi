import { useId, useState, type FormEvent } from 'react'
import { Link } from 'react-router-dom'
import { ArrowLeft, Pencil, Plus, Trash2, Users } from 'lucide-react'
import { useCreateFamilyMember, useDeleteFamilyMember, useFamily, useUpdateFamilyMember } from '@/api/hooks'
import { FAMILY_RELATIONS, type FamilyGender, type FamilyMember, type FamilyRelation } from '@/api/types'
import { DoctorAvatar } from '@/components/health/Avatars'
import { Button, Dialog, EmptyState, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { useLanguage } from '@/hooks/LanguageProvider'
import { EMPTY_FAMILY_FORM, GENDER_LABEL, MAX_FAMILY_MEMBERS, RELATION_LABEL, familyCreateBody, familyPatchBody, formFromMember, memberSubtitle, validateFamilyForm, type FamilyField, type FamilyForm } from '@/lib/family'
import { nativeName } from '@/lib/language'
import { cn } from '@/lib/format'

const field = 'h-12 w-full rounded-2xl border border-line bg-bg/60 px-4 text-[15px] outline-none transition focus:border-accent focus:ring-2 focus:ring-accent/25'

export default function FamilyPage() {
  const toast = useToast()
  const { data, isLoading, isError, error, refetch } = useFamily()
  const del = useDeleteFamilyMember()
  const [editing, setEditing] = useState<FamilyMember | 'new' | null>(null)
  const [removing, setRemoving] = useState<FamilyMember | null>(null)
  const members = data ?? []
  const full = members.length >= MAX_FAMILY_MEMBERS

  const remove = () => {
    if (!removing) return
    del.mutate(removing.id, {
      onSuccess: () => {
        toast.success(`${removing.name} removed`)
        setRemoving(null)
      },
      onError: (e) => toast.error(e instanceof Error ? e.message : 'Could not remove this person'),
    })
  }

  return (
    <div className="mx-auto w-full max-w-2xl px-4 py-5 md:px-8 md:py-8">
      <Link to="/settings" className="mb-3 inline-flex min-h-10 items-center gap-1.5 text-sm font-semibold text-accent-text hover:underline">
        <ArrowLeft className="size-4" aria-hidden /> Settings
      </Link>
      <header className="mb-5 flex flex-wrap items-end justify-between gap-3">
        <div className="min-w-0">
          <h1 className="text-[1.65rem] leading-tight font-bold tracking-tight md:text-3xl">Family</h1>
          <p className="mt-1.5 text-muted">Save the people you book visits for. When you book, pick who the visit is for and their details are filled in.</p>
        </div>
        {!editing && (
          <Button variant="primary" disabled={full} onClick={() => setEditing('new')}>
            <Plus className="size-4" aria-hidden /> Add a family member
          </Button>
        )}
      </header>
      {full && !editing && <p className="mb-4 text-sm text-muted">You can save up to {MAX_FAMILY_MEMBERS} people. Remove one to add another.</p>}

      {editing && <MemberForm key={editing === 'new' ? 'new' : editing.id} member={editing === 'new' ? null : editing} onDone={() => setEditing(null)} />}

      {isLoading ? (
        <div className="space-y-3" aria-busy>{[0, 1].map((i) => <Skeleton key={i} className="h-20" />)}</div>
      ) : isError ? (
        <div role="alert" className="card flex flex-wrap items-center justify-between gap-3 p-4">
          <span className="min-w-0 flex-1 text-sm text-danger">{error instanceof Error ? error.message : 'Could not load your family list.'}</span>
          <Button size="sm" onClick={() => void refetch()}>Retry</Button>
        </div>
      ) : members.length === 0 ? (
        !editing && (
          <div className="card">
            <EmptyState icon={<Users className="size-6" />} title="No family members yet" action={<Button variant="primary" onClick={() => setEditing('new')}><Plus className="size-4" aria-hidden /> Add a family member</Button>}>
              Add a child, parent or anyone you book doctor visits for.
            </EmptyState>
          </div>
        )
      ) : (
        <ul className="space-y-3" aria-label="Family members">
          {members.map((m) => (
            <li key={m.id} className={cn('card flex items-center gap-3 p-3.5', editing && editing !== 'new' && editing.id === m.id && 'border-accent')}>
              <DoctorAvatar seed={`family-${m.id}`} name={m.name} size={52} />
              <div className="min-w-0 flex-1">
                <p className="font-bold break-words">{m.name}</p>
                <p className="text-sm text-muted">{memberSubtitle(m)}</p>
                <p className="text-sm text-muted">{[m.language ? nativeName(m.language) : null, m.mobile, m.gender ? GENDER_LABEL[m.gender] : null].filter(Boolean).join(' · ') || 'No other details saved'}</p>
              </div>
              <div className="flex shrink-0 items-center gap-0.5">
                <button type="button" onClick={() => setEditing(m)} aria-label={`Edit ${m.name}`} className="grid size-11 place-items-center rounded-2xl text-muted transition hover:bg-soft hover:text-fg">
                  <Pencil className="size-[18px]" aria-hidden />
                </button>
                <button type="button" onClick={() => setRemoving(m)} aria-label={`Remove ${m.name}`} className="grid size-11 place-items-center rounded-2xl text-muted transition hover:bg-danger-soft hover:text-danger">
                  <Trash2 className="size-[18px]" aria-hidden />
                </button>
              </div>
            </li>
          ))}
        </ul>
      )}

      <Dialog
        open={!!removing}
        onClose={() => !del.isPending && setRemoving(null)}
        title="Remove this person?"
        footer={
          <>
            <Button data-autofocus disabled={del.isPending} onClick={() => setRemoving(null)}>Keep</Button>
            <Button variant="danger" loading={del.isPending} onClick={remove}>Remove</Button>
          </>
        }
      >
        <p><strong className="text-fg">{removing?.name}</strong> will be removed from your family list. Their past appointments stay in your Care Plan.</p>
      </Dialog>
    </div>
  )
}

function MemberForm({ member, onDone }: { member: FamilyMember | null; onDone: () => void }) {
  const toast = useToast()
  const { languages } = useLanguage()
  const create = useCreateFamilyMember()
  const update = useUpdateFamilyMember()
  const ids = { name: useId(), relation: useId(), year: useId(), gender: useId(), mobile: useId(), lang: useId() }
  const [form, setForm] = useState<FamilyForm>(member ? formFromMember(member) : EMPTY_FAMILY_FORM)
  const [errors, setErrors] = useState<Partial<Record<FamilyField, string>>>({})
  const [formError, setFormError] = useState<string | null>(null)
  const busy = create.isPending || update.isPending
  const set = <K extends keyof FamilyForm>(k: K, v: FamilyForm[K]) => {
    setForm((f) => ({ ...f, [k]: v }))
    setErrors((e) => ({ ...e, [k]: undefined }))
  }

  const submit = (e: FormEvent) => {
    e.preventDefault()
    const found = validateFamilyForm(form)
    setErrors(found)
    setFormError(null)
    if (Object.keys(found).length) return
    const onError = (err: unknown) => setFormError(err instanceof Error ? err.message : 'Could not save. Please try again.')
    if (member) {
      update.mutate({ id: member.id, patch: familyPatchBody(form) }, { onSuccess: () => { toast.success('Saved'); onDone() }, onError })
    } else {
      create.mutate(familyCreateBody(form), { onSuccess: () => { toast.success(`${form.name.trim()} added`); onDone() }, onError })
    }
  }

  return (
    <form onSubmit={submit} noValidate aria-label={member ? `Edit ${member.name}` : 'Add a family member'} className="card mb-5 space-y-4 p-4 md:p-5">
      <h2 className="text-lg font-bold">{member ? `Edit ${member.name}` : 'Add a family member'}</h2>
      <div className="grid gap-4 sm:grid-cols-2">
        <div className="sm:col-span-2">
          <label htmlFor={ids.name} className="label-caps mb-1.5 block">Full name</label>
          <input id={ids.name} value={form.name} maxLength={80} autoComplete="off" onChange={(e) => set('name', e.target.value)} aria-invalid={!!errors.name} aria-describedby={errors.name ? `${ids.name}-e` : undefined} className={field} />
          {errors.name && <p id={`${ids.name}-e`} role="alert" className="mt-1 text-sm font-medium text-danger">{errors.name}</p>}
        </div>
        <div>
          <label htmlFor={ids.relation} className="label-caps mb-1.5 block">Relation to you</label>
          <select id={ids.relation} value={form.relation} onChange={(e) => set('relation', e.target.value as FamilyRelation)} className={field}>
            {FAMILY_RELATIONS.map((r) => <option key={r} value={r}>{RELATION_LABEL[r]}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={ids.year} className="label-caps mb-1.5 block">Birth year <span className="font-normal normal-case">(optional)</span></label>
          <input id={ids.year} value={form.birthYear} inputMode="numeric" maxLength={4} placeholder="For example 2016" onChange={(e) => set('birthYear', e.target.value.replace(/\D/g, ''))} aria-invalid={!!errors.birthYear} aria-describedby={errors.birthYear ? `${ids.year}-e` : undefined} className={field} />
          {errors.birthYear && <p id={`${ids.year}-e`} role="alert" className="mt-1 text-sm font-medium text-danger">{errors.birthYear}</p>}
        </div>
        <div>
          <label htmlFor={ids.gender} className="label-caps mb-1.5 block">Gender <span className="font-normal normal-case">(optional)</span></label>
          <select id={ids.gender} value={form.gender} onChange={(e) => set('gender', e.target.value as FamilyGender | '')} className={field}>
            <option value="">Prefer not to say</option>
            {(Object.keys(GENDER_LABEL) as FamilyGender[]).map((g) => <option key={g} value={g}>{GENDER_LABEL[g]}</option>)}
          </select>
        </div>
        <div>
          <label htmlFor={ids.lang} className="label-caps mb-1.5 block">Language</label>
          <select id={ids.lang} value={form.language} onChange={(e) => set('language', e.target.value)} className={field}>
            <option value="">Same as mine</option>
            {languages.map((l) => <option key={l.code} value={l.code}>{l.native_name === l.name ? l.name : `${l.native_name} · ${l.name}`}</option>)}
          </select>
        </div>
        <div className="sm:col-span-2">
          <label htmlFor={ids.mobile} className="label-caps mb-1.5 block">Mobile number <span className="font-normal normal-case">(optional)</span></label>
          <input id={ids.mobile} value={form.mobile} inputMode="tel" maxLength={16} placeholder="10-digit number" onChange={(e) => set('mobile', e.target.value)} aria-invalid={!!errors.mobile} aria-describedby={errors.mobile ? `${ids.mobile}-e` : undefined} className={field} />
          {errors.mobile && <p id={`${ids.mobile}-e`} role="alert" className="mt-1 text-sm font-medium text-danger">{errors.mobile}</p>}
        </div>
      </div>
      {formError && <p role="alert" className="rounded-xl border border-danger/30 bg-danger-soft px-3 py-2.5 text-sm text-danger">{formError}</p>}
      <div className="flex flex-wrap gap-2">
        <Button type="submit" variant="primary" loading={busy}>{member ? 'Save changes' : 'Add person'}</Button>
        <Button type="button" disabled={busy} onClick={onDone}>Cancel</Button>
      </div>
    </form>
  )
}

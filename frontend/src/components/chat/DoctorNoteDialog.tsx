import { useEffect, useState } from 'react'
import { Check, Copy, MessageCircle } from 'lucide-react'
import { api } from '@/api/endpoints'
import type { DoctorNote } from '@/api/types'
import { Button, Dialog, Skeleton } from '@/components/ui/primitives'
import { useToast } from '@/components/ui/Toast'
import { shareText } from '@/lib/share'

/** A short note for the doctor, built from what the patient said in this chat, ready to send or show at the clinic. */
export function DoctorNoteDialog({ conversationId, open, onClose }: { conversationId: string | null; open: boolean; onClose: () => void }) {
  const toast = useToast()
  const [note, setNote] = useState<DoctorNote | null>(null)
  const [failed, setFailed] = useState(false)
  const [copied, setCopied] = useState(false)

  useEffect(() => {
    if (!open || !conversationId) return
    let cancelled = false
    setNote(null)
    setFailed(false)
    api.doctorNote(conversationId).then((n) => !cancelled && setNote(n)).catch(() => !cancelled && setFailed(true))
    return () => {
      cancelled = true
    }
  }, [open, conversationId])

  const copy = async () => {
    if (!note) return
    try {
      await navigator.clipboard.writeText(note.text)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      toast.error('Could not copy. Select the text and copy it by hand.')
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="Note for your doctor"
      footer={
        <>
          <Button onClick={() => void copy()} disabled={!note}>{copied ? <Check className="size-4" aria-hidden /> : <Copy className="size-4" aria-hidden />} {copied ? 'Copied' : 'Copy'}</Button>
          <Button variant="primary" disabled={!note} onClick={() => note && void shareText(note.text, 'Note for the doctor')}><MessageCircle className="size-4" aria-hidden /> Share</Button>
        </>
      }
    >
      {failed ? (
        <p role="alert" className="text-sm text-danger">Could not prepare the note. Please try again.</p>
      ) : !note ? (
        <Skeleton className="h-40" />
      ) : (
        <>
          <pre className="max-h-72 overflow-y-auto rounded-2xl bg-soft p-4 text-sm leading-relaxed break-words whitespace-pre-wrap font-sans">{note.text}</pre>
          <p className="mt-3 text-xs text-muted">Made only from what you told Saathi. Read it before you share it, and correct anything that is wrong.</p>
        </>
      )}
    </Dialog>
  )
}

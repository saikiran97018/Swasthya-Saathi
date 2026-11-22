import { Link, Navigate, useParams } from 'react-router-dom'
import { ArrowLeft } from 'lucide-react'
import { PageHeader } from '@/components/ui/primitives'

/** Razorpay (and the app stores) need public Terms, Privacy, Refund and Contact pages. DRAFTS: have a lawyer review them before launch. */
const CONTACT = (import.meta.env.VITE_CONTACT_EMAIL as string | undefined) || 'support@your-domain.example'
const BUSINESS = (import.meta.env.VITE_BUSINESS_NAME as string | undefined) || 'Swasthya Saathi'

type Doc = { title: string; paragraphs: string[] }

export const LEGAL: Record<string, Doc> = {
  terms: {
    title: 'Terms of use',
    paragraphs: [
      `${BUSINESS} is a health-information and appointment-planning assistant. It gives general information, not medical advice, diagnosis or treatment. It is not a substitute for a doctor.`,
      'In an emergency call 112 (ambulance 108) at once. Do not wait for the assistant.',
      'Appointments with clinics found on the map are planned visits until the clinic confirms them. Fees, timings and availability come from public sources and may be wrong; please confirm with the clinic.',
      'Saathi Plus is an optional paid subscription that removes the free plan\'s daily limits. Payments are processed by Razorpay. You can cancel any time from the Saathi Plus page; access continues until the end of the period you have paid for.',
      'You agree not to misuse the service, attempt to break it, or use it to harm others. We may suspend accounts that do.',
      'The service is provided as it is. To the extent the law allows, we are not liable for decisions taken only on the basis of the assistant\'s replies.',
    ],
  },
  privacy: {
    title: 'Privacy policy',
    paragraphs: [
      'What we keep: your conversations, appointments, reminders, family profiles and emergency contacts you add, and your settings. Voice recordings are used to turn speech into text and are not kept after processing.',
      'Who sees it: speech-to-text, text-to-speech and language-model providers receive the text or audio needed to answer you. Map providers receive the city or coordinates you search for. Razorpay receives your payment details directly; we never see your card, UPI or bank details.',
      'Notifications: if you allow them, your browser gives us an address to send reminders to. You can turn them off in Settings at any time.',
      'We do not sell your data. We do not ask for Aadhaar, bank or card numbers in the chat.',
      `To see, correct or delete your data, write to ${CONTACT}.`,
    ],
  },
  refunds: {
    title: 'Cancellation and refunds',
    paragraphs: [
      'You can cancel Saathi Plus at any time on the Saathi Plus page. The subscription then stops renewing and stays active until the end of the period you have already paid for.',
      'Payments for a period that has started are not refundable, except where the law requires it or a charge was made in error.',
      `If you were charged twice or by mistake, write to ${CONTACT} with your payment reference. Approved refunds go back to the original payment method, usually within 5 to 7 working days.`,
    ],
  },
  contact: {
    title: 'Contact us',
    paragraphs: [`Questions, payment problems or data requests: ${CONTACT}.`, 'For a medical emergency call 112 (ambulance 108); we cannot respond to emergencies by email.'],
  },
}

export default function LegalPage() {
  const { doc = '' } = useParams()
  const page = LEGAL[doc]
  if (!page) return <Navigate to="/legal/terms" replace />
  return (
    <div className="mx-auto w-full max-w-2xl p-4 md:p-8">
      <Link to="/plans" className="mb-3 inline-flex items-center gap-1.5 text-sm text-muted hover:text-fg"><ArrowLeft className="size-4" aria-hidden /> Back</Link>
      <PageHeader title={page.title} />
      <div className="card space-y-3 p-5 text-[15px] leading-relaxed">
        {page.paragraphs.map((p) => <p key={p}>{p}</p>)}
      </div>
      <nav aria-label="Legal pages" className="mt-4 flex flex-wrap gap-x-4 gap-y-1 text-sm text-muted">
        {Object.entries(LEGAL).map(([key, d]) => <Link key={key} to={`/legal/${key}`} className="hover:text-fg">{d.title}</Link>)}
      </nav>
    </div>
  )
}

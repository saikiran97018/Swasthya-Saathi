/** Razorpay Checkout (card, UPI, netbanking) opens in a pop-up served by Razorpay. Payment details never touch our server. */

export interface CheckoutSuccess {
  razorpay_payment_id: string
  razorpay_subscription_id: string
  razorpay_signature: string
}

interface CheckoutOptions {
  key: string
  subscription_id: string
  name: string
  description: string
  theme?: { color: string }
  handler: (r: CheckoutSuccess) => void
  modal?: { ondismiss?: () => void }
}

declare global {
  interface Window {
    Razorpay?: new (options: CheckoutOptions) => { open: () => void; on: (event: string, cb: (r: unknown) => void) => void }
  }
}

const SRC = 'https://checkout.razorpay.com/v1/checkout.js'
let loading: Promise<void> | null = null

/** Load Razorpay's script once. */
export function loadCheckout(): Promise<void> {
  if (typeof window === 'undefined') return Promise.reject(new Error('No window'))
  if (window.Razorpay) return Promise.resolve()
  loading ??= new Promise<void>((resolve, reject) => {
    const s = document.createElement('script')
    s.src = SRC
    s.async = true
    s.onload = () => resolve()
    s.onerror = () => {
      loading = null
      s.remove()
      reject(new Error('Could not load the payment window. Check your internet connection and try again.'))
    }
    document.head.appendChild(s)
  })
  return loading
}

export async function openSubscriptionCheckout(opts: { keyId: string; subscriptionId: string; description: string; onSuccess: (r: CheckoutSuccess) => void; onDismiss: () => void }): Promise<void> {
  await loadCheckout()
  if (!window.Razorpay) throw new Error('The payment window is not available.')
  const checkout = new window.Razorpay({
    key: opts.keyId,
    subscription_id: opts.subscriptionId,
    name: 'Swasthya Saathi',
    description: opts.description,
    theme: { color: '#0f766e' },
    handler: opts.onSuccess,
    modal: { ondismiss: opts.onDismiss },
  })
  checkout.on('payment.failed', () => opts.onDismiss())
  checkout.open()
}

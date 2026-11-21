import { StrictMode } from 'react'
import { createRoot } from 'react-dom/client'
import { BrowserRouter } from 'react-router-dom'
import { QueryClient, QueryClientProvider } from '@tanstack/react-query'
import { ApiError } from '@/api/client'
import App from './App'
import { AuthGate } from './AuthGate'
import { ToastProvider } from '@/components/ui/Toast'
import { ErrorBoundary } from '@/components/ui/ErrorBoundary'
import { ChatProvider } from '@/hooks/ChatProvider'
import { LanguageProvider } from '@/hooks/LanguageProvider'
import './index.css'

const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      refetchOnWindowFocus: false,
      // Don't retry client errors (4xx); retry network/server hiccups once or twice.
      retry: (count, error) => !(error instanceof ApiError && error.status >= 400 && error.status < 500) && count < 2,
    },
  },
})

createRoot(document.getElementById('root') as HTMLElement).render(
  <StrictMode>
    <ErrorBoundary>
      <QueryClientProvider client={queryClient}>
        <AuthGate>
          <ToastProvider>
            <LanguageProvider>
              <ChatProvider>
                <BrowserRouter>
                  <App />
                </BrowserRouter>
              </ChatProvider>
            </LanguageProvider>
          </ToastProvider>
        </AuthGate>
      </QueryClientProvider>
    </ErrorBoundary>
  </StrictMode>,
)

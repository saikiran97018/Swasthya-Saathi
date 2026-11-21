import { Component, type ErrorInfo, type ReactNode } from 'react'
import { TriangleAlert } from 'lucide-react'
import { Button } from './primitives'

interface Props {
  children: ReactNode
  /** Changing this value (e.g. the route) clears a previous error. */
  resetKey?: string
}
interface State {
  error: Error | null
}

export class ErrorBoundary extends Component<Props, State> {
  state: State = { error: null }

  static getDerivedStateFromError(error: Error): State {
    return { error }
  }

  componentDidCatch(error: Error, info: ErrorInfo) {
    console.error('UI error:', error, info.componentStack)
  }

  componentDidUpdate(prev: Props) {
    if (this.state.error && prev.resetKey !== this.props.resetKey) this.setState({ error: null })
  }

  render() {
    if (!this.state.error) return this.props.children
    return (
      <div role="alert" className="mx-auto flex max-w-md flex-col items-center px-6 py-20 text-center">
        <div className="mb-4 grid size-14 place-items-center rounded-2xl bg-danger-soft text-danger">
          <TriangleAlert className="size-7" />
        </div>
        <h2 className="text-lg font-semibold">Something went wrong on this screen</h2>
        <p className="mt-1.5 text-sm text-muted">{this.state.error.message || 'An unexpected error occurred.'}</p>
        <div className="mt-5 flex gap-2">
          <Button variant="primary" onClick={() => this.setState({ error: null })}>
            Try again
          </Button>
          <Button onClick={() => window.location.assign('/')}>Go to home</Button>
        </div>
      </div>
    )
  }
}

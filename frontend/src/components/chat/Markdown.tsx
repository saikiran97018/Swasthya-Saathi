import { memo, useState, type ReactNode } from 'react'
import ReactMarkdown, { type Components } from 'react-markdown'
import remarkGfm from 'remark-gfm'
import { Check, Copy } from 'lucide-react'

function CodeBlock({ code, language }: { code: string; language: string }) {
  const [copied, setCopied] = useState(false)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(code)
      setCopied(true)
      window.setTimeout(() => setCopied(false), 1500)
    } catch {
      /* clipboard unavailable */
    }
  }
  return (
    <div className="my-2 overflow-hidden rounded-xl border border-line bg-soft text-sm">
      <div className="flex items-center justify-between border-b border-line px-3 py-1.5 text-xs text-muted">
        <span>{language || 'text'}</span>
        <button onClick={copy} aria-label="Copy code" className="inline-flex items-center gap-1 rounded px-1.5 py-0.5 hover:bg-line/60 hover:text-fg">
          {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
          {copied ? 'Copied' : 'Copy'}
        </button>
      </div>
      <pre className="scroll-thin overflow-x-auto p-3 font-mono text-[13px] leading-relaxed">
        <code>{code}</code>
      </pre>
    </div>
  )
}

const components: Components = {
  a: ({ href, children }) => (
    <a href={href} target="_blank" rel="noopener noreferrer">
      {children}
    </a>
  ),
  pre: ({ children }) => <>{children}</>,
  code: ({ className, children }) => {
    const text = String(children ?? '')
    const match = /language-(\w+)/.exec(className ?? '')
    // react-markdown renders fenced blocks as <pre><code class="language-x">; inline code has no newline/class.
    if (match || text.includes('\n')) return <CodeBlock code={text.replace(/\n$/, '')} language={match?.[1] ?? ''} />
    return <code>{children as ReactNode}</code>
  },
}

/** Markdown for assistant replies. Raw HTML is never rendered (react-markdown's default). */
export const Markdown = memo(function Markdown({ children }: { children: string }) {
  return (
    <div className="prose-chat">
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={components}>
        {children}
      </ReactMarkdown>
    </div>
  )
})

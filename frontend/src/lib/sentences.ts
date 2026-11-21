/**
 * Sentence splitting for streamed text-to-speech.
 *
 * As the model streams tokens we speak each *finished* sentence immediately instead of waiting for
 * the whole reply. `extractSentences` takes the text buffered so far and returns the sentences that
 * are safe to speak plus the unfinished remainder to keep buffering.
 */

// A boundary is . ! ? … or the Devanagari danda/double danda followed by whitespace
// (so "6.5" and "Rs.500" survive), or any line break (paragraph / list item).
const BOUNDARY = /([.!?…।॥]+["')\]”’]*)\s+|\n+/g
const MIN_CHUNK = 28 // join very short sentences ("Okay.", "Dr.") with the next so speech isn't choppy
const MAX_CHUNK = 260 // a run-on with no punctuation is cut at a comma/space so speech can start

export interface Extracted {
  sentences: string[]
  rest: string
}

function hardSplit(text: string): string[] {
  const out: string[] = []
  let remaining = text.trim()
  while (remaining.length > MAX_CHUNK) {
    const window = remaining.slice(0, MAX_CHUNK)
    let cut = Math.max(window.lastIndexOf(', '), window.lastIndexOf('; '), window.lastIndexOf(': '))
    if (cut < MAX_CHUNK / 3) cut = window.lastIndexOf(' ')
    if (cut <= 0) cut = MAX_CHUNK - 1
    out.push(remaining.slice(0, cut + 1).trim())
    remaining = remaining.slice(cut + 1).trim()
  }
  if (remaining) out.push(remaining)
  return out
}

export function extractSentences(buffer: string, final = false): Extracted {
  const pieces: string[] = []
  let last = 0
  for (const match of buffer.matchAll(BOUNDARY)) {
    const start = match.index ?? 0
    pieces.push(buffer.slice(last, start + (match[1]?.length ?? 0)))
    last = start + match[0].length
  }
  let rest = buffer.slice(last)

  if (final && rest.trim()) {
    pieces.push(rest)
    rest = ''
  }

  // Merge short pieces forward; drop pieces with no letters/digits (stray punctuation, bullets).
  const merged: string[] = []
  let carry = ''
  for (const raw of pieces) {
    const piece = raw.replace(/\s+/g, ' ').trim()
    if (!piece || !/[\p{L}\p{N}]/u.test(piece)) continue
    carry = carry ? `${carry} ${piece}` : piece
    if (carry.length >= MIN_CHUNK) {
      merged.push(carry)
      carry = ''
    }
  }
  if (carry) {
    if (final) merged.push(carry)
    else rest = `${carry} ${rest}`.trimStart() // keep a short tail buffered until more text arrives
  }

  let sentences = merged.flatMap((s) => (s.length > MAX_CHUNK ? hardSplit(s) : [s]))

  // A long unterminated tail: speak all but its last part now.
  if (!final && rest.length > MAX_CHUNK) {
    const parts = hardSplit(rest)
    rest = parts.pop() ?? ''
    sentences = sentences.concat(parts)
  }
  return { sentences, rest }
}

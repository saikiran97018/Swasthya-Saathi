/** In-memory store of synthesized audio per message id, so "Replay" never asks the backend again. */
const cache = new Map<string, Promise<Blob>[]>()
const MAX_MESSAGES = 40

export function rememberAudio(messageId: string, blobs: Promise<Blob>[]): void {
  if (!blobs.length) return
  cache.delete(messageId)
  cache.set(messageId, blobs)
  // A failed synthesis must not poison replay: forget the entry so the next play retries.
  blobs.forEach((b) => b.catch(() => cache.get(messageId) === blobs && cache.delete(messageId)))
  while (cache.size > MAX_MESSAGES) {
    const oldest = cache.keys().next().value
    if (oldest === undefined) break
    cache.delete(oldest)
  }
}

export function recallAudio(messageId: string): Promise<Blob>[] | undefined {
  return cache.get(messageId)
}

export function clearAudioCache(): void {
  cache.clear()
}

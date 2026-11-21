import { describe, expect, it } from 'vitest'
import { extractSentences } from './sentences'

describe('extractSentences', () => {
  it('returns finished sentences and keeps the unfinished tail buffered', () => {
    const r = extractSentences('You should rest and drink plenty of water. Take paracetamol if the fever is high. If it lasts')
    expect(r.sentences).toEqual(['You should rest and drink plenty of water.', 'Take paracetamol if the fever is high.'])
    expect(r.rest).toBe('If it lasts')
  })

  it('does not speak a sentence whose terminator may still be extended (no trailing whitespace yet)', () => {
    const r = extractSentences('Please visit the nearest health centre today.')
    expect(r.sentences).toEqual([])
    expect(r.rest).toBe('Please visit the nearest health centre today.')
  })

  it('flushes everything when final', () => {
    const r = extractSentences('Please visit the nearest health centre today.', true)
    expect(r.sentences).toEqual(['Please visit the nearest health centre today.'])
    expect(r.rest).toBe('')
  })

  it('does not split on decimals or abbreviations without a space', () => {
    const r = extractSentences('The fever is above 39.5 degrees so call the doctor right now. Next sentence here', false)
    expect(r.sentences).toEqual(['The fever is above 39.5 degrees so call the doctor right now.'])
  })

  it('splits on the Devanagari danda', () => {
    const r = extractSentences('आपको आराम करना चाहिए और पानी पीना चाहिए। डॉक्टर से मिलें और जांच करवाएं। आगे', false)
    expect(r.sentences.length).toBe(2)
    expect(r.sentences[0]?.endsWith('।')).toBe(true)
    expect(r.rest).toBe('आगे')
  })

  it('merges very short sentences with the next one so speech is not choppy', () => {
    const r = extractSentences('Okay. I understand your concern about the cough. More text', false)
    expect(r.sentences).toEqual(['Okay. I understand your concern about the cough.'])
  })

  it('treats line breaks as boundaries and drops bullet-only lines', () => {
    const r = extractSentences('Here are the steps you can follow\n- \nDrink warm water regularly during the day\nmore', false)
    expect(r.sentences).toEqual(['Here are the steps you can follow', 'Drink warm water regularly during the day'])
  })

  it('cuts a very long unpunctuated run-on so speech can start', () => {
    const long = 'word, '.repeat(120)
    const r = extractSentences(long, false)
    expect(r.sentences.length).toBeGreaterThan(0)
    expect(r.sentences.every((s) => s.length <= 260)).toBe(true)
  })

  it('streaming token by token yields the same sentences as one pass', () => {
    const text = 'I am sorry you are unwell. Fever for two days needs a doctor visit. I can help you book an appointment today. Shall I look for a doctor near you?'
    let buffer = ''
    const spoken: string[] = []
    for (const ch of text) {
      buffer += ch
      const { sentences, rest } = extractSentences(buffer, false)
      spoken.push(...sentences)
      buffer = rest
    }
    spoken.push(...extractSentences(buffer, true).sentences)
    expect(spoken.join(' ')).toBe(extractSentences(text, true).sentences.join(' '))
    expect(spoken.join(' ').replace(/\s+/g, ' ')).toBe(text)
  })

  it('handles empty and punctuation-only input', () => {
    expect(extractSentences('', true)).toEqual({ sentences: [], rest: '' })
    expect(extractSentences('... ', true).sentences).toEqual([])
  })
})

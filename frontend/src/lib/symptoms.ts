/** Quick-select symptoms on the Triage screen. `phrase` is what goes into the message sent to the assistant. */
export interface SymptomChip {
  id: string
  label: string
  phrase: string
  /** Shown straight away; the others appear under "More". */
  primary: boolean
}

// Deliberately no "chest pain" chip: emergencies are recognised by the assistant from what the person writes or says.
export const SYMPTOM_CHIPS: SymptomChip[] = [
  { id: 'fever', label: 'Fever & chills', phrase: 'fever and chills', primary: true },
  { id: 'cough', label: 'Persistent cough', phrase: 'a persistent cough', primary: true },
  { id: 'rash', label: 'Skin rash', phrase: 'a skin rash', primary: true },
  { id: 'stomach', label: 'Stomach discomfort', phrase: 'stomach discomfort', primary: true },
  { id: 'headache', label: 'Headache', phrase: 'a headache', primary: false },
  { id: 'bodyache', label: 'Body ache', phrase: 'body aches', primary: false },
  { id: 'sorethroat', label: 'Sore throat', phrase: 'a sore throat', primary: false },
  { id: 'tired', label: 'Tiredness', phrase: 'tiredness', primary: false },
  { id: 'general', label: 'General consultation', phrase: 'a general consultation', primary: false },
]

export const MAX_FREE_TEXT = 1000

export type DiscomfortLabel = 'Mild' | 'Moderate' | 'Urgent'

/** 1-3 Mild, 4-7 Moderate, 8-10 Urgent. */
export function discomfortLabel(level: number): DiscomfortLabel {
  if (level <= 3) return 'Mild'
  if (level <= 7) return 'Moderate'
  return 'Urgent'
}

export function clampLevel(level: number): number {
  if (!Number.isFinite(level)) return 4
  return Math.min(10, Math.max(1, Math.round(level)))
}

function joinPhrases(parts: string[]): string {
  if (parts.length <= 1) return parts.join('')
  return `${parts.slice(0, -1).join(', ')} and ${parts[parts.length - 1]}`
}

/**
 * The single message the Triage screen hands to the assistant. Always English (the assistant replies in the
 * person's chosen language). Returns '' when there is nothing to assess yet.
 */
export function composeTriageMessage(input: { chips: string[]; text: string; level?: number | null }): string {
  const chosen = SYMPTOM_CHIPS.filter((c) => input.chips.includes(c.id))
  const text = input.text.replace(/\s+/g, ' ').trim().slice(0, MAX_FREE_TEXT)
  if (chosen.length === 0 && !text) return ''

  const lines: string[] = ['Please check how urgent my symptoms are and which kind of doctor I should see.']
  const general = chosen.find((c) => c.id === 'general')
  const symptoms = chosen.filter((c) => c.id !== 'general').map((c) => c.phrase)
  if (symptoms.length) lines.push(`Symptoms: ${joinPhrases(symptoms)}.`)
  if (general) lines.push('I would also like a general consultation.')
  if (text) lines.push(`In my own words: ${text}`)
  // The level is only mentioned when the person actually set it.
  if (input.level !== undefined && input.level !== null) {
    const level = clampLevel(input.level)
    lines.push(`Discomfort level: ${level}/10 (${discomfortLabel(level).toLowerCase()}).`)
  }
  return lines.join(' ')
}

/** Example descriptions for the "Try Examples" button, in the languages we can write natively. Others fall back to English. */
const EXAMPLES: Record<string, string[]> = {
  en: ['I have had a fever and a sore throat since yesterday.', 'I have a headache and feel very tired.', 'My child has had a cough and a runny nose for two days.', 'I have an itchy skin rash on my arms.'],
  hi: ['मुझे कल से बुखार और गले में खराश है।', 'मुझे सिर में दर्द है और बहुत थकान लग रही है।', 'मेरे बच्चे को दो दिन से खांसी और जुकाम है।', 'मेरी बाहों पर खुजली वाले दाने निकल आए हैं।'],
  te: ['నాకు నిన్నటి నుండి జ్వరం మరియు గొంతు నొప్పి ఉన్నాయి.', 'నాకు తలనొప్పిగా ఉంది మరియు చాలా అలసటగా ఉంది.', 'నా బిడ్డకు రెండు రోజులుగా దగ్గు మరియు జలుబు ఉన్నాయి.', 'నా చేతులపై దురదతో కూడిన దద్దుర్లు వచ్చాయి.'],
  ta: ['நேற்றிலிருந்து எனக்கு காய்ச்சலும் தொண்டை வலியும் இருக்கிறது.', 'எனக்கு தலைவலி உள்ளது, மிகவும் சோர்வாக இருக்கிறது.', 'என் குழந்தைக்கு இரண்டு நாட்களாக இருமலும் சளியும் உள்ளது.', 'என் கைகளில் அரிப்புடன் கூடிய தடிப்புகள் உள்ளன.'],
}

/** The n-th example (wrapping around) for a language code, or English when we have none in that language. */
export function exampleFor(language: string | null | undefined, index: number): string {
  const list = EXAMPLES[(language ?? 'en').toLowerCase().split(/[-_]/)[0] ?? 'en'] ?? (EXAMPLES.en as string[])
  return list[((index % list.length) + list.length) % list.length] as string
}

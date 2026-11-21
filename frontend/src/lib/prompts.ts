export interface SuggestedPrompt {
  /** Language code of the text, so the app can switch the conversation to it. */
  lang: string
  text: string
}

/** Starter prompts shown on the dashboard and in empty chats: health access in several languages. */
export const SUGGESTED_PROMPTS: SuggestedPrompt[] = [
  { lang: 'en', text: "I've had fever for 2 days. Which doctor should I see?" },
  { lang: 'en', text: 'Book an appointment with a skin doctor in Guntur' },
  { lang: 'hi', text: 'मुझे अपने अपॉइंटमेंट की याद दिलाओ' },
  { lang: 'te', text: 'నాకు డాక్టర్ అపాయింట్‌మెంట్ కావాలి' },
  { lang: 'ta', text: 'எனக்கு அருகில் உள்ள மருத்துவமனையை கண்டுபிடி' },
  { lang: 'kn', text: 'ನನ್ನ ಅಪಾಯಿಂಟ್‌ಮೆಂಟ್ ರದ್ದುಮಾಡಿ' },
  { lang: 'bn', text: 'আমার জ্বর হয়েছে, কোন ডাক্তার দেখাব?' },
  { lang: 'ml', text: 'എനിക്ക് ഡോക്ടറുടെ അപ്പോയിന്റ്മെന്റ് വേണം' },
]

/** Quick actions on the dashboard (each starts a chat with this text). */
export const QUICK_ACTIONS = [
  { key: 'symptoms', label: 'Check my symptoms', text: 'I want to check my symptoms and know what kind of doctor to see.' },
  { key: 'doctor', label: 'Find a doctor near me', text: 'Help me find a doctor near me.' },
  { key: 'book', label: 'Book an appointment', text: 'I would like to book a doctor appointment.' },
  { key: 'remind', label: 'Remind me of my visit', text: 'Remind me about my upcoming appointment.' },
] as const

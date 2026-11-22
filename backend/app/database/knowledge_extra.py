"""More curated, general-information documents for the assistant's knowledge base (first aid, common illnesses, maternal schemes).

Kept deliberately cautious: no medicine doses, no diagnosis, and a pointer to a doctor or helpline whenever the situation could be serious.
Scheme rules change, so those entries tell people to confirm details with their ASHA worker, anganwadi or the official helpline.
"""

EXTRA_KNOWLEDGE: list[dict] = [
    {
        "title": "Snakebite first aid",
        "category": "first_aid",
        "content": (
            "Treat every snakebite as an emergency: call 108 or go to the nearest hospital at once. Keep the person calm and as still as possible, "
            "because moving and panic spread the venom faster. Keep the bitten arm or leg lower than or level with the heart, take off rings, "
            "bangles and tight clothing before swelling starts, and lightly support the limb.\n\n"
            "Do not cut the bite, suck out the venom, tie a tight band, apply herbal paste or give alcohol. Anti-snake venom is available free at "
            "government hospitals and many primary health centres. If it is safe, remember what the snake looked like, but never try to catch it."
        ),
    },
    {
        "title": "Burns first aid",
        "category": "first_aid",
        "content": (
            "For a burn, cool it straight away under clean running tap water for about 20 minutes. Gently take off rings, watches and tight "
            "clothes near the burn before it swells. Cover it loosely with a clean, non-fluffy cloth.\n\n"
            "Do not use ice, toothpaste, oil, butter or powder, and do not burst blisters. Go to a hospital for burns that are large, on the face, "
            "hands, feet or private parts, deep or white or charred, caused by electricity or chemicals, or any burn on a child or an older person. "
            "Call 108 if the person has trouble breathing after a fire or smoke."
        ),
    },
    {
        "title": "Heat stroke and dehydration in hot weather",
        "category": "first_aid",
        "content": (
            "In very hot weather, drink water, ORS or buttermilk often, wear light loose clothes and avoid going out at midday. Heat stroke is an "
            "emergency: very hot dry or sweaty skin, confusion, fainting, a fast pulse or a fit. Call 108, move the person to shade, loosen clothes "
            "and cool the body with wet cloths and fanning. Give small sips of water only if the person is fully awake.\n\n"
            "Babies, older people, pregnant women and people working outdoors are at higher risk."
        ),
    },
    {
        "title": "Bleeding and wounds",
        "category": "first_aid",
        "content": (
            "For bleeding, press firmly on the wound with a clean cloth and keep pressing; raise the injured arm or leg. If the cloth soaks through, "
            "add more cloth on top instead of removing it. Call 108 for bleeding that does not slow within 10 minutes, a deep or gaping wound, or "
            "if the person feels faint.\n\n"
            "Wash small cuts with clean running water and soap and cover them. Ask a doctor about a tetanus injection after a deep, dirty or "
            "rusty-object wound if the last one was more than five years ago or is not known."
        ),
    },
    {
        "title": "ORS, dehydration and diarrhoea in children",
        "category": "child_health",
        "content": (
            "Loose motions and vomiting can dry the body out quickly, especially in babies and young children. Give ORS (oral rehydration salts) in "
            "small, frequent sips, mixing one packet in the amount of clean water printed on the packet. ORS packets are free from ASHA workers and "
            "primary health centres. Keep breastfeeding a baby, and keep giving normal food. Health workers may also advise zinc tablets for young children.\n\n"
            "See a doctor the same day for: blood in the motions, a high fever, a child who is very sleepy or will not drink, sunken eyes, no urine for "
            "eight hours or more, or diarrhoea lasting more than two days."
        ),
    },
    {
        "title": "Dengue and malaria (mosquito fevers)",
        "category": "health",
        "content": (
            "Fever with chills, severe headache, body and joint pain, vomiting or a rash can be dengue or malaria. Get a free blood test at a "
            "government hospital or primary health centre instead of guessing. Drink plenty of fluids and rest. In a suspected dengue fever do not "
            "take aspirin or ibuprofen painkillers unless a doctor says so.\n\n"
            "Go to a hospital at once for dengue warning signs: severe stomach pain, repeated vomiting, bleeding from the gums or nose, black stools, "
            "restlessness or drowsiness, usually 3 to 7 days after the fever starts. Prevent both by not letting water stand in coolers, pots or "
            "tyres, covering water tanks and sleeping under a net."
        ),
    },
    {
        "title": "Anaemia (low haemoglobin)",
        "category": "health",
        "content": (
            "Anaemia causes tiredness, weakness, paleness, breathlessness and dizziness. It is common in women, teenage girls and pregnant women. "
            "A haemoglobin test is available at primary health centres and Ayushman Arogya Mandirs. Iron and folic acid tablets are given free to "
            "pregnant women and adolescents under the Anemia Mukt Bharat programme. Eating green leafy vegetables, pulses, jaggery, eggs, meat or fish "
            "and fruit rich in vitamin C helps.\n\n"
            "Severe breathlessness, chest pain or fainting needs a doctor urgently."
        ),
    },
    {
        "title": "Maternity benefits: JSY, JSSK and PMMVY",
        "category": "scheme",
        "content": (
            "Janani Suraksha Yojana (JSY) gives cash support to women who deliver in a government or accredited health facility. Janani Shishu "
            "Suraksha Karyakram (JSSK) gives pregnant women free delivery including caesarean section, medicines, tests, food and transport, and "
            "covers sick newborns up to one year. Pradhan Mantri Matru Vandana Yojana (PMMVY) gives instalments of cash support to a woman for her "
            "first living child, registered through the anganwadi centre.\n\n"
            "Rules and amounts differ between states and change from time to time, so ask the local ASHA worker or anganwadi worker to confirm."
        ),
    },
    {
        "title": "Health screening at Ayushman Arogya Mandir",
        "category": "scheme",
        "content": (
            "People aged 30 and above can get free screening for high blood pressure, diabetes, oral cancer, breast cancer and cervical cancer at "
            "Ayushman Arogya Mandirs (health and wellness centres) and primary health centres. Getting screened early finds problems while they "
            "are easy to treat. Ask the ASHA worker when the next screening day is.\n\n"
            "See a doctor without waiting for a camp if you notice a lump, a sore in the mouth that does not heal for more than two weeks, "
            "unusual bleeding, or a long-lasting cough or voice change."
        ),
    },
    {
        "title": "Helplines for women, children and senior citizens",
        "category": "emergency",
        "content": (
            "Women Helpline: 181. Childline: 1098 for any child in trouble. Elder Line for senior citizens: 14567. Tele-MANAS for mental health: 14416. "
            "Emergencies: 112; ambulance: 108. Numbers can differ slightly by state, so if one does not connect, call 112 and ask to be transferred."
        ),
    },
    {
        "title": "Using medicines safely",
        "category": "health",
        "content": (
            "Take medicines only as the doctor or pharmacist told you and finish the full course of antibiotics when it is prescribed. Do not take "
            "antibiotics on your own, and do not share your medicines or give adult medicines to children. Tell the doctor about any allergy and about "
            "other medicines you take, including home remedies. Check the expiry date, keep medicines out of children's reach, and carry the "
            "prescription to the pharmacy.\n\n"
            "Stop and see a doctor if a rash, swelling of the face or trouble breathing starts after a medicine. Call 108 if breathing is difficult."
        ),
    },
]

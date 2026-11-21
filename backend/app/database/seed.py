"""Seed data: a health knowledge base, a directory of national health helplines, and DEMO providers.

* The knowledge base and helplines are general public information about Indian health services; the
  assistant tells users to confirm details with the official site or helpline.
* The providers are SAMPLE DATA (`is_demo=True`, names say "Demo"): they exist so the booking workflow can be
  shown end-to-end. Replace them with a real hospital/HMIS integration (see the webhook + `providers` table).
"""
from __future__ import annotations

import logging

from sqlalchemy.ext.asyncio import AsyncSession

from app.database.repositories.knowledge import DirectoryRepository, KnowledgeRepository
from app.database.repositories.providers import ProviderRepository

log = logging.getLogger("app.seed")

KNOWLEDGE: list[dict] = [
    {
        "title": "How Swasthya Saathi works",
        "category": "service",
        "content": (
            "Swasthya Saathi is a multilingual voice and chat assistant that helps people find the right kind of care, book doctor "
            "appointments, get reminders, set follow-up visits and give feedback. You can speak or type in Hindi, Telugu, Tamil, Kannada, "
            "Malayalam, Bengali, Marathi, Gujarati, Punjabi, Odia, Assamese, Urdu, Sanskrit or English.\n\n"
            "After booking you get a reference number (like AP-7K3QX) and reminders one day and two hours before the visit. After the visit "
            "you are asked how it went. You can cancel or reschedule any time before the appointment. In this demo the listed clinics are sample "
            "data. This assistant gives general information, not medical diagnosis."
        ),
    },
    {
        "title": "Emergency and health helpline numbers in India",
        "category": "emergency",
        "content": (
            "112 is the single emergency number for police, fire and ambulance across India. 108 is the ambulance service in many states. "
            "102 is the ambulance service for pregnant women and children in several states, 104 is a state health advice helpline in many states, "
            "14416 is Tele-MANAS, the free 24x7 mental health helpline, 14555 is the Ayushman Bharat PM-JAY helpline, 1098 is Childline and 181 is the women helpline.\n\n"
            "In a medical emergency (chest pain, difficulty breathing, severe bleeding, unconsciousness, stroke signs such as face drooping or slurred speech, "
            "seizures, poisoning, snake bite) call 112 or 108 immediately instead of waiting for an appointment."
        ),
    },
    {
        "title": "Ayushman Bharat PM-JAY health insurance",
        "category": "insurance",
        "source_url": "https://pmjay.gov.in",
        "content": (
            "Ayushman Bharat PM-JAY provides cashless health cover of up to Rs 5 lakh per family per year for hospital treatment at empanelled public and "
            "private hospitals, for families identified as eligible.\n\n"
            "To check eligibility use the 'Am I Eligible' option on mera.pmjay.gov.in with a mobile number, or visit the Ayushman Mitra help desk at an empanelled "
            "hospital or a Common Service Centre. Carry Aadhaar and a ration card or other ID. Eligible beneficiaries complete e-KYC to get an Ayushman card. Helpline: 14555."
        ),
    },
    {
        "title": "ABHA digital health ID",
        "category": "digital_health",
        "source_url": "https://abha.abdm.gov.in",
        "content": (
            "ABHA (Ayushman Bharat Health Account) is a free 14-digit digital health ID. It lets you link your health records (prescriptions, reports) and share "
            "them with doctors only with your consent. You can create an ABHA number on abha.abdm.gov.in using Aadhaar or a mobile number, at an Ayushman Arogya Mandir, "
            "a hospital or a Common Service Centre. Creating it is voluntary."
        ),
    },
    {
        "title": "e-Sanjeevani free teleconsultation",
        "category": "digital_health",
        "source_url": "https://esanjeevani.mohfw.gov.in",
        "content": (
            "e-Sanjeevani is the Government of India's free teleconsultation service. Patients can consult doctors by video or phone from home through the "
            "e-Sanjeevani patient app or portal (OPD service) after registering with a mobile number, and can also get tele-consults at Ayushman Arogya Mandirs "
            "through a health worker. It is suitable for minor illnesses, follow-ups and advice, not emergencies."
        ),
    },
    {
        "title": "Ayushman Arogya Mandir (health and wellness centres)",
        "category": "primary_care",
        "content": (
            "Ayushman Arogya Mandirs (earlier called Health and Wellness Centres) are village and neighbourhood primary health facilities. They offer free "
            "basic care, essential medicines and tests, screening for high blood pressure, diabetes and common cancers, maternal and child health services, "
            "vaccination and referral to bigger hospitals. Ask your ASHA worker or ANM for the nearest one."
        ),
    },
    {
        "title": "Jan Aushadhi low-cost generic medicines",
        "category": "health",
        "source_url": "https://janaushadhi.gov.in",
        "content": (
            "Pradhan Mantri Bhartiya Janaushadhi Kendras sell quality generic medicines at prices much lower than branded equivalents. Ask your doctor to write "
            "the generic name of the medicine. Find the nearest Kendra through the Jan Aushadhi Sugam mobile app or janaushadhi.gov.in."
        ),
    },
    {
        "title": "Fever, diarrhoea and when to see a doctor",
        "category": "first_aid",
        "content": (
            "For fever: rest, drink plenty of fluids, and see a doctor if fever lasts more than 3 days, is very high (above 103 F or 39.4 C), or comes with rash, severe headache, "
            "stiff neck, breathlessness or confusion. Fever in a baby under 3 months always needs a doctor the same day.\n\n"
            "For diarrhoea: take ORS (oral rehydration solution) frequently. Seek care if there is blood in the stool, very frequent watery stools, a child or elder who is "
            "very sleepy, has a dry mouth or passes little urine (signs of dehydration).\n\nThis is general information, not a diagnosis."
        ),
    },
    {
        "title": "Pregnancy and newborn care basics",
        "category": "maternal_child",
        "content": (
            "Every pregnant woman should have regular antenatal check-ups: register the pregnancy early at an Ayushman Arogya Mandir or health centre and ask your ANM or doctor "
            "for the visit schedule. Iron and folic acid tablets and calcium are given free at government facilities. Delivering in a hospital or health facility is safest; "
            "the Janani Suraksha Yojana gives cash assistance for institutional delivery to eligible women.\n\n"
            "Go to a hospital immediately for vaginal bleeding, severe headache or blurred vision, swelling of face or hands, severe stomach pain, fits, leaking fluid, "
            "or if the baby moves much less. A newborn that is not feeding, is very sleepy, has fast breathing or fever needs urgent care."
        ),
    },
    {
        "title": "Child immunisation",
        "category": "maternal_child",
        "content": (
            "Under the Universal Immunisation Programme, vaccines for children and pregnant women are free at government health facilities, sub-centres and Anganwadi "
            "immunisation days. Keep the Mother and Child Protection (MCP) card safe and show it at every visit. Vaccination records can also be tracked on the U-WIN portal. "
            "Ask your ASHA worker or ANM for the due vaccines and the next date. Mild fever or pain at the injection site is common after vaccines."
        ),
    },
    {
        "title": "Diabetes and high blood pressure",
        "category": "chronic",
        "content": (
            "Diabetes and high blood pressure often have no symptoms, so regular screening matters, especially after age 30. Free screening is available at Ayushman Arogya Mandirs. "
            "Take prescribed medicines regularly even when you feel well, do not stop them without asking your doctor, eat less salt and sugar, stay active and keep follow-up visits.\n\n"
            "See a doctor urgently for chest pain, sudden weakness on one side, confusion, very high or very low sugar symptoms (extreme thirst and tiredness, or sweating and shaking)."
        ),
    },
    {
        "title": "Tuberculosis (TB)",
        "category": "chronic",
        "content": (
            "Cough for more than 2 weeks, fever, night sweats, weight loss or blood in sputum can be signs of TB. TB tests and treatment are free at government facilities. "
            "The full course of medicines (usually 6 months) must be completed even when you feel better. Patients may receive nutrition support through the Ni-kshay Poshan Yojana. "
            "National TB helpline: 1800-11-6666."
        ),
    },
    {
        "title": "Mental health support",
        "category": "mental_health",
        "content": (
            "Feeling very sad, anxious, hopeless or unable to sleep for weeks is a health problem that can be treated. Tele-MANAS (14416) is a free, confidential, 24x7 mental "
            "health helpline available in many Indian languages. If someone is thinking of harming themselves or in immediate danger, call 112 and stay with them."
        ),
    },
]

DIRECTORY: list[dict] = [
    dict(name="Unified Emergency Response (police, fire, ambulance)", category="emergency", description="Single national emergency number.", phone="112", website="https://112.gov.in", languages=["en", "hi"]),
    dict(name="Ambulance service", category="emergency", description="Emergency ambulance (108 in many states).", phone="108", languages=["en", "hi"]),
    dict(name="Mother and child ambulance", category="emergency", description="Free ambulance for pregnant women and sick infants in several states.", phone="102", languages=["en", "hi"]),
    dict(name="Tele-MANAS mental health helpline", category="mental_health", description="Free, confidential, 24x7 mental health support in many languages.", phone="14416", website="https://telemanas.mohfw.gov.in", languages=["en", "hi", "te", "ta", "kn", "ml", "bn", "mr", "gu", "pa", "or", "as", "ur"]),
    dict(name="Ayushman Bharat PM-JAY helpline", category="insurance", description="Health cover eligibility, Ayushman card and empanelled hospitals.", phone="14555", website="https://pmjay.gov.in", languages=["en", "hi"]),
    dict(name="e-Sanjeevani teleconsultation", category="digital_health", description="Free government video/phone consultation with doctors.", website="https://esanjeevani.mohfw.gov.in", languages=["en", "hi"]),
    dict(name="ABHA health ID", category="digital_health", description="Create your free digital health ID and link health records.", website="https://abha.abdm.gov.in", languages=["en", "hi"]),
    dict(name="Jan Aushadhi Kendra locator", category="health", description="Find low-cost generic medicine stores.", website="https://janaushadhi.gov.in", languages=["en", "hi"]),
    dict(name="National TB helpline (Ni-kshay)", category="health", description="Tuberculosis information, testing and treatment support.", phone="1800-11-6666", languages=["en", "hi"]),
    dict(name="Childline", category="emergency", description="Help for children in need of care and protection.", phone="1098", website="https://www.childlineindia.org", languages=["en", "hi"]),
    dict(name="Women helpline", category="emergency", description="Support for women in distress.", phone="181", languages=["en", "hi"]),
    dict(name="Senior Citizens helpline", category="health", description="Support and information for elders.", phone="14567", languages=["en", "hi"]),
]

_CLINIC_HOURS = [{"days": [0, 1, 2, 3, 4, 5], "start": "10:00", "end": "13:00"}, {"days": [0, 1, 2, 3, 4, 5], "start": "17:00", "end": "19:00"}]
_OPD_HOURS = [{"days": [0, 1, 2, 3, 4, 5], "start": "09:00", "end": "14:00"}]
_PHC_HOURS = [{"days": [0, 1, 2, 3, 4, 5], "start": "09:00", "end": "13:00"}]
_TELE_HOURS = [{"days": [0, 1, 2, 3, 4, 5, 6], "start": "08:00", "end": "20:00"}]

# (code, name, kind, doctor, specialties, city, state, languages, hours, slot_min, fee, ayushman, tele)
_CITIES = {
    "HYD": ("Hyderabad", "Telangana", ["te", "hi", "en", "ur"]),
    "GNT": ("Guntur", "Andhra Pradesh", ["te", "en", "hi"]),
    "BLR": ("Bengaluru", "Karnataka", ["kn", "en", "hi", "ta", "te"]),
    "MAA": ("Chennai", "Tamil Nadu", ["ta", "en", "hi", "te"]),
    "BOM": ("Mumbai", "Maharashtra", ["mr", "hi", "en", "gu"]),
    "DEL": ("Delhi", "Delhi", ["hi", "en", "pa", "ur"]),
    "CCU": ("Kolkata", "West Bengal", ["bn", "en", "hi"]),
    "COK": ("Kochi", "Kerala", ["ml", "en", "hi", "ta"]),
}

_DOCTORS = ["A. Rao", "S. Iyer", "M. Khan", "P. Sharma", "R. Das", "K. Nair", "L. Reddy", "V. Menon"]


def demo_providers() -> list[dict]:
    out: list[dict] = []
    for i, (key, (city, state, langs)) in enumerate(_CITIES.items()):
        d = lambda n: f"Dr. {_DOCTORS[(i + n) % len(_DOCTORS)]} (demo)"
        out += [
            dict(code=f"HC-{key}-01", name=f"Demo Family Clinic, {city}", kind="clinic", doctor_name=d(0), specialties=["general medicine", "pediatrics"], city=city, state=state,
                 languages=langs, schedule=_CLINIC_HOURS, slot_minutes=20, fee_inr=300, accepts_ayushman=False, teleconsultation=False),
            dict(code=f"HC-{key}-02", name=f"Demo Skin & Care Clinic, {city}", kind="clinic", doctor_name=d(1), specialties=["dermatology"], city=city, state=state,
                 languages=langs[:3], schedule=_CLINIC_HOURS, slot_minutes=20, fee_inr=500, accepts_ayushman=False, teleconsultation=True),
            dict(code=f"HOS-{key}-01", name=f"Demo Government Hospital OPD, {city}", kind="hospital", doctor_name=None,
                 specialties=["general medicine", "gynecology", "orthopedics", "cardiology", "ophthalmology", "ent", "pediatrics"], city=city, state=state,
                 languages=langs, schedule=_OPD_HOURS, slot_minutes=15, fee_inr=20, accepts_ayushman=True, teleconsultation=False),
            dict(code=f"PHC-{key}-01", name=f"Demo Primary Health Centre, {city}", kind="phc", doctor_name=d(2), specialties=["general medicine", "gynecology", "pediatrics"], city=city, state=state,
                 languages=langs[:2], schedule=_PHC_HOURS, slot_minutes=15, fee_inr=0, accepts_ayushman=True, teleconsultation=False),
        ]
    out.append(dict(code="TEL-IN-01", name="Demo Teleconsultation Service (India-wide)", kind="telemedicine", doctor_name=None,
                    specialties=["general medicine", "pediatrics", "dermatology", "psychiatry", "gynecology"], city="Online", state="India",
                    languages=["en", "hi", "te", "ta", "kn", "ml", "bn", "mr", "gu", "pa"], schedule=_TELE_HOURS, slot_minutes=15, fee_inr=150,
                    accepts_ayushman=False, teleconsultation=True))
    out.append(dict(code="TEL-IN-02", name="Demo Mental Wellness Teleconsultation", kind="telemedicine", doctor_name=None,
                    specialties=["psychiatry", "general medicine"], city="Online", state="India",
                    languages=["en", "hi", "te", "ta", "kn", "ml", "bn"], schedule=_TELE_HOURS, slot_minutes=30, fee_inr=400,
                    accepts_ayushman=False, teleconsultation=True))
    return out


async def seed_if_empty(session: AsyncSession, *, include_demo_providers: bool = False) -> None:
    """Knowledge base + helpline directory when empty. The invented sample clinics are added ONLY when asked for
    (SEED_DEMO_PROVIDERS=true), for demos and tests: real places come from OpenStreetMap."""
    kb = KnowledgeRepository(session)
    if await kb.is_empty():
        for doc in KNOWLEDGE:
            await kb.add_document(**doc)
        log.info("Seeded %d knowledge documents", len(KNOWLEDGE))
    directory = DirectoryRepository(session)
    if await directory.is_empty():
        for entry in DIRECTORY:
            await directory.add(**entry)
        log.info("Seeded %d directory entries", len(DIRECTORY))
    providers = ProviderRepository(session)
    if include_demo_providers and await providers.is_empty():
        rows = demo_providers()
        for p in rows:
            await providers.add(**p, is_demo=True, source="demo")
        log.info("Seeded %d DEMO providers", len(rows))

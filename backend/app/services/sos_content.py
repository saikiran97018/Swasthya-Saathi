"""Static content for the SOS screen: national helplines and general first-aid steps.

Kept deliberately conservative and short. The steps follow widely taught basic first aid (Red Cross / WHO style) and
never name medicines or doses. The screen says plainly that it does not replace trained help and does not call anyone.
"""
from __future__ import annotations

from app.schemas.family import FirstAidCard, SosNumber

DISCLAIMER = (
    "These are general first-aid steps, not medical advice, and they do not replace trained help. "
    "This app does not call or message anyone for you: if someone is in danger, call 112 now."
)

NUMBERS = [
    SosNumber(code="112", label="Emergency (police, fire, ambulance)", description="India's single emergency number. Works from any phone.", kind="emergency"),
    SosNumber(code="108", label="Ambulance", description="Emergency ambulance service in many states.", kind="ambulance"),
    SosNumber(code="102", label="Mother and child ambulance", description="Free transport for pregnant women and sick infants in several states.", kind="ambulance"),
    SosNumber(code="181", label="Women helpline", description="Support for women in distress.", kind="women"),
    SosNumber(code="1098", label="Childline", description="Help for children in need of care and protection.", kind="child"),
    SosNumber(code="14416", label="Tele-MANAS", description="Free mental-health support, available 24 hours.", kind="mental_health"),
    SosNumber(code="104", label="Health advice line", description="Health information line run by many state governments.", kind="other"),
]

FIRST_AID = [
    FirstAidCard(
        id="chest_pain", title="Chest pain or a suspected heart attack",
        steps=[
            "Call 112 or 108 now.",
            "Help the person sit down and stay calm and still. Do not let them walk or drive.",
            "Loosen tight clothing.",
            "If they stop responding and are not breathing normally, start chest compressions (see the card on not breathing).",
        ],
        call_if="Chest pain lasting more than a few minutes, spreading to the arm, jaw or back, or with sweating or breathlessness.",
    ),
    FirstAidCard(
        id="not_breathing", title="Not responding and not breathing normally",
        steps=[
            "Shout for help and call 112 or 108, or ask someone else to.",
            "Lay the person on their back on a firm, flat surface.",
            "Put the heel of one hand on the centre of the chest, the other hand on top, and push hard and fast: about 100 to 120 pushes a minute, at least 5 cm deep for an adult.",
            "Let the chest rise fully between pushes. Keep going until help arrives or the person starts to breathe.",
            "If an automatic defibrillator (AED) is nearby, switch it on and follow its spoken instructions.",
        ],
        call_if="Always: this is an emergency.",
    ),
    FirstAidCard(
        id="bleeding", title="Heavy bleeding",
        steps=[
            "Press firmly and directly on the wound with a clean cloth or your hand.",
            "If blood soaks through, add more cloth on top. Do not remove the first one.",
            "Keep pressing without stopping. Raise the injured arm or leg if you can, and lay the person down.",
            "Do not pull out anything stuck in the wound.",
        ],
        call_if="Bleeding does not slow after 10 minutes of firm pressure, blood spurts out, or the person feels faint or confused.",
    ),
    FirstAidCard(
        id="choking", title="Choking",
        steps=[
            "If the person can cough or speak, encourage them to keep coughing.",
            "If they cannot breathe, cough or speak: give up to 5 firm slaps between the shoulder blades.",
            "Then up to 5 abdominal thrusts: stand behind, put a fist just above the navel and pull sharply inward and upward. Alternate back slaps and thrusts.",
            "For a baby under 1 year, use back slaps and chest thrusts only, never abdominal thrusts.",
            "If they become unresponsive, call 112 and start chest compressions.",
        ],
        call_if="The person cannot cough, speak or breathe.",
    ),
    FirstAidCard(
        id="burns", title="Burns",
        steps=[
            "Cool the burn under cool (not ice-cold) running water for at least 20 minutes.",
            "Take off rings, watches or tight items near the burn before it swells, unless stuck to the skin.",
            "Cover loosely with a clean, non-fluffy cloth or cling film.",
            "Do not apply ice, butter, toothpaste or oil, and do not burst blisters.",
        ],
        call_if="The burn is larger than the person's palm, on the face, hands, groin or a joint, looks deep, white or charred, was caused by chemicals or electricity, or the person is a child.",
    ),
    FirstAidCard(
        id="stroke", title="Stroke signs (FAST)",
        steps=[
            "Face: does one side droop when they smile? Arm: can they lift both arms? Speech: is it slurred or confused?",
            "Time: if any sign is present, call 112 or 108 immediately and note the time it started.",
            "Keep the person comfortable and give nothing to eat or drink.",
            "If they are unconscious but breathing, lay them on their side.",
        ],
        call_if="Any of these signs, even if they seem to go away.",
    ),
    FirstAidCard(
        id="seizure", title="Seizure (fit)",
        steps=[
            "Stay calm and note the time it started.",
            "Move hard or sharp objects away and cushion the head.",
            "Do not hold the person down and do not put anything in their mouth.",
            "When the shaking stops, roll them onto their side and stay until they are fully awake.",
        ],
        call_if="It lasts more than 5 minutes, repeats, it is the first seizure, the person is injured or pregnant, or has trouble breathing afterwards.",
    ),
    FirstAidCard(
        id="snakebite", title="Snakebite",
        steps=[
            "Keep the person calm and as still as possible. Limit movement of the bitten limb.",
            "Take off rings, bangles and tight items near the bite before it swells.",
            "Do not cut the wound, suck out venom, tie a tight band, or apply ice or herbs.",
            "Get to a hospital immediately, because treatment is given there. If you safely can, note what the snake looked like and the time.",
        ],
        call_if="Always: call 108 or 112, or go to the nearest hospital now.",
    ),
    FirstAidCard(
        id="poisoning", title="Poisoning or swallowed chemicals",
        steps=[
            "Call 112 or 108 now.",
            "Do not make the person vomit.",
            "If a chemical is on skin or in the eyes, rinse with plenty of clean water for 15 to 20 minutes.",
            "Keep the container or label to show the doctors. Give nothing to eat or drink unless a doctor says so.",
        ],
        call_if="Always.",
    ),
    FirstAidCard(
        id="heat_stroke", title="Heat stroke",
        steps=[
            "Move the person to shade or a cool room and lay them down.",
            "Remove extra clothing and cool the skin with wet cloths or water, and fan them.",
            "If they are fully awake, give small sips of water.",
        ],
        call_if="They are confused, faint, have a fit, or stop sweating while very hot.",
    ),
    FirstAidCard(
        id="pregnancy", title="Pregnancy danger signs",
        steps=[
            "Heavy bleeding, a fit, a severe headache with blurred vision, or no movement from the baby are emergencies.",
            "Call 108 or 102, or go to the nearest hospital now.",
            "Lie on the left side while waiting. Do not eat or drink if you may need an operation.",
        ],
        call_if="Any of these signs.",
    ),
]

"""Orin profile parsing: DeepInfra structured extraction with a deterministic fallback.

The parser is the only place an LLM touches candidate data, and it is constrained
to *reading*. Money and deadlines are never trusted from it — the calculator
recomputes every number from the seeded rule rows.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Any

import requests
from django.conf import settings

from ..models import Entity

logger = logging.getLogger(__name__)

# Monthly USD bands used only when a profile carries no explicit salary.
SENIORITY_BANDS_USD = {
    "junior": 3500.0,
    "mid": 7000.0,
    "senior": 12000.0,
    "staff/principal": 18000.0,
    "director": 24000.0,
}

ENTITY_COUNTRY = {
    Entity.UAE_DIFC: "UAE",
    Entity.UAE_MAINLAND: "UAE",
    Entity.KSA_RIYADH: "KSA",
    Entity.QATAR_DOHA: "QATAR",
    Entity.CERCLI_EOR_REMOTE: "REMOTE",
}

CITY_TERMS = {
    "dubai": ["dubai", "jlt", "difc", "dmcc", "business bay", "dubai marina"],
    "abu dhabi": ["abu dhabi", "masdar", "khalifa city"],
    "sharjah": ["sharjah"],
    "riyadh": ["riyadh", "riyad"],
    "jeddah": ["jeddah", "jidda"],
    "dammam": ["dammam", "khobar", "dhahran"],
    "doha": ["doha", "lusail", "pearl qatar"],
    "london": ["london"],
    "berlin": ["berlin"],
    "bengaluru": ["bengaluru", "bangalore"],
    "karachi": ["karachi"],
    "cairo": ["cairo", "giza"],
    "amman": ["amman"],
    "beirut": ["beirut"],
    "istanbul": ["istanbul"],
    "paris": ["paris"],
    "new york": ["new york", "nyc"],
    "san francisco": ["san francisco", "bay area"],
    "remote": ["remote", "work from anywhere", "distributed team"],
}

COUNTRY_TERMS = {
    "UAE": ["uae", "united arab emirates", "emirates", "dubai", "abu dhabi", "sharjah"],
    "KSA": ["saudi arabia", "ksa", "riyadh", "jeddah", "dammam"],
    "QATAR": ["qatar", "doha", "lusail"],
    "UK": ["united kingdom", "uk", "london", "england"],
    "GERMANY": ["germany", "berlin", "munich"],
    "INDIA": ["india", "bengaluru", "bangalore", "mumbai", "delhi", "hyderabad", "pune"],
    "PAKISTAN": ["pakistan", "karachi", "lahore", "islamabad"],
    "EGYPT": ["egypt", "cairo", "alexandria"],
    "JORDAN": ["jordan", "amman"],
    "LEBANON": ["lebanon", "beirut"],
    "TURKEY": ["turkey", "istanbul", "ankara"],
    "FRANCE": ["france", "paris", "lyon"],
    "USA": ["usa", "united states", "new york", "san francisco", "california"],
}

SENIORITY_TERMS = [
    ("director", ["director", "head of", "vice president", "vp engineering", "chief"]),
    ("staff/principal", ["principal", "staff", "architect", "distinguished", "fellow"]),
    ("senior", ["senior", "tech lead", "team lead", "lead engineer"]),
    ("junior", ["junior", "graduate", "intern", "entry level", "associate engineer"]),
]

TRANSFERABLE_TERMS = [
    "transferable", "transfer visa", "noc available", "valid uae visa", "valid visa in uae",
    "valid iqama", "iqama transfer", "immediate join", "immediately available",
    "golden visa", "local transfer", "on arrival",
    # local hires who need no new sponsorship consume no quota
    "no sponsorship", "does not require sponsorship", "no visa required", "national",
]

RELOCATION_TERMS = [
    "willing to relocate", "open to relocate", "relocating", "seeking relocation",
    "requires visa sponsorship", "needs sponsorship", "sponsorship required",
    "visa sponsorship required", "outside uae", "outside saudi",
]

ANNUAL_THRESHOLD = 100_000
FX_TO_USD = {"USD": 1.0, "AED": 3.6725, "SAR": 3.75, "QAR": 3.64, "EGP": 48.5, "INR": 83.5}
SALARY_RE = re.compile(
    r"(usd|us\$|\$|aed|sar|qar|egp|inr)\s?(\d{1,3}(?:,\d{3})+|\d{4,6})"
    r"|(\d{1,3}(?:,\d{3})+|\d{4,6})\s?(usd|us\$|\$|aed|sar|qar|egp|inr)\b",
    re.IGNORECASE,
)

PROMPT = """You are Orin, Cercli's MENA recruiting analyst. Read the candidate profile and
return STRICT JSON, no prose, matching exactly this shape:

{
  "full_name": string,
  "current_city": string,
  "current_country": string (ISO-ish name, e.g. "United Arab Emirates"),
  "country_code": one of "UAE" | "KSA" | "QATAR" | "OTHER",
  "in_target_country": boolean (is the candidate already in the target market?),
  "transferable_visa": boolean (holds a permit that can be transferred without leaving),
  "needs_relocation": boolean,
  "seniority": one of "junior" | "mid" | "senior" | "staff/principal" | "director",
  "estimated_monthly_base_usd": number,
  "signals": [string] (max 4 short evidence phrases from the profile),
  "outreach_en": string (<=60 words, warm, specific to the role and city, no invented numbers),
  "outreach_ar": string (the same message in natural Modern Standard Arabic)
}

Target entity/market: __TARGET_ENTITY__.
Profile:
\"\"\"__PROFILE__\"\"\""""


def _hits(text: str, terms: list[str]) -> bool:
    return any(re.search(rf"\b{re.escape(t)}\b", text) for t in terms)


def _first(text: str, groups: dict[str, list[str]]) -> str | None:
    for label, terms in groups.items():
        if _hits(text, terms):
            return label
    return None


def _seniority(text: str) -> str:
    for label, terms in SENIORITY_TERMS:
        if _hits(text, terms):
            return label
    return "mid"


def _name(raw: str) -> str:
    match = re.search(r"(?im)^\s*name\s*[:\-]\s*(\S[^\n]{0,59})$", raw)
    if match:
        return match.group(1).strip()
    first_line = raw.strip().splitlines()[0] if raw.strip() else ""
    return (first_line[:60] or "Candidate").strip()


def _salary(text: str) -> tuple[float, str]:
    """Extract a monthly USD figure; returns (amount, confidence)."""
    for currency_a, num_a, num_b, currency_b in SALARY_RE.findall(text):
        number = num_a or num_b
        if not number:
            continue
        currency = (currency_a or currency_b or "usd").upper()
        if currency in ("$", "US$"):
            currency = "USD"
        value = float(number.replace(",", ""))
        value_usd = value / FX_TO_USD.get(currency, 1.0)
        if value_usd > ANNUAL_THRESHOLD:  # an annual package, not monthly
            value_usd /= 12
        if 800 <= value_usd <= 80_000:
            return round(value_usd, 2), "explicit"
    return 0.0, "missing"


def heuristic_parse(raw_profile: str, target_entity: str) -> dict[str, Any]:
    """Deterministic offline extraction — used when no API key is configured."""
    text = raw_profile.lower()
    city = _first(text, CITY_TERMS) or "unknown"
    country = _first(text, COUNTRY_TERMS) or "unknown"
    target_country = ENTITY_COUNTRY.get(target_entity, "OTHER")

    if target_country == "REMOTE":
        in_target = city == "remote"
    else:
        in_target = country == target_country

    transferable = _hits(text, TRANSFERABLE_TERMS)
    seniority = _seniority(text)
    salary, confidence = _salary(text)
    if not salary:
        salary = SENIORITY_BANDS_USD[seniority]

    signals = []
    if in_target:
        signals.append(f"Currently based in {city}.")
    else:
        signals.append(f"Based in {city}, outside the {target_country} market.")
    if transferable:
        signals.append("Signals a transferable permit / immediate availability.")
    if _hits(text, RELOCATION_TERMS) or not in_target:
        signals.append("Open to relocation for the right role.")
    signals.append(f"Profile reads as {seniority} level.")

    return {
        "full_name": _name(raw_profile),
        "current_city": city,
        "current_country": country,
        "in_target_country": in_target,
        "transferable_visa": transferable,
        "needs_relocation": not in_target,
        "open_to_relocate": _hits(text, RELOCATION_TERMS) or not in_target,
        "seniority": seniority,
        "estimated_monthly_base_usd": salary,
        "salary_confidence": confidence,
        "signals": signals[:4],
        "outreach_en": "",
        "outreach_ar": "",
        "source": "heuristic-mock",
    }


def _coerce(payload: dict[str, Any], fallback: dict[str, Any]) -> dict[str, Any]:
    """Merge LLM output over the heuristic baseline, rejecting implausible values."""
    out = dict(fallback)
    for key in ("full_name", "current_city", "current_country", "seniority"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            out[key] = payload[key].strip()

    for key in ("in_target_country", "transferable_visa", "needs_relocation"):
        if isinstance(payload.get(key), bool):
            out[key] = payload[key]
    out["needs_relocation"] = not out["in_target_country"]

    salary = payload.get("estimated_monthly_base_usd")
    if isinstance(salary, (int, float)) and 800 <= float(salary) <= 80_000:
        out["estimated_monthly_base_usd"] = round(float(salary), 2)
        out["salary_confidence"] = "llm"

    if out["seniority"] not in SENIORITY_BANDS_USD:
        out["seniority"] = fallback["seniority"]

    signals = payload.get("signals")
    if isinstance(signals, list):
        cleaned = [s.strip() for s in signals if isinstance(s, str) and s.strip()][:4]
        if cleaned:
            out["signals"] = cleaned

    for key in ("outreach_en", "outreach_ar"):
        if isinstance(payload.get(key), str) and payload[key].strip():
            out[key] = payload[key].strip()

    out["source"] = "deepinfra"
    return out


def deepinfra_parse(raw_profile: str, target_entity: str) -> dict[str, Any]:
    """One cheap structured call; any failure degrades to the heuristic parser."""
    fallback = heuristic_parse(raw_profile, target_entity)
    if not settings.DEEPINFRA_API_KEY:
        logger.info("DEEPINFRA_API_KEY absent — using deterministic mock parser.")
        return fallback

    try:
        # String replacement, not str.format — the prompt is full of literal JSON braces.
        content_prompt = PROMPT.replace("__TARGET_ENTITY__", target_entity).replace(
            "__PROFILE__", raw_profile[:4000]
        )
        body = {
            "model": settings.DEEPINFRA_MODEL,
            "temperature": 0,
            "max_tokens": 900,
            "response_format": {"type": "json_object"},
            "messages": [{"role": "user", "content": content_prompt}],
        }
        response = requests.post(
            f"{settings.DEEPINFRA_BASE_URL.rstrip('/')}/chat/completions",
            headers={
                "Authorization": f"Bearer {settings.DEEPINFRA_API_KEY}",
                "Content-Type": "application/json",
            },
            json=body,
            # (connect, read): fail fast on a dead host, allow real generation time.
            timeout=(5, settings.LLM_TIMEOUT_SECONDS),
        )
        response.raise_for_status()
        content = response.json()["choices"][0]["message"]["content"]
        content = re.sub(r"^```(?:json)?|```$", "", content.strip(), flags=re.MULTILINE).strip()
        return _coerce(json.loads(content), fallback)
    except Exception as exc:  # noqa: BLE001 — the demo must never hard-fail here
        logger.warning("DeepInfra parse failed (%s) — falling back to heuristic parser.", exc)
        fallback["llm_error"] = str(exc)[:200]
        return fallback


def parse_candidate(raw_profile: str, target_entity: str) -> dict[str, Any]:
    """Public entrypoint used by the pipeline, mutations and Celery tasks."""
    return deepinfra_parse(raw_profile, target_entity)

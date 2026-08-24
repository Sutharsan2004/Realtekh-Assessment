"""
Groq LLM integration.

The LLM's ONLY job is to produce structured, evidence-based per-requirement
analysis (JSON). It never states a final score or recommendation -- that is
always computed deterministically in scoring.py from this structured output.
"""
from __future__ import annotations

import json
import os
import re
from typing import List, Optional, Tuple

from dotenv import load_dotenv

from models import RequirementEvaluation

load_dotenv()

GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")
# Groq model IDs are case-sensitive provider identifiers, not display names.
GROQ_MODEL = os.getenv("GROQ_MODEL", "qwen/qwen3.6-27b")

SYSTEM_PROMPT = """You are a resume-to-job-description requirement extraction engine.

You must analyze the Job Description and break it into individual discrete
requirements, then evaluate the resume against EACH requirement.

Create a separate requirement entry for every distinct skill explicitly named
in the JD. Do not group several skills into one broad requirement, because
each skill needs its own resume-work-experience and recency check.

Rules you MUST follow:
- Never consider or mention age, gender, race, religion, disability, nationality,
  marital status, or any other protected/irrelevant trait. If the JD or resume
  mentions such traits, ignore them entirely.
- For every requirement, classify:
  - "requirement_type": "mandatory" or "preferred"
  - "category": one of "mandatory", "experience", "projects", "preferred", "education"
    (use "mandatory" for core must-have skill/qualification requirements that are
    not specifically experience-years, project-track-record, education, or
    "nice to have" preferred items)
  - "resume_status": one of "supported", "partially_supported", "not_found",
    "unclear", "not_applicable"
  - "resume_evidence": a short quote or close paraphrase from the resume that
    supports your status (empty string if none found)
  - "jd_evidence": a short quote or close paraphrase from the JD describing the
    requirement
  - "score": your own 0-100 estimate of how well this single requirement is met
    (this is advisory input only; the application computes the real final score)
  - "recency_status": one of "recent", "older", "not_found", "unclear",
    "not_applicable". For every JD skill or experience requirement, inspect
    the resume's work-experience entries in date order. Use "recent" only when
    the skill is evidenced in the candidate's most recent/current role. If a
    skill appears in earlier roles but is not evidenced in the most recent role,
    use "older". Use "not_found" when it is not evidenced in work experience;
    use "unclear" if dates/roles are insufficient to determine this; and use "not_applicable" only for items
    such as education that do not require work-experience recency.
  - "recency_evidence": the role name/company and dates (when stated) that
    support the recency result; empty only when no evidence is available.
  - "recency_insight": one concise, neutral explanation. Explicitly flag when
    a JD skill appears only in older roles, for example: "Python appears in the
    2020-2022 role but not in the 2024-present role." Do not assume that a
    skill missing from a role was not used unless the resume chronology supports
    that conclusion; say "not evidenced" instead.
- Do NOT compute or state an overall score or a final recommendation. Only
  return the structured per-requirement list.
- Return exactly one valid JSON object. Do not include Markdown fences, prose,
  comments, or a reasoning trace. Every string value must use double quotes.
  Use this valid JSON shape (replace the example values with your analysis):

{
  "requirements": [
    {
      "requirement_text": "Example requirement",
      "requirement_type": "mandatory",
      "category": "mandatory",
      "resume_status": "supported",
      "resume_evidence": "Example resume evidence",
      "jd_evidence": "Example job-description evidence",
      "score": 75,
      "recency_status": "recent",
      "recency_evidence": "Backend Engineer, Example Co (2023-present): Python APIs",
      "recency_insight": "Python is evidenced in the most recent role."
    }
  ]
}
"""


class LLMError(Exception):
    pass


def _extract_json(text: str) -> dict:
    text = text.strip()
    text = re.sub(r"^```(json)?", "", text.strip())
    text = re.sub(r"```$", "", text.strip())
    text = text.strip()
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # fallback: grab the first {...} block
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match:
        return json.loads(match.group(0))
    raise LLMError("Could not parse JSON from LLM response.")


def _call_groq(job_title: str, job_description: str, resume_text: str) -> str:
    if not GROQ_API_KEY:
        raise LLMError("GROQ_API_KEY is not configured.")
    try:
        from groq import Groq
    except ImportError as e:
        raise LLMError(f"groq package not installed: {e}")

    client = Groq(api_key=GROQ_API_KEY)
    user_prompt = f"""JOB TITLE:
{job_title}

JOB DESCRIPTION:
{job_description}

RESUME:
{resume_text}
"""
    try:
        completion = client.chat.completions.create(
            model=GROQ_MODEL,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=4000,
            response_format={"type": "json_object"},
            # Qwen reasoning can otherwise be included in, and invalidate, a
            # JSON-mode response. extra_body keeps this compatible with the
            # project's pinned Groq SDK.
            extra_body={
                "reasoning_effort": "none",
                "reasoning_format": "hidden",
            },
        )
        return completion.choices[0].message.content
    except Exception as e:  # network / API failure of any kind
        raise LLMError(f"Groq API call failed: {e}")


def evaluate_resume(
    job_title: str, job_description: str, resume_text: str
) -> Tuple[List[RequirementEvaluation], Optional[str]]:
    """
    Returns (requirements, error). If error is not None, requirements will be
    a safe fallback list (single placeholder) so the pipeline can still
    degrade gracefully instead of crashing.
    """
    try:
        raw = _call_groq(job_title, job_description, resume_text)
        data = _extract_json(raw)
        raw_reqs = data.get("requirements", [])
        if not isinstance(raw_reqs, list) or len(raw_reqs) == 0:
            raise LLMError("LLM returned no requirements.")

        parsed: List[RequirementEvaluation] = []
        for item in raw_reqs:
            try:
                parsed.append(RequirementEvaluation(**item))
            except Exception:
                # skip a single malformed requirement rather than failing the whole batch
                continue

        if not parsed:
            raise LLMError("No requirement entries survived validation.")

        return parsed, None

    except LLMError as e:
        return _fallback_requirements(str(e)), str(e)
    except Exception as e:
        return _fallback_requirements(str(e)), f"Unexpected error: {e}"


def _fallback_requirements(error_msg: str) -> List[RequirementEvaluation]:
    """Degraded-mode placeholder used when the AI call cannot complete."""
    return [
        RequirementEvaluation(
            requirement_text="AI evaluation unavailable",
            requirement_type="mandatory",
            category="mandatory",
            resume_status="unclear",
            resume_evidence="",
            jd_evidence=f"AI/network failure: {error_msg}",
            score=50,
        )
    ]

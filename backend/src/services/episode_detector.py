"""
Episode detection engine.

Evaluates a transcript against the patient's context to decide whether
an episode is occurring. Uses a two-stage approach:
  1. Rule-based matching (fast, deterministic) — trigger phrases and regex patterns.
  2. LLM-based analysis (optional, richer) — contextual understanding.

If stage 1 finds a high-severity match, it can skip LLM for speed.
"""

import re
import logging
from dataclasses import dataclass

from .llm import get_llm_provider

logger = logging.getLogger(__name__)


@dataclass
class EpisodeResult:
    is_episode: bool
    severity: int  # 0-5
    reason: str
    llm_response: str | None = None


def _build_system_prompt(context: dict) -> str:
    profile = context.get("static_profile", {})
    name = profile.get("preferred_name", "el paciente")
    address = profile.get("current_address", "su domicilio")
    caregivers = ", ".join(profile.get("caregiver_names", []))
    style = context.get("assistant_style", {})
    tone = style.get("tone", "calmado")
    max_words = style.get("max_words", 40)

    return (
        f"Eres un asistente para una persona con demencia llamada {name}. "
        f"Responde SIEMPRE en español, con frases cortas, tono {tone}, máximo {max_words} palabras. "
        f"No inventes datos. No des consejos médicos. No menciones que eres una IA.\n"
        f"Contexto: {name} está en {address}. "
        f"Cuidadores: {caregivers}.\n"
        f"Si la persona está confundida, oriéntala con calma y dile que su cuidador va a ser avisado."
    )


def _build_analysis_prompt(context: dict, transcript: str) -> str:
    triggers = context.get("trigger_phrases", [])
    rules = context.get("risk_rules", [])

    trigger_lines = []
    for t in triggers:
        if isinstance(t, str):
            trigger_lines.append(f'- "{t}" (severidad 3)')
        else:
            trigger_lines.append(f'- "{t["text"]}" (severidad {t.get("severity", 3)})')
    trigger_list = "\n".join(trigger_lines)

    rule_lines = []
    for r in rules:
        if isinstance(r, str):
            rule_lines.append(f'- patrón: "{r}" → riesgo: medio')
        else:
            rule_lines.append(f'- patrón: "{r["pattern"]}" → riesgo: {r.get("risk", "desconocido")}')
    rule_list = "\n".join(rule_lines)

    return (
        f"Analiza la siguiente transcripción del paciente y decide si está teniendo un episodio "
        f"de desorientación o necesita ayuda.\n\n"
        f"Frases gatillo conocidas:\n{trigger_list}\n\n"
        f"Reglas de riesgo:\n{rule_list}\n\n"
        f"Transcripción: \"{transcript}\"\n\n"
        f"Responde SOLO con un JSON así: "
        f'{{\"episode\": true/false, \"severity\": 0-5, \"reason\": \"explicación breve\"}}'
    )


class EpisodeDetector:
    """Detects episodes using a combination of rules and LLM analysis."""

    def __init__(self, context_json: dict):
        self.context = context_json

    def _rule_based_check(self, transcript: str) -> EpisodeResult | None:
        """Stage 1: fast regex/keyword matching."""
        text_lower = transcript.lower().strip()

        # Check trigger phrases (supports plain strings or {"text": ..., "severity": ...})
        for trigger in self.context.get("trigger_phrases", []):
            if isinstance(trigger, str):
                phrase = trigger.lower()
                severity = 3
                display = trigger
            else:
                phrase = trigger.get("text", "").lower()
                severity = trigger.get("severity", 3)
                display = trigger.get("text", phrase)
            if phrase and phrase in text_lower:
                return EpisodeResult(
                    is_episode=True,
                    severity=severity,
                    reason=f'Frase gatillo detectada: "{display}"',
                )

        # Check risk rules (supports plain strings or {"pattern": ..., "risk": ...})
        for rule in self.context.get("risk_rules", []):
            if isinstance(rule, str):
                pattern = rule
                risk_label = rule
            else:
                pattern = rule.get("pattern", "")
                risk_label = rule.get("risk", pattern)
            if pattern and re.search(pattern, text_lower):
                return EpisodeResult(
                    is_episode=True,
                    severity=4,
                    reason=f"Regla de riesgo activada: {risk_label}",
                )

        return None

    async def analyze(self, transcript: str, use_llm: bool = True) -> EpisodeResult:
        """
        Full analysis pipeline.
        Returns EpisodeResult with detection decision and optional LLM response.
        """
        # Stage 1: rules
        rule_result = self._rule_based_check(transcript)

        if rule_result and rule_result.severity >= 4:
            # High severity — generate calming response via LLM if available
            if use_llm:
                try:
                    llm = get_llm_provider()
                    system = _build_system_prompt(self.context)
                    response = await llm.generate(system, transcript)
                    rule_result.llm_response = response
                except Exception as e:
                    logger.warning(f"LLM generation failed, returning rule-only result: {e}")
            return rule_result

        if rule_result:
            # Lower severity rule match — still generate LLM response
            if use_llm:
                try:
                    llm = get_llm_provider()
                    system = _build_system_prompt(self.context)
                    response = await llm.generate(system, transcript)
                    rule_result.llm_response = response
                except Exception as e:
                    logger.warning(f"LLM generation failed: {e}")
            return rule_result

        # Stage 2: LLM-based analysis (no rule matched)
        if use_llm:
            try:
                llm = get_llm_provider()
                analysis_prompt = _build_analysis_prompt(self.context, transcript)
                raw = await llm.generate(
                    "Eres un sistema de detección de episodios de demencia. Responde SOLO en JSON válido.",
                    analysis_prompt,
                )
                # Try to parse LLM JSON response
                import json
                # Find JSON in response
                json_match = re.search(r'\{.*\}', raw, re.DOTALL)
                if json_match:
                    parsed = json.loads(json_match.group())
                    is_episode = bool(parsed.get("episode", False))
                    severity = int(parsed.get("severity") or 0)
                    reason = parsed.get("reason") or "Análisis LLM"

                    llm_response = None
                    if is_episode:
                        system = _build_system_prompt(self.context)
                        llm_response = await llm.generate(system, transcript)

                    return EpisodeResult(
                        is_episode=is_episode,
                        severity=severity,
                        reason=reason,
                        llm_response=llm_response,
                    )
            except Exception as e:
                logger.warning(f"LLM analysis failed: {e}")

        # No episode detected
        return EpisodeResult(is_episode=False, severity=0, reason="Sin coincidencias")

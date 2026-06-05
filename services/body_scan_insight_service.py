"""LLM insight workflow for body progress scans."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from typing import Any

import pandas as pd

from config import get_settings
from db import repository
from llm.factory import get_llm_client
from llm.schemas import BodyScanInsightSchema
from services.llm_workflow import generate_structured_payload


@dataclass(frozen=True)
class BodyScanInsightResult:
    """Stored body scan insight response."""

    insight_id: int
    payload: dict[str, Any]


def _safe_json_loads(raw: Any) -> Any:
    if raw is None or (isinstance(raw, float) and pd.isna(raw)):
        return None
    if isinstance(raw, dict | list):
        return raw
    try:
        return json.loads(str(raw))
    except json.JSONDecodeError:
        return None


def _normalize_string_list(value: Any) -> list[str]:
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    if isinstance(value, str) and value.strip():
        return [value.strip()]
    return []


def _normalize_insight_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized = {key: value for key, value in payload.items() if value not in (None, "")}
    explanation = str(normalized.get("explanation", "")).strip()
    if explanation and not normalized.get("summary"):
        normalized["summary"] = explanation
        normalized["visual_changes"] = [explanation]
    body_shape_analysis = _normalize_string_list(normalized.pop("body_shape_analysis", None))
    if body_shape_analysis:
        normalized["visual_changes"] = body_shape_analysis + _normalize_string_list(normalized.get("visual_changes"))
    for key in (
            "visual_changes",
            "posture_and_symmetry",
            "running_form_implications",
            "progress_trends",
            "risks_or_unknowns",
            "coaching_actions",
            "next_photo_protocol",
            "evidence",
            "limitations",
    ):
        normalized[key] = _normalize_string_list(normalized.get(key))
    normalized["summary"] = str(normalized.get("summary", "")).strip()
    try:
        normalized["confidence"] = max(0.0, min(100.0, float(normalized.get("confidence", 0.0))))
    except (TypeError, ValueError):
        normalized["confidence"] = 0.0
    return normalized


def _compact_measurements(measurements: dict[str, Any]) -> dict[str, Any]:
    """Keep only coaching-relevant scan metrics for the LLM context."""

    allowed_top_level = {
        "processor",
        "message",
        "pose_quality",
        "landmark_count",
        "visible_landmark_count",
        "shoulder_tilt_degrees",
        "hip_tilt_degrees",
        "shoulder_width_normalized",
        "hip_width_normalized",
        "torso_lean_degrees",
        "left_knee_angle_degrees",
        "right_knee_angle_degrees",
        "symmetry_notes",
    }
    compact = {key: measurements[key] for key in allowed_top_level if key in measurements}
    shape_metrics = measurements.get("shape_metrics")
    if isinstance(shape_metrics, dict):
        compact["shape_metrics"] = _compact_shape_metrics(shape_metrics)
    return compact


def _compact_shape_metrics(shape_metrics: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "sam3d_mesh_analysis_status",
        "sam3d_vertex_count",
        "sam3d_face_count",
        "sam3d_height_proxy",
        "sam3d_width_proxy",
        "sam3d_depth_proxy",
        "sam3d_width_to_height_ratio",
        "sam3d_depth_to_height_ratio",
        "sam3d_width_to_depth_ratio",
        "sam3d_upper_body_vertex_ratio",
        "sam3d_lower_body_vertex_ratio",
        "sam3d_left_right_vertex_balance",
        "sam3d_front_back_vertex_balance",
        "sam3d_person_count",
        "sam3d_keypoint_shoulder_width_px",
        "sam3d_keypoint_hip_width_px",
        "sam3d_keypoint_shoulder_to_hip_ratio",
        "sam3d_keypoint_torso_height_px",
    }
    return {key: shape_metrics[key] for key in allowed if key in shape_metrics}


def _fallback_insight(context: dict[str, Any]) -> dict[str, Any]:
    scans = context.get("scans", [])
    latest = scans[-1] if scans else {}
    metrics = latest.get("measurements") or {}
    evidence = []
    posture = []
    actions = []
    for key, label in (
            ("pose_quality", "Pose quality"),
            ("shoulder_tilt_degrees", "Shoulder tilt"),
            ("hip_tilt_degrees", "Hip tilt"),
            ("torso_lean_degrees", "Torso lean"),
            ("left_knee_angle_degrees", "Left knee angle"),
            ("right_knee_angle_degrees", "Right knee angle"),
    ):
        if metrics.get(key) is not None:
            evidence.append(f"{label}: {metrics[key]}")
    if not evidence:
        evidence.append("No reliable pose metrics were available yet.")
    quality = metrics.get("pose_quality")
    shape_metrics = metrics.get("shape_metrics") or {}
    shoulder_tilt = metrics.get("shoulder_tilt_degrees")
    hip_tilt = metrics.get("hip_tilt_degrees")
    torso_lean = metrics.get("torso_lean_degrees")
    if quality is not None:
        if float(quality) >= 0.75:
            posture.append(
                "The latest scan has usable pose quality, so posture metrics can be reviewed as coaching cues.")
        else:
            posture.append(
                "The latest scan quality is low, so improve the photo setup before trusting detailed comparisons.")
    if shoulder_tilt is not None:
        posture.append(f"Shoulder tilt is {float(shoulder_tilt):.1f} degrees in the latest scan.")
    if hip_tilt is not None:
        posture.append(f"Hip tilt is {float(hip_tilt):.1f} degrees in the latest scan.")
    if torso_lean is not None:
        posture.append(f"Torso lean is {float(torso_lean):.1f} degrees in the latest scan.")
    if shape_metrics:
        for key, label in (
                ("sam3d_height_proxy", "SAM mesh height proxy"),
                ("sam3d_width_proxy", "SAM mesh width proxy"),
                ("sam3d_depth_proxy", "SAM mesh depth proxy"),
                ("sam3d_width_to_height_ratio", "SAM width-to-height ratio"),
                ("sam3d_depth_to_height_ratio", "SAM depth-to-height ratio"),
                ("sam3d_left_right_vertex_balance", "SAM left-right mesh balance"),
        ):
            if shape_metrics.get(key) is not None:
                evidence.append(f"{label}: {shape_metrics[key]}")
        posture.append(
            "SAM 3D mesh metrics are available for shape/proportion tracking; compare them only against matching views and similar photo setup."
        )
    if shoulder_tilt is not None and abs(float(shoulder_tilt)) > 6:
        actions.append(
            "Add simple posture awareness and single-arm loaded carries; re-check shoulder tilt in the next matching view.")
    if hip_tilt is not None and abs(float(hip_tilt)) > 6:
        actions.append(
            "Keep hip stability work consistent: side planks, single-leg bridges, and controlled step-downs.")
    if not actions:
        actions.append(
            "Keep the scan protocol consistent and use the next matching view to confirm whether these cues are stable.")
    summary = (
        f"{len(scans)} scan(s) are stored. Latest scan view is {latest.get('view', 'unknown')} on "
        f"{latest.get('scan_date', 'unknown date')}. The current interpretation is based on stored pose metrics because "
        "the LLM did not provide a complete structured JSON response."
    )

    return {
        "summary": summary,
        "visual_changes": ["Use consistent front, side, and back photos before making trend judgments."],
        "posture_and_symmetry": posture
                                or ["Review shoulder, hip, torso, and knee metrics once multiple comparable scans exist."],
        "running_form_implications": [
            "Treat single-photo posture metrics as a cue for observation, not proof of a running-form problem."
        ],
        "progress_trends": [f"{len(scans)} scan(s) are available for comparison."],
        "risks_or_unknowns": [
            "Photo angle, clothing, lighting, fatigue, and camera height can change the interpretation."
        ],
        "coaching_actions": actions,
        "next_photo_protocol": [
            "Use the same location, camera height, distance, lighting, clothing, and relaxed standing posture."
        ],
        "evidence": evidence,
        "limitations": ["This is not medical diagnosis and does not estimate body fat or injury status."],
        "confidence": 35.0 if scans else 0.0,
    }


class BodyScanInsightService:
    """Generate and persist LLM analysis for body scan history."""

    def __init__(self, llm_client=None) -> None:
        self.settings = get_settings()
        self.llm_client = llm_client or get_llm_client(
            provider=self.settings.llm_provider,
            openai_api_key=self.settings.openai_api_key,
            openai_model=self.settings.openai_model,
            ollama_base_url=self.settings.ollama_base_url,
            ollama_model=self.settings.ollama_model,
        )

    def generate(self, session, user, athlete_question: str = "") -> BodyScanInsightResult:
        scans_df = self._body_scans_dataframe(session, user.id)
        prior_insights_df = self._body_scan_insights_dataframe(session, user.id)
        context = self._build_context(user, scans_df, prior_insights_df, athlete_question)
        payload = _fallback_insight(context)

        if scans_df.empty:
            payload["summary"] = "No body scans are available yet. Upload at least one scan before asking for analysis."
        else:
            system_prompt, user_prompt = self._build_prompt(context)
            result = generate_structured_payload(
                llm_client=self.llm_client,
                system_prompt=system_prompt,
                user_prompt=user_prompt,
                response_schema=BodyScanInsightSchema,
                unavailable_message="Body scan insight model unavailable",
            )
            if result.warning:
                payload["llm_warning"] = result.warning
            else:
                llm_payload = result.payload
                normalized = _normalize_insight_payload(result.payload)
                if normalized.get("summary"):
                    payload.update(normalized)
                    if "explanation" in llm_payload and not llm_payload.get("visual_changes"):
                        payload["llm_warning"] = "LLM returned prose instead of the requested full JSON schema."
                else:
                    payload[
                        "llm_warning"] = f"LLM returned an unusable payload: {json.dumps(llm_payload, default=str)[:500]}"

        payload["athlete_name"] = user.name
        payload["scan_count"] = len(context["scans"])
        payload["prior_insight_count"] = len(context["prior_insights"])
        payload["athlete_question"] = athlete_question.strip()

        scan_ids = [int(scan["id"]) for scan in context["scans"]]
        insight_date = self._latest_scan_date(context) or date.today()
        stored = self._store_body_scan_insight(
            session=session,
            user_id=user.id,
            insight_date=insight_date,
            scan_ids=scan_ids,
            summary=str(payload.get("summary", "")),
            payload_json=json.dumps(payload, default=str),
            prompt_context_json=json.dumps(context, default=str),
        )
        payload["body_scan_insight_id"] = stored
        return BodyScanInsightResult(insight_id=stored, payload=payload)

    def _body_scans_dataframe(self, session, user_id: int) -> pd.DataFrame:
        return repository.body_scans_dataframe(session, user_id)

    def _body_scan_insights_dataframe(self, session, user_id: int) -> pd.DataFrame:
        return repository.body_scan_insights_dataframe(session, user_id)

    def _build_context(
            self,
            user,
            scans_df: pd.DataFrame,
            prior_insights_df: pd.DataFrame,
            athlete_question: str,
    ) -> dict[str, Any]:
        scans = []
        for row in scans_df.sort_values(["scan_date", "created_at"]).tail(12).itertuples():
            measurements = _safe_json_loads(getattr(row, "measurements_json", None)) or {}
            compact_measurements = _compact_measurements(measurements)
            keypoints = _safe_json_loads(getattr(row, "keypoints_json", None)) or {}
            scans.append(
                {
                    "id": int(row.id),
                    "scan_date": str(pd.Timestamp(row.scan_date).date()),
                    "view": row.view,
                    "status": row.status,
                    "pose_quality": row.pose_quality if pd.notna(row.pose_quality) else None,
                    "processor_name": row.processor_name,
                    "notes": row.notes,
                    "measurements": compact_measurements,
                    "shape_metrics": compact_measurements.get("shape_metrics") or {},
                    "landmark_count": len(keypoints.get("landmarks", [])) if isinstance(keypoints, dict) else None,
                }
            )

        prior_insights = []
        for row in prior_insights_df.head(5).itertuples():
            payload = _safe_json_loads(row.payload_json) or {}
            prior_insights.append(
                {
                    "insight_date": str(pd.Timestamp(row.insight_date).date()),
                    "summary": payload.get("summary", row.summary),
                    "coaching_actions": payload.get("coaching_actions", []),
                    "progress_trends": payload.get("progress_trends", []),
                    "limitations": payload.get("limitations", []),
                }
            )

        return {
            "athlete": {
                "name": user.name,
                "age": user.age,
                "gender": user.gender,
                "height_cm": user.height,
                "weight_kg": user.weight,
                "injury_notes": user.injury_notes,
            },
            "athlete_question": athlete_question.strip(),
            "scans": scans,
            "prior_insights": prior_insights,
        }

    def _build_prompt(self, context: dict[str, Any]) -> tuple[str, str]:
        system_prompt = (
            "You are a careful running coach and movement-analysis assistant. Interpret body progress scan metadata, "
            "MediaPipe pose metrics, SAM 3D mesh shape/proportion metrics, user notes, and previous scan insights. "
            "Be specific, practical, and conservative. "
            "Do not diagnose medical conditions, do not estimate body fat percentage, and do not claim certainty from "
            "photos. Explain what the scan data suggests, what is uncertain, and what the athlete should do next. "
            "Return only one valid JSON object. Do not use markdown. Do not add prose outside the JSON object. "
            "The JSON object must contain exactly these keys: summary string; visual_changes array of strings; "
            "posture_and_symmetry array of strings; running_form_implications array of strings; progress_trends "
            "array of strings; risks_or_unknowns array of strings; coaching_actions array of strings; "
            "next_photo_protocol array of strings; evidence array of strings; limitations array of strings; "
            "confidence number 0-100."
        )
        user_prompt = (
            """
Give a detailed, practical, and conservative interpretation of what the body scan suggests about body shape, posture, symmetry, movement tendencies, and progress trends. Focus on coaching value, not diagnosis.

Hard rules:
- Do not diagnose medical conditions.
- Do not estimate body fat percentage or body fat mass.
- Do not claim certainty from photos or scans.
- Do not invent measurements that are not present.
- Do not use generic fitness advice unless it is clearly tied to the scan data.
- Compare only like-for-like views and say clearly when a comparison is weak.
- Treat SAM 3D metrics as relative tracking proxies, not clinical body-composition measurements.
- If landmarks are missing, pose quality is unknown, or the scan is low quality, say so explicitly.
- If prior_insights exist, use them to track whether the story is improving, stable, or worsening over time.
- Be specific and reference exact scan dates, views, metric names, and values whenever possible.
- If a metric is not directly interpretable, explain what it can still be used for as a trend marker.
- Focus on what the athlete should do next.

Output rules:
- Return only one valid JSON object.
- Do not use markdown.
- Do not add any prose outside the JSON object.
- Use exactly the keys listed below.
- All array items must be concise but informative.
- confidence must be an integer from 0 to 100.

Required JSON shape:
{
  "summary": "One detailed paragraph describing the main body-scan story in plain language.",
  "visual_changes": [
    "Describe visible changes across scans, or say none if this is the first scan.",
    "Interpret supported body shape and proportion metrics such as width, depth, and silhouette-related markers."
  ],
  "posture_and_symmetry": [
    "Interpret shoulder/hip balance, left-right balance, front-back balance, and any posture cues.",
    "State clearly if the evidence is weak because only one view or no landmarks are available."
  ],
  "running_form_implications": [
    "Explain what the scan may suggest for running mechanics, stability, or load distribution.",
    "Separate strong signals from weak speculation."
  ],
  "progress_trends": [
    "Track whether shape metrics are improving, stable, or worsening over time.",
    "Mention exact metrics and whether changes are likely meaningful or too small to interpret."
  ],
  "risks_or_unknowns": [
    "List uncertainties, missing data, or reasons not to over-interpret the scan.",
    "Mention any setup issues that would reduce reliability."
  ],
  "coaching_actions": [
    "Give practical next steps for strength, mobility, recovery, or running form.",
    "Make the actions specific and tied to the scan findings."
  ],
  "next_photo_protocol": [
    "Explain how the next scan should be taken to improve comparability.",
    "Include view, lighting, pose, clothing, camera distance, and timing suggestions."
  ],
  "evidence": [
    "Quote or summarize the exact metric(s) that support the main interpretation.",
    "Use scan dates and view names."
  ],
  "limitations": [
    "State what cannot be concluded from this scan data alone.",
    "State what additional data would improve confidence."
  ],
  "confidence": 0
}

Interpretation guidance:
- Use anthropometric language such as width-to-height ratio, depth-to-height ratio, shoulder-to-hip ratio, left-right balance, and front-back balance.
- If shoulder-to-hip ratio is high, discuss broad upper-body / narrower lower-body proportions as a possibility, but avoid overstating it.
- If left-right balance is near zero, describe better symmetry; if farther from zero, describe possible asymmetry.
- If front-back balance is far from neutral, mention whether the silhouette appears more front-dominant or back-dominant in the reconstruction.
- If only one scan exists, frame the response as a baseline and say no trend can yet be confirmed.
- If shape metrics suggest a more upper-body-dominant build, translate that into running implications such as trunk stability, arm carriage, or load distribution, but keep it cautious.

Style:
- Be specific, practical, and conservative.
- Prefer concrete observations over vague praise.
- Use short, information-dense sentences.
- Avoid motivational fluff.
- Avoid repeating the same idea across sections.
- The response should read like an expert scan review for an athlete.

Now analyze this athlete’s scan history:
            """

            f"  <body_scan_context>{json.dumps(context, default=str, ensure_ascii=True)}</body_scan_context>"
        )
        return system_prompt, user_prompt

    def _latest_scan_date(self, context: dict[str, Any]) -> date | None:
        scans = context.get("scans", [])
        if not scans:
            return None
        return pd.Timestamp(scans[-1]["scan_date"]).date()

    def _store_body_scan_insight(
            self,
            *,
            session,
            user_id: int,
            insight_date: date,
            scan_ids: list[int],
            summary: str,
            payload_json: str,
            prompt_context_json: str,
    ) -> int:
        stored = repository.store_body_scan_insight(
            session=session,
            user_id=user_id,
            insight_date=insight_date,
            scan_ids=scan_ids,
            summary=summary,
            payload_json=payload_json,
            prompt_context_json=prompt_context_json,
            model_provider=self.settings.llm_provider,
            model_name=self.settings.openai_model if self.settings.llm_provider == "openai" else self.settings.ollama_model,
        )
        return int(stored.id)

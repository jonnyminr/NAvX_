from __future__ import annotations

from typing import Any


def _num(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return number


def _available_routes(context: dict[str, Any]) -> list[dict[str, Any]]:
    result = context.get("route_result") or {}
    return [
        route
        for route in (result.get("routes") or [])
        if isinstance(route, dict) and route.get("available") is not False
    ]


def _value_list(routes: list[dict[str, Any]], field: str) -> list[tuple[dict[str, Any], float]]:
    out: list[tuple[dict[str, Any], float]] = []
    for route in routes:
        value = _num(route.get(field))
        if value is not None:
            out.append((route, value))
    return out


def _sea_ice_max(route: dict[str, Any]) -> float | None:
    sea = route.get("sea_ice") or {}
    return _num(sea.get("maximum_concentration_percent"))


def _route_row(route: dict[str, Any]) -> dict[str, Any]:
    return {
        "profile": route.get("profile"),
        "distance_km": _num(route.get("distance_km")),
        "eta_hours": _num(route.get("eta_hours")),
        "risk": route.get("risk"),
        "risk_score": _num(route.get("risk_score")),
        "minimum_cpa_km": _num(route.get("minimum_cpa_km")),
        "min_clearance_km": _num(route.get("min_clearance_km")),
        "hazard_count": len(route.get("hazards") or []),
        "sea_ice_max_percent": _sea_ice_max(route),
        "closest_iceberg_id": route.get("closest_iceberg_id"),
        "tca_utc": route.get("tca_utc"),
    }


def build_decision_report(context: dict[str, Any], model_status: dict[str, Any]) -> dict[str, Any]:
    """Build a deterministic, evidence-grounded NAV-X decision report.

    This is intentionally structured decision support and does not use a generative LLM.
    It transforms already-calculated route/model evidence into a structured
    recommendation and explainability report. Missing measurements remain
    unavailable rather than being inferred.
    """
    result = context.get("route_result") or {}
    routes = _available_routes(context)
    iceberg = model_status.get("iceberg_drift") or {}
    ais = model_status.get("ais_anomaly") or {}

    base = {
        "mode": "STRUCTURED_EXPLAINABLE_DECISION_SUPPORT",
        "generative_llm": False,
        "autonomous_navigation": False,
        "model_contribution": {
            "iceberg_drift_ml": {
                "status": iceberg.get("status", "UNKNOWN"),
                "runtime_enabled": bool(iceberg.get("runtime_enabled")),
                "model_version": iceberg.get("model_version"),
                "training_samples": iceberg.get("training_samples", 0),
            },
            "ais_anomaly_ml": {
                "status": ais.get("status", "UNKNOWN"),
                "trained": bool(ais.get("trained")),
                "model_version": ais.get("model_version"),
                "training_samples": ais.get("training_samples", 0),
            },
            "risk_engine": "Explainable rule/metric-based route risk engine; no supervised risk-ML accuracy is claimed.",
        },
        "route_matrix": [_route_row(route) for route in routes],
        "warning": "Decision support only. Not a certified autonomous-navigation command.",
    }

    if not routes:
        return {
            **base,
            "readiness": "NO_ROUTE_EVIDENCE",
            "recommendation": None,
            "summary": "Generate a verified voyage before NAV-X issues a route decision report.",
            "reasons": ["No calculated route alternatives are available in the supplied NAV-X context."],
            "tradeoffs": [],
            "evidence_completeness": 0,
        }

    recommended_profile = str(result.get("recommended_profile") or "").upper().strip()
    recommended = next(
        (route for route in routes if str(route.get("profile") or "").upper() == recommended_profile),
        None,
    )

    if recommended is None:
        return {
            **base,
            "readiness": "PARTIAL_EVIDENCE",
            "recommendation": None,
            "summary": "Route alternatives exist, but the backend did not issue a verified risk-based recommendation.",
            "reasons": [
                "NAV-X will not select a preferred route when the route engine reports insufficient verified evidence."
            ],
            "tradeoffs": [],
            "evidence_completeness": 40,
        }

    rec_row = _route_row(recommended)
    reasons: list[str] = []
    tradeoffs: list[str] = []

    risk_values = _value_list(routes, "risk_score")
    if risk_values and rec_row["risk_score"] is not None:
        minimum_risk = min(value for _, value in risk_values)
        if abs(rec_row["risk_score"] - minimum_risk) < 1e-9:
            reasons.append(
                f"Lowest available backend risk score: {rec_row['risk_score']:.1f}/100 among the calculated routes."
            )

    clearance_values = _value_list(routes, "min_clearance_km")
    if clearance_values and rec_row["min_clearance_km"] is not None:
        maximum_clearance = max(value for _, value in clearance_values)
        if abs(rec_row["min_clearance_km"] - maximum_clearance) < 1e-9:
            reasons.append(
                f"Largest calculated minimum iceberg clearance: {rec_row['min_clearance_km']:.1f} km."
            )

    cpa_values = _value_list(routes, "minimum_cpa_km")
    if cpa_values and rec_row["minimum_cpa_km"] is not None:
        maximum_cpa = max(value for _, value in cpa_values)
        if abs(rec_row["minimum_cpa_km"] - maximum_cpa) < 1e-9:
            reasons.append(
                f"Largest reported minimum CPA among available routes: {rec_row['minimum_cpa_km']:.1f} km."
            )

    sea_values = [(route, _sea_ice_max(route)) for route in routes]
    sea_values = [(route, value) for route, value in sea_values if value is not None]
    if sea_values and rec_row["sea_ice_max_percent"] is not None:
        minimum_sea = min(value for _, value in sea_values)
        if abs(rec_row["sea_ice_max_percent"] - minimum_sea) < 1e-9:
            reasons.append(
                f"Lowest maximum sampled sea-ice concentration: {rec_row['sea_ice_max_percent']:.1f}%."
            )

    hazard_counts = [len(route.get("hazards") or []) for route in routes]
    if hazard_counts and rec_row["hazard_count"] == min(hazard_counts):
        reasons.append(
            f"Fewest time-matched iceberg hazard encounters: {rec_row['hazard_count']}."
        )

    eta_values = _value_list(routes, "eta_hours")
    if eta_values and rec_row["eta_hours"] is not None:
        fastest = min(value for _, value in eta_values)
        delta = rec_row["eta_hours"] - fastest
        if delta > 0.01:
            tradeoffs.append(f"ETA trade-off versus the fastest available route: +{delta:.2f} h.")
        else:
            tradeoffs.append("No ETA penalty versus the fastest available route.")

    distance_values = _value_list(routes, "distance_km")
    if distance_values and rec_row["distance_km"] is not None:
        shortest = min(value for _, value in distance_values)
        delta = rec_row["distance_km"] - shortest
        if delta > 0.1:
            tradeoffs.append(f"Distance trade-off versus the shortest available route: +{delta:.1f} km.")

    if not reasons:
        reasons.append(
            "The backend selected this profile from the current verified route-analysis result; no additional comparative metric is complete enough to make a stronger claim."
        )

    evidence_fields = [
        rec_row["distance_km"],
        rec_row["eta_hours"],
        rec_row["risk_score"],
        rec_row["minimum_cpa_km"],
        rec_row["min_clearance_km"],
        rec_row["sea_ice_max_percent"],
    ]
    completeness = round(100 * sum(value is not None for value in evidence_fields) / len(evidence_fields))
    readiness = "READY" if completeness >= 67 else "PARTIAL_EVIDENCE"

    return {
        **base,
        "readiness": readiness,
        "recommendation": rec_row,
        "summary": f"NAV-X recommends {recommended.get('profile')} using the current verified route result and ML-assisted iceberg forecast inputs.",
        "reasons": reasons,
        "tradeoffs": tradeoffs,
        "evidence_completeness": completeness,
        "backend_explanation": result.get("explanation"),
    }

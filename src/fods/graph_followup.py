"""Deterministic routing and evidence formatting for optional graph follow-ups."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from fods.knowledge_graph import normalize, query

RELATIONSHIP_LABELS = {
    "HAS_CONCEPT": "discusses concept",
    "USES_METHOD": "uses method",
    "REPORTS_FINDING": "reports finding",
    "STATES_LIMITATION": "states limitation",
}


@dataclass(frozen=True)
class FollowupRoute:
    kind: str
    value: str


def _clean_value(value: str) -> str:
    return " ".join(value.strip().rstrip("?!. ").split())


def route_question(question: str) -> FollowupRoute | None:
    """Map supported natural-language forms to existing bounded graph queries."""
    text = " ".join(question.split())
    patterns = (
        ("METHOD", r"which papers (?:use|employ|apply|adopt) (.+)"),
        ("CONCEPT", r"which papers (?:discuss|mention|cover|address|study) (.+)"),
        ("FINDING_FOR_TOPIC", r"what findings (?:are |were )?reported (?:for|about|on) (.+)"),
        (
            "LIMITATION_FOR_TOPIC",
            r"what limitations (?:are |were )?(?:mentioned|reported|stated) "
            r"(?:for|about|in|on) (.+)",
        ),
        ("CITED_BY", r"which papers cite (.+)"),
    )
    for kind, pattern in patterns:
        match = re.fullmatch(pattern, text, flags=re.IGNORECASE)
        if match:
            value = _clean_value(match.group(1))
            if kind == "CITED_BY" and value.casefold() in {
                "this paper",
                "that paper",
                "it",
                "this one",
            }:
                return None
            return FollowupRoute(kind, value) if value else None

    shared = re.fullmatch(
        r"(?:what|which) concepts are shared between (.+?) and (.+)",
        text,
        flags=re.IGNORECASE,
    )
    if shared:
        paper_a, paper_b = (_clean_value(value) for value in shared.groups())
        if paper_a and paper_b:
            return FollowupRoute("SHARED", f"{paper_a}|{paper_b}")
    return None


def run_followup(
    snapshot: dict[str, Any],
    route: FollowupRoute,
    *,
    max_depth: int = 3,
    max_nodes: int = 200,
    max_edges: int = 500,
    max_evidence: int = 50,
) -> dict[str, Any]:
    """Run the existing graph query and keep only paper-linked evidence records."""
    query_kind = (
        "CONCEPT" if route.kind in {"FINDING_FOR_TOPIC", "LIMITATION_FOR_TOPIC"} else route.kind
    )
    result = query(
        snapshot,
        kind=query_kind,
        value=route.value,
        max_depth=max_depth,
        max_nodes=max_nodes,
        max_edges=max_edges,
        max_evidence=max_evidence,
    )
    nodes = {node["id"]: node for node in result["nodes"]}
    relation_by_route = {
        "CONCEPT": "HAS_CONCEPT",
        "METHOD": "USES_METHOD",
        "FINDING_FOR_TOPIC": "REPORTS_FINDING",
        "LIMITATION_FOR_TOPIC": "STATES_LIMITATION",
        "SHARED": "HAS_CONCEPT",
    }
    expected_relation = relation_by_route.get(route.kind)
    expected_entity = normalize(route.value) if route.kind in {"CONCEPT", "METHOD"} else None
    evidence_edges = [edge for edge in result["edges"] if edge.get("type") == "HAS_SOURCE_EVIDENCE"]
    evidence_records = []
    for edge in result["edges"]:
        relationship = edge.get("type")
        if relationship not in RELATIONSHIP_LABELS:
            continue
        if expected_relation and relationship != expected_relation:
            continue
        paper_id = edge.get("source")
        entity_id = edge.get("target")
        paper = nodes.get(paper_id, {})
        entity = nodes.get(entity_id, {})
        if paper.get("type") != "PAPER" or not entity.get("type"):
            continue
        if expected_entity and entity.get("normalized") != expected_entity:
            continue
        for evidence_edge in evidence_edges:
            evidence = nodes.get(evidence_edge.get("target"), {})
            if (
                evidence_edge.get("source") != entity_id
                or evidence_edge.get("paper_id") != paper_id
                or evidence.get("type") != "EVIDENCE_SPAN"
                or evidence.get("paper_id") != paper_id
                or not evidence.get("segment_ids")
                or not evidence.get("label")
            ):
                continue
            evidence_records.append(
                {
                    "paper_id": paper_id,
                    "paper_title": paper.get("label", paper_id),
                    "relationship": RELATIONSHIP_LABELS[relationship],
                    "item": entity.get("label", ""),
                    "segment_ids": evidence["segment_ids"],
                    "excerpt": evidence["label"],
                }
            )
    # Stable ordering also makes the text CLI and fixture runs reproducible.
    evidence_records.sort(
        key=lambda record: (
            record["paper_id"],
            record["relationship"],
            record["item"].casefold(),
            tuple(record["segment_ids"]),
        )
    )

    bibliographic = []
    if route.kind == "CITED_BY":
        for edge in result["edges"]:
            if edge.get("type") != "CITES":
                continue
            citing = nodes.get(edge.get("source"), {})
            cited = nodes.get(edge.get("target"), {})
            if citing.get("type") == "PAPER" and cited.get("type") == "PAPER":
                bibliographic.append(
                    {
                        "citing_paper_id": citing["id"],
                        "citing_paper_title": citing.get("label", citing["id"]),
                        "cited_paper_id": cited["id"],
                        "cited_paper_title": cited.get("label", cited["id"]),
                        "basis": "stored bibliographic reference",
                    }
                )
    bibliographic.sort(key=lambda record: (record["citing_paper_id"], record["cited_paper_id"]))

    if route.kind == "CITED_BY":
        summary = (
            f"Found {len(bibliographic)} stored bibliographic citation(s)."
            if bibliographic
            else "No citing papers were found in this graph snapshot."
        )
    elif route.kind == "SHARED":
        summary = (
            f"Found {len(evidence_records)} evidence-backed record(s) for shared concepts. "
            "Shared labels indicate vocabulary overlap, not agreement or support."
            if evidence_records
            else "No shared evidence-backed concepts were found in this graph snapshot."
        )
    else:
        summary = (
            f"Found {len(evidence_records)} evidence-backed graph record(s)."
            if evidence_records
            else "No matching evidence-backed records were found in this graph snapshot."
        )

    return {
        "route": {"kind": route.kind, "value": route.value},
        "summary": summary,
        "evidence_records": evidence_records,
        "bibliographic_records": bibliographic,
        "limits": {
            "max_depth": max_depth,
            "max_nodes": max_nodes,
            "max_edges": max_edges,
            "max_evidence": max_evidence,
        },
    }

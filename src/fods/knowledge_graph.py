"""Deterministic, optional knowledge graph indexing for saved FODS enrichments.

This module is deliberately not imported by the research runtime. Indexing runs
only through explicit ``fods graph`` commands and publishes one atomic JSON file.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import unicodedata
from collections import Counter, deque
from contextlib import contextmanager
from pathlib import Path
from typing import Any

from fods.tools import PaperEnrichment, segment_text
from rla.models import Paper

SCHEMA_VERSION = 2  # v2 guarantees every extracted entity edge has valid evidence.
CATEGORIES = {
    "concepts": ("CONCEPT", "HAS_CONCEPT"),
    "methods": ("METHOD", "USES_METHOD"),
    "findings": ("FINDING", "REPORTS_FINDING"),
    "limitations": ("LIMITATION", "STATES_LIMITATION"),
}


def normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value).casefold().strip()
    value = re.sub(r"\s+", " ", value)
    # Preserve letters/digits and meaningful internal punctuation; normalize
    # typographic variants and punctuation runs conservatively.
    value = value.replace("’", "'").replace("–", "-").replace("—", "-")
    return re.sub(r"\s*([,;:])\s*", r"\1 ", value).strip(" .;,")


def _id(*parts: str) -> str:
    raw = "\x1f".join(parts).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()[:28]


def _read_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


@contextmanager
def topic_lock(lock_path: Path):
    """Cross-process exclusive lock for all mutations of one topic snapshot."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        handle = lock_path.open("a+b")
    except OSError as exc:
        raise OSError(f"could not open graph mutation lock {lock_path}: {exc}") from exc
    acquired = False
    try:
        if os.name == "nt":
            import msvcrt

            # Never read the byte here: another process holding the byte-range
            # lock can make even a read fail with PermissionError on Windows.
            # Appending the sentinel is safe if two first-time openers race;
            # both still lock the stable first byte below.
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"0")
                handle.flush()
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        acquired = True
    except OSError as exc:
        handle.close()
        raise OSError(f"could not acquire graph mutation lock {lock_path}: {exc}") from exc
    try:
        yield
    finally:
        try:
            if acquired:
                if os.name == "nt":
                    import msvcrt

                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    import fcntl

                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def classify_inputs(
    data_dir: Path, topic: str, context: dict[str, Any]
) -> tuple[dict[str, dict], dict[str, dict], dict[str, Any]]:
    """Discover raw candidates, classify them, and select only unambiguous inputs."""
    paper_list = [p for p in context.get("papers", []) if p.get("id")]
    papers = {str(p["id"]): p for p in paper_list}
    duplicate_ids = {
        str(p["id"])
        for p in paper_list
        if sum(str(x.get("id")) == str(p["id"]) for x in paper_list) > 1
    }
    candidates: dict[str, list[tuple[str, dict, dict]]] = {pid: [] for pid in papers}
    raw_artifacts = 0
    malformed_artifacts = 0
    for path in sorted((data_dir / "fods" / "enrichments").glob("*.json")):
        try:
            artifact = _read_json(path)
        except (OSError, json.JSONDecodeError):
            malformed_artifacts += 1
            continue
        if (
            not isinstance(artifact, dict)
            or str(artifact.get("topic", "")).casefold() != topic.casefold()
        ):
            continue
        raw_artifacts += 1
        for item in artifact.get("paper_enrichments", []):
            if isinstance(item, dict) and str(item.get("paper_id", "")) in candidates:
                candidates[str(item["paper_id"])].append((str(path), artifact, item))

    selected: dict[str, dict] = {}
    per_paper = {}
    totals = Counter()
    for pid, paper in papers.items():
        records = candidates[pid]
        expected = str(paper.get("content_hash") or "")
        hash_match: bool | None = None
        artifact_refs = [
            {
                "path": path,
                "fingerprint": hashlib.sha256(
                    json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
                ).hexdigest(),
            }
            for path, _, item in records
        ]
        if pid in duplicate_ids:
            status, reason = "DUPLICATE_OR_AMBIGUOUS", "duplicate paper ID in context"
        elif not expected or expected != Paper.model_validate(paper).computed_hash():
            hash_match = False
            status, reason = "HASH_MISMATCH", "context paper content hash is missing or invalid"
        elif not records:
            status, reason = "MISSING_ENRICHMENT", "no relevant artifact record"
        else:
            matches = [
                (path, artifact, item)
                for path, artifact, item in records
                if item.get("paper_hash") == expected
            ]
            if not matches:
                hash_match = False
                status, reason = (
                    "HASH_MISMATCH",
                    "artifact exists but none match context paper hash",
                )
            else:
                hash_match = True
                parsed = []
                invalid_schema = []
                for path, artifact, item in matches:
                    try:
                        parsed.append((path, artifact, item, PaperEnrichment.model_validate(item)))
                    except Exception as exc:
                        invalid_schema.append(type(exc).__name__)
                if not parsed:
                    status, reason = "INVALID_SCHEMA", ",".join(sorted(set(invalid_schema)))
                else:
                    fingerprints = {
                        hashlib.sha256(
                            json.dumps(x[2], sort_keys=True, ensure_ascii=False).encode()
                        ).hexdigest()
                        for x in parsed
                    }
                    if len(fingerprints) > 1:
                        status, reason = (
                            "DUPLICATE_OR_AMBIGUOUS",
                            "conflicting matching enrichment records",
                        )
                    else:
                        path, artifact, item, parsed_item = sorted(parsed, key=lambda x: x[0])[0]
                        facts = [
                            (category, fact)
                            for category in CATEGORIES
                            for fact in getattr(parsed_item, category)
                        ]
                        validity = [_valid_evidence(paper, fact) for _, fact in facts]
                        valid_count = sum(value["valid"] for value in validity)
                        invalid_count = len(validity) - valid_count
                        if invalid_count:
                            status, reason = (
                                ("PARTIALLY_ELIGIBLE", "some item evidence invalid")
                                if valid_count
                                else ("INVALID_EVIDENCE", "no items have valid evidence")
                            )
                        else:
                            status, reason = "ELIGIBLE", "matching schema and evidence"
                        item_fingerprint = hashlib.sha256(
                            json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
                        ).hexdigest()
                        if valid_count:
                            selected[pid] = {
                                **item,
                                "_artifact_fingerprint": item_fingerprint,
                                "_artifact_path": path,
                            }
                        per_paper[pid] = {
                            "status": status,
                            "reason": reason,
                            "hash_match": hash_match,
                            "artifact_count": len(records),
                            "artifact_refs": artifact_refs,
                            "artifact_path": path,
                            "artifact_fingerprint": item_fingerprint,
                            "valid_items": valid_count,
                            "invalid_items": invalid_count,
                        }
                        totals[status] += 1
                        totals["valid_items"] += valid_count
                        totals["invalid_items"] += invalid_count
                        continue
        per_paper[pid] = {
            "status": status,
            "reason": reason,
            "hash_match": hash_match,
            "artifact_count": len(records),
            "artifact_refs": artifact_refs,
        }
        totals[status] += 1
    for pid in duplicate_ids:
        duplicates_for_id = sum(str(p.get("id")) == pid for p in paper_list)
        totals["DUPLICATE_OR_AMBIGUOUS"] += duplicates_for_id - 1
    report = {
        "context_papers": len(paper_list),
        "raw_topic_artifacts": raw_artifacts,
        "malformed_artifacts_unattributable": malformed_artifacts,
        "duplicate_context_ids": sorted(duplicate_ids),
        "totals": dict(totals),
        "papers": per_paper,
    }
    return papers, selected, report


def load_inputs(data_dir: Path, topic: str, context: dict[str, Any]):
    papers, enrichments, _ = classify_inputs(data_dir, topic, context)
    return papers, enrichments


def eligibility_manifest(
    papers: dict[str, dict], enrichments: dict[str, dict]
) -> dict[str, dict[str, str]]:
    """Compatibility wrapper; use classify_inputs for authoritative raw scans."""
    result: dict[str, dict[str, str]] = {}
    for paper_id, paper in papers.items():
        expected = str(paper.get("content_hash") or "")
        if not expected:
            result[paper_id] = {"status": "excluded", "reason": "missing content hash"}
            continue
        item = enrichments.get(paper_id)
        if not item:
            result[paper_id] = {"status": "excluded", "reason": "missing enrichment"}
            continue
        if item.get("paper_hash") != expected:
            result[paper_id] = {"status": "excluded", "reason": "content hash mismatch"}
            continue
        try:
            parsed = PaperEnrichment.model_validate(item)
        except Exception as exc:
            result[paper_id] = {
                "status": "excluded",
                "reason": f"invalid enrichment: {type(exc).__name__}",
            }
            continue
        item_results = [
            _valid_evidence(paper, fact)
            for category in CATEGORIES
            for fact in getattr(parsed, category)
        ]
        valid_count = sum(item["valid"] for item in item_results)
        invalid_count = len(item_results) - valid_count
        result[paper_id] = {
            "status": "eligible" if not invalid_count else "partially_eligible",
            "reason": "all extracted items grounded"
            if not invalid_count
            else "invalid evidence items excluded individually",
            "valid_items": str(valid_count),
            "invalid_items": str(invalid_count),
        }
    return result


def _valid_evidence(paper: dict, fact: dict) -> dict[str, Any]:
    if hasattr(fact, "model_dump"):
        fact = fact.model_dump(mode="python")
    ids = fact.get("evidence_segment_ids")
    if not isinstance(ids, list) or not ids or any(not isinstance(sid, str) for sid in ids):
        return {"valid": False, "reason": "missing_or_malformed_segment_ids"}
    if len(ids) != len(set(ids)):
        return {"valid": False, "reason": "duplicate_segment_ids"}
    abstract = paper.get("abstract", "")
    segments = {s["segment_id"]: s["text"] for s in segment_text(abstract)}
    if not ids or any(sid not in segments for sid in ids):
        return {"valid": False, "reason": "unknown_segment_id"}
    excerpt = " ".join(segments[sid] for sid in ids).strip()
    supplied = " ".join(str(fact.get("evidence_excerpt", "")).split())
    if not supplied:
        return {"valid": False, "reason": "missing_excerpt"}
    if supplied != " ".join(excerpt.split()):
        return {"valid": False, "reason": "excerpt_mismatch"}
    return {"valid": True, "segment_ids": list(ids), "excerpt": excerpt, "reason": "validated"}


def empty_snapshot(topic: str) -> dict[str, Any]:
    return {
        "schema_version": SCHEMA_VERSION,
        "topic": topic,
        "nodes": {},
        "edges": {},
        "indexes": {"lookup": {}, "adjacency": {}},
        "manifest": {},
    }


def _put_edge(
    snapshot: dict,
    source: str,
    target: str,
    kind: str,
    paper_id: str,
    trust: str,
    fingerprint: str = "",
) -> None:
    edge_id = _id("edge", source, target, kind, paper_id)
    snapshot["edges"][edge_id] = {
        "id": edge_id,
        "source": source,
        "target": target,
        "type": kind,
        "paper_id": paper_id,
        "trust": trust,
        "enrichment_fingerprint": fingerprint,
    }


def _remove_paper(snapshot: dict, paper_id: str) -> None:
    snapshot["edges"] = {
        k: e for k, e in snapshot["edges"].items() if e.get("paper_id") != paper_id
    }
    snapshot["nodes"] = {
        k: n
        for k, n in snapshot["nodes"].items()
        if not (n.get("type") == "EVIDENCE_SPAN" and n.get("paper_id") == paper_id)
        and not (n.get("type") == "PAPER" and k == paper_id)
    }


def _index_citations(
    snapshot: dict,
    papers: dict[str, dict],
    eligible: set[str],
    sources: set[str],
    newly_eligible: set[str],
) -> None:
    """Incrementally add exact-ID citations when both records are present."""
    snapshot["edges"] = {
        key: edge
        for key, edge in snapshot["edges"].items()
        if not (
            edge.get("type") == "CITES"
            and (
                edge.get("paper_id") in sources
                or edge.get("paper_id") not in eligible
                or edge.get("target") not in eligible
            )
        )
    }
    citation_sources = set(sources)
    if newly_eligible:
        citation_sources.update(
            paper_id
            for paper_id in eligible - sources
            if set(papers[paper_id].get("references", [])) & newly_eligible
        )
    for paper_id in citation_sources:
        for cited_id in papers[paper_id].get("references", []):
            if cited_id in eligible and cited_id in snapshot["nodes"]:
                _put_edge(snapshot, paper_id, cited_id, "CITES", paper_id, "BIBLIOGRAPHIC")


def _index_paper(
    snapshot: dict, paper_id: str, paper: dict, extraction: dict, fingerprint: str
) -> tuple[float, list[dict[str, str]]]:
    normalization_ms = 0.0
    rejected = []
    snapshot["nodes"][paper_id] = {
        "id": paper_id,
        "type": "PAPER",
        "label": paper.get("title", paper_id),
        "year": paper.get("year"),
        "doi": paper.get("doi", ""),
        "url": paper.get("url", ""),
        "content_hash": paper.get("content_hash", ""),
    }
    for category, (node_type, relation) in CATEGORIES.items():
        for index, fact in enumerate(extraction.get(category, [])):
            term = str(fact.get("text", "")).strip()
            normalization_start = time.perf_counter()
            normalized = normalize(term)
            normalization_ms += (time.perf_counter() - normalization_start) * 1000
            if not normalized:
                continue
            valid = _valid_evidence(paper, fact)
            if not valid["valid"]:
                rejected.append(
                    {
                        "paper_id": paper_id,
                        "category": category,
                        "item_index": str(index),
                        "reason": valid["reason"],
                    }
                )
                continue
            entity_id = f"{node_type.lower()}:{_id(node_type, normalized)}"
            node = snapshot["nodes"].setdefault(
                entity_id,
                {
                    "id": entity_id,
                    "type": node_type,
                    "label": term,
                    "normalized": normalized,
                    "original_terms": [],
                },
            )
            node["original_terms"] = sorted(set([*node.get("original_terms", []), term]))
            _put_edge(snapshot, paper_id, entity_id, relation, paper_id, "STRUCTURAL", fingerprint)
            segment_ids, excerpt = valid["segment_ids"], valid["excerpt"]
            evidence_id = (
                f"evidence:{_id(paper_id, category, str(index), ','.join(segment_ids), excerpt)}"
            )
            snapshot["nodes"][evidence_id] = {
                "id": evidence_id,
                "type": "EVIDENCE_SPAN",
                "label": excerpt,
                "paper_id": paper_id,
                "paper_hash": paper.get("content_hash", ""),
                "segment_ids": segment_ids,
                "category": category,
                "enrichment_fingerprint": fingerprint,
            }
            _put_edge(
                snapshot,
                entity_id,
                evidence_id,
                "HAS_SOURCE_EVIDENCE",
                paper_id,
                "STRUCTURAL",
                fingerprint,
            )
    return round(normalization_ms, 3), rejected


def validate(snapshot: dict) -> None:
    nodes, edges = snapshot["nodes"], snapshot["edges"]
    if len(nodes) != len(set(nodes)) or len(edges) != len(set(edges)):
        raise ValueError("duplicate graph identifiers")
    for edge in edges.values():
        if edge["source"] not in nodes or edge["target"] not in nodes:
            raise ValueError(f"dangling graph edge {edge.get('id', '<unknown>')}")
        if not edge.get("trust"):
            raise ValueError(f"graph edge {edge['id']} has no provenance classification")
    for node in nodes.values():
        if node.get("type") == "EVIDENCE_SPAN":
            paper = nodes.get(node.get("paper_id"))
            if not paper or paper.get("type") != "PAPER" or not node.get("segment_ids"):
                raise ValueError(f"invalid evidence span {node['id']}")
    indexes = snapshot.get("indexes")
    if not isinstance(indexes, dict):
        raise ValueError("graph snapshot is missing its lookup indexes")
    for node_ids in indexes.get("lookup", {}).values():
        if any(node_id not in nodes for node_id in node_ids):
            raise ValueError("graph lookup index contains a missing node")
    for node_id, edge_ids in indexes.get("adjacency", {}).items():
        if node_id not in nodes or any(edge_id not in edges for edge_id in edge_ids):
            raise ValueError("graph adjacency index contains a missing node or edge")


def rebuild_indexes(snapshot: dict) -> None:
    lookup: dict[str, list[str]] = {}
    adjacency: dict[str, list[str]] = {}
    for node_id, node in snapshot["nodes"].items():
        normalized = node.get("normalized")
        if normalized:
            key = f"{node.get('type')}:{normalized}"
            lookup.setdefault(key, []).append(node_id)
        if node.get("type") == "PAPER":
            lookup.setdefault(f"PAPER:{node_id}", []).append(node_id)
    for edge_id, edge in snapshot["edges"].items():
        adjacency.setdefault(edge["source"], []).append(edge_id)
        adjacency.setdefault(edge["target"], []).append(edge_id)
    snapshot["indexes"] = {
        "lookup": {key: sorted(values) for key, values in sorted(lookup.items())},
        "adjacency": {key: sorted(values) for key, values in sorted(adjacency.items())},
    }


def update_snapshot(
    snapshot: dict,
    papers: dict[str, dict],
    enrichments: dict[str, dict],
    *,
    deleted: set[str] | None = None,
) -> dict[str, Any]:
    start = time.perf_counter()
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported graph snapshot schema")
    current = json.loads(json.dumps(snapshot))
    old_records = current.get("manifest", {}).get("paper_hashes", {})
    all_records = {}
    for pid, record in enrichments.items():
        fingerprint_payload = {
            "enrichment": record,
            "references": sorted(papers[pid].get("references", [])),
        }
        all_records[pid] = hashlib.sha256(
            json.dumps(fingerprint_payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
        ).hexdigest()
    removed = set(deleted or ())
    new_records = {pid: digest for pid, digest in all_records.items() if pid not in removed}
    stale = (set(old_records) - set(new_records)) - removed
    if stale:
        raise ValueError(
            "papers disappeared from source corpus; pass --delete-paper explicitly: "
            f"{sorted(stale)}"
        )
    changed = [pid for pid, digest in new_records.items() if old_records.get(pid) != digest]
    indexing_start = time.perf_counter()
    normalization_ms = 0.0
    rejected_evidence = []
    for pid in removed:
        if pid not in old_records:
            raise ValueError(f"cannot delete paper absent from graph: {pid}")
        _remove_paper(current, pid)
    for pid in changed:
        _remove_paper(current, pid)
        item_normalization_ms, item_rejections = _index_paper(
            current, pid, papers[pid], enrichments[pid], new_records[pid]
        )
        normalization_ms += item_normalization_ms
        rejected_evidence.extend(item_rejections)
    newly_eligible = {pid for pid in changed if pid not in old_records}
    _index_citations(current, papers, set(new_records), set(changed), newly_eligible)
    # Remove entity nodes no longer referenced by structural edges.
    used = {e["target"] for e in current["edges"].values()} | {
        e["source"] for e in current["edges"].values()
    }
    current["nodes"] = {
        key: node
        for key, node in current["nodes"].items()
        if node.get("type") in {"PAPER", "EVIDENCE_SPAN"} or key in used
    }
    rebuild_indexes(current)
    hashes = {pid: digest for pid, digest in new_records.items() if pid not in removed}
    current["manifest"] = {
        "schema_version": SCHEMA_VERSION,
        "paper_hashes": hashes,
        "record_count_inspected": len(papers),
        "eligible_paper_count": len(hashes),
        "updated_at": time.time(),
    }
    indexing_ms = round((time.perf_counter() - indexing_start) * 1000, 3)
    validation_start = time.perf_counter()
    validate(current)
    validation_ms = round((time.perf_counter() - validation_start) * 1000, 3)
    return current, {
        "inspected": len(papers),
        "processed": len(changed),
        "new": sum(pid not in old_records for pid in changed),
        "changed": sum(pid in old_records for pid in changed),
        "deleted": len(removed),
        "elapsed_ms": round((time.perf_counter() - start) * 1000, 3),
        "indexing_ms": indexing_ms,
        "normalization_ms": round(normalization_ms, 3),
        "validation_ms": validation_ms,
        "rejected_evidence_items": rejected_evidence,
        "rejected_evidence_count": len(rejected_evidence),
    }


def publish(path: Path, snapshot: dict) -> None:
    validate(snapshot)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(snapshot, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        if os.path.exists(temp_name):
            os.unlink(temp_name)


def query(
    snapshot: dict,
    *,
    kind: str,
    value: str,
    max_depth: int = 2,
    max_nodes: int = 50,
    max_edges: int = 100,
    max_evidence: int = 20,
) -> dict[str, Any]:
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise ValueError("unsupported graph snapshot schema")
    nodes, edges = snapshot["nodes"], snapshot["edges"]
    norm = normalize(value)
    lookup = snapshot.get("indexes", {}).get("lookup", {})
    adjacency = snapshot.get("indexes", {}).get("adjacency", {})
    candidate_ids = lookup.get(f"{kind}:{norm}", [])
    if kind == "PAPER":
        candidate_ids = lookup.get(f"PAPER:{value}", candidate_ids)
    candidates = [nodes[node_id] for node_id in candidate_ids if node_id in nodes]
    if kind == "CITED_BY":
        if value in nodes:
            cited_edges = [
                edges[edge_id]
                for edge_id in adjacency.get(value, [])
                if edges[edge_id].get("type") == "CITES" and edges[edge_id].get("target") == value
            ][:max_edges]
            cited_nodes = {value} | {edge["source"] for edge in cited_edges}
            return {
                "query": {"kind": kind, "value": value},
                "nodes": [nodes[node_id] for node_id in sorted(cited_nodes)],
                "edges": cited_edges,
                "manifest": snapshot.get("manifest", {}),
            }
    if kind == "SHARED" and len(value.split("|", 1)) == 2:
        a, b = value.split("|", 1)
        ca = {
            edges[edge_id]["target"]
            for edge_id in adjacency.get(a, [])
            if edges[edge_id]["source"] == a and edges[edge_id]["type"] == "HAS_CONCEPT"
        }
        cb = {
            edges[edge_id]["target"]
            for edge_id in adjacency.get(b, [])
            if edges[edge_id]["source"] == b and edges[edge_id]["type"] == "HAS_CONCEPT"
        }
        candidates = [nodes[n] for n in sorted(ca & cb) if n in nodes]
    starts = [n["id"] for n in candidates]
    seen = set(starts)
    selected_edges = []
    frontier = deque((node_id, 0) for node_id in starts)
    evidence_count = 0
    while frontier and len(seen) <= max_nodes and len(selected_edges) < max_edges:
        current, depth = frontier.popleft()
        if depth >= max_depth:
            continue
        for edge_id in adjacency.get(current, []):
            edge = edges[edge_id]
            if edge["type"] == "HAS_SOURCE_EVIDENCE" and evidence_count >= max_evidence:
                continue
            if edge not in selected_edges:
                selected_edges.append(edge)
                if edge["type"] == "HAS_SOURCE_EVIDENCE":
                    evidence_count += 1
            neighbor = edge["target"] if edge["source"] == current else edge["source"]
            if neighbor not in seen and len(seen) < max_nodes:
                seen.add(neighbor)
                frontier.append((neighbor, depth + 1))
    return {
        "query": {"kind": kind, "value": value},
        "nodes": [nodes[n] for n in sorted(seen)],
        "edges": selected_edges,
        "manifest": snapshot.get("manifest", {}),
    }


def statistics(snapshot: dict) -> dict[str, Any]:
    return {
        "nodes_by_type": dict(Counter(n["type"] for n in snapshot["nodes"].values())),
        "edges_by_type": dict(Counter(e["type"] for e in snapshot["edges"].values())),
        "nodes": len(snapshot["nodes"]),
        "edges": len(snapshot["edges"]),
    }

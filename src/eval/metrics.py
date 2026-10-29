"""Pure E2–E5 and E8 calculations. Gold files are opened only by score.py."""

from src.engine.state_machine import EventType, State, validate_transition

DRIVING_LABELS = ("new", "refinement", "contradiction", "supersession")
SIX_LABELS = DRIVING_LABELS + ("restatement", "not_requirement")
HISTORICAL_LABELS = ("refinement", "contradiction", "supersession", "restatement")
NO_MATCH_LABELS = ("new", "not_requirement")

NULL_RESULT_PROTOCOL = (
    "If E5 accuracy does not separate the systems, lead with illegal-transition rate "
    "(structurally 0 for the pipeline), invented-id rate (0 by construction for the pipeline), "
    "repeat variance, false-supersession on hedges, and tokens and cost as the register grows. "
    "This framing was fixed before the measured runs."
)


def _div(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def evidence_spans(evidence: list[dict] | None) -> list[tuple[str, int, int]]:
    spans = []
    for item in evidence or []:
        if not isinstance(item, dict):
            continue
        try:
            spans.append((str(item["turn_id"]), int(item["start"]), int(item["end"])))
        except (KeyError, TypeError, ValueError):
            continue
    return spans


def _overlap(left: tuple[str, int, int], right: tuple[str, int, int]) -> int:
    if left[0] != right[0]:
        return 0
    return max(0, min(left[2], right[2]) - max(left[1], right[1]))


def align_by_span(
    gold_events: list[dict],
    predictions: list[dict],
) -> tuple[list[tuple[dict, dict | None]], list[dict]]:
    """Greedy one-to-one match on intersecting evidence spans. Not text similarity."""
    scored: list[tuple[int, int, int]] = []
    gold_spans = [evidence_spans(event.get("evidence")) for event in gold_events]
    pred_spans = [evidence_spans(item.get("evidence")) for item in predictions]
    for gold_index, lefts in enumerate(gold_spans):
        for pred_index, rights in enumerate(pred_spans):
            amount = sum(_overlap(left, right) for left in lefts for right in rights)
            if amount > 0:
                scored.append((amount, gold_index, pred_index))
    scored.sort(key=lambda item: (-item[0], item[1], item[2]))
    used_gold: set[int] = set()
    used_pred: set[int] = set()
    chosen: dict[int, int] = {}
    for _, gold_index, pred_index in scored:
        if gold_index in used_gold or pred_index in used_pred:
            continue
        used_gold.add(gold_index)
        used_pred.add(pred_index)
        chosen[gold_index] = pred_index
    aligned = [
        (event, predictions[chosen[index]] if index in chosen else None)
        for index, event in enumerate(gold_events)
    ]
    spurious = [item for index, item in enumerate(predictions) if index not in used_pred]
    return aligned, spurious


def _gold_requirement_id(event: dict) -> str | None:
    value = event.get("canonical_requirement_id", event.get("requirement_id"))
    return value if isinstance(value, str) and value else None


def map_created_ids(aligned: list[tuple[dict, dict | None]]) -> dict[str, str]:
    """Map a gold family id to the id the pipeline allocated for its `new` event."""
    mapping: dict[str, str] = {}
    for gold, prediction in aligned:
        if gold.get("relation") != "new" or prediction is None:
            continue
        created = prediction.get("created_requirement_id")
        gold_id = _gold_requirement_id(gold)
        if isinstance(created, str) and created and gold_id and gold_id not in mapping:
            mapping[gold_id] = created
    return mapping


def relation_report(pairs: list[tuple[str | None, str | None]], labels: tuple[str, ...]) -> dict:
    """Macro-F1 over ``labels``. Classes with support 0 are listed and left out of the mean."""
    per_class = {}
    f1_values = []
    excluded = []
    columns = list(labels) + ["error"]
    confusion = {label: {column: 0 for column in columns} for label in labels}
    for gold, predicted in pairs:
        column = predicted if predicted in labels else "error"
        if gold in confusion:
            confusion[gold][column] += 1
        elif gold is None:
            row = confusion.setdefault("unaligned", {name: 0 for name in columns})
            row[column] += 1
    for label in labels:
        support = sum(gold == label for gold, _ in pairs)
        tp = sum(gold == label and predicted == label for gold, predicted in pairs)
        fp = sum(predicted == label and gold != label for gold, predicted in pairs)
        fn = support - tp
        precision = _div(tp, tp + fp)
        recall = _div(tp, tp + fn) if support else None
        if support == 0:
            excluded.append(label)
            f1 = None
        elif not precision or not recall:
            f1 = 0.0
            f1_values.append(f1)
        else:
            f1 = 2 * precision * recall / (precision + recall)
            f1_values.append(f1)
        per_class[label] = {
            "precision": precision,
            "recall": recall,
            "f1": f1,
            "support": support,
        }
    return {
        "per_class": per_class,
        "macro_f1": sum(f1_values) / len(f1_values) if f1_values else None,
        "excluded_zero_support": excluded,
        "confusion": confusion,
    }


def _relation_pairs(
    aligned: list[tuple[dict, dict | None]],
    spurious: list[dict],
) -> list[tuple[str | None, str | None]]:
    pairs: list[tuple[str | None, str | None]] = []
    for gold, prediction in aligned:
        predicted = None
        if prediction is not None and prediction.get("predicted_relation") != "error":
            predicted = prediction.get("predicted_relation")
        pairs.append((gold.get("relation"), predicted))
    for prediction in spurious:
        if prediction.get("predicted_relation") != "error":
            pairs.append((None, prediction.get("predicted_relation")))
    return pairs


def retrieval_recall(
    aligned: list[tuple[dict, dict | None]],
    mapping: dict[str, str],
    cutoffs: tuple[int, ...] = (3, 5, 8),
) -> dict:
    """Recall of the gold family on each channel. A missing family stays in the denominator."""
    cases = []
    for gold, prediction in aligned:
        if gold.get("relation") not in HISTORICAL_LABELS:
            continue
        gold_id = _gold_requirement_id(gold)
        cases.append((mapping.get(gold_id) if gold_id else None, prediction))
    channels = {}
    for channel in ("bm25", "dense", "fused"):
        channels[channel] = {}
        for cutoff in cutoffs:
            hits = 0
            for expected, prediction in cases:
                ranking = []
                if prediction is not None:
                    ranking = list((prediction.get("rankings") or {}).get(channel) or [])
                if expected is not None and expected in ranking[:cutoff]:
                    hits += 1
            channels[channel][str(cutoff)] = _div(hits, len(cases))
    return {"support": len(cases), "recall_at_k": channels}


def historical_id_accuracy(
    aligned: list[tuple[dict, dict | None]],
    mapping: dict[str, str],
) -> dict:
    cases = [
        (gold, prediction)
        for gold, prediction in aligned
        if gold.get("relation") in HISTORICAL_LABELS
    ]
    correct = 0
    for gold, prediction in cases:
        gold_id = _gold_requirement_id(gold)
        expected = mapping.get(gold_id) if gold_id else None
        predicted = None if prediction is None else prediction.get("predicted_id")
        if (
            expected is not None
            and predicted == expected
            and prediction.get("predicted_relation") != "error"
        ):
            correct += 1
    return {"accuracy": _div(correct, len(cases)), "support": len(cases), "correct": correct}


def no_match_rates(
    aligned: list[tuple[dict, dict | None]],
    predictions: list[dict],
) -> dict:
    """Accuracy and precision stay separate. The classifier is always shown k families."""
    gold_cases = [
        (gold, prediction)
        for gold, prediction in aligned
        if gold.get("relation") in NO_MATCH_LABELS
    ]
    correct = sum(
        1
        for _, prediction in gold_cases
        if prediction is not None
        and prediction.get("predicted_id") is None
        and prediction.get("predicted_relation") != "error"
    )
    null_predictions = [
        item
        for item in predictions
        if item.get("predicted_id") is None and item.get("predicted_relation") != "error"
    ]
    true_positives = sum(
        1 for item in null_predictions if item.get("aligned_relation") in NO_MATCH_LABELS
    )
    return {
        "accuracy": _div(correct, len(gold_cases)),
        "accuracy_support": len(gold_cases),
        "precision": _div(true_positives, len(null_predictions)),
        "precision_support": len(null_predictions),
    }


def joint_accuracy(
    aligned: list[tuple[dict, dict | None]],
    mapping: dict[str, str],
) -> dict:
    correct = 0
    for gold, prediction in aligned:
        if prediction is None or prediction.get("predicted_relation") == "error":
            continue
        relation_ok = prediction.get("predicted_relation") == gold.get("relation")
        if gold.get("relation") in NO_MATCH_LABELS:
            id_ok = prediction.get("predicted_id") is None
        else:
            gold_id = _gold_requirement_id(gold)
            id_ok = prediction.get("predicted_id") == (mapping.get(gold_id) if gold_id else None)
        if relation_ok and id_ok:
            correct += 1
    return {"accuracy": _div(correct, len(aligned)), "support": len(aligned), "correct": correct}


def invented_id_rate(predictions: list[dict]) -> dict:
    """An id outside the offered list. `new` may introduce an id; that is not invented."""
    considered = 0
    invented = 0
    for prediction in predictions:
        relation = prediction.get("predicted_relation")
        if relation in NO_MATCH_LABELS or relation in {None, "error"}:
            continue
        considered += 1
        predicted = prediction.get("predicted_id")
        offered = set((prediction.get("rankings") or {}).get("offered") or [])
        if predicted is not None and predicted not in offered:
            invented += 1
    return {"rate": _div(invented, considered), "support": considered, "invented": invented}


def false_supersession(aligned: list[tuple[dict, dict | None]]) -> dict:
    eligible = [
        (gold, prediction) for gold, prediction in aligned if gold.get("relation") != "supersession"
    ]
    applied = 0
    labelled = 0
    for _, prediction in eligible:
        if prediction is None:
            continue
        if prediction.get("predicted_relation") == "supersession":
            applied += 1
            labelled += 1
        elif (prediction.get("rankings") or {}).get("downgraded_from") == "supersession":
            labelled += 1
    return {
        "rate": _div(applied, len(eligible)),
        "support": len(eligible),
        "applied": applied,
        "model_label_before_downgrade": labelled,
        "note": "D1 gold has no hedge flag, so this is not a hedge-only rate.",
    }


def extraction_report(
    aligned: list[tuple[dict, dict | None]],
    spurious: list[dict],
    extraction: dict | None,
) -> dict:
    matched = sum(prediction is not None for _, prediction in aligned)
    misses = [
        {
            "event_index": gold.get("event_index"),
            "meeting_ordinal": gold.get("meeting_ordinal"),
            "requirement_id": _gold_requirement_id(gold),
        }
        for gold, prediction in aligned
        if prediction is None
    ]
    gold_count = len(aligned)
    predicted_count = matched + len(spurious)
    precision = _div(matched, predicted_count)
    recall = _div(matched, gold_count)
    if precision is None or recall is None or precision + recall == 0:
        f1 = 0.0 if gold_count or predicted_count else None
    else:
        f1 = 2 * precision * recall / (precision + recall)
    returned = int((extraction or {}).get("returned") or 0)
    accepted = int((extraction or {}).get("accepted") or 0)
    rejected = int((extraction or {}).get("rejected_unresolvable") or 0)
    return {
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "support": {"gold": gold_count, "predicted": predicted_count, "matched": matched},
        "misses": misses,
        "spurious": [item.get("candidate_id") for item in spurious],
        "evidence_support_accuracy": _div(accepted, returned),
        "unsupported_rate": _div(rejected, returned),
        "extraction_counts": extraction or {},
    }


def _apply_gold_relation(current: State | None, relation: str | None) -> tuple[State, bool] | None:
    """Replay one gold label through the engine. Eval confirms a new requirement."""
    if relation == "new":
        proposed = validate_transition(None, EventType.CREATE)
        if proposed is None:
            return None
        confirmed = validate_transition(proposed, EventType.CONFIRM)
        if confirmed is None:
            return None
        return confirmed, False
    event = {
        "refinement": EventType.REFINE,
        "contradiction": EventType.CONTRADICT,
        "supersession": EventType.SUPERSEDE,
    }.get(relation or "")
    if event is None:
        return None
    resulting = validate_transition(current, event)
    if resulting is None:
        return None
    return resulting, True


def expected_register(gold_events: list[dict], after_meeting: int) -> dict[str, dict[str, object]]:
    """Expected version and state at a meeting cutoff.

    ``expected_state_after`` wins when the file has it. D1 does not, so the state
    is the engine's result for the gold relation, with new items confirmed.
    """
    state: dict[str, State] = {}
    version: dict[str, int] = {}
    ordered = sorted(
        gold_events,
        key=lambda event: (event.get("meeting_ordinal", 0), event.get("event_index", 0)),
    )
    for event in ordered:
        if int(event.get("meeting_ordinal") or 0) > after_meeting:
            continue
        requirement_id = _gold_requirement_id(event)
        if requirement_id is None:
            continue
        applied = _apply_gold_relation(state.get(requirement_id), event.get("relation"))
        if applied is not None:
            resulting, increments = applied
            if event.get("relation") == "new":
                version[requirement_id] = 1
            elif increments:
                version[requirement_id] = version.get(requirement_id, 0) + 1
            state[requirement_id] = resulting
        override = event.get("expected_state_after")
        if isinstance(override, str) and override:
            state[requirement_id] = State(override)
        elif isinstance(override, dict) and override.get("state"):
            state[requirement_id] = State(override["state"])
            if "version" in override:
                version[requirement_id] = int(override["version"])
    return {
        requirement_id: {"state": current.value, "version": version.get(requirement_id, 0)}
        for requirement_id, current in state.items()
    }


def register_accuracy(
    gold_events: list[dict],
    actual_at: dict[int, dict[str, dict[str, object]]],
    mapping: dict[str, str],
) -> dict:
    """Per-meeting state and version accuracy, plus reversal final-state accuracy."""
    ordinals = sorted({int(event.get("meeting_ordinal") or 0) for event in gold_events})
    per_meeting = {}
    birth_state: dict[str, str] = {}
    for ordinal in ordinals:
        expected = expected_register(gold_events, ordinal)
        actual = actual_at.get(ordinal, {})
        correct = 0
        mismatches = []
        for gold_id, exp in expected.items():
            if gold_id not in birth_state:
                birth_state[gold_id] = str(exp["state"])
            system_id = mapping.get(gold_id)
            observed = actual.get(system_id) if system_id else None
            match = (
                observed is not None
                and observed.get("state") == exp["state"]
                and observed.get("version") == exp["version"]
            )
            if match:
                correct += 1
            else:
                mismatches.append(
                    {
                        "requirement_id": gold_id,
                        "system_id": system_id,
                        "expected": exp,
                        "actual": observed,
                    }
                )
        per_meeting[str(ordinal)] = {
            "accuracy": _div(correct, len(expected)),
            "support": len(expected),
            "correct": correct,
            "mismatches": mismatches,
        }
    final_ordinal = ordinals[-1] if ordinals else 0
    final_expected = expected_register(gold_events, final_ordinal) if ordinals else {}
    final_actual = actual_at.get(final_ordinal, {})
    reversals = {
        gold_id: exp
        for gold_id, exp in final_expected.items()
        if exp["state"] != birth_state.get(gold_id)
        or exp["state"] in {"contradicted", "superseded"}
    }
    reversal_correct = 0
    for gold_id, exp in reversals.items():
        system_id = mapping.get(gold_id)
        observed = final_actual.get(system_id) if system_id else None
        if (
            observed is not None
            and observed.get("state") == exp["state"]
            and observed.get("version") == exp["version"]
        ):
            reversal_correct += 1
    return {
        "per_meeting": per_meeting,
        "reversal_final_state_accuracy": _div(reversal_correct, len(reversals)),
        "reversal_support": len(reversals),
        "reversal_correct": reversal_correct,
    }


def illegal_transition_rate(events: list[dict]) -> dict:
    """Walk committed events through the engine. A forced write does not become legal."""
    state: dict[str, State] = {}
    illegal = 0
    details = []
    ordered = sorted(
        events,
        key=lambda event: (event.get("seq") is None, event.get("seq") or 0, event.get("ts") or ""),
    )
    for event in ordered:
        requirement_id = event.get("requirement_id")
        if not isinstance(requirement_id, str):
            illegal += 1
            details.append({"event_type": event.get("event_type"), "reason": "missing requirement"})
            continue
        try:
            event_type = EventType(event.get("event_type"))
        except ValueError:
            illegal += 1
            details.append({"requirement_id": requirement_id, "reason": "unknown event"})
            continue
        resulting = validate_transition(state.get(requirement_id), event_type)
        if resulting is None:
            illegal += 1
            source = state[requirement_id].value if requirement_id in state else "none"
            details.append(
                {
                    "requirement_id": requirement_id,
                    "event_type": event_type.value,
                    "from_state": source,
                }
            )
            continue
        state[requirement_id] = resulting
    return {
        "rate": _div(illegal, len(ordered)),
        "illegal": illegal,
        "events": len(ordered),
        "details": details,
    }


def e8_from_calls(calls: list[dict]) -> dict:
    """Count attempts, including failures; unknown provider usage never means free."""

    def summarize(items: list[dict]) -> dict:
        unknown = sum(call.get("usage_known") is False for call in items)
        known = [call for call in items if call.get("usage_known") is not False]
        recorded_cost = sum(float(call.get("cost") or 0.0) for call in known)
        recorded_input = sum(int(call.get("input_tokens") or 0) for call in known)
        recorded_output = sum(int(call.get("output_tokens") or 0) for call in known)
        return {
            "calls": len(items),
            "failed_calls": sum(call.get("outcome") == "failed" for call in items),
            "unknown_usage_calls": unknown,
            "usage_complete": unknown == 0,
            "input_tokens": None if unknown else recorded_input,
            "output_tokens": None if unknown else recorded_output,
            "cost": None if unknown else recorded_cost,
            "recorded_input_tokens": recorded_input,
            "recorded_output_tokens": recorded_output,
            "recorded_cost": recorded_cost,
            "retries": sum(int(call.get("retries") or 0) for call in items),
        }

    stages = sorted({str(call.get("stage") or "unknown") for call in calls})
    by_stage = {}
    for stage in stages:
        items = [call for call in calls if str(call.get("stage") or "unknown") == stage]
        by_stage[stage] = {
            **summarize(items),
            "latency_ms": sum(int(call.get("latency_ms") or 0) for call in items),
        }
    ordered = sorted(int(call.get("latency_ms") or 0) for call in calls)

    def percentile(fraction: float) -> int | None:
        if not ordered:
            return None
        index = min(len(ordered) - 1, max(0, int(round(fraction * (len(ordered) - 1)))))
        return ordered[index]

    return {
        **summarize(calls),
        "by_stage": by_stage,
        "latency_ms_p50": percentile(0.50),
        "latency_ms_p95": percentile(0.95),
        "latency_scope": "per recorded attempt, including failures; not end-to-end latency",
    }

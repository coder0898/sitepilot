"""Phase 1 (1a): template-name registry (fixes the doc's own template-naming
rule being violated by `message_dispatch.py` sending
`template = event.event_type` straight to the WhatsApp provider - an internal
event-type string like `task.status_changed`, not a Meta-approved template
name, was never a valid `template.name` for the Graph API call
`MetaCloudApiAdapter` makes).

`TEMPLATE_REGISTRY` maps every `event_type` string this codebase's services
currently emit (via `OutboxService.emit(event_type=...)` - see each
`app.services.*` module for the emit call site) to the Meta template it
should render as. Names are chosen to align with the WhatsApp Operating
Model doc's own template names where a clear 1:1 mapping exists; where the
doc has no per-transition template (e.g. every `task.status_changed`
transition sharing one message shape), a sensible generic name is used
instead and flagged below.

Unmapped/unknown event types fall back to `DEFAULT_TEMPLATE` - logged, never
raising, and never leaking the raw internal event-type string out as if it
were a real template name (a stray/renamed event type must degrade to a
generic notification, not silently break dispatch or expose internals to
the WhatsApp provider).
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class TemplateSpec:
    """One event type's WhatsApp template binding.

    `variable_order` names the `OutboxEvent.payload` keys to render into the
    Meta template's body parameters, in the order the approved template's
    placeholders expect them (`{{1}}`, `{{2}}`, ...) - see `render_components`.
    """

    meta_template_name: str
    language: str
    variable_order: tuple[str, ...]


DEFAULT_TEMPLATE = TemplateSpec("generic_notification", "en", ())


TEMPLATE_REGISTRY: dict[str, TemplateSpec] = {
    # ---- task events ---------------------------------------------------
    "task.status_changed": TemplateSpec(
        # No doc template maps 1:1 to every individual transition - one
        # generic status-update template covers all of them.
        "task_status_update", "en", ("task_id", "before_status", "target_status", "reason"),
    ),
    "task.verification_recorded": TemplateSpec(
        "task_verification_recorded", "en", ("task_id", "decision", "remarks", "decision_mode"),
    ),
    "task.approval_recorded": TemplateSpec(
        # BR-008: Admin is a recipient here (see message_dispatch.py's
        # `_ADMIN_CC_TASK_EVENTS`), never the decision-maker of record.
        "task_approval_decision", "en", ("task_id", "decision", "remarks", "decision_mode"),
    ),
    "task.blocker_created": TemplateSpec(
        "task_blocker_alert", "en", ("task_id", "type", "description"),
    ),
    "task.blocker_resolved": TemplateSpec(
        "task_blocker_resolved", "en", ("task_id", "resolved_by"),
    ),
    "task.delay_recorded": TemplateSpec(
        "task_delay_recorded", "en", ("task_id", "responsibility_type", "impact_days"),
    ),
    "task.support_assigned": TemplateSpec(
        "task_support_assigned", "en", ("task_id", "employee_id", "responsibility"),
    ),
    "task.support_ended": TemplateSpec(
        # Non-doc event type (doc doesn't distinguish "support ended" from
        # "support reassigned") - mapped to the nearest doc-aligned name,
        # flagged for later product review per the plan's Decisions section.
        "task_support_ended", "en", ("task_id", "previous_employee_id", "replacement_employee_id", "reason_code"),
    ),
    "task.evidence_submitted": TemplateSpec(
        "task_evidence_submitted", "en", ("task_id", "update_type"),
    ),
    "task.vendor_assigned": TemplateSpec(
        "task_vendor_assigned", "en", ("task_id", "vendor_id"),
    ),
    "task.readiness_declared": TemplateSpec(
        # Non-doc event type (Phase 3 advisory overlay table, not a doc
        # workflow) - mapped to the nearest doc-aligned name, flagged for
        # later product review per the plan's Decisions section.
        "task_readiness_declared", "en", ("task_id", "status", "note"),
    ),
    "task.attendance_recorded": TemplateSpec(
        # Non-doc event type - see task.readiness_declared's note above.
        "task_attendance_recorded", "en", ("task_id", "employee_id", "status", "note"),
    ),
    "task.rescheduled": TemplateSpec(
        # Plan Phase 4: no doc template covers a planned-date replan
        # specifically - the closest doc-aligned name is used, flagged for
        # later product review per the plan's Decisions section.
        "task_rescheduled", "en", ("task_id", "planned_start_date", "planned_end_date", "reason"),
    ),
    # ---- project events -------------------------------------------------
    "project.role_change_requested": TemplateSpec(
        "project_role_change_requested", "en", ("project_id", "role_type", "reason_code"),
    ),
    "project.role_change_approved": TemplateSpec(
        "project_role_change_approved", "en", ("project_id", "role_type"),
    ),
    "project.role_change_rejected": TemplateSpec(
        "project_role_change_rejected", "en", ("project_id", "role_type", "reason"),
    ),
    # ---- project_external_approval (gate) events -------------------------
    "project_external_approval.assigned": TemplateSpec(
        "external_approval_assigned", "en", ("approval_id", "assigned_to_user_id"),
    ),
    "project_external_approval.reassigned": TemplateSpec(
        "external_approval_reassigned", "en", ("approval_id", "assigned_to_user_id"),
    ),
    "project_external_approval.unassigned": TemplateSpec(
        "external_approval_unassigned", "en", ("approval_id", "previous_assignee_id"),
    ),
    "project_external_approval.submitted": TemplateSpec(
        # Doc's "external approval status update" template - the closest
        # doc-named match for a submission notice.
        "external_approval_status_update", "en", ("approval_id", "submission_id"),
    ),
    "project_external_approval.decided": TemplateSpec(
        "external_approval_decided", "en", ("approval_id", "decision", "reason"),
    ),
    "project_external_approval.status_checked": TemplateSpec(
        # Non-doc event type (Phase 3 advisory overlay table, the gate
        # analog of task.blocker_created) - mapped to the nearest
        # doc-aligned name, flagged for later product review.
        "external_approval_status_checked", "en", ("approval_id", "health", "note"),
    ),
}


def resolve(event_type: str) -> TemplateSpec:
    """Registry lookup with a logged, non-raising fallback. Never returns a
    `TemplateSpec` built from the raw `event_type` string itself - an
    unmapped event type degrades to `DEFAULT_TEMPLATE`, not a fabricated
    template name derived from internal wording."""
    spec = TEMPLATE_REGISTRY.get(event_type)
    if spec is not None:
        return spec
    logger.warning("No template registered for event_type=%r; falling back to default template.", event_type)
    return DEFAULT_TEMPLATE


def render_components(spec: TemplateSpec, payload: dict) -> list[dict]:
    """Builds Meta's WhatsApp template body-parameters shape (the
    `components` list `MetaCloudApiAdapter._build_body` already reads off
    `payload["components"]`, but nothing has ever populated until now).

    A spec with no `variable_order` (e.g. `DEFAULT_TEMPLATE`) still returns
    one body component with an empty `parameters` list, matching the shape
    Meta expects for a template with no placeholders."""
    return [
        {
            "type": "body",
            "parameters": [{"type": "text", "text": str(payload.get(key, ""))} for key in spec.variable_order],
        }
    ]

// Plain-language Problem / Why for each template_draft_validator issue code.
// A code missing here falls back to the server's own message.
const TASK_SETTING = { problem:"A task has a setting this version can't use", why:"Open the task, check its details and save it again." };
const APPROVAL_LINKS = { problem:"An approval's task links don't add up", why:"Open the approval, check the tasks it is required before, and save it again." };

export const ISSUE_COPY = {
  template_code_required: { problem:"The template has no code", why:"Every template needs a unique code." },
  template_name_required: { problem:"The template has no name", why:"Give the template a name people will recognise." },
  template_requires_task: { problem:"The template has no tasks", why:"Add at least one task before publishing." },
  version_duration_invalid: { problem:"The template's duration isn't valid", why:"The number of days must be a positive whole number." },

  task_title_required: { problem:"A task has no name", why:"Every task needs a name so the team knows what to do." },
  task_code_required: { problem:"A task has no code", why:"Open Advanced in the task and enter a code." },
  task_code_duplicate: { problem:"Two tasks share the same code", why:"Each task code must be unique. Change one of them under Advanced." },
  task_sequence_invalid: { problem:"The task order needs saving again", why:"Move any task up or down and save the order." },
  task_sequence_duplicate: { problem:"The task order needs saving again", why:"Move any task up or down and save the order." },
  task_schedule_invalid: { problem:"A task's days aren't valid", why:"It must start on Day 1 or later and can't end before it starts." },
  task_exceeds_version_duration: { problem:"A task ends after the template's last day", why:"Move its end day inside the template's duration." },
  pre_activation_task_has_days: { problem:"An older pre-activation task has project days", why:"Open it and schedule it on project days." },
  task_duration_invalid: { problem:"A task's duration isn't valid", why:"Re-enter its start and end day." },
  task_applicability_invalid: TASK_SETTING,
  task_schedule_classification_invalid: TASK_SETTING,
  task_class_invalid: { problem:"A task has an unknown class", why:"Choose Standard or Class A." },
  task_kind_invalid: { problem:"A task has an unknown type", why:"Open Advanced in the task and choose ordinary work." },

  dependency_cycle: { problem:"Some tasks wait for each other in a loop", why:"None of the tasks in the loop could ever start. Remove one of their \"can't start until\" links." },
  dependency_self_reference: { problem:"A task waits for itself", why:"Remove that \"can't start until\" link." },
  dependency_duplicate: { problem:"The same \"can't start until\" link appears twice", why:"Delete the extra one under Dependencies." },
  dependency_task_reference_invalid: { problem:"A \"can't start until\" link points to a missing task", why:"Delete the link under Dependencies." },
  dependency_type_unsupported: { problem:"A dependency has a type this version can't use", why:"Edit it under Dependencies." },

  gate_name_required: { problem:"An approval has no name", why:"Give it a name, for example \"Fire NOC\"." },
  gate_code_required: { problem:"An approval has no code", why:"Open Advanced in the approval and enter a code." },
  gate_code_duplicate: { problem:"Two approvals share the same code", why:"Each approval code must be unique. Change one under Advanced." },
  gate_sequence_invalid: { problem:"The approval order needs fixing", why:"Open the approval and save it again." },
  gate_sequence_duplicate: { problem:"The approval order needs fixing", why:"Open the approval and save it again." },
  exact_gate_requires_mapping: { problem:"An approval is meant to be linked to tasks, but none are", why:"Tick the tasks it is required before." },
  gate_required_by_invalid: { problem:"An approval's due-date rule can't produce a date" },
  gate_due_date_missing: { problem:"An approval has no due date" },
  broad_gate_requires_configuration: { problem:"An approval only has imported wording", why:"It isn't linked to tasks, so each project has to sort it out by hand. Tick the tasks it is required before." },
  unmapped_gate_requires_configuration: { problem:"An approval isn't linked to any task", why:"No task will list it as a prerequisite. Tick the tasks it is required before." },
  gate_classification_invalid: APPROVAL_LINKS,
  exact_gate_configuration_flag_invalid: APPROVAL_LINKS,
  exact_gate_has_broad_text: APPROVAL_LINKS,
  broad_gate_text_required: APPROVAL_LINKS,
  broad_gate_has_exact_rows: APPROVAL_LINKS,
  broad_gate_configuration_flag_required: APPROVAL_LINKS,
  unmapped_gate_contains_mapping: APPROVAL_LINKS,
  unmapped_gate_configuration_flag_required: APPROVAL_LINKS,
  mapping_gate_reference_invalid: APPROVAL_LINKS,
  mapping_task_reference_invalid: APPROVAL_LINKS,
  mapping_duplicate: APPROVAL_LINKS,
};

/** Problem / Why for one issue; Why defaults to the server's message, which explains rule-specific cases. */
export function issueCopy(issue) {
  const copy = ISSUE_COPY[issue.code];
  return { problem: copy?.problem || issue.message, why: copy?.why ?? (copy ? issue.message : "") };
}

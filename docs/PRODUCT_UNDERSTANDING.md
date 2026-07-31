# Product Understanding Document
**WorkVed Site Operations & Project Management Portal**

This document reflects analysis of the business context provided by the product owner. It is a conceptual/business-level model only — no technical or implementation detail is included.

---

## A. Product Understanding Summary

WorkVed is an internal operations management platform for digitizing and streamlining commercial interior execution and managed office operations. It replaces fragmented, informal coordination tools (WhatsApp, phone calls, spreadsheets) with a structured, workflow-driven system.

Core problem being solved: site execution today lacks real-time visibility, relies on manual follow-up, has poor coordination across roles, has no centralized record of task history/delays/approvals/accountability, and makes management-level reporting and early risk detection difficult.

The stated goal is to become a "single source of truth" for site execution and operations, initially for commercial interior projects, coworking spaces, managed offices, and facility operations — with a longer-term ambition to become a broader AI-assisted operations platform for commercial real estate and interior execution businesses.

---

## B. User Roles & Responsibilities

| Role | Responsibilities |
|---|---|
| **Super Admin** | Complete system control; manages templates, configurations, users, permissions, and system-level settings. |
| **Admin** | Manages operational activities; reviews execution status; monitors reports and escalations. |
| **Project Manager** | Owns project execution; assigns tasks; tracks progress; manages dependencies and deadlines. |
| **Supervisor** | Verifies site-level activities; reviews employee updates; escalates issues. |
| **Internal Employee** | Views assigned tasks; updates task status; provides completion updates. |
| **Vendor** | Limited external interaction; receives task communication/updates where required. |

Note on hierarchy: the roles appear to be listed in descending order of system authority (Super Admin → Admin → Project Manager → Supervisor → Employee → Vendor), but the exact permission boundaries between adjacent roles (e.g., what Admin can do that PM cannot, or vice versa) are not fully specified — see Section F.

---

## C. Core Workflows

1. **Project Setup**
   Create a project/site → configure an execution template → define tasks, dependencies, milestones, and responsibilities.

2. **Task Management**
   Tasks are assigned to responsible users and tracked through status states: Pending → In Progress → Completed / Blocked → Verified.

3. **Daily Operations**
   Surface today's tasks, track pending/carry-forward activities, and capture status updates from team members.

4. **Dependency Management**
   Identify blocked activities, track prerequisite tasks, and prevent execution delays caused by unmet dependencies.

5. **Review & Approval**
   Supervisor verifies employee updates → Project Manager reviews overall execution progress → Management receives visibility/reports.

6. **Reporting**
   Daily progress reports, weekly project summaries, delay identification, and performance tracking.

7. **Template-Based Execution**
   Reusable project execution templates supporting different project durations and workflows (e.g., the referenced "45-day execution template").

---

## D. Feature Map

Grouped by the workflows above — these are the feature *areas* implied by the business description, not a technical spec:

- **Project/Site Setup** — project creation, template configuration, definition of tasks/milestones/dependencies/responsibilities.
- **Task Assignment & Tracking** — assignment to users, status lifecycle (Pending, In Progress, Completed, Blocked, Verified).
- **Daily Operations View** — "today's tasks," carry-forward/pending activity tracking, team update capture.
- **Dependency Tracking** — prerequisite linkage between tasks, blocked-task identification.
- **Verification & Approval** — supervisor verification step, PM review step, management-level visibility.
- **Reporting & Analytics** — daily reports, weekly summaries, delay identification, performance tracking.
- **Template Management** — reusable, duration-flexible execution templates.
- **Role-Based Access Control** — permissions differentiated by the six defined roles.
- **User & Configuration Management** (Super Admin scope) — users, permissions, system-level settings.

---

## E. Business Rules

Explicitly stated constraints and principles governing how the system must be built and evolved:

- Existing functionality must not be broken when adding new features.
- Avoid unnecessary architectural changes.
- Follow existing coding patterns and project structure.
- Do not modify the database schema unless a genuine requirement exists.
- Maintain backward compatibility.
- Changes must be modular and scalable.
- Role permissions must always be respected.
- Business workflows take priority over technical optimization.
- Missing requirements must not be assumed — clarification should be sought instead.
- Development follows clean architecture, maintainability, clear layer separation (frontend/backend/database), and production-ready implementation over quick fixes.
- Development proceeds incrementally, in controlled phases.

---

## F. Missing Information / Questions

The following are not defined in the provided context and are marked **unclear** rather than assumed:

1. **Key entities and relationships** — the overview describes workflows and roles but does not explicitly define the data entities (e.g., Project, Site, Task, Template, Milestone, User, Vendor, Dependency) or how they relate to one another (one-to-many/many-to-many, ownership, etc.). This should be confirmed before any entity model is treated as fact.
2. **Role permission boundaries** — the specific actions each role can/cannot perform relative to adjacent roles (especially Admin vs. Project Manager, and what "limited external interaction" means precisely for Vendors) are not detailed.
3. **Task status transition rules** — whether all status transitions (e.g., Pending → Verified, Blocked → Completed) are allowed, or whether a strict sequence/gate is enforced, is unclear.
4. **Escalation rules** — what triggers an escalation, who it routes to, and any SLA/time-based thresholds are not defined.
5. **Multi-project/multi-site scope** — whether the current phase supports multiple concurrent projects/sites per user, or is scoped to single-project operation for now, is unclear (multi-site is listed under "Future capabilities," implying current scope may be narrower).
6. **Template structure** — what a "template" concretely contains (task lists, durations, role assignments, milestone definitions) beyond "reusable, duration-flexible" is not detailed. A reference document (`Recovered_45_Day_Execution_Template_Reference.docx`) exists in the project's docs folder but was not reviewed as part of this analysis per your instruction to stay at the business-context level.
7. **Reporting audience/detail levels** — whether daily/weekly reports differ by role (e.g., management sees a rollup, PM sees detail) is not specified.
8. **Vendor interaction scope** — "receives task communication/updates where required" is vague on whether vendors can update task status themselves or are purely notified.
9. **Definition of "verified"** — what distinguishes a "Completed" task from a "Verified" one, and who besides the Supervisor can verify, is not specified.
10. **Current development stage detail** — "under active development" with several features "being built" is stated, but which specific features are already functional today versus planned is not defined in this overview.

---

*This document is based solely on the business/product overview supplied by the product owner. No codebase inspection or technical analysis was performed in producing it.*

# Workved SiteOps V2 - Employee Access Onboarding

**Status:** Release 1 implementation baseline  
**Authentication provider:** Supabase Auth

## Deterministic workflow

1. A prospective employee may request `admin`, `project_manager`, `supervisor`, or `internal_employee`. `super_admin` is never publicly requestable.
2. The requested role is advisory. The reviewer confirms the least-privilege final role.
3. Work-email ownership must be verified before approval becomes available.
4. An Admin-submitted request and every request for the Admin role require Super Admin approval.
5. A self-service request for Project Manager, Supervisor, or Internal Employee is reviewed primarily by an active Admin; Super Admin remains the fallback.
6. Online presence is not an approval-routing rule. Requests remain in the durable queue until decided.
7. The request submitter cannot approve the same request.
8. Approval links the verified Supabase identity to one SiteOps employee account; it does not create a second identity.
9. Approval is idempotent. Repeated submission returns the existing decision and account.
10. Approved employees receive a one-time password-setup email.

## States

`pending_email_verification` -> `pending_approval` -> `approved` or `rejected`

Terminal administrative states are `expired` and `cancelled`.

## Audit and lifecycle

- Submission, verification, resend, approval, rejection, and activation events are retained.
- Duplicate open requests and duplicate employee identities are blocked.
- Offboarding deactivates access while preserving accountable business history.
- Permanent deletion remains restricted to inactive, unreferenced test or duplicate accounts.

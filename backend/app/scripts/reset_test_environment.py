"""
Developer utility: reset local/staging SiteOps test data.

Preserves:
- super_admin users
- template-owned V2 data

Deletes:
- project execution/test data
- non-super-admin users

Usage:
    python -m app.scripts.reset_test_environment

Requires explicit confirmation:
    RESET-SITEOPS
"""

from sqlalchemy import text

from app.database import SessionLocal


CONFIRMATION = "RESET-SITEOPS"


DELETE_SQL = [
    # Child project records first
    "DELETE FROM siteops_v2.project_dependencies",
    "DELETE FROM siteops_v2.project_external_gates",
    "DELETE FROM siteops_v2.project_tasks",
    "DELETE FROM siteops_v2.project_memberships",
    "DELETE FROM siteops_v2.projects",

    # Remove non privileged users only
    "DELETE FROM users WHERE role != 'super_admin'",
]


def count_rows(db, table):
    try:
        return db.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar() or 0
    except Exception:
        return 0


def run_reset():
    with SessionLocal() as db:
        summary = {
            "projects": count_rows(db, "siteops_v2.projects"),
            "tasks": count_rows(db, "siteops_v2.project_tasks"),
            "users": count_rows(db, "users"),
        }

        print("\nWARNING: This will remove SiteOps test data.")
        print(summary)

        value = input("\nType RESET-SITEOPS to continue: ").strip()

        if value != CONFIRMATION:
            print("Reset cancelled.")
            return

        for query in DELETE_SQL:
            try:
                db.execute(text(query))
            except Exception as exc:
                # Some installations may not have optional tables yet.
                # Continue and report.
                print(f"Skipped: {query}")
                print(f"Reason: {exc}")

        db.commit()

        print("\nReset completed.")
        print("Preserved:")
        print("- Super Admin users")
        print("- Template data")


if __name__ == "__main__":
    run_reset()

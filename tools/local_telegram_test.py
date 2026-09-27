"""Local-only helper for manually testing Telegram chunks T1, T2 and T6.

Run from the repo root with the backend virtualenv (it only needs httpx and
psycopg, both in backend/requirements.txt):

    backend\\.venv\\Scripts\\python.exe tools\\local_telegram_test.py <command>

Commands
    seed                         test people, an active project, a vendor
    relay [--once]               deliver the TEST bot's real messages and taps
                                 to the local backend (instead of a tunnel)
    link --who emp_a --chat ID   send that person's Telegram messages to chat ID
    link --who vendor --chat ID  same for the test vendor's contact
    buttons                      Acknowledge buttons still waiting to be pressed
    press --chat ID --data CODE  simulate tapping a button (no tunnel needed)
    say --chat ID --text "..." [--photo]
                                 simulate sending the bot a note (or a photo)
    expire-progress --chat ID    make that chat's Add Progress window time out now
    set-dates --task T002 --start tomorrow [--end today]
                                 give a test task planned dates (IST days)
    remind --at 09:00 [--day today] [--again]
                                 run the reminders as if it were that IST time
    acks                         what has been acknowledged so far
    tasks                        the test project's first tasks and their status

Never point this at anything but the local stack: it reads DATABASE_URL and
the Telegram webhook secret from the repo's .env and refuses a non-local
database.
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import httpx
import psycopg

ROOT = Path(__file__).resolve().parents[1]
API = "http://localhost:8000"
PROJECT_CODE = "TG-TEST"

PEOPLE = {
    "admin": ("Test Admin", "admin.test@siteops.local", "admin", "TADM", "Admin"),
    "pm": ("Test PM", "pm.test@siteops.local", "project_manager", "TPM", "Project Manager"),
    "supervisor": ("Test Supervisor", "sup.test@siteops.local", "supervisor", "TSUP", "Site Supervisor"),
    "emp_a": ("Rohan Employee", "emp.a@siteops.local", "internal_employee", "TEMPA", "Technician"),
    "emp_b": ("Priya Employee", "emp.b@siteops.local", "internal_employee", "TEMPB", "Technician"),
}
VENDOR_NAME = "Test Vendor Electricals"


def env() -> dict[str, str]:
    values = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            # Same as docker compose: " # ..." after a value is a comment.
            values[key.strip()] = value.split(" #", 1)[0].strip()
    return values


def db() -> psycopg.Connection:
    url = env()["DATABASE_URL"].replace("postgresql+psycopg://", "postgresql://")
    url = url.replace("host.docker.internal", "127.0.0.1")
    if "127.0.0.1" not in url and "localhost" not in url:
        sys.exit("Refusing to run: DATABASE_URL is not a local database.")
    return psycopg.connect(url, autocommit=True)


def token(email: str) -> str:
    response = httpx.post(f"{API}/api/auth/dev-login", json={"email": email}, timeout=30)
    response.raise_for_status()
    return response.json()["access_token"]


def call(method: str, path: str, email: str, body: dict | None = None, ok=(200, 201)) -> httpx.Response:
    response = httpx.request(
        method, f"{API}{path}", json=body, timeout=60, headers={"Authorization": f"Bearer {token(email)}"},
    )
    if response.status_code not in ok:
        sys.exit(f"{method} {path} failed ({response.status_code}): {response.text}")
    return response


def one(conn, sql: str, *params):
    row = conn.execute(sql, params).fetchone()
    return row[0] if row else None


def employee_id(conn, who: str):
    return one(conn, "select e.id from public.employee_profiles e join public.users u on u.id = e.user_id where u.email = %s", PEOPLE[who][1])


def user_id(conn, who: str):
    return one(conn, "select id from public.users where email = %s", PEOPLE[who][1])


def project_id(conn):
    return one(conn, "select id from siteops_v2.projects where code = %s", PROJECT_CODE)


# ---- seed --------------------------------------------------------------------


def seed(_args) -> None:
    conn = db()
    root = env()["BOOTSTRAP_SUPER_ADMIN_EMAIL"]
    for who, (name, email, role, code, designation) in PEOPLE.items():
        if user_id(conn, who) is None:
            call("POST", "/api/users/invite", root, {
                "name": name, "email": email, "role": role, "employee_code": code, "designation": designation,
            })
        token(email)  # first sign-in links the roster row to its login
    print("People: " + ", ".join(f"{who}={PEOPLE[who][1]}" for who in PEOPLE))

    admin = PEOPLE["admin"][1]
    if project_id(conn) is None:
        version = one(conn, "select id from siteops_v2.v2_template_versions where is_current_published order by created_at desc limit 1")
        if version is None:
            sys.exit("No published template. Run: docker exec siteops_mvp_backend python -m app.scripts.import_v2_template import --created-by-email <super admin email>")
        call("POST", "/api/v2/projects", admin, {
            "code": PROJECT_CODE, "name": "Telegram Test Site", "client_name": "Test Client",
            "site_address": "Test Site, Mumbai", "start_date": date.today().isoformat(),
            "project_manager_user_id": str(user_id(conn, "pm")), "supervisor_user_id": str(user_id(conn, "supervisor")),
            "template_version_id": str(version), "assignment_reason": "Local Telegram test",
        })
    pid = project_id(conn)
    status = one(conn, "select status from siteops_v2.projects where id = %s", pid)
    if status == "draft":
        member = one(conn, "select id from siteops_v2.project_memberships where project_id = %s and employee_id = %s and ends_at is null", pid, employee_id(conn, "emp_a"))
        if member is None:
            call("POST", f"/api/v2/projects/{pid}/memberships", admin, {
                "employee_id": str(employee_id(conn, "emp_a")), "project_role": "internal_employee", "reason": "Local Telegram test",
            })
        call("POST", f"/api/v2/projects/{pid}/activate", admin, {"reason": "Local Telegram test"})
    print(f"Project: {PROJECT_CODE} (Telegram Test Site) is active")

    # T1: Rohan is assigned to the first work task with no prerequisites (a
    # template task with no kind is ordinary work).
    first = one(conn, """
        select t.id from siteops_v2.tasks t
        where t.project_id = %s and coalesce(t.task_kind, 'work') = 'work'
          and not exists (select 1 from siteops_v2.task_dependencies d where d.successor_task_id = t.id)
        order by t.template_sequence limit 1""", pid)
    assigned = one(conn, "select id from siteops_v2.task_support_assignments where task_id = %s and ends_at is null", first)
    if assigned is None:
        call("POST", f"/api/v2/projects/{pid}/tasks/{first}/support-assignments", PEOPLE["supervisor"][1], {
            "employee_id": str(employee_id(conn, "emp_a")), "responsibility": "Execution",
        })
    print("T1 task: " + one(conn, "select original_code || ' - ' || title from siteops_v2.tasks where id = %s", first) + " -> assigned to Rohan")

    if one(conn, "select id from siteops_v2.vendors where name = %s", VENDOR_NAME) is None:
        vendor = uuid.uuid4()
        conn.execute(
            "insert into siteops_v2.vendors (id, name, contact_person, phone, status, engagement_type, created_by) "
            "values (%s, %s, 'Ramesh', '+919000000001', 'active', 'main', %s)",
            (vendor, VENDOR_NAME, user_id(conn, "admin")),
        )
        conn.execute(
            "insert into siteops_v2.vendor_contacts (id, vendor_id, name, phone, is_primary, active_channel) "
            "values (%s, %s, 'Ramesh', '+919000000001', true, 'whatsapp')",
            (uuid.uuid4(), vendor),
        )
    print(f"Vendor: {VENDOR_NAME} (not mapped to the project yet - map it in the Web App to test T2)")
    print("Priya (emp.b@siteops.local) is not on the project yet - add her in the Web App to test T2.")


# ---- Telegram helpers -----------------------------------------------------------------


def link(args) -> None:
    conn = db()
    chat = str(args.chat)
    conn.execute("update public.employee_profiles set telegram_chat_id = null where telegram_chat_id = %s", (chat,))
    conn.execute("update siteops_v2.vendor_contacts set telegram_chat_id = null where telegram_chat_id = %s", (chat,))
    if args.who == "vendor":
        conn.execute(
            "update siteops_v2.vendor_contacts set telegram_chat_id = %s, active_channel = 'telegram' "
            "where vendor_id = (select id from siteops_v2.vendors where name = %s)",
            (chat, VENDOR_NAME),
        )
    else:
        conn.execute(
            "update public.employee_profiles set telegram_chat_id = %s, active_channel = 'telegram' "
            "where user_id = (select id from public.users where email = %s)",
            (chat, PEOPLE[args.who][1]),
        )
    print(f"Chat {chat} now receives {args.who}'s Telegram messages (a chat can belong to only one person).")


def buttons(_args) -> None:
    conn = db()
    pid = project_id(conn)
    rows = conn.execute("""
        select 'project member ' || u.name, 'a1:pm:' || replace(m.id::text, '-', ''), e.telegram_chat_id
        from siteops_v2.project_memberships m join public.employee_profiles e on e.id = m.employee_id
        join public.users u on u.id = e.user_id
        where m.project_id = %(p)s and m.ends_at is null and m.acknowledged_at is null
        union all
        select 'task ' || t.original_code || ' for ' || u.name, 'a1:sa:' || replace(s.id::text, '-', ''), e.telegram_chat_id
        from siteops_v2.task_support_assignments s join siteops_v2.tasks t on t.id = s.task_id
        join public.employee_profiles e on e.id = s.employee_id join public.users u on u.id = e.user_id
        where s.project_id = %(p)s and s.ends_at is null and s.acknowledged_at is null
        union all
        select 'vendor on project', 'a1:pv:' || replace(pv.id::text, '-', ''),
               (select c.telegram_chat_id from siteops_v2.vendor_contacts c where c.vendor_id = pv.vendor_id and c.is_primary)
        from siteops_v2.project_vendors pv where pv.project_id = %(p)s and pv.ends_at is null and pv.acknowledged_at is null
        union all
        select 'vendor task ' || t.original_code, 'a1:va:' || replace(a.id::text, '-', ''),
               (select c.telegram_chat_id from siteops_v2.vendor_contacts c where c.vendor_id = a.vendor_id and c.is_primary)
        from siteops_v2.task_vendor_assignments a join siteops_v2.tasks t on t.id = a.task_id
        where a.project_id = %(p)s and a.ends_at is null and a.status = 'pending_ack'
    """, {"p": pid}).fetchall()
    if not rows:
        print("No Acknowledge buttons are waiting.")
    for what, code, chat in rows:
        print(f"{what:40} chat={chat or '-':12} {code}")


def press(args) -> None:
    conn = db()
    update_id = int(one(conn, "select coalesce(max(update_id), 900000) + 1 from siteops_v2.telegram_inbound_updates"))
    chat = int(args.chat)
    body = {"update_id": update_id, "callback_query": {
        "id": f"local-{update_id}", "from": {"id": chat}, "data": args.data,
        "message": {"message_id": 1, "chat": {"id": chat, "type": "private"}},
    }}
    response = httpx.post(
        f"{API}/api/v2/telegram/inbound", json=body, timeout=30,
        headers={"X-Telegram-Bot-Api-Secret-Token": env()["TELEGRAM_WEBHOOK_SECRET"]},
    )
    print(f"{response.status_code} {response.text} - check the bot's reply in Telegram.")


def say(args) -> None:
    """Simulates the person sending the bot a message (text, or a photo with a
    fake file id - fine for T6, whose replies come before any download)."""
    conn = db()
    update_id = int(one(conn, "select coalesce(max(update_id), 900000) + 1 from siteops_v2.telegram_inbound_updates"))
    chat = int(args.chat)
    message = {"message_id": update_id, "chat": {"id": chat, "type": "private"}, "from": {"id": chat}}
    if args.photo:
        message["photo"] = [{"file_id": f"local-photo-{update_id}", "file_size": 1000, "width": 10, "height": 10}]
        if args.text:
            message["caption"] = args.text
    else:
        message["text"] = args.text or "Test note"
    response = httpx.post(
        f"{API}/api/v2/telegram/inbound", json={"update_id": update_id, "message": message}, timeout=30,
        headers={"X-Telegram-Bot-Api-Secret-Token": env()["TELEGRAM_WEBHOOK_SECRET"]},
    )
    print(f"{response.status_code} {response.text} - check the bot's reply in Telegram.")


def relay(args) -> None:
    """Pulls the TEST bot's updates from Telegram (getUpdates) and hands each
    one to the local webhook - a tunnel without a tunnel. Real /start codes,
    button taps, notes and photos then reach the local backend. Refuses a bot
    that has a webhook: that bot's updates belong to a live server."""
    bot = f"https://api.telegram.org/bot{env()['TELEGRAM_ACCESS_TOKEN']}"
    me = httpx.get(f"{bot}/getMe", timeout=30).json()["result"]["username"]
    if httpx.get(f"{bot}/getWebhookInfo", timeout=30).json()["result"].get("url"):
        sys.exit(f"@{me} has a webhook set - it looks like a live bot. Relay refused.")
    secret = env()["TELEGRAM_WEBHOOK_SECRET"]
    print(f"Relaying @{me} -> {API}/api/v2/telegram/inbound (Ctrl+C to stop)")
    offset = None
    while True:
        try:
            params = {"timeout": 25, **({"offset": offset} if offset else {})}
            updates = httpx.get(f"{bot}/getUpdates", params=params, timeout=40).json().get("result", [])
        except httpx.HTTPError as exc:
            print(f"Telegram unreachable ({exc.__class__.__name__}), retrying in 5s...")
            time.sleep(5)
            continue
        for update in updates:
            offset = update["update_id"] + 1
            message = update.get("message") or {}
            what = (
                f"tap {update['callback_query'].get('data')}" if update.get("callback_query")
                else "/start <code>" if (message.get("text") or "").startswith("/start")
                else "photo/file" if message.get("photo") or message.get("document")
                else f"text {message.get('text', '')[:30]!r}"
            )
            response = httpx.post(
                f"{API}/api/v2/telegram/inbound", json=update, timeout=60,
                headers={"X-Telegram-Bot-Api-Secret-Token": secret},
            )
            print(f"{update['update_id']}: {what} -> local {response.status_code}")
        if args.once:
            if offset:  # tell Telegram these were delivered, so they aren't offered again
                httpx.get(f"{bot}/getUpdates", params={"offset": offset, "timeout": 0}, timeout=30)
            return


def _ist_day(value: str) -> date:
    today = (datetime.now(timezone.utc) + timedelta(hours=5, minutes=30)).date()
    offsets = {"yesterday": -1, "today": 0, "tomorrow": 1}
    return today + timedelta(days=offsets[value]) if value in offsets else date.fromisoformat(value)


def set_dates(args) -> None:
    """Gives a test task a planned start and/or finish date (IST days)."""
    conn = db()
    start = _ist_day(args.start) if args.start else None
    end = _ist_day(args.end) if args.end else None
    if start and end and end < start:
        start = end
    task = one(conn, "select id from siteops_v2.tasks where project_id = %s and original_code = %s", project_id(conn), args.task)
    if task is None:
        sys.exit(f"No task {args.task} in {PROJECT_CODE}.")
    conn.execute(
        "update siteops_v2.tasks set planned_start_date = coalesce(%s, planned_start_date), "
        "planned_end_date = coalesce(%s, planned_end_date) where id = %s", (start, end, task),
    )
    conn.execute(
        "update siteops_v2.tasks set planned_start_date = planned_end_date where id = %s and planned_end_date < planned_start_date",
        (task,),
    )
    row = conn.execute("select lifecycle_status, planned_start_date, planned_end_date from siteops_v2.tasks where id = %s", (task,)).fetchone()
    print(f"{args.task}: status {row[0]}, start {row[1]}, finish {row[2]}")


def remind(args) -> None:
    """Runs the reminder scheduler inside the backend as if it were --at (IST)
    on --day, then delivers the messages straight away."""
    day = _ist_day(args.day)
    hour, minute = (int(part) for part in args.at.split(":"))
    if args.again:
        db().execute("delete from siteops_v2.task_reminders_log where scheduled_for_date between %s and %s",
                     (day - timedelta(days=1), day + timedelta(days=1)))
    code = (
        "from datetime import datetime\n"
        "from app.database import SessionLocal\n"
        "from app.services.outbox_scheduler import run_dispatch_pass\n"
        "from app.services.task_reminders import IST, TaskReminderService\n"
        f"now = datetime({day.year}, {day.month}, {day.day}, {hour}, {minute}, tzinfo=IST)\n"
        "with SessionLocal() as s:\n"
        "    sent = TaskReminderService(s).send_due_reminders(now)\n"
        "    print(f'{len(sent)} reminder(s) at {now:%d %b %H:%M} IST:')\n"
        "    for kind, task in sent: print('  ', kind, task.original_code)\n"
        "run_dispatch_pass()\n"
    )
    import shutil
    import subprocess
    docker = shutil.which("docker") or r"C:\Program Files\Docker\Docker\resources\bin\docker.exe"
    subprocess.run([docker, "exec", "siteops_mvp_backend", "python", "-c", code], check=False)


def expire_progress(args) -> None:
    conn = db()
    count = conn.execute(
        "update siteops_v2.telegram_pending_inputs set expires_at = now() - interval '1 minute' "
        "where chat_id = %s and kind = 'task_add_progress'", (str(args.chat),),
    ).rowcount
    print("Add Progress window expired - now send a note or photo." if count else "No open Add Progress window for that chat.")


def acks(_args) -> None:
    conn = db()
    pid = project_id(conn)
    for sql in (
        "select 'member ' || u.name, m.acknowledged_at from siteops_v2.project_memberships m join public.employee_profiles e on e.id = m.employee_id join public.users u on u.id = e.user_id where m.project_id = %(p)s and m.ends_at is null",
        "select 'task ' || t.original_code || ' ' || u.name, s.acknowledged_at from siteops_v2.task_support_assignments s join siteops_v2.tasks t on t.id = s.task_id join public.employee_profiles e on e.id = s.employee_id join public.users u on u.id = e.user_id where s.project_id = %(p)s and s.ends_at is null",
        "select 'vendor on project', pv.acknowledged_at from siteops_v2.project_vendors pv where pv.project_id = %(p)s and pv.ends_at is null",
        "select 'vendor task ' || t.original_code || ' (' || a.status || ')', (select max(v.created_at) from siteops_v2.vendor_acknowledgements v where v.task_vendor_assignment_id = a.id) from siteops_v2.task_vendor_assignments a join siteops_v2.tasks t on t.id = a.task_id where a.project_id = %(p)s and a.ends_at is null",
    ):
        for what, at in conn.execute(sql, {"p": pid}).fetchall():
            print(f"{what:45} {'acknowledged ' + str(at) if at else 'not acknowledged'}")


def tasks(_args) -> None:
    conn = db()
    for code, title, status, task_hex in conn.execute(
        "select original_code, title, lifecycle_status, replace(id::text, '-', '') from siteops_v2.tasks "
        "where project_id = %s and coalesce(task_kind, 'work') = 'work' order by template_sequence limit 8", (project_id(conn),),
    ).fetchall():
        print(f"{code:6} {status:12} {task_hex}  {title}")
    print("Task buttons: t1:rd:<id> Mark Ready, t1:st:<id> Start, t1:ap:<id> Add Progress, t1:dn:<id> Done")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("seed").set_defaults(run=seed)
    p = sub.add_parser("link")
    p.add_argument("--who", required=True, choices=[*PEOPLE, "vendor"])
    p.add_argument("--chat", required=True)
    p.set_defaults(run=link)
    sub.add_parser("buttons").set_defaults(run=buttons)
    p = sub.add_parser("press")
    p.add_argument("--chat", required=True)
    p.add_argument("--data", required=True)
    p.set_defaults(run=press)
    p = sub.add_parser("say")
    p.add_argument("--chat", required=True)
    p.add_argument("--text")
    p.add_argument("--photo", action="store_true")
    p.set_defaults(run=say)
    p = sub.add_parser("relay")
    p.add_argument("--once", action="store_true", help="deliver what is waiting, then stop")
    p.set_defaults(run=relay)
    p = sub.add_parser("set-dates")
    p.add_argument("--task", required=True, help="task code, e.g. T002")
    p.add_argument("--start", help="yesterday / today / tomorrow / YYYY-MM-DD")
    p.add_argument("--end", help="yesterday / today / tomorrow / YYYY-MM-DD")
    p.set_defaults(run=set_dates)
    p = sub.add_parser("remind")
    p.add_argument("--at", required=True, help="IST time, e.g. 09:00, 13:30, 18:30, 06:30, 09:30")
    p.add_argument("--day", default="today", help="yesterday / today / tomorrow / YYYY-MM-DD")
    p.add_argument("--again", action="store_true", help="forget reminders already sent around that day first")
    p.set_defaults(run=remind)
    p = sub.add_parser("expire-progress")
    p.add_argument("--chat", required=True)
    p.set_defaults(run=expire_progress)
    sub.add_parser("acks").set_defaults(run=acks)
    sub.add_parser("tasks").set_defaults(run=tasks)
    args = parser.parse_args()
    args.run(args)


if __name__ == "__main__":
    main()

"""Issue silent opening statements so clients keep seeing today's balance.

Usage (stop the app first):
    python scripts/issue_opening_statements.py --dry-run
    python scripts/issue_opening_statements.py --backup-dir D:\\law-office-backups

--dry-run makes no backup and no writes; it prints, per client, the legacy
balance, the balance after migration and the difference (rows differing by
$1.00 or more are flagged). The real run backs up client-accounts/,
client-billing/ and firm-settings/ to a timestamped folder under --backup-dir
(refused inside this OneDrive-synced project), then for each client issues an
'opening' statement (no email) for all not-yet-covered time, or a baseline when
there's nothing positive to bill. Safe to re-run. The migration is only marked
complete when no record was unreadable or skipped.

To roll back: stop the app, copy client-accounts/, client-billing/ and
firm-settings/ back from the backup folder, and delete
firm-settings/migrations.json if the backup lacks it.
"""

import argparse
import math
import shutil
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import shared   # noqa: E402
import billing  # noqa: E402

try:
    from dotenv import load_dotenv
except ImportError:  # pragma: no cover
    def load_dotenv(*_a, **_k):
        return False

LAST_BACKUP = None
LAST_REPORT = []   # rows: (username, legacy_due, new_due, delta, action)


def _legacy_due(client) -> float:
    owed = round(float(client.get("hours_billed") or 0) - float(client.get("hours_paid") or 0), 2)
    return max(0.0, round(owed * float(shared.HOURLY_RATE), 2))


def _plan(client, ledger):
    """Read-only: (action, new_due) the migration will produce for this client.
    Raises ValueError for non-finite hours."""
    log = client.get("billing_log") or []
    if ledger["covered_through"] >= len(log):
        return "covered", billing.amount_due(client, ledger)
    entries = billing.unbilled_entries(client, ledger)
    hours = billing._hours(entries)
    if not math.isfinite(hours):
        raise ValueError("non-finite hours in billing log")
    if entries and hours > 0:
        amount = round(hours * float(shared.HOURLY_RATE), 2)
        new_due = max(0.0, round(billing.statement_total(ledger) + amount
                                 - billing.paid_total(client), 2))
        return "opening", new_due
    return "baseline", billing.amount_due(client, ledger)


def migrate(backup_root, project_root: Path = ROOT, dry_run: bool = False) -> dict:
    global LAST_BACKUP, LAST_REPORT
    LAST_BACKUP = None
    LAST_REPORT = []
    dest = None
    if not dry_run:
        shared.require_outside_dir(backup_root, project_root)
        stamp = f"{datetime.now():%Y%m%d_%H%M%S_%f}"
        dest = Path(backup_root).resolve() / f"billing-migration-{stamp}"
        shutil.copytree(shared.CLIENT_ACCOUNTS_DIR, dest / "client-accounts")
        for name, src in (("client-billing", shared.CLIENT_BILLING_DIR),
                          ("firm-settings", shared.FIRM_SETTINGS_DIR)):
            if Path(src).exists():
                shutil.copytree(src, dest / name)
    counts = {"opening": 0, "baseline": 0, "covered": 0, "unreadable": 0, "skipped": 0}
    for path in sorted(shared.CLIENT_ACCOUNTS_DIR.glob("*.json")):
        username = path.stem
        legacy = None
        try:
            client = shared.load_client(username)
            if not client:
                print(f"  ! skipped (not loadable): {path.name}")
                counts["skipped"] += 1
                LAST_REPORT.append((username, None, None, None, "skipped"))
                continue
            legacy = _legacy_due(client)
            ledger = billing.load_ledger(username)
            action, new_due = _plan(client, ledger)
            if not dry_run:
                if action == "covered":
                    pass
                elif billing.issue_statement(username, reason="opening", issued_by="migration",
                                             notify=False):
                    action = "opening"
                elif billing.set_baseline(username):
                    action = "baseline"
                else:
                    action = "covered"
                if action != "opening":
                    fresh = shared.load_client(username)
                    new_due = billing.amount_due(fresh, billing.load_ledger(username))
            counts[action] += 1
            LAST_REPORT.append((username, legacy, new_due, round(new_due - legacy, 2), action))
        except Exception as exc:
            print(f"  ! {username}: {exc}")
            counts["unreadable"] += 1
            LAST_REPORT.append((username, legacy, None, None, "unreadable"))
    if not dry_run:
        if counts["unreadable"] == 0 and counts["skipped"] == 0:
            billing.mark_migrated()
        LAST_BACKUP = dest
    return counts


def _money(v):
    return "-" if v is None else f"{v:,.2f}"


def print_report(report):
    print(f"{'Client':<28}{'Legacy due':>14}{'New due':>14}{'Delta':>12}  Action")
    for username, legacy, new_due, delta, action in report:
        flag = "  <-- CHECK" if delta is not None and abs(delta) >= 1.00 else ""
        print(f"{username:<28}{_money(legacy):>14}{_money(new_due):>14}{_money(delta):>12}  {action}{flag}")
    print(f"Totals: legacy {_money(sum(r[1] or 0 for r in report))}, "
          f"new {_money(sum(r[2] or 0 for r in report))}")


def main():
    load_dotenv(ROOT / ".env")
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--backup-dir")
    parser.add_argument("--dry-run", action="store_true",
                        help="report what would happen; no backup, no writes")
    args = parser.parse_args()
    if not args.dry_run and not args.backup_dir:
        parser.error("--backup-dir is required unless --dry-run is given")
    try:
        shared._fernet()
    except RuntimeError as exc:
        print(exc)
        return 2
    counts = migrate(Path(args.backup_dir) if args.backup_dir else None, dry_run=args.dry_run)
    print_report(LAST_REPORT)
    print(f"Opening statements: {counts['opening']}")
    print(f"Baselines:          {counts['baseline']}")
    print(f"Already covered:    {counts['covered']}")
    print(f"Unreadable:         {counts['unreadable']}")
    print(f"Skipped:            {counts['skipped']}")
    if args.dry_run:
        print("Dry run: nothing was written.")
    else:
        print(f"Backup written to {LAST_BACKUP} (encrypted copies; keep until you've checked balances)")
        if counts["unreadable"] or counts["skipped"]:
            print("Migration NOT marked complete - fix the records listed above and "
                  "re-run (safe to re-run).")
    return 1 if (counts["unreadable"] or counts["skipped"]) else 0


if __name__ == "__main__":
    raise SystemExit(main())

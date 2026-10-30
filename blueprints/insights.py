"""blueprints/insights.py — attorney token usage, firm insights, and tax export."""

from datetime import datetime

from flask import Blueprint, render_template, request, jsonify, session

import shared
from shared import require_attorney, ATTORNEYS
from services.storage import all_clients, read_json

# Data folders and money settings are read as shared.<NAME> at call time, so
# the test suite's patched values reach these routes.

insights_bp = Blueprint("insights", __name__)


# ── Token usage ────────────────────────────────────────────────────────────────

@insights_bp.route("/portal/attorney/token-usage")
@require_attorney
def attorney_token_usage():
    username = session.get("username", "")
    path     = shared.TOKEN_USAGE_DIR / f"{username}.json"
    if not path.exists():
        return jsonify({
            "total_input_tokens": 0, "total_output_tokens": 0,
            "today_input": 0, "today_output": 0,
            "log": [], "by_label": {}
        })
    data  = read_json(path, {})
    today = datetime.now().strftime("%Y-%m-%d")
    today_in = today_out = 0
    by_label: dict = {}
    for entry in data.get("log", []):
        lbl = entry.get("label", "Other")
        by_label.setdefault(lbl, {"input": 0, "output": 0, "calls": 0})
        by_label[lbl]["input"]  += entry.get("input_tokens", 0)
        by_label[lbl]["output"] += entry.get("output_tokens", 0)
        by_label[lbl]["calls"]  += 1
        if entry.get("timestamp", "").startswith(today):
            today_in  += entry.get("input_tokens", 0)
            today_out += entry.get("output_tokens", 0)
    return jsonify({
        "total_input_tokens":  data.get("total_input_tokens", 0),
        "total_output_tokens": data.get("total_output_tokens", 0),
        "today_input":         today_in,
        "today_output":        today_out,
        "by_label":            by_label,
    })


# ── Firm Insights & Tax Export ─────────────────────────────────────────────────

@insights_bp.route("/portal/attorney/insights")
@require_attorney
def attorney_insights():
    try:
        year = int(request.args.get("year", datetime.now().year))
    except ValueError:
        year = datetime.now().year

    clients_list = all_clients()

    all_leads = []
    for p in shared.LEADS_DIR.glob("*.json"):
        lead = read_json(p)
        if isinstance(lead, dict):
            all_leads.append(lead)

    intake_count       = len(list(shared.CLIENT_FILES_DIR.rglob("intake_*.pdf")))
    total_client_files = sum(1 for p in shared.CLIENT_FILES_DIR.rglob("*") if p.is_file())
    research_sessions  = len(list(shared.RESEARCH_HISTORY_DIR.glob("*.json")))
    draft_sessions     = len(list(shared.DRAFT_HISTORY_DIR.glob("*.json")))

    atty_stats: dict = {}
    for uname, info in ATTORNEYS.items():
        atty_stats[uname] = {
            "display":                  info["display"],
            "total_clients":            0,
            "total_hours_billed":       0.0,
            "total_hours_paid":         0.0,
            "total_revenue_billed":     0.0,
            "total_revenue_collected":  0.0,
            "year_hours_billed":        0.0,
            "year_revenue_billed":      0.0,
            "year_revenue_collected":   0.0,
            "clients_with_court_dates": 0,
            "clients_with_meetings":    0,
            "total_messages":           0,
            "total_time_logs":          0,
            "case_types":               {},
        }

    total_court_dates   = 0
    total_meetings      = 0
    total_messages      = 0
    total_time_logs     = 0
    total_payments_sum  = 0.0
    case_type_breakdown: dict = {}

    for c in clients_list:
        atty = c.get("assigned_attorney", "")
        if atty not in atty_stats:
            continue
        s = atty_stats[atty]
        s["total_clients"] += 1

        hrs      = float(c.get("hours_billed", 0) or 0)
        hrs_paid = float(c.get("hours_paid",   0) or 0)
        s["total_hours_billed"]     += hrs
        s["total_hours_paid"]       += hrs_paid
        s["total_revenue_billed"]   += hrs * shared.HOURLY_RATE

        pmt_sum = sum(float(p.get("amount", 0) or 0) for p in c.get("payments", []))
        s["total_revenue_collected"] += pmt_sum
        total_payments_sum           += pmt_sum

        ct = c.get("case_type", "Other")
        s["case_types"][ct] = s["case_types"].get(ct, 0) + 1
        case_type_breakdown[ct] = case_type_breakdown.get(ct, 0) + 1

        if c.get("next_court_date"):
            total_court_dates += 1
            s["clients_with_court_dates"] += 1
        if c.get("next_meeting"):
            total_meetings += 1
            s["clients_with_meetings"] += 1

        msgs  = len(c.get("messages", []))
        tlogs = len(c.get("time_logs", []))
        total_messages  += msgs
        total_time_logs += tlogs
        s["total_messages"]  += msgs
        s["total_time_logs"] += tlogs

        for entry in c.get("billing_log", []):
            if str(entry.get("date", "")).startswith(str(year)):
                e_hrs = float(entry.get("hours", 0) or 0)
                s["year_hours_billed"]   += e_hrs
                s["year_revenue_billed"] += e_hrs * shared.HOURLY_RATE

        for pmt in c.get("payments", []):
            if str(pmt.get("date", "")).startswith(str(year)):
                s["year_revenue_collected"] += float(pmt.get("amount", 0) or 0)

    for s in atty_stats.values():
        for k in ("total_hours_billed", "total_hours_paid", "total_revenue_billed",
                  "total_revenue_collected", "year_hours_billed",
                  "year_revenue_billed", "year_revenue_collected"):
            s[k] = round(s[k], 2)

    total_leads     = len(all_leads)
    active_leads    = sum(1 for l in all_leads if not l.get("archived"))
    archived_leads  = sum(1 for l in all_leads if l.get("archived"))
    total_clients   = len(clients_list)
    # Share of everyone who ever contacted the firm (every lead, plus clients who
    # came in through intake without a lead record) that became a client.
    denom           = max(total_leads, total_clients)
    conversion_rate = round(total_clients / denom * 100, 1) if denom else 0

    leads_by_source:    dict = {}
    leads_by_case_type: dict = {}
    for l in all_leads:
        src = l.get("source", "Direct")
        leads_by_source[src] = leads_by_source.get(src, 0) + 1
        lct = l.get("case_type", "Unknown")
        leads_by_case_type[lct] = leads_by_case_type.get(lct, 0) + 1

    total_hours      = sum(float(c.get("hours_billed", 0) or 0) for c in clients_list)
    _raw_monthly     = (shared.MONTHLY_RENT + shared.MONTHLY_SALARIES + shared.MONTHLY_SOFTWARE +
                        shared.MONTHLY_INSURANCE + shared.MONTHLY_MARKETING + shared.MONTHLY_MISC)
    monthly_overhead = round(_raw_monthly, 2)
    annual_overhead  = round(_raw_monthly * 12, 2)
    overhead_reserve = round(total_payments_sum * shared.OVERHEAD_RESERVE_PCT, 2)
    est_net_profit   = round(total_payments_sum - overhead_reserve, 2)

    return jsonify({
        "year": year,
        "firm": {
            "total_clients":           total_clients,
            "total_hours_billed":      round(total_hours, 2),
            "total_revenue_billed":    round(total_hours * shared.HOURLY_RATE, 2),
            "total_revenue_collected": round(total_payments_sum, 2),
            "total_court_dates":       total_court_dates,
            "total_meetings":          total_meetings,
            "total_messages":          total_messages,
            "total_time_logs":         total_time_logs,
            "total_client_files":      total_client_files,
            "research_sessions":       research_sessions,
            "draft_sessions":          draft_sessions,
            "intake_forms":            intake_count,
            "hourly_rate":             shared.HOURLY_RATE,
            "case_type_breakdown":     case_type_breakdown,
        },
        "leads": {
            "total":           total_leads,
            "active":          active_leads,
            "archived":        archived_leads,
            "conversion_rate": conversion_rate,
            "by_source":       leads_by_source,
            "by_case_type":    leads_by_case_type,
        },
        "overhead": {
            "monthly_rent":      shared.MONTHLY_RENT,
            "monthly_salaries":  shared.MONTHLY_SALARIES,
            "monthly_software":  shared.MONTHLY_SOFTWARE,
            "monthly_insurance": shared.MONTHLY_INSURANCE,
            "monthly_marketing": shared.MONTHLY_MARKETING,
            "monthly_misc":      shared.MONTHLY_MISC,
            "monthly_total":     monthly_overhead,
            "annual_total":      annual_overhead,
            "reserve_pct":       shared.OVERHEAD_RESERVE_PCT,
            "overhead_reserve":  overhead_reserve,
            "est_net_profit":    est_net_profit,
        },
        "attorneys": atty_stats,
    })


@insights_bp.route("/portal/attorney/insights/export-tax")
@require_attorney
def insights_export_tax():
    try:
        year = int(request.args.get("year", datetime.now().year))
    except ValueError:
        year = datetime.now().year
    atty_filter  = request.args.get("attorney", "")
    clients_list = all_clients()
    summaries    = []

    for uname, info in ATTORNEYS.items():
        if atty_filter and uname != atty_filter:
            continue
        s = {
            "username":       uname,
            "display":        info["display"],
            "year_hours":     0.0,
            "year_revenue":   0.0,
            "year_collected": 0.0,
            "cases":          0,
            "case_list":      [],
        }
        for c in clients_list:
            if c.get("assigned_attorney") != uname:
                continue
            s["cases"] += 1
            for entry in c.get("billing_log", []):
                if str(entry.get("date", "")).startswith(str(year)):
                    e_hrs = float(entry.get("hours", 0) or 0)
                    s["year_hours"]   += e_hrs
                    s["year_revenue"] += e_hrs * shared.HOURLY_RATE
            for pmt in c.get("payments", []):
                if str(pmt.get("date", "")).startswith(str(year)):
                    s["year_collected"] += float(pmt.get("amount", 0) or 0)
            s["case_list"].append({
                "name": c.get("client_name", ""),
                "type": c.get("case_type",   ""),
                "hrs":  round(float(c.get("hours_billed", 0) or 0), 2),
            })
        s["year_hours"]     = round(s["year_hours"],     2)
        s["year_revenue"]   = round(s["year_revenue"],   2)
        s["year_collected"] = round(s["year_collected"], 2)
        summaries.append(s)

    return render_template(
        "tax_summary.html",
        year=year,
        summaries=summaries,
        hourly_rate=shared.HOURLY_RATE,
    )

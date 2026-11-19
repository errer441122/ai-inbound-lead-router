"""Native CSV readers for Advertising, Web/Product Analytics, CRM/ESP, and E-commerce exports.

Auto-detects standard exports from:
- Meta Ads Manager (Campaign/Ad set spend, leads, purchases, reported ROAS)
- Meta Lead Center / Instant Forms (Lead-level email -> campaign mapping, including UTF-16 TSV/CSV)
- GA4 Traffic/User Acquisition (comment-line stripping, campaign sessions & revenue)
- Amplitude / Mixpanel / Adobe Analytics (generic event/user attribution export)
- Klaviyo Lists & Segments Export (Double Opt-In consent, suppression, Initial Campaign)
- HubSpot Contacts Export (Marketing status, DOI, Lifecycle Stage, Original Traffic Source Drill-Down)
- HubSpot Deals Export (B2B pipeline & Closed-Won revenue)
- Shopify Orders Export (line-item folding, refund/void filtering, Discount Amount, 1st & 2nd orders)

Pure Python standard library (identical execution in CLI and browser Pyodide).
"""

from __future__ import annotations

import csv
import hashlib
import io
from datetime import date, datetime
from pathlib import Path

FORMULA_START = ("=", "+", "-", "@", "\t", "\r")
DATE_FORMATS = ("%Y-%m-%d", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d")
NOT_A_SALE = {"refunded", "voided"}
SINGLE_OPTIN_LEAK_SOURCES = {
    "shopify",
    "shopify_checkout",
    "shopify_checkout_checkbox",
    "meta_instant_form_raw",
    "manual_import",
    "csv_import",
}


def safe_cell(value: object) -> str:
    text = "" if value is None else str(value)
    return "'" + text if text.startswith(FORMULA_START) else text


def sha256_email(email: str) -> str:
    """Meta Custom Audiences standard: lowercase, trimmed, UTF-8 SHA-256 hex digest."""
    return hashlib.sha256(email.strip().lower().encode("utf-8")).hexdigest()


def norm_campaign(name: str | None) -> str:
    return " ".join((name or "").strip().lower().split())


def read_text_tolerant(path: Path) -> str:
    raw = path.read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):
        return raw.decode("utf-16")
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


def read_csv_rows(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    text = read_text_tolerant(path)
    lines = text.splitlines()
    start = 0
    while start < len(lines) and (not lines[start].strip() or lines[start].lstrip().startswith("#")):
        start += 1
    body = "\n".join(lines[start:])
    if not body.strip():
        return [], []
    header_line = lines[start]
    delimiter = max(",;\t", key=header_line.count)
    reader = csv.DictReader(io.StringIO(body, newline=""), delimiter=delimiter)
    cols = [c.strip() for c in (reader.fieldnames or [])]
    rows: list[dict[str, str]] = []
    for raw in reader:
        cleaned = {(k.strip() if k else ""): (v or "").strip() for k, v in raw.items()}
        if any(cleaned.values()):
            rows.append(cleaned)
    return cols, rows


def to_csv_text(header: list[str], rows: list[list[object]]) -> str:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    for r in rows:
        w.writerow([safe_cell(c) if isinstance(c, str) else c for c in r])
    return buf.getvalue()


def parse_day(text: str | None) -> date | None:
    raw = (text or "").strip()
    if not raw:
        return None
    head = raw.split()[0].split("T")[0]
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(head, fmt).date()
        except ValueError:
            continue
    return None


def parse_amount(text: str | None) -> float:
    cleaned = "".join(ch for ch in (text or "") if ch.isdigit() or ch in ",.-")
    if not cleaned or cleaned in ("-", ".", ","):
        return 0.0
    if "," in cleaned and "." in cleaned:
        cleaned = cleaned.replace(".", "").replace(",", ".") if cleaned.rfind(",") > cleaned.rfind(".") else cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    return float(cleaned)


def _col(columns: list[str], *candidates: str) -> str | None:
    low_map = {c.lower(): c for c in columns}
    for cand in candidates:
        if cand in columns:
            return cand
        if cand.lower() in low_map:
            return low_map[cand.lower()]
    # Prefix match for localized Meta columns like "Amount spent (EUR)" or "Amount spent (USD)"
    for cand in candidates:
        cl = cand.lower()
        for col in columns:
            if col.lower().startswith(cl):
                return col
    return None


def _truthy(val: str | None) -> bool:
    return (val or "").strip().lower() in {"true", "yes", "1", "y", "si", "sì"}


def read_ads_spend(path: Path) -> tuple[str, dict[str, dict]]:
    """Read Meta Ads Manager (or generic paid campaign) CSV aggregated by campaign."""
    cols, rows = read_csv_rows(path)
    camp_col = _col(cols, "Campaign name", "Campaign", "campaign_name", "utm_campaign")
    spend_col = _col(cols, "Amount spent", "Spend", "Cost", "ad_spend")
    if not camp_col or not spend_col:
        raise ValueError(
            "Unrecognised Ads export: expected Meta Ads Manager columns "
            "('Campaign name' and 'Amount spent (...)') or campaign_name + ad_spend."
        )

    impr_col = _col(cols, "Impressions")
    click_col = _col(cols, "Link clicks", "Clicks (all)", "Clicks")
    leads_col = _col(cols, "Leads", "On-Facebook leads", "Website leads", "Results", "Conversions")
    purch_col = _col(cols, "Purchases", "Website purchases")
    roas_col = _col(cols, "Purchase ROAS", "ROAS")
    rev_col = _col(cols, "Purchases conversion value", "Website purchases conversion value", "Platform revenue")

    fmt = "meta_ads_manager" if "Campaign name" in cols or any(c.startswith("Amount spent") for c in cols) else "generic_ads"
    campaigns: dict[str, dict] = {}

    for row in rows:
        raw_name = row.get(camp_col, "").strip()
        if not raw_name or raw_name.lower() in {"total", "all", "results"}:
            continue
        key = norm_campaign(raw_name)
        c = campaigns.setdefault(
            key,
            {
                "campaign_key": key,
                "campaign_name": raw_name,
                "ad_spend": 0.0,
                "impressions": 0,
                "clicks": 0,
                "platform_leads": 0,
                "platform_purchases": 0,
                "platform_reported_revenue": 0.0,
            },
        )
        spend = parse_amount(row.get(spend_col))
        c["ad_spend"] += spend
        if impr_col:
            c["impressions"] += int(round(parse_amount(row.get(impr_col))))
        if click_col:
            c["clicks"] += int(round(parse_amount(row.get(click_col))))
        if leads_col:
            c["platform_leads"] += int(round(parse_amount(row.get(leads_col))))
        if purch_col:
            c["platform_purchases"] += int(round(parse_amount(row.get(purch_col))))
        if rev_col and row.get(rev_col):
            c["platform_reported_revenue"] += parse_amount(row.get(rev_col))
        elif roas_col and row.get(roas_col):
            c["platform_reported_revenue"] += spend * parse_amount(row.get(roas_col))

    for c in campaigns.values():
        c["ad_spend"] = round(c["ad_spend"], 2)
        c["platform_reported_revenue"] = round(c["platform_reported_revenue"], 2)
    return fmt, campaigns


def read_lead_capture(path: Path) -> tuple[str, dict[str, dict]]:
    """Read Meta Lead Ads / Instant Form CSV or Product Analytics (Amplitude/Mixpanel) user->campaign map."""
    cols, rows = read_csv_rows(path)
    email_col = _col(cols, "email", "Email", "user_email")
    camp_col = _col(cols, "campaign_name", "Campaign name", "utm_campaign", "Initial Campaign", "campaign")
    if not email_col or not camp_col:
        raise ValueError("Unrecognised lead/analytics export: expected email and campaign_name/utm_campaign columns.")

    adset_col = _col(cols, "adset_name", "Ad set name", "utm_content")
    created_col = _col(cols, "created_time", "Created Time", "event_time", "created_at")
    fmt = "meta_lead_ads" if "form_name" in cols or "adset_name" in cols else "analytics_user_attribution"
    leads: dict[str, dict] = {}
    for row in rows:
        email = row.get(email_col, "").strip().lower()
        camp = row.get(camp_col, "").strip()
        if not email or not camp:
            continue
        leads.setdefault(
            email,
            {
                "email": email,
                "campaign_key": norm_campaign(camp),
                "campaign_name": camp,
                "adset_name": row.get(adset_col, "") if adset_col else "",
                "captured_date": parse_day(row.get(created_col)) if created_col else None,
            },
        )
    return fmt, leads


def read_ga4_campaigns(path: Path) -> dict[str, dict]:
    """Read GA4 Traffic/User Acquisition CSV export aggregated by campaign."""
    cols, rows = read_csv_rows(path)
    camp_col = _col(cols, "Session campaign", "First user campaign", "Campaign", "utm_campaign")
    if not camp_col:
        raise ValueError("Unrecognised GA4 export: expected 'Session campaign' or 'First user campaign'.")
    sess_col = _col(cols, "Sessions", "Total users")
    conv_col = _col(cols, "Key events", "Conversions")
    rev_col = _col(cols, "Purchase revenue", "Total revenue", "Revenue")
    out: dict[str, dict] = {}
    for row in rows:
        camp = row.get(camp_col, "").strip()
        if not camp or camp.startswith("("):
            continue
        key = norm_campaign(camp)
        g = out.setdefault(key, {"campaign_name": camp, "ga4_sessions": 0, "ga4_key_events": 0, "ga4_revenue": 0.0})
        if sess_col:
            g["ga4_sessions"] += int(round(parse_amount(row.get(sess_col))))
        if conv_col:
            g["ga4_key_events"] += int(round(parse_amount(row.get(conv_col))))
        if rev_col:
            g["ga4_revenue"] = round(g["ga4_revenue"] + parse_amount(row.get(rev_col)), 2)
    return out


def read_crm_contacts(path: Path) -> tuple[str, dict[str, dict]]:
    """Read native Klaviyo List Export or HubSpot Contacts Export with GDPR DOI & attribution."""
    cols, rows = read_csv_rows(path)
    col_set = set(cols)
    email_col = _col(cols, "Email", "email")
    if not email_col:
        raise ValueError("Unrecognised CRM export: missing Email column.")

    is_klaviyo = bool(col_set & {"Email Marketing Consent", "Klaviyo ID", "Email Marketing Consent Method"})
    is_hubspot = bool(col_set & {"Marketing contact status", "Original Traffic Source", "Lifecycle Stage"})
    fmt = "klaviyo_list_export" if is_klaviyo else ("hubspot_contacts_export" if is_hubspot else "canonical_crm")

    contacts: dict[str, dict] = {}
    for row in rows:
        email = row.get(email_col, "").strip().lower()
        if not email:
            continue

        if fmt == "klaviyo_list_export":
            raw_status = row.get(_col(cols, "Email Marketing Consent") or "", "").lower()
            supp = row.get(_col(cols, "Email Suppression Reason", "Suppression Reason") or "", "")
            method = row.get(_col(cols, "Email Marketing Consent Method", "Consent Method") or "", "")
            ts = row.get(_col(cols, "Email Marketing Consent Timestamp", "Consent Timestamp") or "", "")
            doi = row.get(_col(cols, "Email Marketing Double Opt-In", "Double Opt-In") or "", "").lower()
            camp = row.get(_col(cols, "Initial Campaign", "utm_campaign", "Campaign") or "", "")

            if supp:
                consent_state = "hard_bounce" if "bounce" in supp.lower() else "opted_out"
            elif raw_status in {"subscribed", "opted_in", "true", "yes"}:
                if not method or not parse_day(ts):
                    consent_state = "missing_proof"
                elif doi in {"false", "no", "0", "single"} or method.lower().replace(" ", "_") in SINGLE_OPTIN_LEAK_SOURCES:
                    consent_state = "single_optin_unconfirmed"
                else:
                    consent_state = "verified_doi"
            elif raw_status in {"unsubscribed", "opted_out"}:
                consent_state = "opted_out"
            else:
                consent_state = "unconfirmed"

            contacts[email] = {
                "email": email,
                "consent_state": consent_state,
                "consent_source": method,
                "consent_timestamp": ts,
                "campaign_key": norm_campaign(camp),
                "campaign_name": camp,
                "lifecycle_stage": "",
            }
            continue

        if fmt == "hubspot_contacts_export":
            unsub = _truthy(row.get(_col(cols, "Unsubscribed from all email", "Opted out of email") or "", ""))
            bounce = row.get(_col(cols, "Email hard bounce reason") or "", "")
            mkt = row.get(_col(cols, "Marketing contact status") or "", "").lower()
            legal = row.get(_col(cols, "Legal basis for processing contact's data") or "", "")
            doi = row.get(_col(cols, "Double opt-in status", "Marketing email confirmation status") or "", "").lower()
            ts = row.get(_col(cols, "Marketing email confirmation date", "Create Date") or "", "")
            stage = row.get(_col(cols, "Lifecycle Stage") or "", "").strip().lower()
            camp = row.get(
                _col(cols, "Original Traffic Source Drill-Down 1", "utm_campaign", "Campaign") or "",
                "",
            )
            src = row.get(_col(cols, "Original Traffic Source") or "", "")

            if bounce:
                consent_state = "hard_bounce"
            elif unsub:
                consent_state = "opted_out"
            elif mkt and "non-marketing" in mkt:
                consent_state = "non_marketing_contact"
            elif doi in {"confirmation pending", "pending", "unconfirmed", "false", "no"}:
                consent_state = "unconfirmed"
            elif ("freely given consent" in legal.lower() or "marketing contact" in mkt) and parse_day(ts):
                consent_state = "verified_doi"
            else:
                consent_state = "missing_proof"

            contacts[email] = {
                "email": email,
                "consent_state": consent_state,
                "consent_source": src or legal,
                "consent_timestamp": ts,
                "campaign_key": norm_campaign(camp),
                "campaign_name": camp,
                "lifecycle_stage": stage,
            }
            continue

        # Canonical fallback
        status = row.get(_col(cols, "consent_status") or "", "").lower()
        ts = row.get(_col(cols, "consent_timestamp") or "", "")
        src = row.get(_col(cols, "consent_source") or "", "")
        camp = row.get(_col(cols, "utm_campaign", "campaign_name", "campaign") or "", "")
        consent_state = "verified_doi" if (status == "opted_in" and src and parse_day(ts)) else (status or "unconfirmed")
        contacts[email] = {
            "email": email,
            "consent_state": consent_state,
            "consent_source": src,
            "consent_timestamp": ts,
            "campaign_key": norm_campaign(camp),
            "campaign_name": camp,
            "lifecycle_stage": row.get(_col(cols, "lifecycle_stage") or "", "").lower(),
        }

    return fmt, contacts


def read_shopify_orders(path: Path) -> tuple[str, dict[str, dict]]:
    """Read Shopify Orders > Export or canonical orders CSV -> per-customer 1st/2nd order stats."""
    cols, rows = read_csv_rows(path)
    is_shopify = {"Name", "Email", "Created at", "Total"} <= set(cols)

    events: list[dict] = []
    if is_shopify:
        folded: dict[str, dict[str, str]] = {}
        for r in rows:
            name = r.get("Name", "")
            if not name:
                continue
            target = folded.setdefault(name, {})
            for k, v in r.items():
                if v and not target.get(k):
                    target[k] = v
        for name, o in folded.items():
            if o.get("Cancelled at") or o.get("Financial Status", "").lower() in NOT_A_SALE:
                continue
            email = o.get("Email", "").strip().lower()
            when = parse_day(o.get("Created at"))
            if not email or when is None:
                continue
            events.append({
                "email": email,
                "order_date": when,
                "net_value": parse_amount(o.get("Total")),
                "discount": parse_amount(o.get("Discount Amount")),
                "discount_code": o.get("Discount Code", ""),
            })
        fmt = "shopify_orders"
    else:
        email_col = _col(cols, "email", "Email")
        date_col = _col(cols, "order_date", "created_at", "date")
        val_col = _col(cols, "order_value", "total", "order_value_eur", "revenue")
        disc_col = _col(cols, "discount_amount", "discount")
        if not email_col or not date_col or not val_col:
            raise ValueError("Unrecognised orders CSV: expected Shopify Orders export or email + order_date + order_value.")
        for r in rows:
            email = r.get(email_col, "").strip().lower()
            when = parse_day(r.get(date_col))
            if not email or when is None:
                continue
            events.append({
                "email": email,
                "order_date": when,
                "net_value": parse_amount(r.get(val_col)),
                "discount": parse_amount(r.get(disc_col)) if disc_col else 0.0,
                "discount_code": "",
            })
        fmt = "canonical_orders"

    by_email: dict[str, list[dict]] = {}
    for ev in events:
        by_email.setdefault(ev["email"], []).append(ev)

    agg: dict[str, dict] = {}
    for email, evs in by_email.items():
        evs.sort(key=lambda e: e["order_date"])
        distinct_days = sorted({e["order_date"] for e in evs})
        has_second = len(distinct_days) >= 2
        days_to_second = (distinct_days[1] - distinct_days[0]).days if has_second else None
        total_rev = round(sum(e["net_value"] for e in evs), 2)
        total_disc = round(sum(e["discount"] for e in evs), 2)
        agg[email] = {
            "orders": len(evs),
            "first_order_date": evs[0]["order_date"],
            "first_order_value": round(evs[0]["net_value"], 2),
            "has_second_order": has_second,
            "days_to_second_order": days_to_second,
            "total_net_revenue": total_rev,
            "total_discount_burn": total_disc,
            "discount_only_buyer": all(e["discount"] > 0 or bool(e["discount_code"]) for e in evs),
        }
    return fmt, agg


def read_hubspot_deals(path: Path) -> dict[str, dict]:
    """Read HubSpot CRM Deals export aggregated per associated contact email."""
    cols, rows = read_csv_rows(path)
    email_col = _col(cols, "Associated Contact Email", "Contact Email", "Email", "email")
    stage_col = _col(cols, "Deal Stage", "Stage", "deal_stage")
    amt_col = _col(cols, "Amount", "Deal Amount", "amount")
    if not email_col or not stage_col or not amt_col:
        raise ValueError("Unrecognised Deals CSV: expected Associated Contact Email, Deal Stage, and Amount.")

    out: dict[str, dict] = {}
    for r in rows:
        email = r.get(email_col, "").strip().lower()
        if not email:
            continue
        stage = r.get(stage_col, "").strip().lower()
        amt = parse_amount(r.get(amt_col))
        d = out.setdefault(email, {"deals": 0, "open_pipeline": 0.0, "closed_won_deals": 0, "closed_won_revenue": 0.0})
        d["deals"] += 1
        if "won" in stage:
            d["closed_won_deals"] += 1
            d["closed_won_revenue"] = round(d["closed_won_revenue"] + amt, 2)
        elif "lost" not in stage:
            d["open_pipeline"] = round(d["open_pipeline"] + amt, 2)
    return out

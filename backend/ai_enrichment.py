"""
ai_enrichment.py — Uses Claude API to enrich raw tenders with AI summaries
and eligibility checklists.

This is the core value-add of TenderAlert Pro over a raw data feed.
For each tender, Claude produces:
  - A plain-English summary (what the buyer actually wants)
  - An eligibility checklist (documents, certs, experience required)
  - A difficulty rating (Easy / Medium / Hard)

Run directly to test: python ai_enrichment.py
"""

import anthropic
from config import ANTHROPIC_API_KEY
from database import get_conn, save_ai_summary, init_db

MODEL = "claude-haiku-4-5-20251001"  # Fast + cost-efficient for structured extraction
MAX_DESCRIPTION_CHARS = 1500        # Truncate long descriptions to control token spend
ENRICH_BATCH_SIZE = 20              # Max tenders enriched per scheduler run


def build_prompt(tender: dict) -> str:
    """Build the Claude prompt for a single tender."""
    value_str = (
        f"RWF {tender['value_amount']:,.0f}"
        if tender.get("value_amount")
        else "Not disclosed"
    )
    deadline = (tender.get("deadline") or "")[:10] or "Not specified"
    description = (tender.get("description") or "")[:MAX_DESCRIPTION_CHARS]

    return f"""You are a procurement analyst helping Rwandan businesses find tender opportunities.

Analyze this government tender and respond in EXACTLY this format (no extra text):

SUMMARY:
[2 plain-English sentences explaining what the buyer wants and what the winning bidder will do]

CHECKLIST:
• [requirement 1 — document, certification, or qualification needed]
• [requirement 2]
• [requirement 3]
• [requirement 4 if applicable]
• [requirement 5 if applicable]

DIFFICULTY: [Easy / Medium / Hard]
Easy = any registered SME can apply | Medium = need proven experience + specific docs | Hard = large firm + specialized certifications required

SECTORS: [comma-separated list from ONLY these options: ict, construction, health, education, agriculture, consulting, supply]
Assign 1-3 sectors that best match this tender. Examples:
- Software development → ict
- Road construction → construction
- Hospital equipment → health, supply
- School renovation → education, construction
- Farm inputs → agriculture, supply
- Audit services → consulting

---
Tender Title: {tender['title']}
Buyer: {tender['buyer_name']}
Category: {tender['category']}
Value: {value_str}
Deadline: {deadline}
Description: {description or 'No description provided.'}"""


VALID_SECTORS = {"ict", "construction", "health", "education", "agriculture", "consulting", "supply"}


def parse_sectors_from_response(text: str) -> str:
    """Extract SECTORS: line from Claude's response and return cleaned comma-separated tags."""
    for line in text.splitlines():
        if line.strip().upper().startswith("SECTORS:"):
            raw = line.split(":", 1)[1].strip()
            # Parse comma-separated, validate each against known sectors
            tags = [s.strip().lower() for s in raw.split(",")]
            valid = [t for t in tags if t in VALID_SECTORS]
            return ",".join(valid) if valid else ""
    return ""


def strip_sectors_line(text: str) -> str:
    """Remove the SECTORS: line from the response (don't show it to users)."""
    lines = []
    for line in text.splitlines():
        if not line.strip().upper().startswith("SECTORS:"):
            lines.append(line)
    # Clean trailing whitespace
    return "\n".join(lines).strip()


def enrich_tender(tender: dict) -> tuple[str | None, str]:
    """
    Call Claude to generate an AI summary + sector tags for a single tender.
    Returns (summary_text, tags_csv) on success, (None, "") on failure.
    """
    if not ANTHROPIC_API_KEY:
        print("[ai] ANTHROPIC_API_KEY not set — skipping enrichment.")
        return None, ""

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=MODEL,
            max_tokens=600,
            messages=[{"role": "user", "content": build_prompt(tender)}],
        )
        full_response = message.content[0].text.strip()
        tags = parse_sectors_from_response(full_response)
        summary = strip_sectors_line(full_response)
        return summary, tags
    except anthropic.APIError as e:
        print(f"[ai] API error for {tender.get('ocid')}: {e}")
        return None, ""
    except Exception as e:
        print(f"[ai] Unexpected error for {tender.get('ocid')}: {e}")
        return None, ""


def get_unenriched_tenders(limit: int = ENRICH_BATCH_SIZE) -> list[dict]:
    """
    Fetch active tenders with a future deadline that don't have an AI summary yet.
    """
    conn = get_conn()
    c = conn.cursor()
    c.execute(
        """
        SELECT * FROM tenders
        WHERE (ai_summary IS NULL OR ai_summary = '')
          AND status = 'active'
          AND deadline > datetime('now')
        ORDER BY deadline ASC
        LIMIT ?
        """,
        (limit,),
    )
    rows = [dict(r) for r in c.fetchall()]
    conn.close()
    return rows


def enrich_new_tenders(limit: int = ENRICH_BATCH_SIZE) -> int:
    """
    Enrich up to `limit` unenriched active tenders with Claude summaries.
    Returns the count of successfully enriched tenders.
    """
    tenders = get_unenriched_tenders(limit)

    if not tenders:
        print("[ai] No unenriched tenders to process.")
        return 0

    print(f"[ai] Enriching {len(tenders)} tender(s) with Claude...")
    enriched = 0

    for t in tenders:
        short_title = t["title"][:60] + ("..." if len(t["title"]) > 60 else "")
        print(f"[ai] → {short_title}")
        summary, tags = enrich_tender(t)
        if summary:
            save_ai_summary(t["ocid"], summary, tags=tags)
            enriched += 1
            tag_info = f" [tags: {tags}]" if tags else ""
            print(f"[ai]   ✓ Enriched ({enriched}/{len(tenders)}){tag_info}")
        else:
            print(f"[ai]   ✗ Failed — skipping")

    print(f"[ai] Done. {enriched}/{len(tenders)} tenders enriched.")
    return enriched


def preview_enrichment(n: int = 3):
    """
    Fetch N real tenders, enrich them with Claude, and print to console.
    Used for testing without sending WhatsApp messages.
    """
    from poller import fetch_live_ocds, fetch_bulk_ocds

    print("[ai] Fetching tenders for preview enrichment...")
    tenders = fetch_live_ocds(page_size=n)
    if not tenders:
        tenders = fetch_bulk_ocds()[:n]

    if not tenders:
        print("[ai] No tenders fetched — check your network or RPPA API.")
        return

    print("\n" + "=" * 65)
    print(f"  TenderAlert Pro - AI Enrichment Preview ({len(tenders)} tenders)")
    print("=" * 65 + "\n")

    for i, t in enumerate(tenders, 1):
        value_str = f"RWF {t['value_amount']:,.0f}" if t.get("value_amount") else "Value TBD"
        deadline = (t.get("deadline") or "")[:10] or "No deadline"

        print("-" * 65)
        print(f"[{i}] {t['title']}")
        print(f"     Buyer    : {t['buyer_name']}")
        print(f"     Category : {t['category']}")
        print(f"     Value    : {value_str}")
        print(f"     Deadline : {deadline}")
        print(f"\n  ⏳ Calling Claude...")

        summary, tags = enrich_tender(t)
        if summary:
            print(f"\n  📋 AI Analysis:\n")
            for line in summary.splitlines():
                print(f"     {line}")
            if tags:
                print(f"\n  🏷️  Sectors: {tags}")
        else:
            print("  ✗ Enrichment failed.")
        print()


# ── Deep Analysis (Paid Feature) ─────────────────────────────────────────

DEEP_MODEL = "claude-sonnet-4-20250514"  # Smarter model for paid feature
DEEP_MAX_DESCRIPTION = 3000

DEEP_ANALYSIS_SCHEMA = """{
  "summary": "2-3 plain English sentences about what this tender is for",
  "qualification": {
    "assessment": "LIKELY_ELIGIBLE or UNLIKELY or NEEDS_REVIEW",
    "reasons": ["reason 1", "reason 2"]
  },
  "required_documents": ["document 1", "document 2"],
  "evaluation_criteria": ["criteria 1", "criteria 2"],
  "competition_insight": {
    "num_bidders_this_tender": 0,
    "historical_avg_bidders": 0,
    "top_winners_from_buyer": [{"name": "Company", "wins": 0, "avg_amount": 0}],
    "typical_winning_range": {"min": 0, "max": 0}
  },
  "key_deadlines": [{"event": "event name", "date": "YYYY-MM-DD"}],
  "budget_info": "budget description",
  "risk_factors": ["risk 1", "risk 2"],
  "recommendation": "WORTH_BIDDING or SKIP or RESEARCH_MORE",
  "recommendation_reason": "brief explanation"
}"""


def build_deep_prompt(tender: dict, buyer_history: list, competition_stats: dict) -> str:
    """Build comprehensive Claude prompt using full OCDS data + historical intelligence."""
    import json as _json

    # Parse raw_json for rich OCDS fields
    raw = {}
    try:
        raw = _json.loads(tender.get("raw_json", "{}") or "{}")
    except _json.JSONDecodeError:
        pass

    tender_obj = raw.get("tender", {})
    planning = raw.get("planning", {})
    buyer_obj = raw.get("buyer", {})
    parties = raw.get("parties", [])
    awards = raw.get("awards", [])
    contracts = raw.get("contracts", [])

    # Extract rich fields
    description = (tender_obj.get("description") or tender.get("description") or "")[:DEEP_MAX_DESCRIPTION]
    rationale = planning.get("rationale", "")
    budget_amount = (planning.get("budget", {}).get("amount", {}) or {}).get("amount")
    budget_currency = (planning.get("budget", {}).get("amount", {}) or {}).get("currency", "RWF")
    procurement_method = tender_obj.get("procurementMethod", "")
    num_tenderers = tender_obj.get("numberOfTenderers")
    has_framework = (tender_obj.get("techniques") or {}).get("hasFrameworkAgreement", False)

    # Lots
    lots = tender_obj.get("lots", [])
    lots_text = ""
    if lots:
        lot_lines = []
        for lot in lots[:5]:
            lv = (lot.get("value") or {}).get("amount")
            lot_lines.append(f"  - {lot.get('title', 'Unnamed lot')}: {f'RWF {lv:,.0f}' if lv else 'value not disclosed'}")
        lots_text = "\n".join(lot_lines)

    # Tenderers (who bid)
    tenderers = tender_obj.get("tenderers", [])
    tenderer_names = [t.get("name", "") for t in tenderers[:10]]

    # Awards in this release
    awards_text = ""
    if awards:
        award_lines = []
        for a in awards[:3]:
            suppliers = ", ".join(s.get("name", "") for s in a.get("suppliers", [])[:5])
            av = (a.get("value") or {}).get("amount")
            award_lines.append(f"  - Winner: {suppliers} | Amount: {f'RWF {av:,.0f}' if av else 'N/A'} | Date: {(a.get('date') or '')[:10]}")
        awards_text = "\n".join(award_lines)

    # Buyer contact
    contact = {}
    for party in parties:
        if "buyer" in (party.get("roles") or []) or "procuringEntity" in (party.get("roles") or []):
            contact = party.get("contactPoint", {})
            break

    # Contracts
    contracts_text = ""
    if contracts:
        for c in contracts[:2]:
            cv = (c.get("value") or {}).get("amount")
            period = c.get("period", {})
            contracts_text += f"  - Value: {f'RWF {cv:,.0f}' if cv else 'N/A'} | Period: {(period.get('startDate') or '')[:10]} to {(period.get('endDate') or '')[:10]}\n"

    # Historical intelligence section
    history_text = "No historical data available for this buyer."
    if buyer_history:
        history_lines = ["Past awards from this buyer:"]
        for h in buyer_history[:10]:
            ha = h.get("award_amount")
            history_lines.append(
                f"  - {h.get('supplier_name', '?')} won '{h.get('title', '')[:40]}' "
                f"for {f'RWF {ha:,.0f}' if ha else 'N/A'} ({(h.get('award_date') or '')[:10]})"
            )
        history_text = "\n".join(history_lines)

    stats_text = ""
    if competition_stats and competition_stats.get("total_awards"):
        avg_b = competition_stats.get("avg_bidders")
        avg_a = competition_stats.get("avg_amount")
        stats_text = f"""
Competition statistics for this buyer:
  - Total past awards: {competition_stats['total_awards']}
  - Average bidders per tender: {f'{avg_b:.1f}' if avg_b else 'unknown'}
  - Average winning amount: {f'RWF {avg_a:,.0f}' if avg_a else 'unknown'}
  - Top suppliers: {', '.join(s['supplier_name'] + f' ({s["wins"]} wins)' for s in competition_stats.get('top_suppliers', [])[:3])}"""

    value_str = f"RWF {tender['value_amount']:,.0f}" if tender.get("value_amount") else "Not disclosed"
    deadline = (tender.get("deadline") or "")[:10] or "Not specified"

    return f"""You are a senior Rwanda government procurement analyst. A business wants to know whether they should bid on this tender and what they need to prepare.

Analyze ALL the data below and return a JSON object with EXACTLY this schema (no extra text, no markdown fences):

{DEEP_ANALYSIS_SCHEMA}

IMPORTANT:
- Base your analysis on the actual data provided, not assumptions
- For required_documents: infer from Rwanda procurement standards (RRA clearance, RSSB, bank guarantee, beneficial ownership, etc.)
- For evaluation_criteria: infer from procurement method and category
- For competition_insight: use the historical data provided
- For risk_factors: consider incumbents, timeline, framework agreements, competition level
- recommendation must be one of: WORTH_BIDDING, SKIP, RESEARCH_MORE

=== TENDER DATA ===
Title: {tender['title']}
Buyer: {tender['buyer_name']}
Category: {tender['category']}
Value: {value_str}
Deadline: {deadline}
Procurement Method: {procurement_method or 'Not specified'}
Framework Agreement: {'Yes' if has_framework else 'No'}
Number of Bidders: {num_tenderers or 'Unknown'}

Description: {description or 'No description provided.'}

Planning Rationale: {rationale or 'Not provided.'}
Budget: {f'{budget_currency} {budget_amount:,.0f}' if budget_amount else 'Not disclosed'}

{f'Lots:{chr(10)}{lots_text}' if lots_text else ''}
{f'Bidders: {", ".join(tenderer_names)}' if tenderer_names else ''}
{f'Awards:{chr(10)}{awards_text}' if awards_text else ''}
{f'Contracts:{chr(10)}{contracts_text}' if contracts_text else ''}
{f'Buyer Contact: {contact.get("name", "")} | {contact.get("email", "")} | {contact.get("telephone", "")}' if contact.get("name") else ''}

=== HISTORICAL INTELLIGENCE ===
{history_text}
{stats_text}"""


def deep_analyze_tender(tender: dict) -> dict | None:
    """
    Perform deep AI analysis on a tender using full OCDS data + historical intelligence.
    Returns structured analysis dict or None on failure.
    Caches results in the database.
    """
    import json as _json
    from database import get_deep_analysis, save_deep_analysis, get_buyer_history, get_competition_stats

    ocid = tender.get("ocid", "")

    # Check cache first
    cached = get_deep_analysis(ocid)
    if cached:
        try:
            return _json.loads(cached)
        except _json.JSONDecodeError:
            pass

    if not ANTHROPIC_API_KEY:
        print("[ai] ANTHROPIC_API_KEY not set.")
        return None

    # Get historical data
    buyer_name = tender.get("buyer_name", "")
    category = tender.get("category", "")
    buyer_history = get_buyer_history(buyer_name, category) if buyer_name else []
    comp_stats = get_competition_stats(buyer_name, category) if buyer_name else {}

    # Build prompt and call Claude Sonnet
    prompt = build_deep_prompt(tender, buyer_history, comp_stats)
    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=DEEP_MODEL,
            max_tokens=2000,
            messages=[{"role": "user", "content": prompt}],
        )
        raw_text = message.content[0].text.strip()

        # Strip markdown fences if present
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        # Try to extract JSON
        analysis = _json.loads(raw_text)

        # Validate minimum fields
        if "summary" not in analysis or "recommendation" not in analysis:
            print(f"[ai] Deep analysis missing required fields for {ocid}")
            return None

        # Cache the result
        save_deep_analysis(ocid, _json.dumps(analysis))
        return analysis

    except _json.JSONDecodeError:
        # Try to find JSON in the response
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                analysis = _json.loads(raw_text[start:end])
                save_deep_analysis(ocid, _json.dumps(analysis))
                return analysis
            except _json.JSONDecodeError:
                pass
        print(f"[ai] Failed to parse deep analysis JSON for {ocid}")
        return None
    except anthropic.APIError as e:
        print(f"[ai] API error in deep analysis for {ocid}: {e}")
        return None
    except Exception as e:
        print(f"[ai] Unexpected error in deep analysis for {ocid}: {e}")
        return None


# ── Proposal Generation (Premium Feature) ───────────────────────────────

def generate_proposal_content(tender: dict, documents_base64: list[dict], company_profile: dict) -> dict | None:
    """
    Generate a structured proposal using Claude Sonnet.
    documents_base64: list of {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": "..."}}
    company_profile: dict from company_profiles table
    Returns structured proposal dict or None.
    """
    import json as _json

    if not ANTHROPIC_API_KEY:
        return None

    value_str = f"RWF {tender['value_amount']:,.0f}" if tender.get("value_amount") else "Not disclosed"
    deadline = (tender.get("deadline") or "")[:10] or "Not specified"

    # Build company context from profile
    company_text = ""
    if company_profile:
        company_text = f"""
Company Name: {company_profile.get('company_name', '')}
Sectors: {company_profile.get('sectors', '')}
Certifications: {company_profile.get('certifications', 'None listed')}
Typical Contract Range: RWF {company_profile.get('typical_contract_min', 0):,} - {company_profile.get('typical_contract_max', 0):,}
Employees: {company_profile.get('employee_count', 'Unknown')}
Past Clients: {company_profile.get('past_clients', 'None listed')}
District: {company_profile.get('district', '')}"""

    prompt_text = f"""You are a professional bid writer for Rwandan government procurement.

Generate a structured proposal for this tender. The output must be ONLY valid JSON (no markdown fences) matching this schema:

{{
  "cover_letter": {{
    "date": "formatted date",
    "reference": "tender reference number",
    "subject": "Re: Tender for [title]",
    "opening": "formal opening paragraph",
    "body": "2-3 paragraphs: company intro, qualifications, commitment",
    "closing": "formal closing line"
  }},
  "company_profile": {{
    "overview": "3-4 sentences about the company from their documents",
    "core_services": ["service 1", "service 2"],
    "certifications": ["cert from docs"],
    "key_strengths": ["strength relevant to this tender"]
  }},
  "understanding": {{
    "background": "paragraph showing understanding of procuring entity needs",
    "objectives": ["objective 1", "objective 2"]
  }},
  "methodology": {{
    "approach": "overall approach paragraph",
    "phases": [
      {{"phase": "Phase 1", "title": "title", "duration": "X weeks", "activities": ["activity 1"]}}
    ]
  }},
  "experience": {{
    "summary": "paragraph on relevant past experience",
    "projects": [
      {{"title": "project name", "client": "client", "value": "value", "year": "year", "relevance": "why relevant"}}
    ]
  }},
  "admin_checklist": [
    {{"document": "document name", "status": "HAVE or NEED"}}
  ]
}}

IMPORTANT:
- Base company_profile and experience on the actual uploaded documents
- Mark admin_checklist items as HAVE only if confirmed from uploaded documents
- For missing info, write professional placeholder text the user can edit
- Keep language formal, professional, appropriate for Rwandan government procurement

=== TENDER ===
Title: {tender['title']}
Buyer: {tender['buyer_name']}
Category: {tender['category']}
Value: {value_str}
Deadline: {deadline}
Description: {(tender.get('description') or '')[:2000]}

=== COMPANY PROFILE ===
{company_text or 'No company profile available. Use professional placeholder text.'}

The user has uploaded {len(documents_base64)} company document(s). Analyze them for company details, certifications, and past experience."""

    # Build message content with documents
    content = []
    for doc in documents_base64:
        content.append(doc)
    content.append({"type": "text", "text": prompt_text})

    client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

    try:
        message = client.messages.create(
            model=DEEP_MODEL,
            max_tokens=4000,
            messages=[{"role": "user", "content": content}],
        )
        raw_text = message.content[0].text.strip()
        raw_text = raw_text.replace("```json", "").replace("```", "").strip()

        proposal = _json.loads(raw_text)
        return proposal

    except _json.JSONDecodeError:
        start = raw_text.find("{")
        end = raw_text.rfind("}") + 1
        if start >= 0 and end > start:
            try:
                return _json.loads(raw_text[start:end])
            except _json.JSONDecodeError:
                pass
        print(f"[ai] Failed to parse proposal JSON")
        return None
    except Exception as e:
        print(f"[ai] Proposal generation error: {e}")
        return None


if __name__ == "__main__":
    init_db()
    preview_enrichment(n=3)

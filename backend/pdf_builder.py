"""
pdf_builder.py — Generate professional proposal PDFs using ReportLab.
"""

import os
from datetime import datetime
from pathlib import Path

try:
    from reportlab.lib.pagesizes import A4
    from reportlab.lib.units import mm
    from reportlab.lib.colors import HexColor
    from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
    from reportlab.platypus import (
        SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak
    )
    from reportlab.lib.enums import TA_JUSTIFY, TA_CENTER
    HAS_REPORTLAB = True
except ImportError:
    HAS_REPORTLAB = False
    print("[pdf_builder] reportlab not installed. Run: pip install reportlab")

STORAGE_DIR = Path(os.getenv("STORAGE_DIR", "./storage/proposals"))
GREEN = HexColor("#1D9E75")
GREEN_LIGHT = HexColor("#E1F5EE")
AMBER_LIGHT = HexColor("#FAEEDA")
DARK = HexColor("#1a1a1a")
GRAY = HexColor("#666666")


def build_proposal_pdf(proposal: dict, tender: dict, subscriber: dict) -> bytes:
    """Build a professional proposal PDF from structured data. Returns PDF bytes."""
    if not HAS_REPORTLAB:
        return b""

    from io import BytesIO
    buf = BytesIO()
    doc = SimpleDocTemplate(buf, pagesize=A4, leftMargin=60, rightMargin=60, topMargin=60, bottomMargin=60)

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle("SectionTitle", parent=styles["Heading2"], textColor=GREEN, fontSize=14, spaceAfter=8))
    styles.add(ParagraphStyle("Body", parent=styles["Normal"], fontSize=10, leading=14, alignment=TA_JUSTIFY, textColor=DARK))
    styles.add(ParagraphStyle("SmallGray", parent=styles["Normal"], fontSize=8, textColor=GRAY, alignment=TA_CENTER))
    styles.add(ParagraphStyle("BoldBody", parent=styles["Normal"], fontSize=10, leading=14, textColor=DARK))

    elements = []

    # ── Header ──
    company_name = subscriber.get("company_name", "Company")
    elements.append(Paragraph(f"<b>{company_name}</b>", styles["Heading1"]))
    elements.append(Paragraph("TECHNICAL PROPOSAL", styles["SectionTitle"]))
    elements.append(Spacer(1, 6))

    # Tender info box
    value_str = f"RWF {tender['value_amount']:,.0f}" if tender.get("value_amount") else "Not disclosed"
    deadline = (tender.get("deadline") or "")[:10] or "Not specified"
    tender_info = [
        ["Tender:", tender.get("title", "")[:80]],
        ["Buyer:", tender.get("buyer_name", "")],
        ["Value:", value_str],
        ["Deadline:", deadline],
    ]
    t = Table(tender_info, colWidths=[80, 380])
    t.setStyle(TableStyle([
        ("FONTSIZE", (0, 0), (-1, -1), 9),
        ("FONTNAME", (0, 0), (0, -1), "Helvetica-Bold"),
        ("TEXTCOLOR", (0, 0), (-1, -1), DARK),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ("BACKGROUND", (0, 0), (-1, -1), GREEN_LIGHT),
        ("BOX", (0, 0), (-1, -1), 0.5, GREEN),
    ]))
    elements.append(t)
    elements.append(Spacer(1, 16))

    # ── Cover Letter ──
    cover = proposal.get("cover_letter", {})
    if cover:
        elements.append(Paragraph("1. COVER LETTER", styles["SectionTitle"]))
        elements.append(Paragraph(f"<b>Date:</b> {cover.get('date', datetime.now().strftime('%d %B %Y'))}", styles["Body"]))
        elements.append(Paragraph(f"<b>Ref:</b> {cover.get('reference', '')}", styles["Body"]))
        elements.append(Paragraph(f"<b>Subject:</b> {cover.get('subject', '')}", styles["Body"]))
        elements.append(Spacer(1, 8))
        elements.append(Paragraph(cover.get("opening", ""), styles["Body"]))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(cover.get("body", ""), styles["Body"]))
        elements.append(Spacer(1, 6))
        elements.append(Paragraph(cover.get("closing", ""), styles["Body"]))
        elements.append(Spacer(1, 16))

    # ── Company Profile ──
    cp = proposal.get("company_profile", {})
    if cp:
        elements.append(Paragraph("2. COMPANY PROFILE", styles["SectionTitle"]))
        elements.append(Paragraph(cp.get("overview", ""), styles["Body"]))
        elements.append(Spacer(1, 8))

        services = cp.get("core_services", [])
        if services:
            elements.append(Paragraph("<b>Core Services:</b>", styles["BoldBody"]))
            for s in services:
                elements.append(Paragraph(f"• {s}", styles["Body"]))

        certs = cp.get("certifications", [])
        if certs:
            elements.append(Spacer(1, 6))
            elements.append(Paragraph("<b>Certifications:</b>", styles["BoldBody"]))
            for c in certs:
                elements.append(Paragraph(f"• {c}", styles["Body"]))

        strengths = cp.get("key_strengths", [])
        if strengths:
            elements.append(Spacer(1, 6))
            elements.append(Paragraph("<b>Key Strengths:</b>", styles["BoldBody"]))
            for s in strengths:
                elements.append(Paragraph(f"• {s}", styles["Body"]))
        elements.append(Spacer(1, 16))

    # ── Understanding ──
    und = proposal.get("understanding", {})
    if und:
        elements.append(Paragraph("3. UNDERSTANDING OF REQUIREMENTS", styles["SectionTitle"]))
        elements.append(Paragraph(und.get("background", ""), styles["Body"]))
        objectives = und.get("objectives", [])
        if objectives:
            elements.append(Spacer(1, 6))
            elements.append(Paragraph("<b>Objectives:</b>", styles["BoldBody"]))
            for obj in objectives:
                elements.append(Paragraph(f"• {obj}", styles["Body"]))
        elements.append(Spacer(1, 16))

    # ── Methodology ──
    meth = proposal.get("methodology", {})
    if meth:
        elements.append(Paragraph("4. PROPOSED METHODOLOGY", styles["SectionTitle"]))
        elements.append(Paragraph(meth.get("approach", ""), styles["Body"]))
        elements.append(Spacer(1, 8))

        for phase in meth.get("phases", []):
            elements.append(Paragraph(
                f"<b>{phase.get('phase', '')} — {phase.get('title', '')}</b> ({phase.get('duration', '')})",
                styles["BoldBody"]
            ))
            for act in phase.get("activities", []):
                elements.append(Paragraph(f"  • {act}", styles["Body"]))
            elements.append(Spacer(1, 6))
        elements.append(Spacer(1, 10))

    # ── Experience ──
    exp = proposal.get("experience", {})
    if exp:
        elements.append(Paragraph("5. RELEVANT EXPERIENCE", styles["SectionTitle"]))
        elements.append(Paragraph(exp.get("summary", ""), styles["Body"]))
        elements.append(Spacer(1, 8))

        for proj in exp.get("projects", []):
            elements.append(Paragraph(
                f"<b>{proj.get('title', '')}</b> — {proj.get('client', '')} ({proj.get('year', '')})",
                styles["BoldBody"]
            ))
            elements.append(Paragraph(f"Value: {proj.get('value', 'N/A')} | {proj.get('relevance', '')}", styles["Body"]))
            elements.append(Spacer(1, 4))
        elements.append(Spacer(1, 10))

    # ── Admin Checklist ──
    checklist = proposal.get("admin_checklist", [])
    if checklist:
        elements.append(Paragraph("6. ADMINISTRATIVE DOCUMENTS CHECKLIST", styles["SectionTitle"]))
        data = [["Document", "Status"]]
        for item in checklist:
            data.append([item.get("document", ""), item.get("status", "NEED")])

        t = Table(data, colWidths=[350, 80])
        table_style = [
            ("FONTSIZE", (0, 0), (-1, -1), 9),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("BACKGROUND", (0, 0), (-1, 0), GREEN),
            ("TEXTCOLOR", (0, 0), (-1, 0), HexColor("#FFFFFF")),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("GRID", (0, 0), (-1, -1), 0.5, HexColor("#e5e5e5")),
        ]
        for i, item in enumerate(checklist, 1):
            if item.get("status") == "HAVE":
                table_style.append(("BACKGROUND", (1, i), (1, i), GREEN_LIGHT))
            else:
                table_style.append(("BACKGROUND", (1, i), (1, i), AMBER_LIGHT))
        t.setStyle(TableStyle(table_style))
        elements.append(t)

    # Footer
    elements.append(Spacer(1, 20))
    elements.append(Paragraph(
        "Draft generated by TenderAlert Pro — Review and customize before submission",
        styles["SmallGray"]
    ))

    doc.build(elements)
    return buf.getvalue()


def save_proposal_pdf(phone: str, tender_id: str, pdf_bytes: bytes) -> str:
    """Save proposal PDF to disk. Returns file path."""
    user_dir = STORAGE_DIR / phone
    user_dir.mkdir(parents=True, exist_ok=True)

    timestamp = datetime.utcnow().strftime("%Y%m%d_%H%M%S")
    safe_id = tender_id.replace("/", "_")[:40]
    filename = f"proposal_{safe_id}_{timestamp}.pdf"
    file_path = user_dir / filename

    file_path.write_bytes(pdf_bytes)
    print(f"[pdf_builder] Saved proposal ({len(pdf_bytes)} bytes) to {file_path}")
    return str(file_path)

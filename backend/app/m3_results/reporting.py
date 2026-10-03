"""
Module M3 PDF Report Generation Service (F.14, US-3.3).
Generates deterministic executive PDF reports with embedded visualisations and interpretability disclaimers.
"""
from __future__ import annotations
import io
import os
from datetime import datetime, timezone
from reportlab.lib.pagesizes import letter
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate,
    Paragraph,
    Spacer,
    Table,
    TableStyle,
    Image as RLImage,
    KeepTogether,
    HRFlowable,
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from app.m3_results.models import Prediction, Explainability
from app.shared.errors import AppException


def compute_confidence_band(score: float) -> str:
    if score >= 0.85:
        return "High"
    elif score >= 0.65:
        return "Moderate"
    else:
        return "Low"


def build_pdf_report(
    prediction: Prediction,
    explainabilities: list[Explainability],
) -> io.BytesIO:
    """
    Assembles a deterministic, structured PDF summary report for a prediction record.
    Returns: BytesIO buffer of the PDF.
    """
    buffer = io.BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=letter,
        rightMargin=40,
        leftMargin=40,
        topMargin=40,
        bottomMargin=40,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "DocTitle",
        parent=styles["Heading1"],
        fontSize=20,
        leading=24,
        textColor=colors.HexColor("#0f172a"),
        fontName="Helvetica-Bold",
    )
    subtitle_style = ParagraphStyle(
        "DocSubTitle",
        parent=styles["Normal"],
        fontSize=10,
        leading=14,
        textColor=colors.HexColor("#64748b"),
        fontName="Helvetica",
    )
    section_title = ParagraphStyle(
        "SectionTitle",
        parent=styles["Heading2"],
        fontSize=13,
        leading=17,
        textColor=colors.HexColor("#1e293b"),
        fontName="Helvetica-Bold",
    )
    body_style = ParagraphStyle(
        "DocBody",
        parent=styles["Normal"],
        fontSize=9.5,
        leading=13,
        textColor=colors.HexColor("#334155"),
        fontName="Helvetica",
    )
    caveat_style = ParagraphStyle(
        "CaveatText",
        parent=styles["Normal"],
        fontSize=8.5,
        leading=12,
        textColor=colors.HexColor("#475569"),
        fontName="Helvetica-Oblique",
    )

    story = []

    # 1. Header Banner
    story.append(Paragraph("TruePixels.rgb — Forensic Detection Report", title_style))
    now_utc = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    story.append(Paragraph(f"Generated at: {now_utc} | System Report Reference: #{prediction.prediction_id}", subtitle_style))
    story.append(Spacer(1, 12))
    story.append(HRFlowable(width="100%", thickness=1.5, color=colors.HexColor("#3b82f6"), spaceAfter=14))

    # 2. Executive Summary Box
    verdict = prediction.predicted_class
    conf_val = prediction.confidence_score * 100
    conf_band = compute_confidence_band(prediction.confidence_score)
    verdict_color = "#dc2626" if verdict == "AI Generated" else "#16a34a"

    summary_data = [
        [
            Paragraph("<b>Predicted Verdict:</b>", body_style),
            Paragraph(f"<font color='{verdict_color}' size=12><b>{verdict}</b></font>", body_style),
            Paragraph("<b>Confidence Score:</b>", body_style),
            Paragraph(f"<b>{conf_val:.1f}%</b> ({conf_band} Confidence)", body_style),
        ],
        [
            Paragraph("<b>Semantic Score:</b>", body_style),
            Paragraph(f"{prediction.semantic_score:.4f}", body_style),
            Paragraph("<b>Frequency Score:</b>", body_style),
            Paragraph(f"{prediction.frequency_score:.4f}"
                      if prediction.frequency_score is not None else "unavailable", body_style),
        ],
        [
            Paragraph("<b>Active Model:</b>", body_style),
            Paragraph(f"{prediction.model.model_name} (v{prediction.model.model_version})" if prediction.model else "Hybrid ViT/FFT v1.0", body_style),
            Paragraph("<b>Analyzed At:</b>", body_style),
            Paragraph(prediction.prediction_timestamp.strftime("%Y-%m-%d %H:%M:%S UTC"), body_style),
        ],
    ]
    summary_table = Table(summary_data, colWidths=[110, 150, 110, 160])
    summary_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#e2e8f0")),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.HexColor("#e2e8f0")),
        ("PADDING", (0, 0), (-1, -1), 6),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ]))
    story.append(summary_table)
    story.append(Spacer(1, 16))

    # 3. Visual Evidence (Original, Semantic Saliency, Frequency Spectrum)
    story.append(Paragraph("Forensic Visualisations & Evidence", section_title))
    story.append(Spacer(1, 8))

    sem_ref = None
    freq_ref = None
    for item in explainabilities:
        if item.branch == "semantic" and os.path.exists(item.visualization_reference):
            sem_ref = item.visualization_reference
        elif item.branch == "frequency" and os.path.exists(item.visualization_reference):
            freq_ref = item.visualization_reference

    img_elements = []
    # Original Image
    if prediction.image and os.path.exists(prediction.image.file_reference):
        img_elements.append([
            Paragraph("<b>Original Subject</b>", body_style),
            Paragraph("<b>Semantic Attention Overlay</b>", body_style),
        ])
        img1 = RLImage(prediction.image.file_reference, width=2.4*inch, height=2.4*inch)
        img2 = RLImage(sem_ref, width=2.4*inch, height=2.4*inch) if sem_ref else Paragraph("Visualisation not available", body_style)
        img_elements.append([img1, img2])
    elif sem_ref:
        img_elements.append([
            Paragraph("<b>Semantic Attention Overlay</b>", body_style),
            Paragraph("<b>FFT Radial Spectrum</b>", body_style),
        ])
        img1 = RLImage(sem_ref, width=2.4*inch, height=2.4*inch)
        img2 = RLImage(freq_ref, width=2.4*inch, height=2.4*inch) if freq_ref else Paragraph("Spectrum not available", body_style)
        img_elements.append([img1, img2])

    # INTEGRATION (changes.md 6.6): say so when the original is gone, rather
    # than silently leaving it out of the report.
    if not (prediction.image and os.path.exists(prediction.image.file_reference or "")):
        story.append(Paragraph(
            "<i>The original image file is no longer stored on the server. The outcome and "
            "scores above are the recorded result of the analysis made when it was.</i>",
            body_style,
        ))
        story.append(Spacer(1, 8))

    if img_elements:
        vis_table = Table(img_elements, colWidths=[265, 265])
        vis_table.setStyle(TableStyle([
            ("ALIGN", (0, 0), (-1, -1), "CENTER"),
            ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
            ("PADDING", (0, 0), (-1, -1), 4),
        ]))
        story.append(vis_table)

    story.append(Spacer(1, 14))

    # 4. Permanent Interpretability Disclaimer Box (Section 5.1.5 / NF.13)
    caveat_content = [
        [
            Paragraph(
                "<b>Interpretability Notice (NF.13):</b><br/>"
                "Highlighted regions indicate where the neural network attended most heavily and are not "
                "conclusive proof of localised manipulation. Spectral artifacts reflect spatial frequency distribution.",
                caveat_style,
            )
        ]
    ]
    caveat_table = Table(caveat_content, colWidths=[530])
    caveat_table.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#fef3c7")),
        ("PADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(caveat_table)

    doc.build(story)
    buffer.seek(0)
    return buffer

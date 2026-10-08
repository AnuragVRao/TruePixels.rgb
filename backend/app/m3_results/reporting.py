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
from PIL import Image as PILImage
from app.m3_results.explain import caption_for
from app.m3_results.likelihood import describe
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
import reportlab

# The capped likelihoods read "≤ 1 %" / "≥ 99 %". The standard Helvetica has
# no glyph for either sign, so just those two characters are set in Vera, a
# TrueType font that ships inside reportlab itself (no system font needed).
_RL_FONTS = os.path.join(os.path.dirname(reportlab.__file__), "fonts")
for _name, _file in (("Vera", "Vera.ttf"), ("VeraBd", "VeraBd.ttf")):
    if _name not in pdfmetrics.getRegisteredFontNames():
        pdfmetrics.registerFont(TTFont(_name, os.path.join(_RL_FONTS, _file)))


def _symbols(text: str, bold: bool = False) -> str:
    """Wrap the ≤ / ≥ signs in a font that has them (Paragraph markup)."""
    font = "VeraBd" if bold else "Vera"
    for sign in ("≤", "≥"):
        text = text.replace(sign, f'<font name="{font}">{sign}</font>')
    return text
from app.m3_results.models import Prediction, Explainability
from app.m3_results.overlay import explainability_path
from app.shared.errors import AppException


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
    # C2 v2: P(AI) for either verdict + certainty (likelihood.py), not the old
    # "confidence in the predicted class" with High/Moderate/Low bands.
    shown = describe(prediction)
    likelihood_cell = (f"<b>{_symbols(shown.p_ai_display, bold=True)}</b> ({shown.certainty_label})"
                       if shown.p_ai is not None else "not available")
    verdict_color = "#dc2626" if verdict == "AI Generated" else "#16a34a"

    summary_data = [
        [
            Paragraph("<b>Predicted Verdict:</b>", body_style),
            Paragraph(f"<font color='{verdict_color}' size=12><b>{verdict}</b></font>", body_style),
            Paragraph("<b>Likelihood AI-generated:</b>", body_style),
            Paragraph(likelihood_cell, body_style),
        ],
        [
            Paragraph("<b>Semantic score:</b>", body_style),
            Paragraph(f"{prediction.semantic_score:.4f}", body_style),
            Paragraph("<b>Frequency score:</b>", body_style),
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
    story.append(Spacer(1, 8))
    # The likelihood in words, plus anything that changes how to read it
    # (leans AI below the threshold; semantic-only = low reliability; not calibrated).
    story.append(Paragraph(f"<b>{_symbols(shown.headline, bold=True)}</b>", body_style))
    for note in shown.notes:
        story.append(Paragraph(note, caveat_style))
    story.append(Paragraph("The semantic and frequency values above are detector scores, not "
                           "probabilities. The verdict compares their weighted combination with a "
                           "threshold set to keep false alarms on genuine photographs at or below 10 %.",
                           caveat_style))
    story.append(Spacer(1, 16))

    # 3. Visual Evidence (Original, Semantic Saliency, Frequency Spectrum)
    # INTEGRATION (Phase 3, changes.md 6.7): all three panels in every case,
    # each with what it shows and what it does not; aspect ratio preserved;
    # stored references resolved through the explainability folder (they are
    # stored relative now). It used to drop the frequency panel whenever the
    # original existed.
    story.append(Paragraph("Forensic Visualisations & Evidence", section_title))
    story.append(Spacer(1, 8))

    caption_style = ParagraphStyle("PanelCaption", parent=body_style, fontSize=7.5, leading=9.5,
                                   textColor=colors.HexColor("#4b5563"))
    panels: dict[str, tuple[str, str]] = {}
    for item in explainabilities:
        path = explainability_path(item.visualization_reference)
        if os.path.exists(path):
            panels[item.branch] = (path, item.technique)

    def fitted(path: str, box: float = 2.4 * inch) -> RLImage:
        # A downscaled in-memory copy (<= 1600 px): the PDF's size and the
        # memory it takes no longer scale with the original's resolution, and
        # no file handle outlives this call.
        with PILImage.open(path) as handle:
            copy = handle.convert("RGB")
        copy.thumbnail((1600, 1600))
        data = io.BytesIO()
        copy.save(data, format="PNG")
        data.seek(0)
        w, h = copy.size
        scale = box / max(w, h)
        return RLImage(data, width=w * scale, height=h * scale)

    original_path = prediction.image.file_reference if prediction.image else None
    original_ok = bool(original_path and os.path.exists(original_path))
    if not original_ok:
        # INTEGRATION (changes.md 6.6): say so when the original is gone.
        story.append(Paragraph(
            "<i>The original image file is no longer stored on the server. The outcome and "
            "scores above are the recorded result of the analysis made when it was.</i>",
            body_style,
        ))
        story.append(Spacer(1, 8))

    def original_caption(path: str) -> str:
        # Phase 5b review: say plainly that the PDF holds a copy, not the original.
        try:
            with PILImage.open(path) as source:
                width, height = source.size
        except Exception:  # noqa: BLE001 - the caption must not break the report
            return "Copy of the original image, for reference."
        if max(width, height) > 1600:
            return (f"Downscaled copy of the original ({width}x{height} px), at most 1600 px per side, "
                    "for reference only. The analysis ran on the full-resolution original.")
        return f"Copy of the original image ({width}x{height} px), as analysed."

    def cell(title: str, path: str | None, missing_text: str, caption: str | None) -> list:
        parts = [Paragraph(f"<b>{title}</b>", body_style), Spacer(1, 3)]
        parts.append(fitted(path) if path else Paragraph(f"<i>{missing_text}</i>", caption_style))
        if caption:
            parts += [Spacer(1, 3), Paragraph(caption, caption_style)]
        return parts

    semantic = panels.get("semantic")
    frequency = panels.get("frequency")
    grid = [
        [
            cell("Original image", original_path if original_ok else None,
                 "Original no longer stored.", original_caption(original_path) if original_ok else None),
            cell("Semantic attention (SigLIP 2)", semantic[0] if semantic else None,
                 "Not generated for this prediction.", caption_for(semantic[1]) if semantic else None),
        ],
        [
            cell("Frequency content (SPAI patches)", frequency[0] if frequency else None,
                 "Not generated for this prediction (for example, the image is smaller than "
                 "the frequency detector's 224 px patch).",
                 caption_for(frequency[1]) if frequency else None),
            [Paragraph(
                "<b>Reading these panels.</b> They describe the models' internal behaviour on "
                "this image. They are not evidence of where, or whether, the image was "
                "manipulated, and they do not change the verdict above.", caption_style)],
        ],
    ]
    vis_table = Table(grid, colWidths=[265, 265])
    vis_table.setStyle(TableStyle([
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
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

    # Page footer on every page: which fitted P(AI) map produced the likelihood
    # (D4 calibration_ref), so a printed report can be traced to its calibration.
    footer = (f"TruePixels.rgb report #{prediction.prediction_id}  |  P(AI) map: "
              + (shown.calibration_ref or "none - not calibrated for the model configuration used"))

    def _footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#64748b"))
        canvas.drawString(document.leftMargin, 22, footer)
        canvas.drawRightString(document.pagesize[0] - document.rightMargin, 22, f"page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer

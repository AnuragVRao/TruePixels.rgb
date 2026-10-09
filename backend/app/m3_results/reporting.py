"""
Module M3 PDF Report Generation Service (F.14, US-3.3).
Generates deterministic PDF reports with embedded visualisations and interpretability disclaimers.

Written for the person who uploaded the image, not for an engineer: the
result and what it means come first in plain words, the evidence follows
with readable captions, and the technical identifiers go last.
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
)
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from PIL import Image as PILImage
from app.m3_results.explain import caption_for
from app.m3_results.models import Prediction, Explainability
from app.m3_results.overlay import explainability_path
from app.shared.errors import AppException

INK = colors.HexColor("#0f172a")
TEXT = colors.HexColor("#1e293b")
MUTED = colors.HexColor("#475569")
RULE = colors.HexColor("#cbd5e1")
AI_RED = colors.HexColor("#b91c1c")
REAL_GREEN = colors.HexColor("#15803d")
PAGE_WIDTH = letter[0] - 2 * 48  # usable width between the margins


def compute_confidence_band(score: float) -> str:
    if score >= 0.85:
        return "High"
    elif score >= 0.65:
        return "Moderate"
    else:
        return "Low"


def _content_detector_name(prediction: Prediction) -> str:
    """Display name of the content detector that produced THIS prediction (its D3 row)."""
    from sqlalchemy.orm import object_session

    from app.m2_analysis.models import ModelRegistry

    session = object_session(prediction)
    row_id = getattr(prediction, "semantic_model_id", None)
    name = ""
    if session is not None and row_id is not None:
        row = session.get(ModelRegistry, row_id)
        name = row.model_name if row else ""
    if "commfor" in name.lower():
        return "Community Forensics"
    if "siglip" in name.lower():
        return "SigLIP 2"
    return name or "content detector"


def _tau(prediction: Prediction) -> float | None:
    hyper = getattr(prediction.model, "hyperparameters", None) if prediction.model else None
    tau = (hyper or {}).get("tau") if isinstance(hyper, dict) else None
    try:
        return float(tau) if tau is not None else None
    except (TypeError, ValueError):
        return None


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
        rightMargin=48,
        leftMargin=48,
        topMargin=48,
        bottomMargin=54,
        title=f"TruePixels.rgb report #{prediction.prediction_id}",
    )

    base = getSampleStyleSheet()["Normal"]

    def style(name: str, **kw) -> ParagraphStyle:
        kw.setdefault("fontName", "Helvetica")
        kw.setdefault("textColor", TEXT)
        return ParagraphStyle(name, parent=base, **kw)

    title_style = style("Title", fontName="Helvetica-Bold", fontSize=22, leading=27, textColor=INK)
    meta_style = style("Meta", fontSize=10, leading=14, textColor=MUTED)
    h2 = style("H2", fontName="Helvetica-Bold", fontSize=14, leading=18, textColor=INK,
               spaceBefore=6, spaceAfter=6)
    body = style("Body", fontSize=11, leading=16)
    small = style("Small", fontSize=9.5, leading=13.5, textColor=MUTED)
    bullet = style("Bullet", fontSize=10, leading=13.5, leftIndent=14, bulletIndent=2, spaceAfter=2)
    panel_title = style("PanelTitle", fontName="Helvetica-Bold", fontSize=11, leading=14, textColor=INK)

    verdict = prediction.predicted_class
    is_ai = verdict == "AI Generated"
    accent = AI_RED if is_ai else REAL_GREEN
    confidence_pct = prediction.confidence_score * 100
    band = compute_confidence_band(prediction.confidence_score)
    semantic_only = prediction.frequency_score is None
    tau = _tau(prediction)

    story = []

    # 1. Title -----------------------------------------------------------------
    story.append(Paragraph("Image Analysis Report", title_style))
    analysed = prediction.prediction_timestamp.strftime("%d %b %Y, %H:%M UTC")
    generated = datetime.now(timezone.utc).strftime("%d %b %Y, %H:%M UTC")
    story.append(Paragraph(
        f"TruePixels.rgb &nbsp;·&nbsp; Report #{prediction.prediction_id} &nbsp;·&nbsp; "
        f"Analysed {analysed} &nbsp;·&nbsp; Report created {generated}", meta_style))
    story.append(Spacer(1, 16))

    # Images used below -----------------------------------------------------------
    # INTEGRATION (Phase 3, changes.md 6.7): all three panels in every case,
    # each with what it shows and what it does not; aspect ratio preserved;
    # stored references resolved through the explainability folder.
    panels: dict[str, tuple[str, str]] = {}
    for item in explainabilities:
        path = explainability_path(item.visualization_reference)
        if os.path.exists(path):
            panels[item.branch] = (path, item.technique)

    def fitted(path: str, max_w: float, max_h: float) -> RLImage:
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
        scale = min(max_w / w, max_h / h)  # any aspect ratio fits the same box
        return RLImage(data, width=w * scale, height=h * scale)

    original_path = prediction.image.file_reference if prediction.image else None
    original_ok = bool(original_path and os.path.exists(original_path))

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


    # 2. The result, in plain words ------------------------------------------
    meaning = ("The system judged this image <b>most likely AI-generated</b>."
               if is_ai else
               "The system judged this image <b>most likely a real photograph</b>.")
    result_text = [
        Paragraph("RESULT", style("Kicker", fontName="Helvetica-Bold", fontSize=9, leading=11, textColor=MUTED)),
        Spacer(1, 2),
        Paragraph(f"<font color='{accent.hexval()}'>{verdict}</font>",
                  style("Verdict", fontName="Helvetica-Bold", fontSize=26, leading=31)),
        Paragraph(f"Confidence: <b>{confidence_pct:.1f} %</b> &nbsp;({band})",
                  style("Conf", fontSize=14, leading=19, textColor=INK)),
        Spacer(1, 8),
        Paragraph(meaning, body),
        Spacer(1, 4),
        Paragraph("Confidence describes how clearly the image's score passed the system's "
                  "decision point. It is an estimate made by a model, not proof.", small),
    ]
    image_col = 2.3 * inch
    if original_ok:
        image_cell = [fitted(original_path, image_col, 1.75 * inch), Spacer(1, 4),
                      Paragraph(original_caption(original_path),
                                style("ImgCap", fontSize=8, leading=10.5, textColor=MUTED))]
    else:
        # INTEGRATION (changes.md 6.6): say so when the original is gone.
        image_cell = [Paragraph(
            "<i>The original image file is no longer stored on the server. The result and "
            "scores are the recorded result of the analysis made when it was.</i>", small)]
    result_box = Table([[result_text, image_cell]],
                       colWidths=[PAGE_WIDTH - image_col - 24, image_col + 24])
    result_box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#f8fafc")),
        ("BOX", (0, 0), (-1, -1), 1, RULE),
        ("LINEBEFORE", (0, 0), (0, -1), 5, accent),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (0, -1), 16),
        ("LEFTPADDING", (1, 0), (1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 14),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 14),
    ]))
    story.append(result_box)
    story.append(Spacer(1, 18))

    # 3. How the result was reached ------------------------------------------
    story.append(Paragraph("How the result was reached", h2))
    story.append(Paragraph(
        "Two independent detectors examined the image. Each gives a score from 0 to 1, where "
        "<b>higher means more AI-like</b>. Their scores are combined into one, and the combined "
        "score decides the result.", body))
    story.append(Spacer(1, 8))

    head = style("Head", fontName="Helvetica-Bold", fontSize=10, leading=13, textColor=MUTED)
    cell = style("Cell", fontSize=10.5, leading=14)
    score_cell = style("Score", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK)
    rows = [
        [Paragraph("Detector", head), Paragraph("Score", head), Paragraph("What it looks at", head)],
        [Paragraph(f"Content detector<br/><font size=9 color='#64748b'>{_content_detector_name(prediction)}</font>", cell),
         Paragraph(f"{prediction.semantic_score:.3f}", score_cell),
         Paragraph("What the picture shows, compared with AI images it learned from.", cell)],
        [Paragraph("Frequency detector<br/><font size=9 color='#64748b'>SPAI</font>", cell),
         Paragraph("—" if semantic_only else f"{prediction.frequency_score:.3f}", score_cell),
         Paragraph("Fine pixel patterns that are invisible to the eye but typical of image generators."
                   + (" <i>Not measured: the image is smaller than 224 pixels.</i>" if semantic_only else ""),
                   cell)],
        [Paragraph("<b>Combined score</b>", cell),
         Paragraph(f"{prediction.fusion_score:.3f}", score_cell),
         Paragraph("The two scores combined. "
                   + (f"At or above <b>{tau:.2f}</b> the result is AI Generated; below it, Real."
                      if tau is not None else "It is compared with a fixed decision point."), cell)],
    ]
    scores = Table(rows, colWidths=[PAGE_WIDTH * 0.28, PAGE_WIDTH * 0.14, PAGE_WIDTH * 0.58])
    scores.setStyle(TableStyle([
        ("LINEBELOW", (0, 0), (-1, 0), 1, RULE),
        ("LINEBELOW", (0, 1), (-1, -2), 0.5, colors.HexColor("#e2e8f0")),
        ("BACKGROUND", (0, -1), (-1, -1), colors.HexColor("#f1f5f9")),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(scores)
    if semantic_only:
        story.append(Spacer(1, 6))
        story.append(Paragraph(
            "<b>Lower reliability:</b> this image is too small for the frequency detector, so the "
            "result rests on the content detector alone, which is the less reliable of the two.", small))
    story.append(Spacer(1, 12))


    # 5. Keep in mind (the permanent interpretability notice, NF.13) ----------
    notes = [
        "This result is a model's estimate, not proof. Use it alongside other evidence.",
        "Confidence is not the chance that the result is correct.",
        "Resizing, heavy editing or 'AI enhancement' (for example by phone cameras or upscalers) "
        "can make a real photo look AI-generated, or hide the traces of an AI image.",
        "Highlighted regions show where the detectors focused. They are not evidence of where an "
        "image was changed.",
        "The system was tested mainly on images from 2022-2023 generators; newer generators may "
        "behave differently.",
    ]
    keep_title = style("KeepTitle", fontName="Helvetica-Bold", fontSize=12, leading=15, textColor=INK, spaceAfter=4)
    keep = [Paragraph("Keep in mind", keep_title)] + [Paragraph(n, bullet, bulletText="•") for n in notes]
    box = Table([[keep]], colWidths=[PAGE_WIDTH])
    box.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), colors.HexColor("#fffbeb")),
        ("BOX", (0, 0), (-1, -1), 1, colors.HexColor("#fde68a")),
        ("LEFTPADDING", (0, 0), (-1, -1), 14),
        ("RIGHTPADDING", (0, 0), (-1, -1), 14),
        ("TOPPADDING", (0, 0), (-1, -1), 8),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 8),
    ]))
    story.append(KeepTogether([box]))
    story.append(Spacer(1, 18))

    semantic = panels.get("semantic")
    frequency = panels.get("frequency")
    if semantic or frequency:
        intro = [Paragraph("Where the detectors looked", h2), Paragraph(
            "These pictures show what each detector paid attention to. They help explain the scores, "
            "but they <b>do not show where or whether the image was edited</b>, and they do not change "
            "the result.", body), Spacer(1, 10)]
        col = (PAGE_WIDTH - 16) / 2

        def panel(title: str, plain: str, item: tuple[str, str] | None, missing: str) -> list:
            parts = [Paragraph(title, panel_title), Spacer(1, 2), Paragraph(plain, small), Spacer(1, 6)]
            if item:
                parts += [fitted(item[0], col - 8, 2.6 * inch), Spacer(1, 6),
                          Paragraph(f"<i>Technical note:</i> {caption_for(item[1])}",
                                    style("Note", fontSize=8, leading=11, textColor=MUTED))]
            else:
                parts.append(Paragraph(f"<i>{missing}</i>", small))
            return parts

        grid = Table([[
            panel("Content detector: attention map",
                  "Warmer colours mark the parts of the picture the content detector focused on most.",
                  semantic, "This picture could not be produced for this image."),
            panel("Frequency detector: pattern map",
                  "The mix of fine and coarse pixel patterns the frequency detector measured.",
                  frequency, "This picture was not produced: the image is smaller than the frequency "
                             "detector's 224-pixel patch."),
        ]], colWidths=[col + 8, col + 8])
        grid.setStyle(TableStyle([
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (0, -1), 16),
        ]))
        story.append(KeepTogether(intro + [grid]))
        story.append(Spacer(1, 18))

    # 6. Technical details, last ---------------------------------------------
    tech_style = style("Tech", fontSize=9, leading=12, textColor=MUTED)
    model = (f"{prediction.model.model_name} (v{prediction.model.model_version})"
             if prediction.model else "Hybrid ViT/FFT v1.0")
    tech = Table([
        [Paragraph("<b>Technical details</b>", tech_style), ""],
        [Paragraph("Report reference", tech_style), Paragraph(f"#{prediction.prediction_id}", tech_style)],
        [Paragraph("Model configuration", tech_style), Paragraph(model, tech_style)],
        [Paragraph("Raw scores", tech_style),
         Paragraph(f"content {prediction.semantic_score:.4f} · frequency "
                   + ("not measured" if semantic_only else f"{prediction.frequency_score:.4f}")
                   + f" · combined {prediction.fusion_score:.4f}", tech_style)],
    ], colWidths=[PAGE_WIDTH * 0.28, PAGE_WIDTH * 0.72])
    tech.setStyle(TableStyle([
        ("SPAN", (0, 0), (-1, 0)),
        ("LINEABOVE", (0, 0), (-1, 0), 0.5, RULE),
        ("TOPPADDING", (0, 0), (-1, -1), 2),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
        ("LEFTPADDING", (0, 0), (-1, -1), 0),
    ]))
    story.append(KeepTogether([tech]))

    footer = f"TruePixels.rgb  ·  Report #{prediction.prediction_id}  ·  A result is a model's estimate, not proof."

    def _footer(canvas, document):
        canvas.saveState()
        canvas.setFont("Helvetica", 8.5)
        canvas.setFillColor(MUTED)
        canvas.drawString(document.leftMargin, 28, footer)
        canvas.drawRightString(document.pagesize[0] - document.rightMargin, 28, f"Page {canvas.getPageNumber()}")
        canvas.restoreState()

    doc.build(story, onFirstPage=_footer, onLaterPages=_footer)
    buffer.seek(0)
    return buffer

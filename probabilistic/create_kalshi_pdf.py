#!/usr/bin/env python3
"""Create a short, checked PDF briefing from the Kalshi 15-minute study."""
import csv
import os
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak, KeepTogether

HERE = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(HERE, "kalshi_15m_pricing_study.pdf")


def read_pdf_curve():
    with open(os.path.join(HERE, "next_15m_pdf.csv")) as handle:
        rows = list(csv.DictReader(handle))
    return rows[0], rows


def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 8)
    canvas.setFillColor(colors.HexColor("#64748B"))
    canvas.drawString(0.65 * inch, 0.4 * inch, "BTCFDUSD 15-minute fair-value research - historical model study")
    canvas.drawRightString(7.85 * inch, 0.4 * inch, f"Page {doc.page}")
    canvas.restoreState()


def main():
    first, curve = read_pdf_curve()
    mid = float(first["fair_up_mid_cents"])
    styles = getSampleStyleSheet()
    title = ParagraphStyle("TitleX", parent=styles["Title"], fontName="Helvetica-Bold", fontSize=22, leading=26, textColor=colors.HexColor("#0F172A"), spaceAfter=12)
    subtitle = ParagraphStyle("SubtitleX", parent=styles["BodyText"], fontName="Helvetica", fontSize=11, leading=14, textColor=colors.HexColor("#475569"), spaceAfter=8)
    heading = ParagraphStyle("HeadingX", parent=styles["Heading2"], fontName="Helvetica-Bold", fontSize=13, leading=16, textColor=colors.HexColor("#0F4C5C"), spaceBefore=12, spaceAfter=6)
    body = ParagraphStyle("BodyX", parent=styles["BodyText"], fontName="Helvetica", fontSize=9.5, leading=13, textColor=colors.HexColor("#1E293B"), spaceAfter=6)
    note = ParagraphStyle("Note", parent=body, backColor=colors.HexColor("#FFF7ED"), borderColor=colors.HexColor("#F59E0B"), borderWidth=0.5, borderPadding=8, spaceBefore=8, spaceAfter=10)
    doc = SimpleDocTemplate(OUT, pagesize=letter, leftMargin=.65 * inch, rightMargin=.65 * inch, topMargin=.6 * inch, bottomMargin=.65 * inch)
    story = []
    story += [Paragraph("15-minute BTC Up/Down pricing study", title), Paragraph("A continuous-PDF approach to estimating a Kalshi-style binary fair midpoint", subtitle), Spacer(1, 10)]
    story.append(Paragraph("Bottom line", heading))
    story.append(Paragraph("On a strict final 20% walk-forward test, the two-hour one-minute-bar feature set did <b>not</b> beat a constant 50/50 fair midpoint for a 15-minute BTCFDUSD up/down contract. The selected regularized model had 0.6938 log loss versus 0.6932 for the constant prior. That is no evidence of an executable directional edge.", note))
    story.append(Paragraph("Contract and fair-value definition", heading))
    story.append(Paragraph("YES settles at $1 when BTCFDUSD close 15 minutes after the contract origin exceeds the origin close, and at $0 otherwise. Ignoring fees, spread, and venue-specific settlement rules, fair YES midpoint = 100 x P(up) cents. The PDF is built so its probability mass above zero is exactly this midpoint probability.", body))
    story.append(Paragraph("Walk-forward scoring", heading))
    score = [["Model", "Log loss", "Brier", "Result"], ["Constant prior", "0.6932", "0.2500", "Benchmark"], ["Global logistic", "0.6938", "0.2503", "No improvement"], ["Selected model", "0.6938", "0.2503", "No improvement"]]
    table = Table(score, colWidths=[2.0*inch, 1.05*inch, 1.0*inch, 2.1*inch])
    table.setStyle(TableStyle([("BACKGROUND", (0,0), (-1,0), colors.HexColor("#0F4C5C")), ("TEXTCOLOR", (0,0), (-1,0), colors.white), ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"), ("FONTNAME", (0,1), (-1,-1), "Helvetica"), ("FONTSIZE", (0,0), (-1,-1), 9), ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#CBD5E1")), ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, colors.HexColor("#F8FAFC")]), ("ALIGN", (1,1), (-1,-1), "CENTER"), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story += [table, Paragraph("The test covers non-overlapping 15-minute contracts from a BTCFDUSD history spanning 2026-04-01 through 2026-07-26. Training uses the first 70%, tuning and probability calibration the next 10%, and the final 20% remains untouched until scoring.", body)]
    story.append(PageBreak())
    story.append(Paragraph("Model design", heading))
    story.append(Paragraph("Inputs are causal summaries of the prior two hours: multi-scale returns and realized volatility (1 to 120 minutes), quote volume, taker-flow imbalance, and intra-minute range. Ridge logistic regression selects stable features; a volatility-regime version is only used when it wins on the calibration period. It did not win here, so the global model was selected.", body))
    story.append(Paragraph("Continuous density construction", heading))
    story.append(Paragraph("For the selected trailing-30-minute volatility regime, a Gaussian kernel density estimate is fitted to historical 15-minute BTC returns. An exponential tilt is solved numerically to force the density's P(return > 0) to equal the calibrated logistic probability. This yields a smooth PDF, percentile prices, and a binary fair midpoint that agree by construction.", body))
    story.append(Paragraph("Latest archived forward quote", heading))
    quote = [["Origin", first["forecast_origin_utc"]], ["15-minute settlement", first["contract_settlement_utc"]], ["Spot reference", f"${float(first['price']) / __import__('math').exp(float(first['return_bps']) / 10000):,.2f}"], ["Fair YES/UP midpoint", f"{mid:.1f} cents"], ["Fair NO/DOWN midpoint", f"{100-mid:.1f} cents"]]
    qtable = Table(quote, colWidths=[1.9*inch, 4.2*inch])
    qtable.setStyle(TableStyle([("BACKGROUND", (0,0), (0,-1), colors.HexColor("#E2E8F0")), ("FONTNAME", (0,0), (0,-1), "Helvetica-Bold"), ("GRID", (0,0), (-1,-1), .25, colors.HexColor("#CBD5E1")), ("FONTSIZE", (0,0), (-1,-1), 9), ("TOPPADDING", (0,0), (-1,-1), 6), ("BOTTOMPADDING", (0,0), (-1,-1), 6)]))
    story += [qtable, Paragraph("This is an archived-data forward quote (latest archive observation), not a live market quote.", body)]
    story.append(Paragraph("What would make this actionable", heading))
    story.append(Paragraph("Next: ingest the aggregate-trade/tick archive and test trade-sign imbalance, trade-arrival intensity, short-horizon price impact, and bid/ask data if obtainable. Evaluate against executable Kalshi prices with the exact cutoff, index, and fee rules. Trade only when executable price clears estimated error and costs.", body))
    story.append(Paragraph("Conclusion", heading))
    story.append(Paragraph("The PDF framework validly turns a return distribution into an up/down midpoint. The bar-only directional signal is not good enough. Next step: tick-level, venue-aligned walk-forward testing.", note))
    doc.build(story, onFirstPage=footer, onLaterPages=footer)


if __name__ == "__main__":
    main()

# reports.py
import os
from pathlib import Path
from typing import List, Dict, Any
import pandas as pd
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

from config import PDF_REPORTS_DIR, NOMBRE_NEGOCIO, SIGNO_MONEDA, FORMATO_MILES
from db import weekly_summary as db_weekly_summary

# Mapeo de nombres de meses en español → número (1‑12)
SPANISH_MONTHS = {
    "Enero": 1,
    "Febrero": 2,
    "Marzo": 3,
    "Abril": 4,
    "Mayo": 5,
    "Junio": 6,
    "Julio": 7,
    "Agosto": 8,
    "Septiembre": 9,
    "Octubre": 10,
    "Noviembre": 11,
    "Diciembre": 12,
}

def _fmt_money(value: float) -> str:
    if FORMATO_MILES:
        return f"{SIGNO_MONEDA}{int(value):,}".replace(",", ".")
    return f"{SIGNO_MONEDA}{value:.2f}"

def generate_text_report(month_name: str, weeks: List[int]) -> str:
    """Return a plain‑text report ready to be sent to Telegram.
    Acepta el nombre del mes en español y lo convierte a número mediante `SPANISH_MONTHS`.
    """
    # Conversión de nombre de mes (español) a número
    month_num = SPANISH_MONTHS.get(month_name.capitalize())
    if month_num is None:
        # intentar con pandas (caso de nombre en inglés)
        try:
            month_num = pd.to_datetime(month_name, format="%B").month
        except Exception:
            raise ValueError(f"Mes no reconocido: {month_name}")
    data = db_weekly_summary(month_num, weeks)

    lines = [
        f"📊 *Reporte semanal – {NOMBRE_NEGOCIO}*",
        f"*Mes:* {month_name}",
        f"*Semanas:* {', '.join(str(w) for w in weeks)}",
        "",
        "*Ventas*",
        "----------------------------",
    ]
    if data["ventas"].empty:
        lines.append("_Sin ventas en el período seleccionado_")
    else:
        for _, row in data["ventas"].iterrows():
            fecha = row["fecha"].strftime("%d/%m")
            lines.append(f"{fecha}: {_fmt_money(row['subtotal'])}")

    lines.extend([
        "",
        "*Gastos*",
        "----------------------------",
    ])
    if data["gastos"].empty:
        lines.append("_Sin gastos en el período seleccionado_")
    else:
        for _, row in data["gastos"].iterrows():
            fecha = row["fecha"].strftime("%d/%m")
            desc = row.get('descripcion') or row.get('tipo')
            lines.append(f"{fecha} – {desc}: {_fmt_money(row['monto'])}")

    tot = data["totales"]
    lines.extend([
        "",
        "*Totales*",
        f"Ventas: {_fmt_money(tot['ventas'])}",
        f"Gastos: {_fmt_money(tot['gastos'])}",
        f"🟢 *Neto*: {_fmt_money(tot['neto'])}",
    ])
    return "\n".join(lines)


def generate_pdf_report(month_name: str, weeks: List[int]) -> Path:
    """Create a PDF file (text‑only) and return its absolute path.
    Acepta el nombre del mes en español.
    """
    # Conversión de nombre de mes (español) a número
    month_num = SPANISH_MONTHS.get(month_name.capitalize())
    if month_num is None:
        try:
            month_num = pd.to_datetime(month_name, format="%B").month
        except Exception:
            raise ValueError(f"Mes no reconocido: {month_name}")
    data = db_weekly_summary(month_num, weeks)

    out_dir = Path(PDF_REPORTS_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    filename = f"reporte_{month_name.lower()}_{'_'.join(map(str, weeks))}.pdf"
    out_path = out_dir / filename

    c = canvas.Canvas(str(out_path), pagesize=LETTER)
    width, height = LETTER
    x_margin, y = 50, height - 50
    line_height = 14

    def _add_line(txt: str, bold: bool = False):
        nonlocal y
        if y < 50:
            c.showPage()
            y = height - 50
        c.setFont("Helvetica-Bold" if bold else "Helvetica", 12)
        c.drawString(x_margin, y, txt)
        y -= line_height

    # Header
    _add_line(f"{NOMBRE_NEGOCIO} – Reporte semanal", bold=True)
    _add_line(f"Mes: {month_name}")
    _add_line(f"Semanas: {', '.join(map(str, weeks))}")
    _add_line("-" * 60)

    # Ventas
    _add_line("Ventas:", bold=True)
    if data["ventas"].empty:
        _add_line("Sin ventas en el periodo")
    else:
        for _, r in data["ventas"].iterrows():
            fecha = r["fecha"].strftime("%d/%m")
            _add_line(f"{fecha}: {_fmt_money(r['subtotal'])}")
    _add_line("-" * 60)

    # Gastos
    _add_line("Gastos:", bold=True)
    if data["gastos"].empty:
        _add_line("Sin gastos en el periodo")
    else:
        for _, r in data["gastos"].iterrows():
            fecha = r["fecha"].strftime("%d/%m")
            desc = r.get('descripcion') or r.get('tipo')
            _add_line(f"{fecha} – {desc}: {_fmt_money(r['monto'])}")
    _add_line("-" * 60)

    # Totales
    tot = data["totales"]
    _add_line("Totales:", bold=True)
    _add_line(f"Ventas: {_fmt_money(tot['ventas'])}")
    _add_line(f"Gastos: {_fmt_money(tot['gastos'])}")
    _add_line(f"Neto: {_fmt_money(tot['neto'])}")

    c.save()
    return out_path

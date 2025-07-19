import pandas as pd
from formatting import clean_text
def build_pdf_report(df: pd.DataFrame, title: str = "Telemetry Report", y_label: str = "", plot: bool = True) -> str:
    import tempfile
    from fpdf import FPDF
    import plotly.graph_objects as go

    pdf = FPDF()
    pdf.add_page()

    pdf.set_font("Arial", 'B', 16)
    pdf.cell(0, 10, clean_text(title), ln=True, align="C")
    pdf.ln(10)

    # Table
    pdf.set_font("Arial", 'B', 12)
    col_width = 190 // len(df.columns)
    for col in df.columns:
        pdf.cell(col_width, 10, clean_text(str(col)), border=1, align="C")
    pdf.ln()

    pdf.set_font("Arial", '', 12)
    for _, row in df.iterrows():
        for col in df.columns:
            val = f"{row[col]:,.2f}" if isinstance(row[col], (int, float)) else clean_text(str(row[col]))
            pdf.cell(col_width, 10, val, border=1, align="C")
        pdf.ln()

    if plot and df.shape[1] >= 2:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=df[df.columns[0]], y=df[df.columns[1]], mode='lines+markers'))
        fig.update_layout(title=title, xaxis_title=df.columns[0], yaxis_title=y_label or df.columns[1])

        tmp_img = tempfile.NamedTemporaryFile(delete=False, suffix=".png")
        fig.write_image(tmp_img.name)
        pdf.ln(10)
        pdf.image(tmp_img.name, x=10, w=190)

    tmp_pdf = tempfile.NamedTemporaryFile(delete=False, suffix=".pdf")
    pdf.output(tmp_pdf.name)
    return tmp_pdf.name

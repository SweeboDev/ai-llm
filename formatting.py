import re
import os
from openai import AzureOpenAI


# Initialize Azure OpenAI client
client = AzureOpenAI(
    api_key=os.getenv("AZURE_OPENAI_KEY"),
    api_version=os.getenv("AZURE_OPENAI_VERSION", "2023-05-15"),
    azure_endpoint=os.getenv("AZURE_OPENAI_ENDPOINT")
)

def clean_text(text):
    replacements = {
        "\u2013": "-",  # en dash
        "\u2014": "-",  # em dash
        "\u2018": "'",  # left single quote
        "\u2019": "'",  # right single quote
        "\u201c": '"',  # left double quote
        "\u201d": '"',  # right double quote
        "\u2026": "...",  # ellipsis
    }
    for bad, good in replacements.items():
        text = text.replace(bad, good)
    return text


def format_reply(prompt: str, result: list) -> str:
    if not result or not isinstance(result, list) or not result[0]:
        return "No recognized data found for that request."

    prompt_lower = prompt.lower()

    # 📦 CSV export
    if "csv" in prompt_lower:
        import csv
        import io

        output = io.StringIO()
        headers = result[0].keys()
        writer = csv.DictWriter(output, fieldnames=headers)
        writer.writeheader()
        writer.writerows(result)

        csv_data = output.getvalue()
        return f"[CSV_DATA_START]\n{csv_data.strip()}\n[CSV_DATA_END]"

    # 🧾 Table format
    if "table view" in prompt_lower or "as a table" in prompt_lower:
        headers = list(result[0].keys())
        rows = [list(r.values()) for r in result]

        col_widths = [
            max(len(str(v)) for v in [h] + [r[i] for r in rows])
            for i, h in enumerate(headers)
        ]

        header_line = " | ".join(f"{h:<{w}}" for h, w in zip(headers, col_widths))
        separator = "-+-".join("-" * w for w in col_widths)
        row_lines = [
            " | ".join(f"{str(val):<{w}}" for val, w in zip(row, col_widths))
            for row in rows
        ]

        return f"Here is the data in table format:\n\n" + "\n".join([header_line, separator] + row_lines)

    from pdf_report import build_pdf_report

    if "pdf" in prompt_lower:
        import pandas as pd
        df = pd.DataFrame(result)
        if df.empty:
            return "No data available to export."

    # Optional dynamic title from prompt or fallback
        title = "Telemetry Report"
        if "microsoft" in prompt_lower:
            title = "Microsoft Device Summary"
        elif "temperature" in prompt_lower:
            title = "Temperature Trend"

        pdf_path = build_pdf_report(df, title=title)
        return f"[PDF_DATA_READY] {pdf_path}"


        
    # 🧠 Default: Let GPT summarize naturally
    phrasing_prompt = f"""
You are a telemetry assistant. The user asked: "{prompt}"

Here is the result:
{result}

Respond with a clear and helpful summary for the user based on the data.
- Be concise.
- Do not explain the SQL or structure.
- Just answer as a helpful assistant would. Dont over word anything, be clear and concise and informative but dont explain the data.
- If you are asked something like "what was the average temperatures in PAR1 Building 2 Datahall 10 in 2025" you should list each reading.
- If the result contains both sensor and real world temperatures, compare them numerically.
- Format as: "Sensor: 23.8°C | Real: 25.4°C → Difference: 1.6°C"

""".strip()

    try:
        response = client.chat.completions.create(
            model=os.getenv("AZURE_OPENAI_DEPLOYMENT"),
            messages=[
                {"role": "system", "content": "You summarize telemetry query results into a clear human response."},
                {"role": "user", "content": phrasing_prompt}
            ],
            max_tokens=300
        )
        return response.choices[0].message.content.strip()

    except Exception as e:
        print("[FORMAT REPLY FAILED]:", str(e))
        return "The request succeeded but I couldn't generate a response."

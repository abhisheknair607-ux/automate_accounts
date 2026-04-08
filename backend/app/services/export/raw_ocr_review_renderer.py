from __future__ import annotations

import json
from datetime import UTC, datetime
from html import escape
from typing import Any

from app.services.export.raw_ocr_mapper import raw_ocr_export_mapper


class RawOCRReviewRenderer:
    def render(
        self,
        *,
        case_id: str,
        invoice_payload: dict[str, Any] | None,
        docket_payload: dict[str, Any] | None,
    ) -> str:
        generated_at = datetime.now(UTC).strftime("%Y-%m-%d %H:%M:%S UTC")
        return f"""<!doctype html>
<html lang="en">
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1" />
    <title>Raw OCR Review</title>
    <style>
      :root {{
        color-scheme: light;
        --ink: #24170f;
        --muted: #6c594d;
        --paper: #f7f0e8;
        --panel: #fffaf6;
        --line: #e7d7c8;
        --accent: #a6541a;
        --accent-soft: #f8e4d3;
        --mono: "Cascadia Code", Consolas, monospace;
        --sans: "Segoe UI", Tahoma, sans-serif;
        --serif: Georgia, "Times New Roman", serif;
      }}
      * {{ box-sizing: border-box; }}
      body {{
        margin: 0;
        padding: 32px;
        font-family: var(--sans);
        color: var(--ink);
        background:
          radial-gradient(circle at top left, rgba(255, 204, 153, 0.28), transparent 32%),
          linear-gradient(180deg, #fff8f2 0%, var(--paper) 100%);
      }}
      main {{
        max-width: 1400px;
        margin: 0 auto;
      }}
      .hero {{
        padding: 24px 28px;
        border: 1px solid var(--line);
        border-radius: 28px;
        background: rgba(255, 250, 246, 0.9);
        box-shadow: 0 18px 50px rgba(78, 49, 28, 0.08);
      }}
      .eyebrow {{
        margin: 0 0 10px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.18em;
        text-transform: uppercase;
        color: var(--accent);
      }}
      h1, h2, h3 {{
        margin: 0;
        font-family: var(--serif);
      }}
      h1 {{
        font-size: 46px;
        line-height: 1.05;
      }}
      h2 {{
        font-size: 34px;
        margin-bottom: 16px;
      }}
      h3 {{
        font-size: 22px;
        margin-bottom: 12px;
      }}
      p {{
        margin: 14px 0 0;
        color: var(--muted);
        max-width: 900px;
        line-height: 1.6;
      }}
      .section {{
        margin-top: 28px;
        padding: 24px 28px;
        border: 1px solid var(--line);
        border-radius: 28px;
        background: rgba(255, 250, 246, 0.95);
        box-shadow: 0 14px 36px rgba(78, 49, 28, 0.06);
      }}
      .meta-grid {{
        display: grid;
        grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
        gap: 12px;
        margin: 18px 0 0;
      }}
      .meta-card {{
        padding: 14px 16px;
        border: 1px solid var(--line);
        border-radius: 18px;
        background: var(--panel);
      }}
      .meta-card small {{
        display: block;
        margin-bottom: 6px;
        font-size: 11px;
        letter-spacing: 0.12em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      .meta-card strong {{
        display: block;
        word-break: break-word;
      }}
      .flag-row {{
        display: flex;
        flex-wrap: wrap;
        gap: 8px;
        margin-top: 14px;
      }}
      .flag {{
        display: inline-flex;
        align-items: center;
        padding: 6px 10px;
        border-radius: 999px;
        background: var(--accent-soft);
        color: var(--accent);
        font-size: 12px;
        font-weight: 700;
      }}
      .content-block {{
        margin-top: 22px;
      }}
      .ocr-table-wrap {{
        overflow-x: auto;
        border: 1px solid var(--line);
        border-radius: 20px;
        background: white;
      }}
      table {{
        width: 100%;
        border-collapse: collapse;
      }}
      th, td {{
        padding: 12px 14px;
        border-bottom: 1px solid #efe4d9;
        vertical-align: top;
        text-align: left;
      }}
      th {{
        position: sticky;
        top: 0;
        background: #fcf6f0;
        font-size: 12px;
        letter-spacing: 0.08em;
        text-transform: uppercase;
        color: var(--muted);
      }}
      tbody tr:last-child td {{
        border-bottom: 0;
      }}
      .text-review {{
        margin: 0;
        padding: 18px 20px;
        overflow: auto;
        border: 1px solid var(--line);
        border-radius: 20px;
        background: #1d130f;
        color: #f8eee7;
        font-family: var(--mono);
        font-size: 13px;
        line-height: 1.55;
        white-space: pre-wrap;
      }}
      details {{
        margin-top: 20px;
        border: 1px solid var(--line);
        border-radius: 20px;
        background: var(--panel);
        overflow: hidden;
      }}
      summary {{
        padding: 14px 16px;
        cursor: pointer;
        font-weight: 700;
      }}
      .details-body {{
        padding: 0 16px 16px;
      }}
      .empty {{
        padding: 16px 18px;
        border: 1px dashed var(--line);
        border-radius: 18px;
        color: var(--muted);
        background: rgba(255, 255, 255, 0.65);
      }}
      .line-number {{
        width: 72px;
        color: var(--muted);
        white-space: nowrap;
      }}
      @media (max-width: 900px) {{
        body {{
          padding: 18px;
        }}
        h1 {{
          font-size: 34px;
        }}
        .section, .hero {{
          padding: 20px;
          border-radius: 22px;
        }}
      }}
    </style>
  </head>
  <body>
    <main>
      <section class="hero">
        <p class="eyebrow">Raw OCR Review</p>
        <h1>Google OCR reading review</h1>
        <p>Case <strong>{escape(case_id)}</strong> rendered as a free-form review document. This file keeps the raw OCR audit separate from canonical reconciliation and P&amp;L exports while making the invoice and docket payloads easier to inspect than a spreadsheet.</p>
        <p>Generated at {escape(generated_at)}.</p>
      </section>
      {self._render_document_section("Invoice OCR Review", invoice_payload)}
      {self._render_document_section("Delivery Docket OCR Review", docket_payload)}
    </main>
  </body>
</html>
"""

    def _render_document_section(self, title: str, payload: dict[str, Any] | None) -> str:
        if not payload:
            return f"""
      <section class="section">
        <p class="eyebrow">{escape(title)}</p>
        <h2>{escape(title)}</h2>
        <div class="empty">No completed extraction payload was available for this document.</div>
      </section>
"""

        analysis = payload.get("analysis_result") if isinstance(payload.get("analysis_result"), dict) else {}
        tables = analysis.get("tables") if isinstance(analysis.get("tables"), list) else []
        pages = analysis.get("pages") if isinstance(analysis.get("pages"), list) else []
        documents = analysis.get("documents") if isinstance(analysis.get("documents"), list) else []
        flags = self._review_flags(payload)
        flat_rows = raw_ocr_export_mapper.map_rows(payload)
        metadata = [
            ("Source filename", payload.get("source_filename")),
            ("Model ID", payload.get("model_id")),
            ("API version", analysis.get("api_version")),
            ("Detected pages", str(len(pages) or 0)),
            ("Detected tables", str(len(tables) or 0)),
            ("Structured documents", str(len(documents) or 0)),
        ]
        meta_cards = "".join(
            f"""
            <div class="meta-card">
              <small>{escape(label)}</small>
              <strong>{escape(str(value or "-"))}</strong>
            </div>
            """
            for label, value in metadata
        )

        return f"""
      <section class="section">
        <p class="eyebrow">{escape(title)}</p>
        <h2>{escape(title)}</h2>
        <div class="meta-grid">{meta_cards}</div>
        {self._render_flags(flags)}
        <div class="content-block">
          <h3>Detected line-item tables</h3>
          {self._render_detected_tables(tables)}
        </div>
        <div class="content-block">
          <h3>Structured fields</h3>
          {self._render_structured_documents(documents)}
        </div>
        <div class="content-block">
          <h3>OCR text review</h3>
          {self._render_page_text(pages, analysis.get("content"))}
        </div>
        <details>
          <summary>Flattened raw payload audit</summary>
          <div class="details-body">
            {self._render_flat_rows(flat_rows)}
          </div>
        </details>
      </section>
"""

    def _review_flags(self, payload: dict[str, Any]) -> list[str]:
        flags: list[str] = []
        if payload.get("text_identity_backfill_used"):
            flags.append("Text backfill used")
        if payload.get("layout_backfill_used"):
            flags.append("Layout backfill used")
        if payload.get("layout_model_id"):
            flags.append(f"Layout model: {payload['layout_model_id']}")
        return flags

    def _render_flags(self, flags: list[str]) -> str:
        if not flags:
            return ""
        rendered = "".join(f'<span class="flag">{escape(flag)}</span>' for flag in flags)
        return f'<div class="flag-row">{rendered}</div>'

    def _render_detected_tables(self, tables: list[dict[str, Any]]) -> str:
        if not tables:
            return '<div class="empty">No table blocks were detected in this payload.</div>'
        sections: list[str] = []
        for index, table in enumerate(tables, start=1):
            matrix = self._table_matrix(table)
            if not matrix:
                continue
            header = matrix[0]
            body = matrix[1:] or [[""] * len(header)]
            header_html = "".join(f"<th>{escape(cell)}</th>" for cell in header)
            body_html = "".join(
                "<tr>" + "".join(f"<td>{escape(cell)}</td>" for cell in row) + "</tr>"
                for row in body
            )
            sections.append(
                f"""
                <details {'open' if index == 1 else ''}>
                  <summary>Detected table {index}</summary>
                  <div class="details-body">
                    <div class="ocr-table-wrap">
                      <table>
                        <thead><tr>{header_html}</tr></thead>
                        <tbody>{body_html}</tbody>
                      </table>
                    </div>
                  </div>
                </details>
                """
            )
        return "".join(sections) if sections else '<div class="empty">No readable table rows were available.</div>'

    def _table_matrix(self, table: dict[str, Any]) -> list[list[str]]:
        cells = table.get("cells") if isinstance(table.get("cells"), list) else []
        if not cells:
            return []
        row_count = int(table.get("row_count") or 0)
        column_count = int(table.get("column_count") or 0)
        if row_count <= 0:
            row_count = max(int(cell.get("row_index") or 0) for cell in cells) + 1
        if column_count <= 0:
            column_count = max(int(cell.get("column_index") or 0) for cell in cells) + 1
        matrix = [["" for _ in range(column_count)] for _ in range(row_count)]
        for cell in cells:
            row_index = int(cell.get("row_index") or 0)
            column_index = int(cell.get("column_index") or 0)
            if row_index < row_count and column_index < column_count:
                matrix[row_index][column_index] = str(cell.get("content") or "")
        return matrix

    def _render_structured_documents(self, documents: list[dict[str, Any]]) -> str:
        if not documents:
            return '<div class="empty">This payload did not include structured document fields.</div>'

        sections: list[str] = []
        for index, document in enumerate(documents, start=1):
            doc_type = str(document.get("doc_type") or f"document-{index}")
            confidence = document.get("confidence")
            fields = document.get("fields") if isinstance(document.get("fields"), dict) else {}
            field_rows = "".join(
                f"<tr><td>{escape(field_name)}</td><td>{escape(self._field_preview(field_value))}</td></tr>"
                for field_name, field_value in fields.items()
            )
            items_html = self._render_items_table(fields.get("Items"))
            sections.append(
                f"""
                <details {'open' if index == 1 else ''}>
                  <summary>{escape(doc_type)}{f' (confidence {confidence:.2f})' if isinstance(confidence, (int, float)) else ''}</summary>
                  <div class="details-body">
                    <div class="ocr-table-wrap">
                      <table>
                        <thead><tr><th>Field</th><th>Extracted value</th></tr></thead>
                        <tbody>{field_rows or '<tr><td colspan=\"2\">No structured fields</td></tr>'}</tbody>
                      </table>
                    </div>
                    {items_html}
                  </div>
                </details>
                """
            )
        return "".join(sections)

    def _render_items_table(self, items_field: Any) -> str:
        if not isinstance(items_field, dict):
            return ""
        items = items_field.get("value_array")
        if not isinstance(items, list) or not items:
            return ""

        columns: list[str] = []
        rows: list[dict[str, str]] = []
        for item in items:
            value_object = item.get("value_object") if isinstance(item, dict) else None
            if not isinstance(value_object, dict):
                continue
            row: dict[str, str] = {}
            for key, value in value_object.items():
                if key not in columns:
                    columns.append(key)
                row[key] = self._field_preview(value)
            rows.append(row)

        if not columns:
            return ""

        header_html = "".join(f"<th>{escape(column)}</th>" for column in columns)
        body_html = "".join(
            "<tr>" + "".join(f"<td>{escape(row.get(column, ''))}</td>" for column in columns) + "</tr>"
            for row in rows
        )
        return f"""
        <div class="content-block">
          <h3>Line-item field view</h3>
          <div class="ocr-table-wrap">
            <table>
              <thead><tr>{header_html}</tr></thead>
              <tbody>{body_html}</tbody>
            </table>
          </div>
        </div>
        """

    def _field_preview(self, value: Any) -> str:
        if not isinstance(value, dict):
            return str(value or "")
        if "content" in value and value.get("content"):
            return str(value["content"])
        if "value_string" in value:
            return str(value["value_string"])
        if "value_date" in value:
            return str(value["value_date"])
        if "value_number" in value:
            return str(value["value_number"])
        currency = value.get("value_currency")
        if isinstance(currency, dict):
            amount = currency.get("amount")
            code = currency.get("currency_code")
            return f"{amount} {code}".strip()
        if "value_array" in value and isinstance(value["value_array"], list):
            return f"{len(value['value_array'])} item(s)"
        return json.dumps(value, ensure_ascii=True)

    def _render_page_text(self, pages: list[dict[str, Any]], content: Any) -> str:
        if pages:
            page_sections: list[str] = []
            for page in pages:
                page_number = page.get("page_number") or "?"
                open_attr = "open" if str(page_number) == "1" else ""
                lines = page.get("lines") if isinstance(page.get("lines"), list) else []
                if not lines:
                    continue
                body_html = "".join(
                    f"<tr><td class=\"line-number\">Line {index}</td><td>{escape(str(line.get('content') or ''))}</td></tr>"
                    for index, line in enumerate(lines, start=1)
                )
                page_sections.append(
                    f"""
                    <details {open_attr}>
                      <summary>Page {escape(str(page_number))}</summary>
                      <div class="details-body">
                        <div class="ocr-table-wrap">
                          <table>
                            <thead><tr><th class="line-number">Line</th><th>OCR text</th></tr></thead>
                            <tbody>{body_html}</tbody>
                          </table>
                        </div>
                      </div>
                    </details>
                    """
                )
            if page_sections:
                return "".join(page_sections)

        cleaned = str(content or "").strip()
        if not cleaned:
            return '<div class="empty">No OCR text block was stored for this payload.</div>'
        return f'<pre class="text-review">{escape(cleaned)}</pre>'

    def _render_flat_rows(self, rows: list[dict[str, str]]) -> str:
        if not rows:
            return '<div class="empty">No flattened raw payload rows were available.</div>'
        body_html = "".join(
            "<tr>"
            f"<td>{escape(row.get('JSON Path', ''))}</td>"
            f"<td>{escape(row.get('Value', ''))}</td>"
            f"<td>{escape(row.get('Value Type', ''))}</td>"
            "</tr>"
            for row in rows
        )
        return f"""
        <div class="ocr-table-wrap">
          <table>
            <thead>
              <tr>
                <th>JSON Path</th>
                <th>Value</th>
                <th>Value Type</th>
              </tr>
            </thead>
            <tbody>{body_html}</tbody>
          </table>
        </div>
        """


raw_ocr_review_renderer = RawOCRReviewRenderer()

import json

from tools import system_report_tool as report


def sample_report():
    return report.ReportData(
        generated_at="2026-08-21_19-00-00",
        system_rows=[("Equipo", "PC <test>"), ("RAM", "16 GB")],
        disk_rows=[("C:", "C:/", "500 GB", "200 GB libres")],
        network_rows=[("IP local", "192.168.1.10")],
        top_cpu=[(123, "python.exe", 12.5, 3.2)],
        top_memory=[(456, "browser.exe", 2.0, 15.5)],
        temp_summary=[("C:/Temp", "20 MB")],
        event_summary=[
            (
                "21/08/2026 18:00:00",
                "Error",
                "Disk",
                "7",
                "Alto",
                "Revisar <disco>",
            )
        ],
    )


def test_report_text_and_html_include_sections_and_escape_html():
    data = sample_report()

    text = report.report_to_text(data)
    html = report.report_to_html(data)

    assert "Sistema" in text
    assert "Eventos recientes de Windows" in text
    assert "PID 123 | python.exe" in text
    assert "PC <test>" in text

    assert "Informe técnico del equipo" in html
    assert "PC &lt;test&gt;" in html
    assert "Revisar &lt;disco&gt;" in html
    assert "PC <test>" not in html


def test_report_pdf_is_generated(tmp_path):
    output = tmp_path / "report.pdf"
    report.report_to_pdf(sample_report(), output)

    assert output.exists()
    assert output.stat().st_size > 500
    assert output.read_bytes().startswith(b"%PDF")


def test_load_event_snapshot_reads_saved_events(monkeypatch, tmp_path):
    payload = {
        "events": [
            {
                "date": "21/08/2026",
                "level": "Error",
                "provider": "Disk",
                "event_id": 7,
                "risk": "Alto",
                "interpretation": "Revisar disco",
            }
        ]
    }
    (tmp_path / "event_report_snapshot.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )
    monkeypatch.setattr(report, "DATA_DIR", tmp_path)
    monkeypatch.setattr(report, "ensure_app_dirs", lambda: None)

    rows = report.load_event_snapshot()

    assert rows == [
        ("21/08/2026", "Error", "Disk", "7", "Alto", "Revisar disco")
    ]


def test_system_report_gui_populates_preview_tables_and_exports(qtbot, monkeypatch, tmp_path):
    tool = report.Tool()
    qtbot.addWidget(tool)
    tool.show()
    data = sample_report()

    tool.on_report_ready(data)

    assert tool.report_data is data
    assert "python.exe" in tool.preview.toPlainText()
    assert tool.system_table.rowCount() == 2
    assert tool.disk_table.rowCount() == 1
    assert tool.btn_html.isEnabled()
    assert tool.btn_pdf.isEnabled()
    assert tool.btn_txt.isEnabled()

    html_path = tmp_path / "out.html"
    monkeypatch.setattr(
        report.QFileDialog,
        "getSaveFileName",
        lambda *args, **kwargs: (str(html_path), ""),
    )
    monkeypatch.setattr(report.QMessageBox, "information", lambda *args, **kwargs: None)
    tool.export_html()

    assert html_path.exists()
    assert "PC &lt;test&gt;" in html_path.read_text(encoding="utf-8")

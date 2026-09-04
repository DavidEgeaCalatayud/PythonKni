from __future__ import annotations

from types import SimpleNamespace

import pytest

from pythonkni.web_recon import window
from pythonkni.web_recon.models import (
    DnsRecord,
    DnsSummary,
    FindingSeverity,
    HttpCheck,
    HttpSummary,
    PortResult,
    ReconFinding,
    ReconReport,
    ReconTarget,
    TechnologyEvidence,
    TlsSummary,
    WhoisSummary,
)


@pytest.fixture
def tool(qtbot):
    instance = window.Tool()
    qtbot.addWidget(instance)
    return instance


def sample_report():
    target = ReconTarget(
        "example.com",
        "https://example.com/",
        "https",
        "example.com",
        443,
    )
    return ReconReport(
        target=target,
        addresses=("1.2.3.4",),
        dns=DnsSummary(
            records=(DnsRecord("A", "example.com", "1.2.3.4"),),
            dmarc_policy="reject",
            dnssec_published=True,
        ),
        whois=WhoisSummary(registrar="Registrar"),
        tls=TlsSummary(
            available=True,
            version="TLSv1.3",
            cipher="AES",
            not_after="later",
            expires_in_days=100,
        ),
        http=HttpSummary(
            final_url="https://example.com/",
            status_code=200,
            checks=(HttpCheck("CSP", True, "ok"),),
        ),
        technologies=(TechnologyEvidence("nginx", "header"),),
        ports=(PortResult(443, "HTTPS", fingerprint="https · nginx"),),
        findings=(
            ReconFinding(
                "id",
                FindingSeverity.INFO,
                "DNS",
                "Info",
                "desc",
                "evidence",
            ),
        ),
    )


def test_tool_builds_all_recon_tabs_and_safe_defaults(tool):
    assert tool.tabs.count() == 10
    assert tool.external_check.isChecked() is False
    assert tool.active_check.isChecked() is False
    assert tool.nerva_check.isEnabled() is False
    tool.active_check.setChecked(True)
    assert tool.nerva_check.isEnabled() is True


def test_start_recon_validates_target(tool, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "show_warning", lambda *args: messages.append(args))
    tool.target_input.setText("")
    tool.start_recon()
    assert messages


def test_start_and_stop_recon_manage_worker(tool, monkeypatch):
    started = []
    monkeypatch.setattr(
        tool,
        "start_managed_worker",
        lambda worker, cancel=None: started.append(worker),
    )
    tool.target_input.setText("example.com")
    tool.active_check.setChecked(True)
    tool.start_recon()
    assert tool.worker is started[0]
    assert tool.run_button.isEnabled() is False
    cancelled = []
    tool.worker = SimpleNamespace(
        isRunning=lambda: True,
        cancel=lambda: cancelled.append(True),
    )
    tool.stop_recon()
    assert cancelled == [True]
    tool._cancelled()
    assert "cancelled" in tool.status_label.text().lower()
    tool._worker_finished()
    assert tool.worker is None


def test_finished_renders_report(tool):
    report = sample_report()
    tool._finished(report)
    assert "example.com" in tool.overview.toPlainText()
    assert tool.dns_table.rowCount() == 1
    assert tool.whois_table.item(0, 1).text() == "Registrar"
    assert tool.tls_table.item(0, 1).text() == "TLSv1.3"
    assert tool.http_table.item(0, 1).text() == "PASS"
    assert tool.tech_table.item(0, 0).text() == "nginx"
    assert tool.ports_table.item(0, 2).text().startswith("https")
    assert tool.findings_table.item(0, 0).text() == "INFO"


def test_failure_is_presented(tool, monkeypatch):
    messages = []
    monkeypatch.setattr(window, "show_error", lambda *args: messages.append(args))
    tool._failed(RuntimeError("boom"))
    assert messages
    assert "boom" in tool.status_label.text()

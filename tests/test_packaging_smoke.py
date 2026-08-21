import main


def test_discover_tool_classes_loads_all_plugins():
    normal_tools, config_tool, load_errors = main.discover_tool_classes()

    assert load_errors == []
    assert config_tool is not None
    names = {tool.name for tool in normal_tools}
    assert "Gestor de Procesos" in names
    assert "Informe Técnico del Equipo" in names
    assert "Visor de eventos de Windows" in names
    assert "PDF Toolkit" in names


def test_packaging_smoke_requires_declared_assets(monkeypatch, tmp_path):
    fake_config = object()
    monkeypatch.setattr(
        main,
        "discover_tool_classes",
        lambda: ([object()], fake_config, []),
    )
    monkeypatch.setattr(main, "ASSETS_DIR", tmp_path)

    assert main.run_packaging_smoke_test() == 1

    (tmp_path / "spinner.gif").write_bytes(b"GIF89a")
    assert main.run_packaging_smoke_test() == 0


def test_packaging_smoke_fails_on_plugin_import_errors(monkeypatch, tmp_path):
    (tmp_path / "spinner.gif").write_bytes(b"GIF89a")
    monkeypatch.setattr(main, "ASSETS_DIR", tmp_path)
    monkeypatch.setattr(
        main,
        "discover_tool_classes",
        lambda: ([object()], object(), ["tools.broken_tool: missing module"]),
    )

    assert main.run_packaging_smoke_test() == 1

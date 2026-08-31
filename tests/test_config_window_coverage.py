from pythonkni.config import window as config_window


def test_load_config_applies_saved_values(qtbot, monkeypatch):
    applied = []
    monkeypatch.setattr(
        config_window,
        "load_config",
        lambda _path: {"theme": "Oscuro", "language": "Inglés"},
    )
    monkeypatch.setattr(
        config_window,
        "apply_runtime_config",
        lambda config: applied.append(dict(config)),
    )
    monkeypatch.setattr(
        config_window.LanguageManager,
        "translate",
        lambda text: text,
    )

    tool = config_window.Tool()
    qtbot.addWidget(tool)

    assert applied == [{"theme": "Oscuro", "language": "Inglés"}]
    assert tool.theme_combobox.currentText() == "Oscuro"
    assert tool.language_combobox.currentText() == "Inglés"
    assert tool.theme_label.text() == "Seleccionar Tema:"
    assert tool.language_label.text() == "Seleccionar Idioma:"
    assert tool.save_button.text() == "Guardar cambios"
    assert tool.close_button.text() == "Cerrar"


def test_invalid_config_falls_back_to_runtime_managers(qtbot, monkeypatch):
    error = ValueError("broken config")
    monkeypatch.setattr(
        config_window,
        "load_config",
        lambda _path: (_ for _ in ()).throw(error),
    )
    monkeypatch.setattr(config_window.ThemeManager, "get_theme", lambda: "Claro")
    monkeypatch.setattr(config_window.LanguageManager, "get_language", lambda: "Español")
    monkeypatch.setattr(config_window.LanguageManager, "translate", lambda text: text)
    warnings = []
    monkeypatch.setattr(
        config_window.QMessageBox,
        "warning",
        lambda *args: warnings.append(args),
    )
    applied = []
    monkeypatch.setattr(
        config_window,
        "apply_runtime_config",
        lambda config: applied.append(dict(config)),
    )

    tool = config_window.Tool()
    qtbot.addWidget(tool)

    assert warnings[-1][1] == "Configuracion"
    assert applied == [{"theme": "Claro", "language": "Español"}]
    assert tool.theme_combobox.currentText() == "Claro"
    assert tool.language_combobox.currentText() == "Español"


def test_save_changes_applies_normalized_config_and_refreshes_ui(qtbot, monkeypatch):
    monkeypatch.setattr(
        config_window,
        "load_config",
        lambda _path: {"theme": "Claro", "language": "Español"},
    )
    monkeypatch.setattr(config_window, "apply_runtime_config", lambda _config: None)
    monkeypatch.setattr(config_window.LanguageManager, "translate", lambda text: f"T:{text}")
    tool = config_window.Tool()
    qtbot.addWidget(tool)
    tool.theme_combobox.setCurrentText("Oscuro")
    tool.language_combobox.setCurrentText("Inglés")

    saved = []
    monkeypatch.setattr(
        config_window,
        "save_runtime_config",
        lambda path, config: saved.append((path, dict(config)))
        or {"theme": "Claro", "language": "Español"},
    )
    themed = []
    monkeypatch.setattr(
        config_window.ThemeManager,
        "apply_theme",
        lambda target: themed.append(target),
    )
    info = []
    monkeypatch.setattr(
        config_window.QMessageBox,
        "information",
        lambda *args: info.append(args),
    )

    tool.save_changes()

    assert saved[0][1] == {"theme": "Oscuro", "language": "Inglés"}
    assert tool.theme_combobox.currentText() == "Claro"
    assert tool.language_combobox.currentText() == "Español"
    assert themed
    assert tool.theme_label.text() == "T:Seleccionar Tema:"
    assert tool.language_label.text() == "T:Seleccionar Idioma:"
    assert tool.save_button.text() == "T:Guardar cambios"
    assert tool.close_button.text() == "T:Cerrar"
    assert info[-1][1] == "Exito"
    assert info[-1][2] == "T:Cambios guardados"

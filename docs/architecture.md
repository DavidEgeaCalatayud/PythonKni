# Architecture

PythonKni is currently organized as a PyQt5 desktop application with a dynamic tool loader.

## Current Layout

- `main.py`: application entry point and tool menu.
- `tools/*_tool.py`: individual tools with their PyQt windows.
- `tools/app_paths.py`: user-specific paths for configuration, data and logs.
- `tools/logging_config.py`: application logging setup.
- `assets/`: static UI assets.

## Direction

The next structural improvement is moving source code under `src/pythonkni/` and splitting each tool into:

- `*_service.py`: business logic that can be tested without a UI.
- `*_window.py`: PyQt widgets and user interactions.
- `models.py`: simple data structures, when needed.

This keeps the UI thin and makes tests easier to write.

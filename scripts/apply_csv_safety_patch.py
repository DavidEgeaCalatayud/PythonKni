from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    file_path = Path(path)
    text = file_path.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected block not found in {path}")
    file_path.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "tools/disk_analyzer_tool.py",
    "from tools.base_tool import BaseTool\n",
    "from tools.base_tool import BaseTool\nfrom tools.csv_utils import safe_csv_row\n",
)
replace_once(
    "tools/disk_analyzer_tool.py",
    '''                writer.writerow(\n                    [item.name, item.item_type, format_bytes(item.size), item.size, item.path]\n                )''',
    '''                writer.writerow(\n                    safe_csv_row(\n                        [item.name, item.item_type, format_bytes(item.size), item.size, item.path]\n                    )\n                )''',
)

replace_once(
    "tools/network_tool.py",
    "from tools.base_tool import BaseTool\n",
    "from tools.base_tool import BaseTool\nfrom tools.csv_utils import safe_csv_cell\n",
)
replace_once(
    "tools/network_tool.py",
    "                    writer.writerow([line])",
    "                    writer.writerow([safe_csv_cell(line)])",
)

replace_once(
    "pythonkni/startup/window.py",
    "from tools.base_tool import BaseTool\n",
    "from tools.base_tool import BaseTool\nfrom tools.csv_utils import safe_csv_row\n",
)
replace_once(
    "pythonkni/startup/window.py",
    '''                writer.writerow(\n                    [\n                        "Sí" if item.active else "No",\n                        item.name,\n                        item.source,\n                        item.command,\n                        item.item_type,\n                        item.exists,\n                        item.risk,\n                    ]\n                )''',
    '''                writer.writerow(\n                    safe_csv_row(\n                        [\n                            "Sí" if item.active else "No",\n                            item.name,\n                            item.source,\n                            item.command,\n                            item.item_type,\n                            item.exists,\n                            item.risk,\n                        ]\n                    )\n                )''',
)

replace_once(
    "pythonkni/event_viewer/window.py",
    "from tools.base_tool import BaseTool\n",
    "from tools.base_tool import BaseTool\nfrom tools.csv_utils import safe_csv_row\n",
)
replace_once(
    "pythonkni/event_viewer/window.py",
    '''                writer.writerow(\n                    [\n                        item.date,\n                        item.level,\n                        item.provider,\n                        item.event_id,\n                        item.log_name,\n                        item.category,\n                        item.message,\n                        item.risk,\n                        item.interpretation,\n                        item.computer,\n                        item.record_id,\n                    ]\n                )''',
    '''                writer.writerow(\n                    safe_csv_row(\n                        [\n                            item.date,\n                            item.level,\n                            item.provider,\n                            item.event_id,\n                            item.log_name,\n                            item.category,\n                            item.message,\n                            item.risk,\n                            item.interpretation,\n                            item.computer,\n                            item.record_id,\n                        ]\n                    )\n                )''',
)

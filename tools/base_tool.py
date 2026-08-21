from PyQt5.QtWidgets import QMainWindow


class BaseTool(QMainWindow):
    """Common lifecycle and metadata contract for every PythonKni GUI tool."""

    name: str = ""
    description: str = ""
    category: str = "General"

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.setup_ui()

    def setup_ui(self) -> None:
        """Build the tool user interface. Subclasses must override this method."""
        raise NotImplementedError

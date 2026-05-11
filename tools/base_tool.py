from abc import ABC, abstractmethod

from PyQt5.QtWidgets import QMainWindow


class BaseTool(QMainWindow, ABC):
    name: str = ""
    description: str = ""
    category: str = "General"

    @abstractmethod
    def setup_ui(self) -> None:
        """Build the tool user interface."""
        raise NotImplementedError

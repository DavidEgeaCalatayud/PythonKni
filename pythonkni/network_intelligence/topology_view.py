from __future__ import annotations

from PyQt5.QtCore import Qt, pyqtSignal
from PyQt5.QtWidgets import (
    QGraphicsItem,
    QGraphicsLineItem,
    QGraphicsRectItem,
    QGraphicsScene,
    QGraphicsSimpleTextItem,
    QGraphicsView,
)

from .models import AssetRecord
from .topology import NetworkTopology, TopologyNode, build_logical_topology

_NODE_WIDTH = 190.0
_NODE_HEIGHT = 86.0
_HORIZONTAL_GAP = 36.0
_VERTICAL_GAP = 90.0
_MAX_COLUMNS = 5
_ASSET_DATA_ROLE = 0


class NetworkTopologyView(QGraphicsView):
    asset_selected = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.graph: NetworkTopology | None = None
        self.setRenderHints(self.renderHints())
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setAlignment(Qt.AlignCenter)

    def set_assets(self, assets: list[AssetRecord]) -> None:
        self.graph = build_logical_topology(assets)
        scene = QGraphicsScene(self)
        scene.selectionChanged.connect(self._selection_changed)
        self.setScene(scene)
        self._render_graph(scene, self.graph)

    def _render_graph(self, scene: QGraphicsScene, graph: NetworkTopology) -> None:
        positions = self._layout_positions(graph)
        items: dict[str, QGraphicsRectItem] = {}

        for node in graph.nodes:
            x, y = positions[node.node_id]
            item = self._create_node_item(node, x, y)
            items[node.node_id] = item
            scene.addItem(item)

        for edge in graph.edges:
            source = items.get(edge.source_id)
            target = items.get(edge.target_id)
            if source is None or target is None:
                continue
            source_rect = source.sceneBoundingRect()
            target_rect = target.sceneBoundingRect()
            line = QGraphicsLineItem(
                source_rect.center().x(),
                source_rect.bottom(),
                target_rect.center().x(),
                target_rect.top(),
            )
            line.setZValue(-1)
            line.setToolTip(edge.relationship)
            scene.addItem(line)

        bounds = scene.itemsBoundingRect()
        scene.setSceneRect(bounds.adjusted(-40, -40, 40, 40))

    def _layout_positions(self, graph: NetworkTopology) -> dict[str, tuple[float, float]]:
        positions: dict[str, tuple[float, float]] = {}
        internet = next(node for node in graph.nodes if node.node_id == "synthetic:internet")
        gateway = next(node for node in graph.nodes if node.node_id == graph.gateway_node_id)
        children = [
            node
            for node in graph.nodes
            if node.node_id not in {internet.node_id, gateway.node_id}
        ]

        columns = min(_MAX_COLUMNS, max(1, len(children)))
        total_width = columns * _NODE_WIDTH + max(0, columns - 1) * _HORIZONTAL_GAP
        root_x = (total_width - _NODE_WIDTH) / 2
        positions[internet.node_id] = (root_x, 0.0)
        positions[gateway.node_id] = (root_x, _NODE_HEIGHT + _VERTICAL_GAP)

        start_y = (_NODE_HEIGHT + _VERTICAL_GAP) * 2
        for index, node in enumerate(children):
            row, column = divmod(index, _MAX_COLUMNS)
            row_count = min(_MAX_COLUMNS, len(children) - row * _MAX_COLUMNS)
            row_width = row_count * _NODE_WIDTH + max(0, row_count - 1) * _HORIZONTAL_GAP
            row_start_x = (total_width - row_width) / 2
            x = row_start_x + column * (_NODE_WIDTH + _HORIZONTAL_GAP)
            y = start_y + row * (_NODE_HEIGHT + _VERTICAL_GAP)
            positions[node.node_id] = (x, y)
        return positions

    def _create_node_item(self, node: TopologyNode, x: float, y: float) -> QGraphicsRectItem:
        item = QGraphicsRectItem(0, 0, _NODE_WIDTH, _NODE_HEIGHT)
        item.setPos(x, y)
        item.setToolTip(self._node_tooltip(node))
        if node.asset_id is not None:
            item.setFlag(QGraphicsItem.ItemIsSelectable, True)
            item.setData(_ASSET_DATA_ROLE, node.asset_id)

        text = QGraphicsSimpleTextItem(self._node_text(node), item)
        text.setPos(10, 8)
        return item

    @staticmethod
    def _node_text(node: TopologyNode) -> str:
        if node.synthetic:
            return f"{node.label}\n{node.ip}"
        status = "ONLINE" if node.is_online else "OFFLINE"
        risk = node.risk.value if node.risk is not None else "N/A"
        return f"{node.label}\n{node.kind} · {node.ip}\n{status} · {risk}"

    @staticmethod
    def _node_tooltip(node: TopologyNode) -> str:
        if node.synthetic:
            return node.label
        status = "Online" if node.is_online else "Offline"
        risk = node.risk.value if node.risk is not None else "N/A"
        return f"{node.kind}\n{node.ip}\n{status}\nRisk: {risk}"

    def _selection_changed(self) -> None:
        scene = self.scene()
        if scene is None:
            return
        selected = scene.selectedItems()
        if not selected:
            return
        asset_id = selected[0].data(_ASSET_DATA_ROLE)
        if asset_id:
            self.asset_selected.emit(str(asset_id))

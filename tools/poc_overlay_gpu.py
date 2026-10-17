"""Fase 0 - Overlay con GPU: la misma prueba que poc_overlay.py pero dibujada
con Qt Quick (Direct3D 11 por defecto), sincronizada con el refresco del
monitor (vsync). Sirve para decidir si la autopista final se pinta con GPU.

Uso:
    uv run --project app python tools/poc_overlay_gpu.py
    uv run --project app python tools/poc_overlay_gpu.py --api opengl --fullscreen

Atajos: los mismos que poc_overlay.py (Ctrl+Alt+H mostrar/ocultar, Ctrl+Alt+Q salir).

Qué comprobar, además de lo de poc_overlay.py: que el fondo es transparente
(no negro) con cada --api, y el uso de CPU comparado con la versión QPainter.
"""

import argparse
import signal
import sys
import tempfile
import time
from pathlib import Path

from PySide6.QtCore import QTimer, QUrl, Qt
from PySide6.QtGui import QColor, QGuiApplication, QSurfaceFormat
from PySide6.QtQuick import QQuickView, QQuickWindow, QSGRendererInterface

sys.path.insert(0, str(Path(__file__).parent))
from poc_overlay import (  # noqa: E402
    GWL_EXSTYLE, HOTKEY_QUIT, HOTKEY_TOGGLE, WS_EX_LAYERED, WS_EX_NOACTIVATE,
    WS_EX_TOOLWINDOW, WS_EX_TRANSPARENT, HotkeyThread, bring_to_top, parse_hotkey, user32,
)

QML = b"""
import QtQuick

Item {
    id: root
    property real t: 0
    property real fps: 0
    property real worstMs: 0
    property real windowStart: 0
    readonly property var colors: ["#2ecc40", "#ff4136", "#ffdc00", "#0074d9", "#ff851b"]
    readonly property real travel: 1.6
    readonly property real spacing: 0.5
    readonly property real hw: Math.min(width, 520)
    readonly property real laneW: hw / 5
    readonly property real strikeY: height - 120

    FrameAnimation {
        running: true
        onTriggered: {
            root.t += frameTime
            root.fps = smoothFrameTime > 0 ? 1 / smoothFrameTime : 0
            // Peor frame de los ultimos 2 s
            if (root.t - root.windowStart > 2) { root.windowStart = root.t; root.worstMs = 0 }
            root.worstMs = Math.max(root.worstMs, frameTime * 1000)
        }
    }

    Rectangle {
        id: highway
        x: (root.width - root.hw) / 2; width: root.hw; height: root.height
        color: Qt.rgba(10/255, 10/255, 20/255, 150/255)

        Repeater {
            model: 4
            Rectangle { x: (index + 1) * root.laneW - 1; width: 2; height: parent.height; color: "#3cffffff" }
        }

        Repeater {
            model: 5
            Rectangle {
                x: index * root.laneW + root.laneW * 0.15; width: root.laneW * 0.7; height: width
                y: root.strikeY - height / 2; radius: width / 2
                color: "transparent"; border.color: root.colors[index]; border.width: 4
            }
        }

        // Notas: posicion calculada desde el reloj, igual que en la version QPainter.
        Repeater {
            model: 5 * 6
            Rectangle {
                readonly property int lane: index % 5
                readonly property int k: Math.floor(index / 5)
                readonly property real phase: (root.t + lane * 0.13) % root.spacing
                readonly property real timeToHit: k * root.spacing - phase
                x: lane * root.laneW + root.laneW * 0.15; width: root.laneW * 0.7; height: 24; radius: 8
                y: root.strikeY - timeToHit / root.travel * root.strikeY - 12
                color: root.colors[lane]
            }
        }

        Text {
            x: 12; y: 8; color: "white"; font.family: "Consolas"; font.pixelSize: 18; font.bold: true
            text: root.fps.toFixed(1) + " fps  (peor frame " + root.worstMs.toFixed(1) + " ms)"
        }
    }
}
"""

APIS = {
    "d3d11": QSGRendererInterface.GraphicsApi.Direct3D11,
    "d3d12": QSGRendererInterface.GraphicsApi.Direct3D12,
    "opengl": QSGRendererInterface.GraphicsApi.OpenGL,
    "vulkan": QSGRendererInterface.GraphicsApi.Vulkan,
}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--hotkey", default="ctrl+alt+h")
    parser.add_argument("--api", choices=APIS, default="d3d11", help="API gráfica de Qt Quick")
    parser.add_argument("--fullscreen", action="store_true")
    parser.add_argument("--screenshot", type=Path, help="guarda una captura de pantalla a los 3 s (para depurar)")
    args = parser.parse_args()
    sys.stdout.reconfigure(line_buffering=True)

    QQuickWindow.setGraphicsApi(APIS[args.api])
    fmt = QSurfaceFormat.defaultFormat()
    fmt.setAlphaBufferSize(8)
    QSurfaceFormat.setDefaultFormat(fmt)

    app = QGuiApplication(sys.argv)
    view = QQuickView()
    view.setFlags(
        Qt.WindowType.FramelessWindowHint
        | Qt.WindowType.WindowStaysOnTopHint
        | Qt.WindowType.Tool
        | Qt.WindowType.WindowTransparentForInput
        | Qt.WindowType.WindowDoesNotAcceptFocus
    )
    view.setColor(QColor(0, 0, 0, 0))
    view.setResizeMode(QQuickView.ResizeMode.SizeRootObjectToView)
    view.setProperty("_q_showWithoutActivating", True)

    geo = app.primaryScreen().availableGeometry()
    if args.fullscreen:
        view.setGeometry(geo)
    else:
        w = min(560, geo.width())
        view.setGeometry(geo.x() + (geo.width() - w) // 2, geo.y(), w, geo.height())

    # QQuickView solo carga QML desde una URL; lo escribimos a un temporal.
    qml_file = Path(tempfile.gettempdir()) / "music_hero_poc_overlay.qml"
    qml_file.write_bytes(QML)
    view.setSource(QUrl.fromLocalFile(str(qml_file)))
    for err in view.errors():
        print("QML:", err.toString())

    def force_click_through() -> None:
        hwnd = int(view.winId())
        wanted = WS_EX_LAYERED | WS_EX_TRANSPARENT | WS_EX_TOOLWINDOW | WS_EX_NOACTIVATE
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        if style & wanted != wanted:
            user32.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style | wanted)
        style = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
        ok = style & wanted == wanted
        print(f"estilos extendidos: 0x{style:08x} -> click-through {'OK' if ok else 'FALLA'}")

    def on_hotkey(hk_id: int) -> None:
        if hk_id == HOTKEY_TOGGLE:
            view.setVisible(not view.isVisible())
            if view.isVisible():
                force_click_through()
            print("overlay", "visible" if view.isVisible() else "oculto")
        elif hk_id == HOTKEY_QUIT:
            app.quit()

    hotkeys = HotkeyThread({HOTKEY_TOGGLE: parse_hotkey(args.hotkey), HOTKEY_QUIT: parse_hotkey("ctrl+alt+q")})
    hotkeys.pressed.connect(on_hotkey, Qt.ConnectionType.QueuedConnection)
    hotkeys.start()
    for err in hotkeys.errors:
        print("AVISO:", err)

    signal.signal(signal.SIGINT, lambda *_: app.quit())
    tick = QTimer()
    tick.start(200)
    tick.timeout.connect(lambda: None)

    def report() -> None:
        root = view.rootObject()
        if root is not None and view.isVisible():
            cpu = time.process_time()
            wall = time.perf_counter()
            if report.last:
                pct = 100 * (cpu - report.last[0]) / (wall - report.last[1])
                print(f"{root.property('fps'):5.1f} fps  peor frame {root.property('worstMs'):5.1f} ms  CPU {pct:4.1f}%")
            report.last = (cpu, wall)

    topmost = QTimer()
    topmost.timeout.connect(lambda: view.isVisible() and bring_to_top(int(view.winId())))
    topmost.start(500)

    report.last = None
    timer = QTimer()
    timer.timeout.connect(report)
    timer.start(5000)

    if args.screenshot:
        def grab() -> None:
            app.primaryScreen().grabWindow(0).save(str(args.screenshot))
            print("captura guardada en", args.screenshot)

        QTimer.singleShot(3000, grab)

    view.show()
    force_click_through()
    print(f"Overlay GPU ({view.rendererInterface().graphicsApi().name}) en marcha. "
          f"{args.hotkey} muestra/oculta, ctrl+alt+q sale.")
    code = app.exec()
    hotkeys.stop()
    return code


if __name__ == "__main__":
    sys.exit(main())

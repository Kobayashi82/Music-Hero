// Autopista en perspectiva. Python (overlay.Bridge.tick) da en cada fotograma un mapa `f` con:
//   notes: [carril, u, uFin, estado, hopo, sosteniendo] x N  (u: 0 = línea de golpeo, 1 = horizonte;
//          estado 0 pendiente, 1 acertada, 2 fallada)
//   beats: [u, inicioDeCompás] x N, held: 5 bool, flash: 5 (0..1), y el marcador.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property var f: ({ notes: [], beats: [], held: [false, false, false, false, false], flash: [0, 0, 0, 0, 0],
                       score: 0, streak: 0, mult: 1, accuracy: 1, title: "", status: "", message: "",
                       progress: 0, countdown: 0, results: "", opacity: 0.85, missFlash: 0 })
    readonly property var colors: ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
    readonly property real farScale: 0.3
    readonly property real k: 1 / farScale - 1
    property real hwNear: Math.min(width * 0.92, bridge.highwayWidth)
    readonly property real laneW: hwNear / 5
    readonly property real strikeY: height - Math.max(110, height * 0.1)
    readonly property real horizonY: height * 0.08
    readonly property int notePool: 200
    readonly property int beatPool: 32

    function s(u) { return 1 / (1 + k * Math.max(u, -0.3)) }
    function yAt(u) { return strikeY - (strikeY - horizonY) * (1 - s(u)) / (1 - farScale) }
    function xAt(lane, u) { return width / 2 + (lane - 2) * laneW * s(u) }

    FrameAnimation {
        running: true
        onTriggered: root.f = bridge.tick()
    }

    // ---------- autopista ----------
    Shape {
        anchors.fill: parent
        ShapePath {
            strokeWidth: 0; strokeColor: "transparent"
            fillGradient: LinearGradient {
                y1: root.horizonY; y2: root.height
                GradientStop { position: 0; color: Qt.rgba(0.04, 0.04, 0.10, 0) }
                GradientStop { position: 0.25; color: Qt.rgba(0.04, 0.04, 0.10, root.f.opacity * 0.8) }
                GradientStop { position: 1; color: Qt.rgba(0.04, 0.04, 0.10, root.f.opacity) }
            }
            startX: root.xAt(-0.5, 1); startY: root.horizonY
            PathLine { x: root.xAt(4.5, 1); y: root.horizonY }
            PathLine { x: root.xAt(4.5, -0.25); y: root.yAt(-0.25) }
            PathLine { x: root.xAt(-0.5, -0.25); y: root.yAt(-0.25) }
            PathLine { x: root.xAt(-0.5, 1); y: root.horizonY }
        }
    }
    Repeater {  // separaciones entre carriles y bordes
        model: 6
        Shape {
            anchors.fill: parent
            ShapePath {
                strokeWidth: index === 0 || index === 5 ? 3 : 1.5
                strokeColor: index === 0 || index === 5 ? "#88ffffff" : "#33ffffff"
                fillColor: "transparent"
                startX: root.xAt(index - 0.5, 1); startY: root.horizonY
                PathLine { x: root.xAt(index - 0.5, -0.25); y: root.yAt(-0.25) }
            }
        }
    }
    Repeater {  // pulsos y compases
        model: root.beatPool
        Rectangle {
            readonly property int n: root.f.beats.length / 2
            readonly property real u: index < n ? root.f.beats[2 * index] : 2
            readonly property bool bar: index < n && root.f.beats[2 * index + 1] > 0
            visible: index < n
            x: root.xAt(-0.5, u); width: root.xAt(4.5, u) - x
            height: Math.max(1, (bar ? 4 : 2) * root.s(u)); y: root.yAt(u) - height / 2
            color: bar ? "#55ffffff" : "#22ffffff"
        }
    }

    // ---------- línea de golpeo ----------
    Repeater {
        model: 5
        Item {
            readonly property real w: root.laneW * 0.78
            x: root.xAt(index, 0) - w / 2; y: root.strikeY - w * 0.32; width: w; height: w * 0.64
            Rectangle {  // destello al acertar
                anchors.centerIn: parent; width: parent.width * 1.5; height: parent.height * 1.8; radius: height / 2
                color: root.colors[index]; opacity: root.f.flash[index] * 0.55
            }
            Rectangle {
                anchors.fill: parent; radius: height / 2
                color: root.f.held[index] ? root.colors[index] : Qt.rgba(0, 0, 0, 0.5)
                border.color: root.colors[index]; border.width: 4
            }
            Rectangle {
                anchors.centerIn: parent; width: parent.width * 0.45; height: parent.height * 0.45; radius: height / 2
                color: root.f.held[index] ? "white" : "#44ffffff"
            }
        }
    }

    // ---------- notas ----------
    Repeater {
        model: root.notePool
        Item {
            id: gem
            anchors.fill: parent
            readonly property int n: root.f.notes.length / 6
            readonly property bool used: index < n
            readonly property int lane: used ? root.f.notes[6 * index] : 0
            readonly property real u: used ? root.f.notes[6 * index + 1] : 2
            readonly property real uEnd: used ? root.f.notes[6 * index + 2] : 2
            readonly property int state: used ? root.f.notes[6 * index + 3] : 0
            readonly property bool hopo: used && root.f.notes[6 * index + 4] > 0
            readonly property bool sustaining: used && root.f.notes[6 * index + 5] > 0
            readonly property color col: state === 2 ? "#777777" : root.colors[lane]
            visible: used

            Shape {  // cola del sustain
                id: tail
                anchors.fill: parent
                visible: gem.uEnd > gem.u + 0.001
                readonly property real u0: gem.sustaining ? 0 : gem.u
                readonly property real w0: root.laneW * (gem.sustaining ? 0.26 : 0.18) * root.s(u0)
                readonly property real w1: root.laneW * (gem.sustaining ? 0.26 : 0.18) * root.s(gem.uEnd)
                ShapePath {
                    strokeWidth: 0; strokeColor: "transparent"
                    fillColor: Qt.rgba(gem.col.r, gem.col.g, gem.col.b, gem.sustaining ? 0.95 : 0.6)
                    startX: root.xAt(gem.lane, tail.u0) - tail.w0 / 2; startY: root.yAt(tail.u0)
                    PathLine { x: root.xAt(gem.lane, tail.u0) + tail.w0 / 2; y: root.yAt(tail.u0) }
                    PathLine { x: root.xAt(gem.lane, gem.uEnd) + tail.w1 / 2; y: root.yAt(gem.uEnd) }
                    PathLine { x: root.xAt(gem.lane, gem.uEnd) - tail.w1 / 2; y: root.yAt(gem.uEnd) }
                }
            }
            Item {  // la nota
                visible: gem.state !== 1
                readonly property real w: root.laneW * (gem.hopo ? 0.6 : 0.72) * root.s(gem.u)
                x: root.xAt(gem.lane, gem.u) - w / 2; y: root.yAt(gem.u) - w * 0.3
                width: w; height: w * 0.6
                Rectangle {
                    anchors.fill: parent; radius: height / 2
                    color: gem.col; border.color: gem.hopo ? "white" : Qt.darker(gem.col, 1.6)
                    border.width: Math.max(1, (gem.hopo ? 4 : 2) * root.s(gem.u))
                }
                Rectangle {
                    anchors.centerIn: parent; width: parent.width * 0.4; height: parent.height * 0.4; radius: height / 2
                    color: gem.hopo ? "white" : "#ccffffff"
                }
            }
        }
    }

    // ---------- marcador ----------
    Rectangle {  // borde rojo al fallar
        anchors.fill: parent; color: "transparent"
        border.color: "#ff3030"; border.width: 6; opacity: root.f.missFlash * 0.6
    }
    Column {
        x: root.xAt(4.5, 0) + 16; y: root.strikeY - 120; spacing: 2
        Text { text: Math.round(root.f.score).toLocaleString(Qt.locale("es_ES"), "f", 0); color: "white"
               font.pixelSize: 30; font.bold: true; style: Text.Outline; styleColor: "black" }
        Text { text: "x" + root.f.mult; color: ["white", "#ffdc00", "#2ecc40", "#c86cff"][root.f.mult - 1]
               font.pixelSize: 40; font.bold: true; style: Text.Outline; styleColor: "black" }
        Text { text: root.f.streak > 0 ? root.f.streak + " seguidas" : ""; color: "white"
               font.pixelSize: 18; style: Text.Outline; styleColor: "black" }
        Text { text: Math.round(root.f.accuracy * 100) + " %"; color: "#ccffffff"
               font.pixelSize: 18; style: Text.Outline; styleColor: "black" }
    }
    Column {
        anchors.horizontalCenter: parent.horizontalCenter; y: 8; spacing: 4
        Text { anchors.horizontalCenter: parent.horizontalCenter; text: root.f.title; color: "white"
               font.pixelSize: 18; font.bold: true; style: Text.Outline; styleColor: "black" }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter; width: root.hwNear * 0.6; height: 4; radius: 2
            color: "#44ffffff"
            Rectangle { width: parent.width * root.f.progress; height: parent.height; radius: 2; color: "white" }
        }
    }
    Text {
        anchors.centerIn: parent; visible: root.f.countdown > 0
        text: Math.ceil(root.f.countdown); color: "white"; font.pixelSize: 96; font.bold: true
        style: Text.Outline; styleColor: "black"
    }
    Rectangle {
        anchors.centerIn: parent; visible: root.f.status !== "" || root.f.results !== ""
        width: Math.min(root.width - 40, 520); height: box.implicitHeight + 40; radius: 12
        color: "#dd101020"; border.color: "#66ffffff"
        Column {
            id: box
            anchors.centerIn: parent; width: parent.width - 40; spacing: 10
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.f.status; color: "white"
                   font.pixelSize: 30; font.bold: true; visible: text !== "" }
            Text { width: parent.width; horizontalAlignment: Text.AlignHCenter; text: root.f.results; color: "white"
                   font.pixelSize: 18; wrapMode: Text.WordWrap; visible: text !== ""; textFormat: Text.StyledText }
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
        text: root.f.message; color: "#ffdc00"; font.pixelSize: 14; style: Text.Outline; styleColor: "black"
    }
}

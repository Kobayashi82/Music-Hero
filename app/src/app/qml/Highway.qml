// Autopista en perspectiva. Python (play.Bridge.tick) da en cada fotograma un mapa `f` con:
//   notes: [carril, u, uFin, estado, hopo, sosteniendo, notasDelAcorde] x N  (u: 0 = línea de golpeo,
//          1 = horizonte; estado 0 pendiente, 1 acertada, 2 fallada)
//   beats: [u, inicioDeCompás] x N, held / burn (sustain sonando): 5 bool, flash / missLane: 5 (0..1),
//   time (s, para el parpadeo de las llamas), el marcador, menu (title, body, items, values, sel, editing;
//   vacío si no hay), calib, toast y message.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    property var f: ({ notes: [], beats: [], held: [false, false, false, false, false], flash: [0, 0, 0, 0, 0],
                       score: 0, streak: 0, mult: 1, accuracy: 1, title: "", difficulty: "", message: "",
                       progress: 0, countdown: 0, menu: ({}), menuHint: "", calib: ({}), toast: "",
                       opacity: 0.85, missFlash: 0, missLane: [0, 0, 0, 0, 0], burn: [false, false, false, false, false],
                       time: 0, autoplay: false, hwWidth: 560 })
    readonly property var colors: ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
    readonly property var multColors: ["white", "#ffdc00", "#2ecc40", "#c86cff"]
    readonly property real farScale: 0.38
    readonly property real k: 1 / farScale - 1
    property real hwNear: Math.min(width - 460, f.hwWidth)
    readonly property real laneW: hwNear / 5
    readonly property real strikeY: height - Math.max(110, height * 0.1)
    readonly property real horizonY: height * 0.06
    readonly property int notePool: 200
    readonly property int beatPool: 32
    readonly property int stride: 7
    readonly property real glowU: 0.15  // hasta dónde sube la luz del carril pulsado (un tercio de la autopista)
    readonly property bool menuOpen: f.menu !== undefined && f.menu.title !== undefined
    readonly property bool calibrating: f.calib !== undefined && f.calib.total !== undefined

    function s(u) { return 1 / (1 + k * Math.max(u, -0.3)) }
    function yAt(u) { return strikeY - (strikeY - horizonY) * (1 - s(u)) / (1 - farScale) }
    function xAt(lane, u) { return width / 2 + (lane - 2) * laneW * s(u) }
    function fmt(n) { return Math.round(n).toLocaleString(Qt.locale("es_ES"), "f", 0) }

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
                GradientStop { position: 0; color: Qt.rgba(0.03, 0.03, 0.09, 0) }
                GradientStop { position: 0.1; color: Qt.rgba(0.03, 0.03, 0.09, root.f.opacity) }
                GradientStop { position: 1; color: Qt.rgba(0.05, 0.05, 0.12, root.f.opacity) }
            }
            startX: root.xAt(-0.5, 1); startY: root.horizonY
            PathLine { x: root.xAt(4.5, 1); y: root.horizonY }
            PathLine { x: root.xAt(4.5, -0.25); y: root.yAt(-0.25) }
            PathLine { x: root.xAt(-0.5, -0.25); y: root.yAt(-0.25) }
            PathLine { x: root.xAt(-0.5, 1); y: root.horizonY }
        }
    }
    Repeater {  // carril iluminado mientras se pulsa su traste
        model: 5
        Shape {
            anchors.fill: parent
            opacity: root.f.held[index] ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 60 } }
            ShapePath {
                strokeWidth: 0; strokeColor: "transparent"
                fillGradient: LinearGradient {
                    y1: root.yAt(root.glowU); y2: root.strikeY
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 1; color: Qt.alpha(root.colors[index], 0.28) }
                }
                startX: root.xAt(index - 0.5, root.glowU); startY: root.yAt(root.glowU)
                PathLine { x: root.xAt(index + 0.5, root.glowU); y: root.yAt(root.glowU) }
                PathLine { x: root.xAt(index + 0.5, 0); y: root.strikeY }
                PathLine { x: root.xAt(index - 0.5, 0); y: root.strikeY }
            }
        }
    }
    Shape {  // al fallar: la parte de abajo de la autopista se enciende en rojo y se apaga
        anchors.fill: parent
        visible: root.f.missFlash > 0.01
        opacity: root.f.missFlash
        ShapePath {
            strokeWidth: 0; strokeColor: "transparent"
            fillGradient: LinearGradient {
                y1: root.yAt(0.18); y2: root.yAt(-0.25)
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 1; color: "#90ff1e1e" }
            }
            startX: root.xAt(-0.5, 0.18); startY: root.yAt(0.18)
            PathLine { x: root.xAt(4.5, 0.18); y: root.yAt(0.18) }
            PathLine { x: root.xAt(4.5, -0.25); y: root.yAt(-0.25) }
            PathLine { x: root.xAt(-0.5, -0.25); y: root.yAt(-0.25) }
        }
    }
    Repeater {  // separaciones entre carriles y bordes
        model: 6
        Shape {
            anchors.fill: parent
            readonly property bool edge: index === 0 || index === 5
            ShapePath {
                strokeWidth: parent.edge ? 4 : 1.5
                strokeColor: parent.edge ? "#aaffffff" : "#30ffffff"
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
            height: Math.max(1, (bar ? 5 : 2) * root.s(u)); y: root.yAt(u) - height / 2
            color: bar ? "#60ffffff" : "#20ffffff"
        }
    }

    // ---------- línea de golpeo ----------
    Rectangle {
        x: root.xAt(-0.5, 0); width: root.xAt(4.5, 0) - x; y: root.strikeY - 2; height: 4
        color: Qt.tint("#bbffffff", Qt.rgba(1, 0.12, 0.12, root.f.missFlash * 0.85))
    }
    Repeater {
        model: 5
        Item {
            id: strikeBtn
            readonly property real w: root.laneW * 0.84
            readonly property color col: root.colors[index]
            readonly property bool down: root.f.held[index]
            readonly property real miss: root.f.missLane[index]
            x: root.xAt(index, 0) - w / 2 + Math.sin(root.f.time * 70) * miss * root.laneW * 0.05
            y: root.strikeY - w * 0.3; width: w; height: w * 0.6
            Rectangle {  // destello al acertar
                anchors.centerIn: parent; width: parent.width * 1.7; height: parent.height * 2.2; radius: height / 2
                color: parent.col; opacity: root.f.flash[index] * 0.6
                scale: 1 + (1 - root.f.flash[index]) * 0.4
            }
            Rectangle {
                anchors.fill: parent; radius: height / 2
                color: parent.down ? parent.col : Qt.rgba(0, 0, 0, 0.55)
                border.color: parent.down ? "white" : parent.col; border.width: 4
            }
            Rectangle {
                anchors.centerIn: parent; width: parent.width * 0.5; height: parent.height * 0.5; radius: height / 2
                color: parent.down ? "white" : Qt.alpha(parent.col, 0.35)
            }
            Rectangle {  // fallo
                anchors.fill: parent; radius: height / 2; visible: parent.miss > 0.01
                color: Qt.rgba(0.9, 0.05, 0.05, parent.miss * 0.55); border.color: Qt.rgba(1, 0.3, 0.3, parent.miss)
                border.width: 4
            }
        }
    }

    // ---------- notas ----------
    Repeater {
        model: root.notePool
        Item {
            id: gem
            anchors.fill: parent
            readonly property int n: root.f.notes.length / root.stride
            readonly property bool used: index < n
            readonly property int o: root.stride * index
            readonly property int lane: used ? root.f.notes[o] : 0
            readonly property real u: used ? root.f.notes[o + 1] : 2
            readonly property real uEnd: used ? root.f.notes[o + 2] : 2
            readonly property int state: used ? root.f.notes[o + 3] : 0
            readonly property bool hopo: used && root.f.notes[o + 4] > 0
            readonly property bool sustaining: used && root.f.notes[o + 5] > 0
            readonly property color col: state === 2 ? "#6a6a6a" : root.colors[lane]
            visible: used

            Shape {  // cola del sustain
                id: tail
                anchors.fill: parent
                visible: gem.uEnd > gem.u + 0.001
                readonly property real u0: gem.sustaining ? 0 : gem.u
                readonly property real wk: gem.sustaining ? 0.34 : 0.26
                readonly property real w0: root.laneW * wk * root.s(u0)
                readonly property real w1: root.laneW * wk * root.s(gem.uEnd)
                ShapePath {
                    strokeWidth: 0; strokeColor: "transparent"
                    fillColor: Qt.rgba(gem.col.r, gem.col.g, gem.col.b, gem.sustaining ? 1 : 0.7)
                    startX: root.xAt(gem.lane, tail.u0) - tail.w0 / 2; startY: root.yAt(tail.u0)
                    PathLine { x: root.xAt(gem.lane, tail.u0) + tail.w0 / 2; y: root.yAt(tail.u0) }
                    PathLine { x: root.xAt(gem.lane, gem.uEnd) + tail.w1 / 2; y: root.yAt(gem.uEnd) }
                    PathLine { x: root.xAt(gem.lane, gem.uEnd) - tail.w1 / 2; y: root.yAt(gem.uEnd) }
                }
                ShapePath {  // brillo central mientras se mantiene
                    strokeWidth: 0; strokeColor: "transparent"
                    fillColor: gem.sustaining ? "#ccffffff" : "transparent"
                    startX: root.xAt(gem.lane, tail.u0) - tail.w0 / 6; startY: root.yAt(tail.u0)
                    PathLine { x: root.xAt(gem.lane, tail.u0) + tail.w0 / 6; y: root.yAt(tail.u0) }
                    PathLine { x: root.xAt(gem.lane, gem.uEnd) + tail.w1 / 6; y: root.yAt(gem.uEnd) }
                    PathLine { x: root.xAt(gem.lane, gem.uEnd) - tail.w1 / 6; y: root.yAt(gem.uEnd) }
                }
            }
            Item {  // la nota: base oscura (canto) + cara de color + brillo; los HOPO, más planos y con aro blanco
                visible: gem.state !== 1
                readonly property real sc: root.s(gem.u)
                readonly property real w: root.laneW * (gem.hopo ? 0.7 : 0.84) * sc
                x: root.xAt(gem.lane, gem.u) - w / 2; y: root.yAt(gem.u) - w * 0.32
                width: w; height: w * (gem.hopo ? 0.5 : 0.58)
                readonly property bool tap: gem.hopo && gem.state !== 2
                Rectangle {  // halo de los HOPO: se tocan sin strum
                    visible: parent.tap
                    anchors.centerIn: parent; width: parent.width * 1.3; height: parent.height * 1.6; radius: height / 2
                    color: Qt.alpha(Qt.lighter(gem.col, 1.6), 0.4)
                }
                Rectangle {  // canto
                    anchors.fill: parent; anchors.topMargin: parent.height * 0.18; radius: height / 2
                    color: Qt.darker(gem.col, 2.2); border.color: "#cc000000"; border.width: Math.max(1, 2 * parent.sc)
                }
                Rectangle {  // cara (HOPO: blanca con aro grueso del color del carril)
                    id: face
                    readonly property bool tap: parent.tap
                    width: parent.width; height: parent.height * 0.84; radius: height / 2
                    border.color: tap ? gem.col : Qt.darker(gem.col, 1.5)
                    border.width: tap ? Math.max(2, height * 0.2) : Math.max(1, 2 * parent.sc)
                    gradient: Gradient {
                        GradientStop { position: 0; color: face.tap ? "white" : Qt.lighter(gem.col, 1.35) }
                        GradientStop { position: 1; color: face.tap ? Qt.tint(gem.col, "#b0ffffff") : gem.col }
                    }
                }
                Rectangle {  // centro
                    x: parent.width * 0.3; width: parent.width * 0.4
                    y: parent.height * 0.22; height: parent.height * 0.4; radius: height / 2
                    visible: !parent.tap
                    color: "#bbffffff"
                    border.color: Qt.darker(gem.col, 1.3); border.width: Math.max(1, parent.sc)
                }
            }
        }
    }

    // ---------- llamas ----------
    Repeater {  // al acertar, y mientras suena un sustain: tres lenguas de fuego del color del carril
        model: 5
        Item {
            id: flame
            anchors.fill: parent
            readonly property real level: Math.max(root.f.flash[index],
                                                   root.f.burn[index] ? 0.55 + 0.08 * Math.sin(root.f.time * 23 + index) : 0)
            readonly property color col: root.colors[index]
            readonly property real cx: root.xAt(index, 0)
            readonly property real base: root.strikeY + root.laneW * 0.08
            readonly property real fw: root.laneW * 0.66
            readonly property int lane: index
            visible: level > 0.02
            opacity: Math.min(1, level * 1.5)
            Repeater {
                model: 3  // izquierda, centro (la más alta), derecha
                Shape {
                    id: tongue
                    anchors.fill: parent
                    readonly property real side: index - 1
                    readonly property real flick: 1 + 0.2 * Math.sin(root.f.time * (17 + 6 * index) + index * 2.1 + flame.lane)
                    readonly property real h: root.laneW * (index === 1 ? 1.9 : 1.1) * flame.level * flick
                    readonly property real bw: flame.fw * (index === 1 ? 0.6 : 0.42)
                    readonly property real x0: flame.cx + side * flame.fw * 0.26
                    readonly property real sway: root.laneW * 0.07 * Math.sin(root.f.time * 9 + index * 1.7 + flame.lane)
                    ShapePath {
                        strokeWidth: 0; strokeColor: "transparent"
                        fillGradient: LinearGradient {
                            x1: tongue.x0; y1: flame.base; x2: tongue.x0; y2: flame.base - tongue.h
                            GradientStop { position: 0; color: "white" }
                            GradientStop { position: 0.28; color: Qt.lighter(flame.col, 1.5) }
                            GradientStop { position: 0.65; color: Qt.alpha(flame.col, 0.85) }
                            GradientStop { position: 1; color: Qt.alpha(flame.col, 0) }
                        }
                        startX: tongue.x0 - tongue.bw / 2; startY: flame.base
                        PathCubic {
                            x: tongue.x0 + tongue.sway; y: flame.base - tongue.h
                            control1X: tongue.x0 - tongue.bw / 2; control1Y: flame.base - tongue.h * 0.45
                            control2X: tongue.x0 + tongue.sway - tongue.bw * 0.1; control2Y: flame.base - tongue.h * 0.75
                        }
                        PathCubic {
                            x: tongue.x0 + tongue.bw / 2; y: flame.base
                            control1X: tongue.x0 + tongue.sway + tongue.bw * 0.1; control1Y: flame.base - tongue.h * 0.75
                            control2X: tongue.x0 + tongue.bw / 2; control2Y: flame.base - tongue.h * 0.45
                        }
                        PathQuad {
                            x: tongue.x0 - tongue.bw / 2; y: flame.base
                            controlX: tongue.x0; controlY: flame.base + tongue.bw * 0.35
                        }
                    }
                }
            }
        }
    }

    // ---------- marcador ----------
    Rectangle {
        x: root.xAt(4.5, 0) + 18; y: root.strikeY - height + 30
        width: score.implicitWidth + 32; height: score.implicitHeight + 24; radius: 10
        color: "#b0101020"; border.color: "#40ffffff"
        Column {
            id: score
            x: 16; y: 12; spacing: 2
            Text { text: root.fmt(root.f.score); color: "white"; font.pixelSize: 30; font.bold: true }
            Row {
                spacing: 10
                Text { text: "x" + root.f.mult; color: root.multColors[root.f.mult - 1]
                       font.pixelSize: 40; font.bold: true }
                Column {  // las 10 notas para el siguiente multiplicador
                    anchors.verticalCenter: parent.verticalCenter; spacing: 3
                    Row {
                        spacing: 3
                        Repeater {
                            model: 10
                            Rectangle {
                                width: 9; height: 9; radius: 4.5
                                color: root.f.mult >= 4 || index < root.f.streak % 10 ? root.multColors[Math.min(3, root.f.mult)] : "#33ffffff"
                            }
                        }
                    }
                }
            }
            Text { text: root.f.streak > 0 ? root.f.streak + " seguidas" : " "; color: "white"; font.pixelSize: 18 }
            Text { text: Math.round(root.f.accuracy * 100) + " % · " + root.f.difficulty + (root.f.autoplay ? " · demo" : "")
                   color: "#ccffffff"
                   font.pixelSize: 16 }
        }
    }
    Rectangle {  // título y progreso
        anchors.horizontalCenter: parent.horizontalCenter; y: 6
        width: Math.max(titleText.implicitWidth + 32, root.hwNear * 0.6); height: 40; radius: 8
        color: "#b0101020"
        Text { id: titleText; anchors.horizontalCenter: parent.horizontalCenter; y: 5
               text: root.f.title; color: "white"; font.pixelSize: 17; font.bold: true }
        Rectangle {
            anchors.horizontalCenter: parent.horizontalCenter; y: 30; width: parent.width - 24; height: 4; radius: 2
            color: "#44ffffff"
            Rectangle { width: parent.width * root.f.progress; height: parent.height; radius: 2; color: "white" }
        }
    }
    Text {
        anchors.centerIn: parent; visible: root.f.countdown > 0 && !root.menuOpen
        text: Math.ceil(root.f.countdown); color: "white"; font.pixelSize: 110; font.bold: true
        style: Text.Outline; styleColor: "black"
    }
    Rectangle {  // aviso corto
        visible: root.f.toast !== ""
        anchors.horizontalCenter: parent.horizontalCenter; y: root.strikeY - root.laneW - height - 40
        width: Math.min(root.width - 40, toastText.implicitWidth + 40); height: toastText.implicitHeight + 20
        radius: height / 2; color: "#e0101020"; border.color: "#80ffffff"
        Text { id: toastText; anchors.centerIn: parent; width: Math.min(implicitWidth, root.width - 80)
               text: root.f.toast; color: "white"; font.pixelSize: 18; wrapMode: Text.WordWrap
               horizontalAlignment: Text.AlignHCenter }
    }

    // ---------- menú ----------
    Rectangle {
        anchors.fill: parent; color: "#70000000"; visible: root.menuOpen
    }
    Rectangle {
        id: menuBox
        visible: root.menuOpen
        anchors.centerIn: parent
        width: Math.min(root.width - 40, 560); height: menuCol.implicitHeight + 48; radius: 14
        color: "#f0101024"; border.color: "#70ffffff"; border.width: 1.5
        Column {
            id: menuCol
            x: 28; y: 24; width: parent.width - 56; spacing: 6
            Text { width: parent.width; text: root.menuOpen ? root.f.menu.title : ""; color: "white"
                   font.pixelSize: 30; font.bold: true }
            Text { width: parent.width; text: root.menuOpen ? root.f.menu.body : ""; visible: text !== ""
                   color: "#ddffffff"; font.pixelSize: 17; wrapMode: Text.WordWrap; textFormat: Text.StyledText
                   bottomPadding: 8 }
            Repeater {
                model: root.menuOpen ? root.f.menu.items.length : 0
                Rectangle {
                    readonly property bool selected: index === root.f.menu.sel
                    readonly property bool editing: selected && root.f.menu.editing
                    width: menuCol.width; height: 44; radius: 8
                    color: editing ? "#402ecc40" : selected ? "#28ffffff" : "transparent"
                    border.color: selected ? (editing ? "#2ecc40" : "#90ffffff") : "transparent"; border.width: 2
                    Text { x: 16; anchors.verticalCenter: parent.verticalCenter
                           text: root.f.menu.items[index]; color: "white"; font.pixelSize: 20
                           font.bold: parent.selected }
                    Text { anchors.right: parent.right; anchors.rightMargin: 16; anchors.verticalCenter: parent.verticalCenter
                           readonly property string v: root.f.menu.values[index]
                           text: v === "" ? "" : parent.editing ? "▲  " + v + "  ▼" : v
                           color: parent.editing ? "#2ecc40" : "#ccffffff"; font.pixelSize: 20; font.bold: parent.editing }
                }
            }
            Text { width: parent.width; topPadding: 10; horizontalAlignment: Text.AlignHCenter
                   text: root.menuOpen && root.f.menu.editing ? "Strum: cambiar · Verde / + o Rojo / −: listo"
                                                              : root.f.menuHint
                   color: "#99ffffff"; font.pixelSize: 14 }
        }
    }
    Rectangle {  // calibración: arriba, para ver bajar las notas
        visible: root.calibrating
        anchors.horizontalCenter: parent.horizontalCenter; y: root.height * 0.1
        width: Math.min(root.width - 40, 560); height: calCol.implicitHeight + 48; radius: 14
        color: "#f0101024"; border.color: "#70ffffff"; border.width: 1.5
        Column {
            id: calCol
            x: 28; y: 24; width: parent.width - 56; spacing: 12
            Text { text: "Calibrar el retardo"; color: "white"; font.pixelSize: 30; font.bold: true }
            Text { width: parent.width; color: "#ddffffff"; font.pixelSize: 17; wrapMode: Text.WordWrap
                   text: "Rasguea justo cuando cada nota amarilla llegue a la línea: suena un clic al pasar. "
                         + "Los 4 clics agudos del principio solo marcan el ritmo. No hace falta pulsar trastes.<br>"
                   + "Rojo / −: cancelar"; textFormat: Text.StyledText }
            Rectangle {
                width: parent.width; height: 6; radius: 3; color: "#44ffffff"
                Rectangle { width: parent.width * (root.calibrating ? root.f.calib.progress : 0); height: 6; radius: 3
                            color: "#2ecc40" }
            }
            Text { text: "Notas: " + (root.calibrating ? root.f.calib.taps + " / " + root.f.calib.total : ""); color: "white"
                   font.pixelSize: 20 }
        }
    }
    Text {
        anchors.horizontalCenter: parent.horizontalCenter; anchors.bottom: parent.bottom; anchors.bottomMargin: 8
        text: root.f.message; color: "#ffdc00"; font.pixelSize: 14; style: Text.Outline; styleColor: "black"
    }
}

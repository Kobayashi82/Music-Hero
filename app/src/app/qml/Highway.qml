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
                       time: 0, autoplay: false, best: 0, partial: false, hwWidth: 560 })
    readonly property var colors: ["#2ecc40", "#ff4136", "#ffdc00", "#1e90ff", "#ff851b"]
    readonly property var multColors: ["white", "#ffdc00", "#2ecc40", "#c86cff"]
    readonly property real farScale: 0.38
    readonly property real k: 1 / farScale - 1
    property real hwNear: Math.min(width - 640, f.hwWidth)  // play.SIDE_MARGIN: sitio para el marcador
    readonly property real laneW: hwNear / 5
    readonly property real strikeY: height - Math.max(110, height * 0.1)
    readonly property real horizonY: height * 0.06
    readonly property int notePool: 200
    readonly property int beatPool: 32
    readonly property int stride: 7
    // sprites (app/sprites.py, lienzo 256 x 160 con la cara de 180 x 82 centrada en y = 75): proporción del
    // lienzo, cuánto más ancho es que la cara (el resto es halo) y dónde cae el centro de la cara
    readonly property real gemAspect: 160 / 256
    readonly property real gemScale: 256 / 180
    readonly property real faceY: 75 / 160
    function sprite(id) { return "image://sprites/" + id }
    readonly property bool menuOpen: f.menu !== undefined && f.menu.title !== undefined
    readonly property bool calibrating: f.calib !== undefined && f.calib.total !== undefined

    function s(u) { return 1 / (1 + k * Math.max(u, -0.3)) }
    function yAt(u) { return strikeY - (strikeY - horizonY) * (1 - s(u)) / (1 - farScale) }
    function xAt(lane, u) { return width / 2 + (lane - 2) * laneW * s(u) }
    // Matriz que lleva un rectángulo w x h al cuadrilátero (x0,y0) arriba-izq, (x1,y1) arriba-der,
    // (x2,y2) abajo-der, (x3,y3) abajo-izq: una homografía (Heckbert), para texturas en perspectiva.
    function quad(w, h, x0, y0, x1, y1, x2, y2, x3, y3) {
        var dx1 = x1 - x2, dx2 = x3 - x2, dx3 = x0 - x1 + x2 - x3
        var dy1 = y1 - y2, dy2 = y3 - y2, dy3 = y0 - y1 + y2 - y3
        var g = 0, hh = 0
        var det = dx1 * dy2 - dx2 * dy1
        if (Math.abs(det) > 1e-9 && (Math.abs(dx3) > 1e-9 || Math.abs(dy3) > 1e-9)) {
            g = (dx3 * dy2 - dx2 * dy3) / det
            hh = (dx1 * dy3 - dx3 * dy1) / det
        }
        var a = x1 - x0 + g * x1, b = x3 - x0 + hh * x3
        var d = y1 - y0 + g * y1, e = y3 - y0 + hh * y3
        return Qt.matrix4x4(a / w, b / h, 0, x0,
                            d / w, e / h, 0, y0,
                            0, 0, 1, 0,
                            g / w, hh / h, 0, 1)
    }
    function fmt(n) { return Math.round(n).toLocaleString(Qt.locale("es_ES"), "f", 0) }

    FrameAnimation {
        running: true
        onTriggered: root.f = bridge.tick()
    }

    // ---------- autopista ----------
    Shape {
        preferredRendererType: Shape.CurveRenderer
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
    Shape {  // al fallar: la parte de abajo de la autopista se enciende en rojo y se apaga
        preferredRendererType: Shape.CurveRenderer
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
    Repeater {  // separaciones entre carriles
        model: 4
        Shape {
            preferredRendererType: Shape.CurveRenderer
            anchors.fill: parent
            ShapePath {
                strokeWidth: 1.5; strokeColor: "#2cffffff"; fillColor: "transparent"
                startX: root.xAt(index + 0.5, 1); startY: root.horizonY
                PathLine { x: root.xAt(index + 0.5, -0.25); y: root.yAt(-0.25) }
            }
        }
    }
    Repeater {  // raíles metálicos a los lados
        model: 2
        Shape {
            preferredRendererType: Shape.CurveRenderer
            id: rail
            anchors.fill: parent
            readonly property real inner: index === 0 ? -0.5 : 4.5
            readonly property real outer: index === 0 ? -0.62 : 4.62
            ShapePath {
                strokeWidth: 0; strokeColor: "transparent"
                fillGradient: LinearGradient {
                    y1: root.horizonY; y2: root.yAt(-0.25)
                    GradientStop { position: 0; color: "#00838894" }
                    GradientStop { position: 0.35; color: "#a0596069" }
                    GradientStop { position: 1; color: "#f0a3a9b5" }
                }
                startX: root.xAt(rail.inner, 1); startY: root.horizonY
                PathLine { x: root.xAt(rail.outer, 1); y: root.horizonY }
                PathLine { x: root.xAt(rail.outer, -0.25); y: root.yAt(-0.25) }
                PathLine { x: root.xAt(rail.inner, -0.25); y: root.yAt(-0.25) }
            }
            ShapePath {  // filo de luz en el lado de dentro
                strokeWidth: 1.5; strokeColor: "#90ffffff"; fillColor: "transparent"
                startX: root.xAt(rail.inner, 1); startY: root.horizonY
                PathLine { x: root.xAt(rail.inner, -0.25); y: root.yAt(-0.25) }
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
    Repeater {  // botones de la línea de golpeo: se hunden y se encienden al pulsar; tiemblan al fallar
        model: 5
        Item {
            id: strikeBtn
            readonly property real w: root.laneW * 0.96 * root.gemScale
            readonly property real h: w * root.gemAspect
            readonly property real cx: root.xAt(index, 0)
            readonly property real miss: root.f.missLane[index]
            readonly property real flash: root.f.flash[index]
            anchors.fill: parent
            Image {  // halo rojo al fallar
                visible: strikeBtn.miss > 0.01
                source: root.sprite("glow/1"); smooth: true
                width: strikeBtn.w * 1.15; height: width * 0.5
                x: strikeBtn.cx - width / 2; y: root.strikeY - height / 2; opacity: strikeBtn.miss * 0.9
            }
            Image {
                source: root.sprite("fret/" + index + "/" + (root.f.held[index] ? "down" : "up"))
                smooth: true; mipmap: true
                width: strikeBtn.w; height: strikeBtn.h
                x: strikeBtn.cx - width / 2 + Math.sin(root.f.time * 70) * strikeBtn.miss * root.laneW * 0.06
                y: root.strikeY - height * root.faceY
            }
            Image {  // destello al acertar, encima del botón
                visible: strikeBtn.flash > 0.01
                source: root.sprite("glow/" + index); smooth: true
                width: strikeBtn.w * (0.95 + 0.6 * (1 - strikeBtn.flash)); height: width * 0.5
                x: strikeBtn.cx - width / 2; y: root.strikeY - height / 2; opacity: strikeBtn.flash
            }
            Image {  // y un fogonazo blanco más corto en el centro
                visible: strikeBtn.flash > 0.5
                source: root.sprite("glow/white"); smooth: true
                width: strikeBtn.w * 0.6; height: width * 0.45
                x: strikeBtn.cx - width / 2; y: root.strikeY - height / 2; opacity: (strikeBtn.flash - 0.5) * 2
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

            Image {  // cola de la nota larga: textura proyectada en perspectiva sobre el carril
                id: tail
                visible: gem.uEnd > gem.u + 0.001
                readonly property real u0: gem.sustaining ? 0 : gem.u
                readonly property real wk: gem.sustaining ? 0.5 : 0.42
                readonly property real w0: root.laneW * wk * root.s(u0) / 2
                readonly property real w1: root.laneW * wk * root.s(gem.uEnd) / 2
                source: root.sprite("tail/" + gem.lane + "/" + (gem.state === 2 ? "miss" : gem.sustaining ? "live" : "normal"))
                smooth: true
                x: 0; y: 0; width: 64; height: 256
                transform: Matrix4x4 {
                    matrix: root.quad(tail.width, tail.height,
                                      root.xAt(gem.lane, gem.uEnd) - tail.w1, root.yAt(gem.uEnd),
                                      root.xAt(gem.lane, gem.uEnd) + tail.w1, root.yAt(gem.uEnd),
                                      root.xAt(gem.lane, tail.u0) + tail.w0, root.yAt(tail.u0),
                                      root.xAt(gem.lane, tail.u0) - tail.w0, root.yAt(tail.u0))
                }
            }
            Item {  // la nota (sprite); los HOPO llevan además un halo blanco
                visible: gem.state !== 1
                readonly property real w: root.laneW * 0.88 * root.gemScale * root.s(gem.u)
                readonly property real h: w * root.gemAspect
                x: root.xAt(gem.lane, gem.u) - w / 2; y: root.yAt(gem.u) - h * root.faceY
                width: w; height: h
                Image {
                    visible: gem.hopo && gem.state !== 2
                    source: root.sprite("glow/white"); smooth: true
                    width: parent.w * 1.0; height: parent.h * 1.1
                    x: (parent.w - width) / 2; y: parent.h * root.faceY - height / 2; opacity: 0.5
                }
                Image {
                    anchors.fill: parent; smooth: true; mipmap: true
                    source: root.sprite("gem/" + gem.lane + "/" + (gem.state === 2 ? "miss" : gem.hopo ? "hopo" : "normal"))
                }
            }
        }
    }

    // ---------- llamas ----------
    Repeater {  // al acertar (y mientras suena un sustain): fuego del color del carril, animado por fotogramas
        model: 5
        Image {
            readonly property real level: Math.max(root.f.flash[index],
                                                   root.f.burn[index] ? 0.6 + 0.08 * Math.sin(root.f.time * 23 + index) : 0)
            readonly property int frame: Math.floor(root.f.time * 22 + index * 1.7) % 6
            visible: level > 0.02
            source: root.sprite("flame/" + index + "/" + frame); smooth: true
            width: root.laneW * 1.1 * (1 + 0.05 * Math.sin(root.f.time * 31 + index))
            height: width * 2 * (0.45 + 0.55 * level)
            x: root.xAt(index, 0) - width / 2
            y: root.strikeY + height * 0.106 - height  // la base del sprite (a 34 de 320 px del borde) en la línea
            opacity: Math.min(1, level * 1.6)
        }
    }

    // ---------- marcador ----------
    Rectangle {
        x: root.xAt(4.5, 0) + 18; y: root.strikeY - height + 30
        width: score.implicitWidth + 32; height: score.implicitHeight + 24; radius: 10
        color: "#e6101020"; border.color: "#40ffffff"
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
            Text { text: root.f.streak > 1 ? root.f.streak + " seguidas" : root.f.streak === 1 ? "1 seguida" : " "; color: "white"; font.pixelSize: 18 }
            Text { text: Math.round(root.f.accuracy * 100) + " % · " + root.f.difficulty; color: "#ccffffff"; font.pixelSize: 16 }
            Text {  // récord de la canción en esta dificultad; dorado al superarlo
                readonly property bool beaten: root.f.best > 0 && root.f.score > root.f.best && !root.f.partial
                visible: root.f.best > 0
                text: beaten ? "¡Récord! (" + root.fmt(root.f.best) + ")" : "Récord " + root.fmt(root.f.best)
                color: beaten ? "#ffd23c" : "#99ffffff"; font.pixelSize: 15; font.bold: beaten
            }
            Text { visible: root.f.autoplay; text: "Automático"; color: "#ffdc00"; font.pixelSize: 16; font.bold: true }
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

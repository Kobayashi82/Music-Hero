"""Instalar el motor: el modelo de la app. uv run --project app --with pytest pytest app/tests"""

from app.installer import update_model


def test_el_modelo_del_motor_es_el_de_la_app(tmp_path):
    bundled = tmp_path / "app" / "best.pt"
    bundled.parent.mkdir()
    bundled.write_bytes(b"v5d")
    engine = tmp_path / "engine"
    (engine / "models").mkdir(parents=True)
    (engine / "models" / "onsetnet.pt").write_bytes(b"v4")  # de una versión anterior, con otro nombre
    target = update_model(engine, bundled)
    assert target.name == "best.pt" and target.read_bytes() == b"v5d"
    assert not (engine / "models" / "onsetnet.pt").exists()
    bundled.write_bytes(b"v6")  # app reinstalada con un modelo nuevo
    assert update_model(engine, bundled).read_bytes() == b"v6"

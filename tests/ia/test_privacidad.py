"""Test de privacidad del sanitizador (B11).

Toma una query con datos sensibles reales (email, RFC, número de tarjeta),
la sanitiza, escribe el output a un archivo y verifica con grep que ningún
dato original aparezca. Es la prueba dura para el Q&A del Demo Day:
"¿cómo garantizan privacidad?".
"""

import subprocess

from ia import sanitize

# Datos sensibles reales que NO deben aparecer en el output.
DATOS_SENSIBLES = [
    "juan.perez@empresa.com.mx",  # email
    "GODE561231GR8",  # RFC mexicano persona física
    "4532015112830366",  # número de tarjeta (test Visa)
]

QUERY_CON_DATOS_SENSIBLES = f"""
SELECT u.id, u.nombre, u.email, p.tarjeta
FROM usuarios u
JOIN pagos p ON p.usuario_id = u.id
WHERE u.email = '{DATOS_SENSIBLES[0]}'
  AND u.rfc = '{DATOS_SENSIBLES[1]}'
  AND p.tarjeta = '{DATOS_SENSIBLES[2]}'
"""


def test_privacidad_ningun_dato_sensible_aparece_en_output(tmp_path):
    """Sanitiza una query con datos reales y verifica con grep que el output
    no contiene ninguno de los datos originales.
    """
    # 1. Sanitizar
    resultado = sanitize(QUERY_CON_DATOS_SENSIBLES)

    # 2. Guardar el output sanitizado en un archivo (B11 lo pide explícito)
    archivo = tmp_path / "query_sanitizada.sql"
    archivo.write_text(resultado.sql)

    # 3. Verificar con grep que ninguno de los datos originales aparece.
    # grep devuelve exit code 0 si encuentra algo, 1 si no encuentra nada.
    # Queremos que NO encuentre nada → esperamos exit code 1.
    for dato in DATOS_SENSIBLES:
        proceso = subprocess.run(
            ["grep", "-F", dato, str(archivo)],
            capture_output=True,
            text=True,
        )
        assert proceso.returncode == 1, (
            f"FUGA DE PRIVACIDAD: el dato sensible {dato!r} apareció en el "
            f"output sanitizado. Contenido del archivo:\n{archivo.read_text()}"
        )


def test_privacidad_los_datos_si_estan_en_el_mapa_de_literales():
    """Confirma que los datos originales SÍ se conservan en el mapa de
    literales (necesario para reconstruir localmente), pero NO en el SQL.
    """
    resultado = sanitize(QUERY_CON_DATOS_SENSIBLES)

    # En el SQL no deben estar
    for dato in DATOS_SENSIBLES:
        assert dato not in resultado.sql

    # Pero en el mapa sí (porque restore() los necesita)
    originales_en_mapa = {v["original"] for v in resultado.literals.values()}
    # Cada dato sensible va dentro de un string SQL ('...'), así que el
    # original guardado incluye las comillas.
    for dato in DATOS_SENSIBLES:
        assert any(dato in original for original in originales_en_mapa), (
            f"El dato {dato!r} debería estar en el mapa de literales para "
            f"poder reconstruir, pero no está."
        )

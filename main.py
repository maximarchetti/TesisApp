import os
import math
import unicodedata
import threading
import requests
import folium
import pandas as pd
import psycopg2
from psycopg2.pool import ThreadedConnectionPool
from contextlib import contextmanager
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional
from geopy.geocoders import Nominatim
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

DATABASE_URL = os.getenv("DATABASE_URL")

try:
    db_pool = ThreadedConnectionPool(2, 10, dsn=DATABASE_URL)
    print("Connection pool creado exitosamente")
except Exception as e:
    import sys
    print(f"FATAL ERROR: No se pudo conectar a PostgreSQL. Abortando inicio. Detalles: {e}")
    sys.exit(1)

@contextmanager
def get_conn():
    conn = db_pool.getconn()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    finally:
        db_pool.putconn(conn)

app = FastAPI(title="Plataforma de Construcción API", version="7.0")

geolocator = Nominatim(user_agent="tesis_ifts_arquitectura")
geocache   = {"caba": (-34.6037, -58.3816), "centro": (-34.6037, -58.3816)}

SINONIMOS = {
    "albañil": "albañilería general",    "albanil": "albañilería general",
    "albañileria": "albañilería general", "albanileria": "albañilería general",
    "plomero": "instalador sanitarista",  "sanitarista": "instalador sanitarista",
    "electricista matriculado": "electricista", "electricidad": "electricista",
    "gasista matriculado": "gasista",     "gas": "gasista",
    "yeseria": "yesero", "yesería": "yesero", "yeso": "yesero",
    "revoque": "albañilería general",    "mamposteria": "albañilería general"
}

ESTADOS_VALIDOS = {"Pendiente", "Aceptada", "Rechazada", "En Curso", "Finalizada", "Cancelada"}

# ============================================================
# LOCK DEL MOTOR DE IA
# Serializa los reentrenamientos cuando llegan reseñas o
# actualizaciones de ubicación simultáneas vía BackgroundTasks.
# Los reads del motor core no necesitan lock (GIL de Python
# protege la lectura de objetos completos).
# ============================================================
modelo_lock = threading.Lock()

def normalizar_texto(texto):
    if pd.isna(texto):
        return ""
    texto = str(texto).lower().strip()
    for key, val in SINONIMOS.items():
        texto = texto.replace(key, val)
    return ''.join(
        c for c in unicodedata.normalize('NFD', texto)
        if unicodedata.category(c) != 'Mn'
    )

def calcular_distancia_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    a = (math.sin(math.radians(lat2 - lat1) / 2) ** 2
         + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2))
         * math.sin(math.radians(lon2 - lon1) / 2) ** 2)
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def enviar_email(destinatario: str, asunto: str, cuerpo: str):
    print(f"\n[EMAIL] Para: {destinatario} | Asunto: {asunto}\n{cuerpo}\n")
# ============================================================
# VALIDACIONES CPAU / IERIC
# Funciones preparadas para su integración en un futuro
# endpoint de registro de usuarios.
# La verificación se realiza mediante lógica de negocio
# (Python) y no mediante FK a nivel de PostgreSQL, porque
# cpau e ieric representan réplicas locales de organismos
# externos. Una FK podría rechazar a un profesional válido
# si la réplica local estuviera temporalmente desactualizada.
#
# Actualmente estas funciones no son invocadas por ningún
# endpoint de la aplicación.
# ============================================================
def verificar_matricula_cpau(matricula: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT estado_matricula_activo FROM cpau.cpau WHERE matricula_cpau = %s",
                (matricula,)
            )
            resultado = cur.fetchone()
            return bool(resultado and resultado[0])

def verificar_cuil_ieric(cuil: int) -> bool:
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT tarjeta_soyconstructor_activa FROM ieric.ieric WHERE cuil = %s",
                (cuil,)
            )
            resultado = cur.fetchone()
            return bool(resultado and resultado[0])

class SolicitudBusqueda(BaseModel):
    query_texto: str
    lat_arq: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    lon_arq: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    ubicacion_manual: Optional[str] = None
    peso_nlp: float       = 0.4
    peso_estrellas: float = 0.4
    peso_distancia: float = 0.2
    top_n: int = 5

class Oferta(BaseModel):
    id_arquitecto: int
    id_obrero: int

class ActualizarEstado(BaseModel):
    id_contrato: int
    nuevo_estado: str

class UbicacionObrero(BaseModel):
    id_obrero: int
    latitud: float
    longitud: float

class Resena(BaseModel):
    id_contrato: int
    estrellas: int = Field(ge=1, le=5)
    comentario: str

# ============================================================
# MOTOR DE IA — CACHÉ GLOBAL
# ============================================================
df_master_global    = pd.DataFrame()
tfidf_matrix_global = None
vectorizer_global   = None

def inicializar_motor_ia():
    global df_master_global, tfidf_matrix_global, vectorizer_global

    # Lock fuera del print: cubre toda la operación incluyendo
    # la conexión a la base y la escritura de las globales.
    with modelo_lock:
        print("Entrenando Motor Híbrido en memoria...")

        # Una sola query reemplaza los tres read_sql_query anteriores.
        # ::float  → castea NUMERIC(9,6) a float (evita Decimal de Python)
        # COALESCE → reemplaza los fillna() que antes se hacían en Python
        # WHERE    → filtra obreros sin coordenadas antes de llegar a Python
        # Subquery → evita el producto cartesiano de JOINs múltiples
        query = """
            SELECT
                u.id_usuario,
                u.nombre_apellido,
                u.cuil_ieric,
                u.ultima_latitud::float,
                u.ultima_longitud::float,
                i.especialidad_uocra,
                i.zona_residencia,
                COALESCE(stats.promedio_estrellas, 3.0) AS promedio_estrellas,
                COALESCE(stats.cant_trabajos, 0)        AS cant_trabajos
            FROM app.usuarios_app u
            JOIN ieric.ieric i
                ON u.cuil_ieric = i.cuil
                AND i.tarjeta_soyconstructor_activa = TRUE
            LEFT JOIN (
                SELECT
                    c.id_obrero,
                    AVG(r.calificacion_estrellas) AS promedio_estrellas,
                    COUNT(r.id_resena)            AS cant_trabajos
                FROM app.contrataciones c
                JOIN app.resenas r ON r.id_contrato = c.id_contrato
                GROUP BY c.id_obrero
            ) AS stats ON stats.id_obrero = u.id_usuario
            WHERE u.rol = 'Obrero'
              AND u.ultima_latitud  IS NOT NULL
              AND u.ultima_longitud IS NOT NULL
        """

        with get_conn() as conn:
            df_master = pd.read_sql_query(query, conn)

        df_master['oficio_limpio'] = df_master['especialidad_uocra'].apply(normalizar_texto)

        vectorizer_global   = TfidfVectorizer()
        tfidf_matrix_global = vectorizer_global.fit_transform(df_master['oficio_limpio'])
        df_master_global    = df_master
        print(f"✅ Motor IA listo: {len(df_master)} obreros indexados.")

inicializar_motor_ia()

# ============================================================
# MOTOR CORE — RECOMENDACIÓN
# ============================================================
def procesar_recomendacion(solicitud: SolicitudBusqueda):
    lat_final, lon_final = solicitud.lat_arq, solicitud.lon_arq
    ubi_detectada = "GPS detectado"
    manual_presente = (
        solicitud.ubicacion_manual is not None
        and solicitud.ubicacion_manual.strip() != ""
    )

    if manual_presente:
        ubi_detectada = solicitud.ubicacion_manual
        ubi_cache = normalizar_texto(solicitud.ubicacion_manual)
        if ubi_cache in geocache:
            lat_final, lon_final = geocache[ubi_cache]
        else:
            exito_geo = False
            try:
                url_georef = "https://apis.datos.gob.ar/georef/api/direcciones"
                parametros = {
                    "direccion": solicitud.ubicacion_manual,
                    "provincia": "Ciudad Autónoma de Buenos Aires"
                }
                res = requests.get(url_georef, params=parametros, timeout=5).json()
                if res.get('direcciones') and len(res['direcciones']) > 0:
                    lat_final = res['direcciones'][0]['ubicacion']['lat']
                    lon_final = res['direcciones'][0]['ubicacion']['lon']
                    exito_geo = True
            except Exception:
                pass
            if not exito_geo:
                try:
                    location = geolocator.geocode(
                        f"{solicitud.ubicacion_manual}, CABA, Argentina"
                    )
                    if location:
                        lat_final, lon_final = location.latitude, location.longitude
                    else:
                        raise HTTPException(status_code=400, detail="Ubicación no encontrada.")
                except Exception as e:
                    raise HTTPException(status_code=500, detail=f"Fallo mapas: {str(e)}")
            geocache[ubi_cache] = (lat_final, lon_final)

    query_vec  = vectorizer_global.transform([normalizar_texto(solicitud.query_texto)])
    candidatos = df_master_global.copy()
    candidatos['score_nlp'] = cosine_similarity(query_vec, tfidf_matrix_global).flatten()
    candidatos = candidatos[candidatos['score_nlp'] > 0].copy()

    if candidatos.empty:
        return lat_final, lon_final, ubi_detectada, pd.DataFrame()

    candidatos['distancia_km']   = candidatos.apply(
        lambda r: calcular_distancia_km(
            lat_final, lon_final, r['ultima_latitud'], r['ultima_longitud']
        ), axis=1
    )
    candidatos['norm_estrellas'] = ((candidatos['promedio_estrellas'] - 1.0) / 4.0).clip(0, 1)
    if len(candidatos) == 1:
        candidatos['norm_distancia'] = 1.0
    else:
        candidatos['norm_distancia'] = (
            1.0 - MinMaxScaler().fit_transform(candidatos[['distancia_km']])
        )
    candidatos['score_hibrido_final'] = (
        candidatos['score_nlp']        * solicitud.peso_nlp
        + candidatos['norm_estrellas'] * solicitud.peso_estrellas
        + candidatos['norm_distancia'] * solicitud.peso_distancia
    )
    mejores = candidatos.sort_values(
        by='score_hibrido_final', ascending=False
    ).head(solicitud.top_n)
    mejores[['promedio_estrellas', 'distancia_km', 'score_hibrido_final']] = \
        mejores[['promedio_estrellas', 'distancia_km', 'score_hibrido_final']].round(2)

    return lat_final, lon_final, ubi_detectada, mejores

@app.get("/usuario/{id_usuario}")
def obtener_usuario(id_usuario: int):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "SELECT nombre_apellido, rol FROM app.usuarios_app WHERE id_usuario = %s",
                (id_usuario,)
            )
            row = cur.fetchone()
    if row:
        return {"nombre_apellido": row[0], "rol": row[1]}
    raise HTTPException(status_code=404, detail="Usuario no encontrado")

@app.get("/arquitectos")
def listar_arquitectos():
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT id_usuario, nombre_apellido, matricula_cpau "
            "FROM app.usuarios_app WHERE rol = 'Arquitecto' ORDER BY nombre_apellido",
            conn
        )
    return df.fillna("").to_dict(orient="records")

@app.get("/obreros")
def listar_obreros():
    with get_conn() as conn:
        df = pd.read_sql_query(
            "SELECT id_usuario, nombre_apellido "
            "FROM app.usuarios_app WHERE rol = 'Obrero' ORDER BY nombre_apellido",
            conn
        )
    return df.fillna("").to_dict(orient="records")

@app.post("/recomendar")
def endpoint_recomendar(solicitud: SolicitudBusqueda):
    lat_f, lon_f, ubi_det, mejores = procesar_recomendacion(solicitud)
    if mejores.empty:
        return {"mensaje": "No se encontraron obreros", "resultados": []}
    cols = [
        'id_usuario', 'nombre_apellido', 'especialidad_uocra', 'cant_trabajos',
        'promedio_estrellas', 'distancia_km', 'score_hibrido_final',
        'ultima_latitud', 'ultima_longitud'
    ]
    return {
        "ubicacion_detectada": {"lat": lat_f, "lon": lon_f, "nombre": ubi_det},
        "resultados": mejores[cols].to_dict(orient="records")
    }

@app.post("/mapa", response_class=HTMLResponse)
def endpoint_mapa(solicitud: SolicitudBusqueda):
    lat_f, lon_f, ubi_det, mejores = procesar_recomendacion(solicitud)
    mapa = folium.Map(location=[lat_f, lon_f], zoom_start=13, tiles='OpenStreetMap')
    folium.Marker(
        [lat_f, lon_f], popup="Tu Obra",
        icon=folium.Icon(color="blue", icon="building", prefix="fa")
    ).add_to(mapa)
    for _, row in mejores.iterrows():
        folium.Marker(
            [row['ultima_latitud'], row['ultima_longitud']],
            popup=f"{row['nombre_apellido']} - {row['especialidad_uocra']}",
            icon=folium.Icon(color="green", icon="wrench", prefix="fa")
        ).add_to(mapa)
    return mapa._repr_html_()

@app.post("/ofertar")
def enviar_oferta(oferta: Oferta, bt: BackgroundTasks):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "INSERT INTO app.contrataciones (id_arquitecto, id_obrero, estado_obra) "
                    "VALUES (%s, %s, %s)",
                    (oferta.id_arquitecto, oferta.id_obrero, 'Pendiente')
                )
            conn.commit()
    except psycopg2.errors.UniqueViolation as e:
        raise HTTPException(status_code=400, detail=f"Error de Integridad: {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    bt.add_task(enviar_email, "obrero@app.com", "Nueva Oferta", "Tenés una oferta pendiente.")
    return {"mensaje": "Oferta enviada y pendiente de revisión"}

@app.get("/contratos/arquitecto/{id_arq}")
def mis_contratos_arq(id_arq: int):
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT c.id_contrato, u.nombre_apellido AS obrero, c.estado_obra, c.fecha_inicio
            FROM app.contrataciones c
            JOIN app.usuarios_app u ON c.id_obrero = u.id_usuario
            WHERE c.id_arquitecto = %s
            ORDER BY c.id_contrato DESC
        """, conn, params=(id_arq,))
    return df.fillna("").to_dict(orient="records")

@app.get("/contratos/obrero/{id_obrero}")
def mis_contratos_obr(id_obrero: int):
    with get_conn() as conn:
        df = pd.read_sql_query("""
            SELECT c.id_contrato, u.nombre_apellido AS arquitecto, c.estado_obra, c.fecha_inicio
            FROM app.contrataciones c
            JOIN app.usuarios_app u ON c.id_arquitecto = u.id_usuario
            WHERE c.id_obrero = %s
            ORDER BY c.id_contrato DESC
        """, conn, params=(id_obrero,))
    return df.fillna("").to_dict(orient="records")

@app.post("/cambiar_estado")
def cambiar_estado(data: ActualizarEstado, bt: BackgroundTasks):
    if data.nuevo_estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Estado inválido")
    with get_conn() as conn:
        with conn.cursor() as cur:
            if data.nuevo_estado == "En Curso":
                cur.execute(
                    "UPDATE app.contrataciones SET estado_obra=%s, fecha_inicio=CURRENT_TIMESTAMP "
                    "WHERE id_contrato=%s",
                    (data.nuevo_estado, data.id_contrato)
                )
            elif data.nuevo_estado == "Finalizada":
                cur.execute(
                    "UPDATE app.contrataciones SET estado_obra=%s, fecha_fin=CURRENT_TIMESTAMP "
                    "WHERE id_contrato=%s",
                    (data.nuevo_estado, data.id_contrato)
                )
            else:
                cur.execute(
                    "UPDATE app.contrataciones SET estado_obra=%s WHERE id_contrato=%s",
                    (data.nuevo_estado, data.id_contrato)
                )
        conn.commit()
    bt.add_task(
        enviar_email, "usuario@app.com", "Cambio de Estado",
        f"Obra {data.id_contrato} ahora está {data.nuevo_estado}"
    )
    return {"mensaje": f"Estado actualizado a {data.nuevo_estado}"}

@app.post("/resena")
def crear_resena(resena: Resena, bt: BackgroundTasks):
    try:
        with get_conn() as conn:
            with conn.cursor() as cur:
                cur.execute("""
                    INSERT INTO app.resenas
                        (id_contrato, calificacion_estrellas, comentario_texto, fecha_resena)
                    VALUES (%s, %s, %s, CURRENT_DATE)
                """, (resena.id_contrato, resena.estrellas, resena.comentario))
            conn.commit()
    except psycopg2.errors.UniqueViolation:
        raise HTTPException(status_code=400, detail="Ya existe una reseña para esta obra.")
    bt.add_task(inicializar_motor_ia)
    return {"mensaje": "Reseña guardada. El motor de IA se está actualizando."}

@app.post("/actualizar_ubicacion")
def actualizar_ubicacion(datos: UbicacionObrero, bt: BackgroundTasks):
    with get_conn() as conn:
        with conn.cursor() as cur:
            cur.execute(
                "UPDATE app.usuarios_app SET ultima_latitud=%s, ultima_longitud=%s "
                "WHERE id_usuario=%s",
                (datos.latitud, datos.longitud, datos.id_obrero)
            )
        conn.commit()
    bt.add_task(inicializar_motor_ia)
    return {"mensaje": "Ubicación actualizada."}
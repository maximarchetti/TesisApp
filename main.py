import sqlite3
import pandas as pd
import math
import unicodedata
import os
import requests
import folium
from datetime import datetime
from fastapi import FastAPI, HTTPException, BackgroundTasks
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field
from typing import Optional
from geopy.geocoders import Nominatim 
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
from sklearn.preprocessing import MinMaxScaler

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
ruta_app_db = os.path.join(BASE_DIR, 'app.db')
ruta_ieric_db = os.path.join(BASE_DIR, 'ieric.db')

with sqlite3.connect(ruta_app_db) as conn:
    conn.execute("PRAGMA journal_mode=WAL;")
    
app = FastAPI(title="Plataforma de Construcción API", version="6.2")

geolocator = Nominatim(user_agent="tesis_ifts_arquitectura")
geocache = {"caba": (-34.6037, -58.3816), "centro": (-34.6037, -58.3816)}

SINONIMOS = {
    "albañil": "albañilería general", "albanil": "albañilería general", 
    "albañileria": "albañilería general", "albanileria": "albañilería general", 
    "plomero": "instalador sanitarista", "sanitarista": "instalador sanitarista", 
    "electricista matriculado": "electricista", "electricidad": "electricista", 
    "gasista matriculado": "gasista", "gas": "gasista", 
    "yeseria": "yesero", "yesería": "yesero", "yeso": "yesero",
    "revoque": "albañilería general", "mamposteria": "albañilería general"
}

ESTADOS_VALIDOS = {"Pendiente", "Aceptada", "Rechazada", "En Curso", "Finalizada", "Cancelada"}

def normalizar_texto(texto):
    if pd.isna(texto): return ""
    texto = str(texto).lower().strip()
    for key, val in SINONIMOS.items():
        texto = texto.replace(key, val)
    return ''.join(c for c in unicodedata.normalize('NFD', texto) if unicodedata.category(c) != 'Mn')

def calcular_distancia_km(lat1, lon1, lat2, lon2):
    R = 6371.0
    a = math.sin(math.radians(lat2 - lat1) / 2)**2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(math.radians(lon2 - lon1) / 2)**2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def enviar_email(destinatario: str, asunto: str, cuerpo: str):
    print(f"\n[EMAIL] Para: {destinatario} | Asunto: {asunto}\n{cuerpo}\n")

# --- MODELOS ---
class SolicitudBusqueda(BaseModel):
    query_texto: str
    lat_arq: Optional[float] = Field(default=None, ge=-90.0, le=90.0)
    lon_arq: Optional[float] = Field(default=None, ge=-180.0, le=180.0)
    ubicacion_manual: Optional[str] = None
    peso_nlp: float = 0.4
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

# ==========================================
# CACHÉ GLOBAL DEL MOTOR DE IA (SOLUCIÓN DE RENDIMIENTO)
# ==========================================
df_master_global = pd.DataFrame()
tfidf_matrix_global = None
vectorizer_global = None

def inicializar_motor_ia():
    global df_master_global, tfidf_matrix_global, vectorizer_global
    print("Entrenando Motor Híbrido en memoria...")
    with sqlite3.connect(ruta_app_db) as conn_app:
        df_usuarios = pd.read_sql_query("SELECT id_usuario, nombre_apellido, cuil_ieric, ultima_latitud, ultima_longitud FROM usuarios_app WHERE rol = 'Obrero'", conn_app)
        df_calificaciones = pd.read_sql_query("SELECT c.id_obrero, AVG(r.calificacion_estrellas) as promedio_estrellas, COUNT(r.id_resena) as cant_trabajos FROM resenas r JOIN contrataciones c ON r.id_contrato = c.id_contrato GROUP BY c.id_obrero", conn_app)
    with sqlite3.connect(ruta_ieric_db) as conn_ieric:
        df_ieric = pd.read_sql_query("SELECT cuil, especialidad_uocra, zona_residencia FROM ieric WHERE tarjeta_soyconstructor_activa = 1", conn_ieric)
    
    df_master = pd.merge(df_usuarios, df_ieric, left_on='cuil_ieric', right_on='cuil', how='inner')
    df_master = pd.merge(df_master, df_calificaciones, left_on='id_usuario', right_on='id_obrero', how='left')
    df_master = df_master.dropna(subset=['ultima_latitud', 'ultima_longitud'])
    df_master['promedio_estrellas'] = df_master['promedio_estrellas'].fillna(3.0)
    df_master['cant_trabajos'] = df_master['cant_trabajos'].fillna(0)
    df_master['oficio_limpio'] = df_master['especialidad_uocra'].apply(normalizar_texto)
    
    vectorizer_global = TfidfVectorizer()
    tfidf_matrix_global = vectorizer_global.fit_transform(df_master['oficio_limpio'])
    df_master_global = df_master
    print("✅ Motor IA listo y cacheado.")

inicializar_motor_ia()

# --- MOTOR CORE ---
def procesar_recomendacion(solicitud: SolicitudBusqueda):
    lat_final, lon_final = solicitud.lat_arq, solicitud.lon_arq
    ubi_detectada = "GPS detectado"
    manual_presente = solicitud.ubicacion_manual is not None and solicitud.ubicacion_manual.strip() != ""
    
    if manual_presente:
        ubi_detectada = solicitud.ubicacion_manual
        ubi_cache = normalizar_texto(solicitud.ubicacion_manual)
        if ubi_cache in geocache:
            lat_final, lon_final = geocache[ubi_cache]
        else:
            exito_geo = False
            try:
                url_georef = "https://apis.datos.gob.ar/georef/api/direcciones"
                parametros = {"direccion": solicitud.ubicacion_manual, "provincia": "Ciudad Autónoma de Buenos Aires"}
                res = requests.get(url_georef, params=parametros, timeout=5).json()
                if res.get('direcciones') and len(res['direcciones']) > 0:
                    lat_final, lon_final = res['direcciones'][0]['ubicacion']['lat'], res['direcciones'][0]['ubicacion']['lon']
                    exito_geo = True
            except Exception: pass
            if not exito_geo:
                try:
                    location = geolocator.geocode(f"{solicitud.ubicacion_manual}, CABA, Argentina")
                    if location: lat_final, lon_final = location.latitude, location.longitude
                    else: raise HTTPException(status_code=400, detail="Ubicación no encontrada.")
                except Exception as e: raise HTTPException(status_code=500, detail=f"Fallo mapas: {str(e)}")
            geocache[ubi_cache] = (lat_final, lon_final)

    query_vec = vectorizer_global.transform([normalizar_texto(solicitud.query_texto)])
    candidatos = df_master_global.copy()
    candidatos['score_nlp'] = cosine_similarity(query_vec, tfidf_matrix_global).flatten()
    candidatos = candidatos[candidatos['score_nlp'] > 0].copy()
    
    if candidatos.empty: return lat_final, lon_final, ubi_detectada, pd.DataFrame()
    
    candidatos['distancia_km'] = candidatos.apply(lambda r: calcular_distancia_km(lat_final, lon_final, r['ultima_latitud'], r['ultima_longitud']), axis=1)
    candidatos['norm_estrellas'] = ((candidatos['promedio_estrellas'] - 1.0) / 4.0).clip(0, 1)
    if len(candidatos) == 1: candidatos['norm_distancia'] = 1.0
    else: candidatos['norm_distancia'] = 1.0 - MinMaxScaler().fit_transform(candidatos[['distancia_km']])
    candidatos['score_hibrido_final'] = (candidatos['score_nlp'] * solicitud.peso_nlp) + (candidatos['norm_estrellas'] * solicitud.peso_estrellas) + (candidatos['norm_distancia'] * solicitud.peso_distancia)
    mejores = candidatos.sort_values(by='score_hibrido_final', ascending=False).head(solicitud.top_n)
    mejores[['promedio_estrellas', 'distancia_km', 'score_hibrido_final']] = mejores[['promedio_estrellas', 'distancia_km', 'score_hibrido_final']].round(2)
    
    return lat_final, lon_final, ubi_detectada, mejores

# --- ENDPOINTS ---
@app.get("/usuario/{id_usuario}")
def obtener_usuario(id_usuario: int):
    with sqlite3.connect(ruta_app_db) as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT nombre_apellido, rol FROM usuarios_app WHERE id_usuario = ?", (id_usuario,))
        row = cursor.fetchone()
        if row:
            return {"nombre_apellido": row[0], "rol": row[1]}
        raise HTTPException(status_code=404, detail="Usuario no encontrado")

@app.get("/arquitectos")
def listar_arquitectos():
    with sqlite3.connect(ruta_app_db) as conn:
        query = "SELECT id_usuario, nombre_apellido, matricula_cpau FROM usuarios_app WHERE rol = 'Arquitecto' ORDER BY nombre_apellido"
        df = pd.read_sql_query(query, conn)
        df = df.fillna("") # <--- CORRECCIÓN DE JSON (NaN)
        return df.to_dict(orient="records")

@app.get("/obreros")
def listar_obreros():
    with sqlite3.connect(ruta_app_db) as conn:
        query = "SELECT id_usuario, nombre_apellido FROM usuarios_app WHERE rol='Obrero' ORDER BY nombre_apellido"
        df = pd.read_sql_query(query, conn)
        df = df.fillna("") # <--- CORRECCIÓN DE JSON (NaN)
        return df.to_dict(orient="records")

@app.post("/recomendar")
def endpoint_recomendar(solicitud: SolicitudBusqueda):
    lat_f, lon_f, ubi_det, mejores = procesar_recomendacion(solicitud)
    if mejores.empty: return {"mensaje": "No se encontraron obreros", "resultados": []}
    resultados_json = mejores[['id_usuario', 'nombre_apellido', 'especialidad_uocra', 'cant_trabajos', 'promedio_estrellas', 'distancia_km', 'score_hibrido_final', 'ultima_latitud', 'ultima_longitud']].to_dict(orient="records")
    return {"ubicacion_detectada": {"lat": lat_f, "lon": lon_f, "nombre": ubi_det}, "resultados": resultados_json}

@app.post("/mapa", response_class=HTMLResponse)
def endpoint_mapa(solicitud: SolicitudBusqueda):
    lat_f, lon_f, ubi_det, mejores = procesar_recomendacion(solicitud)
    mapa = folium.Map(location=[lat_f, lon_f], zoom_start=13, tiles='CartoDB positron')
    folium.Marker([lat_f, lon_f], popup="Tu Obra", icon=folium.Icon(color="blue", icon="building", prefix="fa")).add_to(mapa)
    for idx, row in mejores.iterrows():
        folium.Marker([row['ultima_latitud'], row['ultima_longitud']], popup=f"{row['nombre_apellido']} - {row['especialidad_uocra']}", icon=folium.Icon(color="green", icon="wrench", prefix="fa")).add_to(mapa)
    return mapa._repr_html_()

@app.post("/ofertar")
def enviar_oferta(oferta: Oferta, bt: BackgroundTasks):
    try:
        with sqlite3.connect(ruta_app_db, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO contrataciones (id_arquitecto, id_obrero, estado_obra) 
                VALUES (?, ?, ?)
            """, (oferta.id_arquitecto, oferta.id_obrero, 'Pendiente'))
            conn.commit()
    except sqlite3.IntegrityError as e:
        raise HTTPException(status_code=400, detail=f"Error de Integridad (BBDD Constraint): {e}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    
    bt.add_task(enviar_email, "obrero@app.com", "Nueva Oferta", "Tenés una oferta pendiente.")
    return {"mensaje": "Oferta enviada y pendiente de revisión"}

@app.get("/contratos/arquitecto/{id_arq}")
def mis_contratos_arq(id_arq: int):
    with sqlite3.connect(ruta_app_db) as conn:
        query = """
            SELECT c.id_contrato, u.nombre_apellido as obrero, c.estado_obra, c.fecha_inicio
            FROM contrataciones c JOIN usuarios_app u ON c.id_obrero = u.id_usuario
            WHERE c.id_arquitecto = ? ORDER BY c.id_contrato DESC
        """
        df = pd.read_sql_query(query, conn, params=(id_arq,))
        df = df.fillna("") # <--- CORRECCIÓN DE JSON (NaN)
    return df.to_dict(orient="records")

@app.get("/contratos/obrero/{id_obrero}")
def mis_contratos_obr(id_obrero: int):
    with sqlite3.connect(ruta_app_db) as conn:
        query = """
            SELECT c.id_contrato, u.nombre_apellido as arquitecto, c.estado_obra, c.fecha_inicio
            FROM contrataciones c JOIN usuarios_app u ON c.id_arquitecto = u.id_usuario
            WHERE c.id_obrero = ? ORDER BY c.id_contrato DESC
        """
        df = pd.read_sql_query(query, conn, params=(id_obrero,))
        df = df.fillna("") # <--- CORRECCIÓN DE JSON (NaN)
    return df.to_dict(orient="records")

@app.post("/cambiar_estado")
def cambiar_estado(data: ActualizarEstado, bt: BackgroundTasks):
    if data.nuevo_estado not in ESTADOS_VALIDOS:
        raise HTTPException(status_code=400, detail="Estado inválido")
    hoy = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with sqlite3.connect(ruta_app_db, timeout=30) as conn:
        cursor = conn.cursor()
        if data.nuevo_estado == "En Curso":
            cursor.execute("UPDATE contrataciones SET estado_obra=?, fecha_inicio=? WHERE id_contrato=?", (data.nuevo_estado, hoy, data.id_contrato))
        elif data.nuevo_estado == "Finalizada":
            cursor.execute("UPDATE contrataciones SET estado_obra=?, fecha_fin=? WHERE id_contrato=?", (data.nuevo_estado, hoy, data.id_contrato))
        else:
            cursor.execute("UPDATE contrataciones SET estado_obra=? WHERE id_contrato=?", (data.nuevo_estado, data.id_contrato))
        conn.commit()
    bt.add_task(enviar_email, "usuario@app.com", "Cambio de Estado", f"Obra {data.id_contrato} ahora está {data.nuevo_estado}")
    return {"mensaje": f"Estado actualizado a {data.nuevo_estado}"}

@app.post("/resena")
def crear_resena(resena: Resena, bt: BackgroundTasks): # <--- 1. Agregamos BackgroundTasks
    try:
        with sqlite3.connect(ruta_app_db, timeout=30) as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO resenas (id_contrato, calificacion_estrellas, comentario_texto, fecha_resena) 
                VALUES (?, ?, ?, ?)
            """, (resena.id_contrato, resena.estrellas, resena.comentario, datetime.now().strftime('%Y-%m-%d')))
            conn.commit()
    except sqlite3.IntegrityError:
        raise HTTPException(status_code=400, detail="Ya existe una reseña para esta obra.")
    
    # <--- 2. LA MAGIA: Reentrenamos el modelo en segundo plano sin hacer esperar al usuario
    bt.add_task(inicializar_motor_ia) 
    
    return {"mensaje": "Reseña guardada. El motor de IA se está actualizando."}

@app.post("/actualizar_ubicacion")
def actualizar_ubicacion(datos: UbicacionObrero, bt: BackgroundTasks): # <--- 1. Agregamos BackgroundTasks
    with sqlite3.connect(ruta_app_db, timeout=30) as conn:
        cursor = conn.cursor()
        cursor.execute("UPDATE usuarios_app SET ultima_latitud=?, ultima_longitud=? WHERE id_usuario=?", (datos.latitud, datos.longitud, datos.id_obrero))
        conn.commit()
        
    # <--- 2.Actualizar el DataFrame global en segundo plano
    bt.add_task(inicializar_motor_ia)
    
    return {"mensaje": "Ubicación actualizada."}
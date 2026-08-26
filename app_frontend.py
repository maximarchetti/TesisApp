import pandas as pd
import streamlit as st
import requests
import folium
from streamlit_folium import st_folium
st.set_page_config(page_title="App Arquitectos - IFTS", page_icon="🏗️", layout="centered")
if 'datos_busqueda' not in st.session_state: st.session_state['datos_busqueda'] = None
if 'rol_actual' not in st.session_state: st.session_state['rol_actual'] = "Arquitecto"
if 'usuario_id' not in st.session_state:
    st.session_state['usuario_id'] = None
if 'obrero_id' not in st.session_state:
    st.session_state['obrero_id'] = None
st.markdown("""
    <style>
    :root { --primary: #0061A1; --secondary: #85D7FC; --dark-grey: #424754; --orange-construction: #ff6600; }
    h1, h2, h3 { color: #0061A1 !important; }
    .stButton>button { background-color: #ff6600; color: white; border-radius: 5px; font-weight: bold; width: 100%; }
    .stButton>button:hover { background-color: #e65c00; color: white; border: 1px solid white; }
    .obrero-card { background-color: #f8f9fa; border-left: 5px solid #0061A1; padding: 15px; border-radius: 5px; margin-bottom: 15px; }
    .obrero-card h4, .obrero-card p, .obrero-card b, .obrero-card small { color: #333333 !important; }
    </style>
""", unsafe_allow_html=True)
API_URL = "http://127.0.0.1:8000"
def cargar_nombre_usuario(user_id):
    try:
        res = requests.get(f"{API_URL}/usuario/{user_id}")
        if res.status_code == 200: return res.json().get("nombre_apellido", "Usuario")
    except: pass
    return "Usuario"
@st.cache_data
def obtener_arquitectos():
    res = requests.get(f"{API_URL}/arquitectos")
    if res.status_code == 200:
        return pd.DataFrame(res.json())
    return pd.DataFrame()
@st.cache_data
def obtener_obreros():
    res = requests.get(f"{API_URL}/obreros")
    if res.status_code == 200:
        return pd.DataFrame(res.json())
    return pd.DataFrame()
with st.sidebar:
    st.markdown("<h1>🏗️ Plataforma</h1>", unsafe_allow_html=True)
    st.session_state['rol_actual'] = st.radio("Ingresar como:",["Arquitecto", "Obrero"])
    st.divider()
    if st.session_state['rol_actual'] == "Arquitecto":
        arquitectos = obtener_arquitectos()
        if not arquitectos.empty:
            seleccion = st.selectbox("Arquitecto",arquitectos["nombre_apellido"])
            fila = arquitectos[arquitectos["nombre_apellido"] == seleccion].iloc[0]
                      
            nuevo_id = int(fila["id_usuario"])

            if st.session_state.get("usuario_id") != nuevo_id:
                st.session_state["usuario_id"] = nuevo_id
                st.session_state.pop("contratos", None)
            
            nombre_activo = fila["nombre_apellido"]
    else:
        obreros = obtener_obreros()
        if not obreros.empty:
            seleccion = st.selectbox("Obrero",obreros["nombre_apellido"])
            fila = obreros[obreros["nombre_apellido"] == seleccion].iloc[0]
                        
            nuevo_id = int(fila["id_usuario"])

            if st.session_state.get("obrero_id") != nuevo_id:
                st.session_state["obrero_id"] = nuevo_id
                st.session_state.pop("ofertas_obrero", None) 
                     
            nombre_activo = fila["nombre_apellido"]
    st.write(f"👤 Conectado: **{nombre_activo}** ({st.session_state['rol_actual']})")
# ==========================================
# PORTAL ARQUITECTO
# ==========================================
if st.session_state['rol_actual'] == "Arquitecto":
    st.title(f"🏗️ Hola, {nombre_activo}")
    tab1, tab2 = st.tabs(["🔍 Buscar Obreros", "📋 Mis Contrataciones"])
    with tab1:
        with st.form("busqueda_form"):
            query_texto = st.text_input("Descripción del trabajo:", placeholder="Ej: Necesito electricista para instalación nueva")
            col1, col2 = st.columns([1, 2])
            with col1:
                tipo_ubicacion = st.radio("Ubicación:", ("Ingresar Manualmente", "📍 GPS (Modo Demostración)"))
            with col2:
                ubicacion_manual = st.text_input("Barrio / Dirección", placeholder="Ej: Caballito") if tipo_ubicacion == "Ingresar Manualmente" else ""
            estrategia = st.selectbox("Estrategia de búsqueda:", ["Balanceada", "Mejores Valorados", "Cercanía"])
            if estrategia == "Balanceada": p_nlp, p_est, p_dist = 0.4, 0.4, 0.2
            elif estrategia == "Mejores Valorados": p_nlp, p_est, p_dist = 0.3, 0.6, 0.1
            else: p_nlp, p_est, p_dist = 0.3, 0.2, 0.5
            top_n = st.selectbox("Cantidad a mostrar:", [3, 5, 10])
            submit_button = st.form_submit_button("Buscar Obreros")
        if submit_button:
            if not query_texto: st.warning("Ingresá una descripción.")
            else:
                payload = {"query_texto": query_texto, "peso_nlp": p_nlp, "peso_estrellas": p_est, "peso_distancia": p_dist, "top_n": top_n}
                if tipo_ubicacion == "Ingresar Manualmente" and ubicacion_manual.strip() != "": payload["ubicacion_manual"] = ubicacion_manual
                else: payload["lat_arq"], payload["lon_arq"] = -34.6037, -58.3816
                try:
                    response = requests.post(f"{API_URL}/recomendar", json=payload, timeout=10)
                    if response.status_code == 200: st.session_state['datos_busqueda'] = response.json()
                    else: st.error("Error en la búsqueda.")
                except: st.error("🚨 No se pudo conectar con FastAPI.")
        if st.session_state['datos_busqueda']:
            datos = st.session_state['datos_busqueda']
            obreros = datos.get("resultados", [])
            if not obreros: st.warning("No se encontraron coincidencias.")
            else:
                ubicacion = datos.get("ubicacion_detectada", {})
                if "nombre" in ubicacion:
                    st.success(f"📌 Ubicación utilizada: {ubicacion['nombre']}")
                if "lat" in ubicacion and "lon" in ubicacion:
                    st.subheader("🗺️ Ubicación Geográfica de la Oferta")
                    mapa = folium.Map(location=[ubicacion['lat'], ubicacion['lon']], zoom_start=13, tiles='CartoDB positron')
                    folium.Marker([ubicacion['lat'], ubicacion['lon']], popup="Tu Obra", icon=folium.Icon(color="blue", icon="building", prefix="fa")).add_to(mapa)
                    for obs in obreros:
                        if "ultima_latitud" in obs and "ultima_longitud" in obs:
                            html = f"<b>{obs['nombre_apellido']}</b><br>{obs['especialidad_uocra']}<br>⭐ {obs['promedio_estrellas']}"
                            folium.Marker([obs["ultima_latitud"], obs["ultima_longitud"]], popup=folium.Popup(html, max_width=250), icon=folium.Icon(color="green", icon="wrench", prefix="fa")).add_to(mapa)
                    st_folium(mapa, width=700, height=400, key="mapa_arq")
                st.subheader("👷 Resultados")
                for ob in obreros:
                    st.markdown(f"""
                    <div class="obrero-card">
                        <h4>{ob['nombre_apellido']} - {ob['especialidad_uocra']}</h4>
                        <p>⭐ {ob['promedio_estrellas']} ({int(ob['cant_trabajos'])} trabajos) | <b>A {ob['distancia_km']} km</b></p>
                    </div>
                    """, unsafe_allow_html=True)
                    if st.button(f"Enviar Oferta", key=f"btn_{ob['id_usuario']}"):
                        res = requests.post(f"{API_URL}/ofertar", json={"id_arquitecto": st.session_state['usuario_id'], "id_obrero": ob['id_usuario']})
                        if res.status_code == 200: st.success("¡Oferta enviada con éxito!")
                        else: st.error(res.json().get('detail', "Error al enviar la oferta"))
    with tab2:
        st.subheader("📋 Mis Contrataciones")
        # Cargar contratos y guardarlos en memoria
        if "contratos" not in st.session_state:
            res = requests.get(f"{API_URL}/contratos/arquitecto/{st.session_state['usuario_id']}"
            )
            if res.status_code == 200:
                st.session_state["contratos"] = res.json()
        if st.button("🔄 Refrescar Historial"):
            try:
                res = requests.get(f"{API_URL}/contratos/arquitecto/{st.session_state['usuario_id']}")
                if res.status_code == 200:
                    st.session_state["contratos"] = res.json()
                st.rerun()
            except Exception as e:
                st.error(str(e))
        # Mostrar contratos guardados en memoria
        if "contratos" in st.session_state:
            contratos = st.session_state["contratos"]
            if not contratos:
                st.write("Aún no tienes contratos.")
            for c in contratos:
                st.info(
                    f"**ID Contrato:** {c['id_contrato']} | "
                    f"**Obrero:** {c['obrero']} | "
                    f"**Estado:** {c['estado_obra']}")
                col1, col2 = st.columns(2)
                # -------------------------
                # OFERTA PENDIENTE
                # -------------------------
                if c['estado_obra'] == 'Pendiente':
                    if col1.button("❌ Cancelar Oferta",key=f"canc_{c['id_contrato']}"):
                        requests.post(f"{API_URL}/cambiar_estado",json={
                                "id_contrato": c['id_contrato'],
                                "nuevo_estado": "Cancelada"
                            } )
                        res = requests.get(f"{API_URL}/contratos/arquitecto/{st.session_state['usuario_id']}")
                        if res.status_code == 200:
                            st.session_state["contratos"] = res.json()
                        st.rerun()
                # -------------------------
                # OFERTA ACEPTADA
                # -------------------------
                elif c['estado_obra'] == 'Aceptada':
                    if col1.button("▶️ Comenzar Obra",key=f"ini_{c['id_contrato']}"):
                        requests.post(f"{API_URL}/cambiar_estado",json={
                                "id_contrato": c['id_contrato'],
                                "nuevo_estado": "En Curso"
                            })
                        res = requests.get(f"{API_URL}/contratos/arquitecto/{st.session_state['usuario_id']}")
                        if res.status_code == 200:
                            st.session_state["contratos"] = res.json()
                        st.rerun()
                # -------------------------
                # OBRA EN CURSO
                # -------------------------
                elif c['estado_obra'] == 'En Curso':
                    if col1.button("✅ Finalizar Obra",key=f"fin_{c['id_contrato']}" ):
                        requests.post(f"{API_URL}/cambiar_estado", json={
                                "id_contrato": c['id_contrato'],
                                "nuevo_estado": "Finalizada"
                            })
                        res = requests.get(f"{API_URL}/contratos/arquitecto/{st.session_state['usuario_id']}")
                        if res.status_code == 200:
                            st.session_state["contratos"] = res.json()
                        st.rerun()
                # -------------------------
                # OBRA FINALIZADA
                # -------------------------
                elif c['estado_obra'] == 'Finalizada':
                    with st.expander(f"⭐ Calificar a {c['obrero']}"):
                        with st.form(f"form_resena_{c['id_contrato']}"):
                            estrellas = st.slider("Estrellas",1,5,5)
                            comentario = st.text_area("Comentario", placeholder="Escribe tu reseña aquí...")                       
                            if st.form_submit_button("Enviar Reseña"):
                                r = requests.post(f"{API_URL}/resena",json={
                                        "id_contrato": c['id_contrato'],
                                        "estrellas": estrellas,
                                        "comentario": comentario})
                                if r.status_code == 200:
                                    res = requests.get(f"{API_URL}/contratos/arquitecto/{st.session_state['usuario_id']}")
                                    if res.status_code == 200:
                                        st.session_state["contratos"] = res.json()
                                    st.success("¡Reseña guardada!")
                                    st.rerun()
                                else:
                                    st.error(r.json().get('detail'))
# ==========================================
# PORTAL OBRERO
# ==========================================
else:
    st.title(f"👷‍♂️ Hola, {nombre_activo}")
    st.info("Activá tu ubicación para recibir ofertas cerca tuyo.")
    if st.button("📍 Compartir mi ubicación actual"):
        requests.post(f"{API_URL}/actualizar_ubicacion",json={"id_obrero": st.session_state['obrero_id'],"latitud": -34.6100,"longitud": -58.4000})
        st.success("Ubicación actualizada en el sistema.")
    st.divider()
    if "ofertas_obrero" not in st.session_state:
        res = requests.get(f"{API_URL}/contratos/obrero/{st.session_state['obrero_id']}")
        if res.status_code == 200:
            st.session_state["ofertas_obrero"] = res.json()
    if st.button("🔄 Ver mis Ofertas de Trabajo"):
        res = requests.get(f"{API_URL}/contratos/obrero/{st.session_state['obrero_id']}")
        if res.status_code == 200:
            st.session_state["ofertas_obrero"] = res.json()  
    if "ofertas_obrero" in st.session_state:
        contratos = st.session_state["ofertas_obrero"]
        if not contratos:
            st.write("No tienes contratos u ofertas asignadas.")
        else:
            for c in contratos:
                st.info(
                    f"📄 Contrato #{c['id_contrato']} | "
                    f"👷 Arquitecto: {c['arquitecto']} | "
                    f"📌 Estado: {c['estado_obra']}"
                )
                if c['estado_obra'] == "Pendiente":
                    col1, col2 = st.columns(2)
                    if col1.button("✅ Aceptar Oferta",key=f"acep_{c['id_contrato']}"):
                        r = requests.post(
                            f"{API_URL}/cambiar_estado",
                            json={"id_contrato": c['id_contrato'],
                                "nuevo_estado": "Aceptada"})
                        res = requests.get(f"{API_URL}/contratos/obrero/{st.session_state['obrero_id']}")
                        if res.status_code == 200:
                            st.session_state["ofertas_obrero"] = res.json()
                        st.success("Oferta aceptada")
                        st.rerun()
                    if col2.button("❌ Rechazar",key=f"rech_{c['id_contrato']}"):
                        r = requests.post(f"{API_URL}/cambiar_estado",
                            json={"id_contrato": c['id_contrato'],
                                "nuevo_estado": "Rechazada"})
                        res = requests.get(f"{API_URL}/contratos/obrero/{st.session_state['obrero_id']}")
                        if res.status_code == 200:
                            st.session_state["ofertas_obrero"] = res.json()
                        st.success("Oferta rechazada")  
                        st.rerun()
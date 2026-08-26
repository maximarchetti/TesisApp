import sqlite3
import polars as pl
from faker import Faker
import random
import os
from datetime import timedelta

# ==========================================
# CONFIGURACIÓN GENERAL
# ==========================================
Faker.seed(123)
random.seed(123)
fake = Faker('es_AR')

print("Iniciando ETL: Generación -> Transformación -> Persistencia (SQLite3)")

# Limpieza previa de archivos para evitar superposición de datos al probar
archivos_db = ['cpau.db', 'ieric.db', 'app.db']
for db in archivos_db:
    if os.path.exists(db):
        os.remove(db)

# ==========================================
# VARIABLES DE RECORTE (TESIS)
# ==========================================
zonas_permitidas = [
    'CABA - Palermo', 'CABA - Belgrano', 'CABA - Caballito', 'CABA - Centro',
    'Avellaneda', 'Lanús', 'Lomas de Zamora', 'Vicente López', 'San Isidro', 'Olivos'
]

especialidades_demandadas = [
    'Electricista', 'Gasista', 'Yesero', 'Instalador Sanitarista', 'Albañilería general'
]

# ==========================================
# 1. PADRÓN OFICIAL CPAU (ARQUITECTOS)
# ==========================================
cant_cpau = 1500
datos_cpau = []
nombres_usados = set() # Lo creamos acá para que arquitectos y obreros compartan el control

for _ in range(cant_cpau):
    
    # 1. Generamos el nombre asegurando que no exista en el set
    while True:
        nombre_candidato = f"{fake.first_name()} {fake.last_name()}"
        if nombre_candidato not in nombres_usados:
            nombres_usados.add(nombre_candidato)
            break # Salimos del while en cuanto encontramos uno nuevo
            
    # 2. Guardamos los datos usando la variable 'nombre_candidato'
    datos_cpau.append({
        'matricula_cpau': fake.unique.random_number(digits=5, fix_len=True),
        'nombre_apellido': nombre_candidato,
        'celular': f"+54911{random.randint(10000000, 99999999)}",
        'estado_matricula_activo': random.choices([True, False], weights=[0.95, 0.05], k=1)[0],
        'fecha_matriculacion': fake.date_between(start_date='-25y', end_date='today').strftime('%Y-%m-%d')
    })
df_cpau = pl.DataFrame(datos_cpau)

# ==========================================
# 2. PADRÓN OFICIAL IERIC (OBREROS)
# ==========================================
cant_ieric = 5000
datos_ieric = []
cuils_usados = set()

for _ in range(cant_ieric):
    while True:
        cuil = int(f"{random.choice([20,23,27])}{random.randint(10000000, 99999999)}")
        if cuil not in cuils_usados:
            cuils_usados.add(cuil)
            break
            
    # --- ACÁ REPETÍS LA VALIDACIÓN DEL NOMBRE ---
    while True:
        nombre_candidato = f"{fake.first_name()} {fake.last_name()}"
        if nombre_candidato not in nombres_usados:
            nombres_usados.add(nombre_candidato)
            break
            
    datos_ieric.append({
        'cuil': cuil,
        'nombre_apellido': nombre_candidato, # <--- Usás la variable validada
        'celular': f"+54911{random.randint(10000000, 99999999)}",
        'edad': random.randint(18, 65),
        'especialidad_uocra': random.choice(especialidades_demandadas),
        'tarjeta_soyconstructor_activa': random.choices([True, False], weights=[0.85, 0.15], k=1)[0],
        'zona_residencia': random.choice(zonas_permitidas)
    })
df_ieric = pl.DataFrame(datos_ieric)

# ==========================================
# 3. USUARIOS DE LA APP
# ==========================================
cpau_legales = df_cpau.filter(pl.col('estado_matricula_activo') == True).sample(n=200, seed=123)
ieric_legales = df_ieric.filter(pl.col('tarjeta_soyconstructor_activa') == True).sample(n=1000, seed=123)

datos_usuarios = []
id_contador = 1

# Esquema estricto de Polars en snake_case
esquema_usuarios = {
    'id_usuario': pl.Int64,
    'nombre_apellido': pl.Utf8,
    'celular': pl.Utf8,
    'rol': pl.Utf8,
    'matricula_cpau': pl.Int64, # Permite None nativamente
    'cuil_ieric': pl.Int64,     # Permite None nativamente
    'email': pl.Utf8,
    'ultima_latitud': pl.Float64,
    'ultima_longitud': pl.Float64
}

# Arquitectos
for row in cpau_legales.iter_rows(named=True):
    datos_usuarios.append({
        'id_usuario': id_contador,
        'nombre_apellido': row['nombre_apellido'],
        'celular': row['celular'],
        'rol': 'Arquitecto',
        'matricula_cpau': row['matricula_cpau'],
        'cuil_ieric': None, 
        'email': fake.unique.email(),
        'ultima_latitud': round(random.uniform(-34.7000, -34.5000), 6),
        'ultima_longitud': round(random.uniform(-58.5500, -58.3000), 6)
    })
    id_contador += 1

# Obreros
for row in ieric_legales.iter_rows(named=True):
    datos_usuarios.append({
        'id_usuario': id_contador,
        'nombre_apellido': row['nombre_apellido'],
        'celular': row['celular'],
        'rol': 'Obrero',
        'matricula_cpau': None,
        'cuil_ieric': row['cuil'],
        'email': fake.unique.email(),
        'ultima_latitud': round(random.uniform(-34.7000, -34.5000), 6),
        'ultima_longitud': round(random.uniform(-58.5500, -58.3000), 6)
    })
    id_contador += 1

df_usuarios = pl.DataFrame(datos_usuarios, schema=esquema_usuarios)

# ==========================================
# 4. CONTRATACIONES (Tabla Intermedia)
# ==========================================
ids_arquitectos = df_usuarios.filter(pl.col('rol') == 'Arquitecto')['id_usuario'].to_list()
ids_obreros = df_usuarios.filter(pl.col('rol') == 'Obrero')['id_usuario'].to_list()

datos_contratos = []
estados_obra = ['Pendiente', 'Aceptada', 'Rechazada', 'En Curso', 'Finalizada', 'Cancelada']
# Pesos para que haya más finalizadas (y así tener muchas reseñas)
pesos_estados = [0.10, 0.05, 0.05, 0.15, 0.60, 0.05] 

cant_contratos = 800
for i in range(1, cant_contratos + 1):
    fecha_inicio_obj = fake.date_time_between(start_date='-2y', end_date='-1m')
    estado = random.choices(estados_obra, weights=pesos_estados, k=1)[0]

    # Lógica estricta de fechas según el estado
    if estado == 'Finalizada':
        duracion = timedelta(days=random.randint(5, 120))
        fecha_fin_obj = fecha_inicio_obj + duracion
        fecha_inicio_str = fecha_inicio_obj.strftime('%Y-%m-%d %H:%M:%S')
        fecha_fin_str = fecha_fin_obj.strftime('%Y-%m-%d %H:%M:%S')
    elif estado == 'En Curso':
        fecha_inicio_str = fecha_inicio_obj.strftime('%Y-%m-%d %H:%M:%S')
        fecha_fin_str = None
    else:
        # Pendiente, Aceptada, Rechazada, Cancelada
        fecha_inicio_str = None
        fecha_fin_str = None

    datos_contratos.append({
        'id_contrato': i,
        'id_arquitecto': random.choice(ids_arquitectos),
        'id_obrero': random.choice(ids_obreros),
        'fecha_inicio': fecha_inicio_str,
        'fecha_fin': fecha_fin_str,
        'estado_obra': estado
    })

df_contrataciones = pl.DataFrame(datos_contratos)

# ==========================================
# 5. RESEÑAS (Vinculadas a Contratos Finalizados)
# ==========================================
contratos_finalizados = df_contrataciones.filter(pl.col('estado_obra') == 'Finalizada')['id_contrato'].to_list()
contratos_con_resena = random.sample(contratos_finalizados, int(len(contratos_finalizados) * 0.8))

datos_resenas = []
comentarios_positivos = ["Excelente predisposición.", "Muy prolijo y puntual.", "Conoce muy bien el oficio, 100% recomendable.", "Cumplió con los plazos de obra."]
comentarios_regulares = ["Buen trabajo, pero llegó tarde un par de días.", "Trabajo aceptable, faltó un poco de limpieza.", "Correcto, sin destacar."]
comentarios_negativos = ["Abandonó la obra a la mitad.", "Mucha desprolijidad, no respeta planos.", "Impuntual crónico."]

for idx, id_contrato in enumerate(contratos_con_resena, start=1):
    estrellas = random.choices([5, 4, 3, 2, 1], weights=[0.4, 0.3, 0.15, 0.1, 0.05], k=1)[0]
    
    if estrellas >= 4:
        comentario = random.choice(comentarios_positivos)
    elif estrellas == 3:
        comentario = random.choice(comentarios_regulares)
    else:
        comentario = random.choice(comentarios_negativos)

    datos_resenas.append({
        'id_resena': idx,
        'id_contrato': id_contrato,
        'calificacion_estrellas': estrellas,
        'comentario_texto': comentario,
        'fecha_resena': fake.date_between(start_date='-1m', end_date='today').strftime('%Y-%m-%d')
    })
df_resenas = pl.DataFrame(datos_resenas)

# ==========================================
# PERSISTENCIA EN SQLITE3
# ==========================================
print("Escribiendo en bases de datos SQLite...")

# --- 1. BASE CPAU ---
conn_cpau = sqlite3.connect('cpau.db')
cursor_cpau = conn_cpau.cursor()
cursor_cpau.execute("""
    CREATE TABLE cpau (
        matricula_cpau INTEGER PRIMARY KEY,
        nombre_apellido TEXT,
        celular TEXT,
        estado_matricula_activo BOOLEAN,
        fecha_matriculacion DATE
    )
""")
cursor_cpau.executemany("INSERT INTO cpau VALUES (?, ?, ?, ?, ?)", df_cpau.iter_rows())
conn_cpau.commit()
conn_cpau.close()

# --- 2. BASE IERIC ---
conn_ieric = sqlite3.connect('ieric.db')
cursor_ieric = conn_ieric.cursor()
cursor_ieric.execute("""
    CREATE TABLE ieric (
        cuil INTEGER PRIMARY KEY,
        nombre_apellido TEXT,
        celular TEXT,
        edad INTEGER,
        especialidad_uocra TEXT,
        tarjeta_soyconstructor_activa BOOLEAN,
        zona_residencia TEXT
    )
""")
cursor_ieric.executemany("INSERT INTO ieric VALUES (?, ?, ?, ?, ?, ?, ?)", df_ieric.iter_rows())
conn_ieric.commit()
conn_ieric.close()

# --- 3. BASE APP (Ecosistema Transaccional) ---
conn_app = sqlite3.connect('app.db')
cursor_app = conn_app.cursor()

# Habilitar claves foráneas obligatoriamente
cursor_app.execute("PRAGMA foreign_keys = ON;")

cursor_app.execute("""
    CREATE TABLE usuarios_app (
        id_usuario INTEGER PRIMARY KEY,
        nombre_apellido TEXT,
        celular TEXT,
        rol TEXT CHECK (rol IN ('Arquitecto', 'Obrero')),
        matricula_cpau INTEGER NULL,
        cuil_ieric INTEGER NULL,
        email TEXT UNIQUE,
        ultima_latitud REAL,
        ultima_longitud REAL
    )
""")
cursor_app.executemany("INSERT INTO usuarios_app VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)", df_usuarios.iter_rows())

cursor_app.execute("""
    CREATE TABLE contrataciones (
        id_contrato INTEGER PRIMARY KEY,
        id_arquitecto INTEGER,
        id_obrero INTEGER,
        fecha_inicio TIMESTAMP,
        fecha_fin TIMESTAMP NULL,
        estado_obra TEXT CHECK (estado_obra IN ('Pendiente', 'Aceptada', 'Rechazada', 'En Curso', 'Finalizada', 'Cancelada')),
        FOREIGN KEY (id_arquitecto) REFERENCES usuarios_app(id_usuario),
        FOREIGN KEY (id_obrero) REFERENCES usuarios_app(id_usuario)
    )
""")
cursor_app.executemany("INSERT INTO contrataciones VALUES (?, ?, ?, ?, ?, ?)", df_contrataciones.iter_rows())

cursor_app.execute("""
    CREATE TABLE resenas (
        id_resena INTEGER PRIMARY KEY,
        id_contrato INTEGER UNIQUE,
        calificacion_estrellas INTEGER CHECK (calificacion_estrellas BETWEEN 1 AND 5),
        comentario_texto TEXT,
        fecha_resena DATE,
        FOREIGN KEY (id_contrato) REFERENCES contrataciones(id_contrato)
    )
""")
cursor_app.executemany("INSERT INTO resenas VALUES (?, ?, ?, ?, ?)", df_resenas.iter_rows())

conn_app.commit()
conn_app.close()

print("\n¡Bases de datos generadas con éxito!")
print(f"- Usuarios de la App: {df_usuarios.height}")
print(f"- Contratos generados: {df_contrataciones.height}")
print(f"- Reseñas generadas: {df_resenas.height}")
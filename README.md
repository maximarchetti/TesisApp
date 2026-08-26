# Plataforma logística con IA

**Trabajo Final Integrador --- Tecnicatura Superior en Ciencia de Datos
e Inteligencia Artificial**\
**Autor:** Maximiliano Marchetti

## Descripción

Demo funcional de una plataforma orientada a optimizar la contratación
de trabajadores especializados para obras de construcción mediante un
sistema de recomendación híbrido que combina procesamiento de lenguaje
natural, reputación y proximidad geográfica.

El sistema permite simular el ciclo completo de asignación de personal,
incluyendo:

-   búsqueda inteligente de trabajadores según especialidad, reputación
    y cercanía geográfica;
-   envío, aceptación, rechazo y cancelación de ofertas laborales;
-   inicio y finalización de obras;
-   registro de reseñas y calificaciones;
-   actualización de la ubicación de los trabajadores;
-   visualización geográfica de resultados mediante mapas.

El proyecto fue desarrollado como una **demo funcional de alcance
académico**, no como una plataforma desplegable para producción.

## Problema abordado

La conformación de cuadrillas eventuales frente a urgencias puede
dificultar la coordinación de una obra. Cuando surge la necesidad de
incorporar personal de manera inmediata, la dependencia de
recomendaciones informales puede generar demoras y obliga a los
profesionales a asumir riesgos al contratar trabajadores sin referencias
verificables.

La propuesta busca agilizar la búsqueda y ofrecer un mecanismo de
recomendación que combine compatibilidad con la especialidad solicitada,
reputación y cercanía geográfica.

## Recolección y generación de datos

Los datos utilizados por la aplicación son **sintéticos** y fueron
generados mediante la librería [Faker](https://faker.readthedocs.io/)
con fines académicos.

La estructura de los datos se diseñó tomando como referencia información
y campos del ámbito profesional, sin utilizar datos personales reales ni
realizar scraping de bases institucionales.

El proyecto utiliza tres bases de datos SQLite independientes:

-   `app.db`: usuarios, contrataciones y reseñas de la aplicación.
-   `cpau.db`: datos sintéticos que simulan un padrón de arquitectos.
-   `ieric.db`: datos sintéticos que simulan registros de trabajadores y
    sus especialidades.

La aplicación realiza los cruces lógicos entre las bases mediante
consultas y procesamiento de datos. SQLite no permite establecer Foreign
Keys físicas entre archivos `.db` independientes, por lo que las
referencias entre sistemas se validan mediante consultas y claves
lógicas.

### Especialidades modeladas

La versión inicial trabaja con cinco especialidades:

1.  Instalador Sanitarista
2.  Electricista
3.  Gasista
4.  Albañilería General
5.  Yesero

## Motor de recomendación

El recomendador combina tres componentes principales:

### 1. Procesamiento de texto

Se utiliza **TF-IDF (`TfidfVectorizer`)** para representar el texto de
la especialidad solicitada y las especialidades de los trabajadores.

El diccionario de sinónimos permite normalizar expresiones relacionadas.
Por ejemplo, términos como `plomero` o `sanitarista` se mapean a
`instalador sanitarista`.

La similitud entre la búsqueda y los perfiles se calcula mediante
**similitud del coseno**.

### 2. Reputación

Se calcula el promedio de las calificaciones históricas de cada
trabajador. Los trabajadores sin reseñas reciben un valor inicial de
referencia para permitir su participación en las recomendaciones.

### 3. Distancia geográfica

La distancia entre la ubicación de la obra y la ubicación registrada del
trabajador se calcula mediante una fórmula de distancia geográfica
basada en coordenadas de latitud y longitud.

La geocodificación de ubicaciones puede utilizar:

-   **Georef Argentina API**
-   **Nominatim**, mediante `Geopy`

### 4. Suma ponderada

Los tres componentes se normalizan y combinan mediante un **Weighted Sum
Model / Scoring Model**.

La estrategia seleccionada por el arquitecto determina la importancia
relativa de:

-   compatibilidad de especialidad;
-   reputación;
-   cercanía.

El resultado se utiliza para ordenar los trabajadores y mostrar primero
los candidatos con mayor puntuación.

> La cantidad de trabajos realizados se muestra en la interfaz para que
> el arquitecto pueda considerarla, pero **no forma parte de la
> puntuación ponderada**. Esta decisión busca evitar penalizar a
> trabajadores con menor trayectoria o recién incorporados a la
> plataforma.

## Geolocalización

La plataforma contempla distintas modalidades según el rol.

### Arquitectos

El arquitecto puede:

-   ingresar manualmente la dirección o zona de la obra; o
-   utilizar la opción de ubicación actual durante la búsqueda.

### Obreros

La plataforma contempla que el trabajador comparta su ubicación para
permitir la búsqueda por cercanía.

En esta versión académica, la captura GPS del trabajador está **simulada
mediante coordenadas estáticas**. La integración con la API de
geolocalización de dispositivos móviles queda como una mejora futura.

## Rendimiento

El backend implementa un mecanismo de caché en memoria para el motor de
recomendación.

Los datos utilizados por el motor y la matriz TF-IDF se cargan al
iniciar la API y se reutilizan en las búsquedas posteriores.

Cuando se actualiza la ubicación de un trabajador o se registra una
nueva reseña, el motor puede reconstruirse mediante tareas en segundo
plano (`BackgroundTasks` de FastAPI).

## Flujo funcional

El sistema permite simular:

1.  selección de un usuario de prueba;
2.  búsqueda de trabajadores;
3.  selección de una estrategia de recomendación;
4.  visualización de candidatos y ubicación en mapa;
5.  envío de una oferta;
6.  aceptación o rechazo por parte del trabajador;
7.  cancelación de ofertas;
8.  inicio de la obra luego de una aceptación;
9.  finalización de la obra;
10. registro de una reseña y calificación.

## Tecnologías utilizadas

### Frontend

-   Python
-   Streamlit
-   Folium
-   Streamlit-Folium

### Backend / API

-   Python
-   FastAPI
-   Uvicorn
-   Pydantic

### Datos

-   SQLite
-   Pandas
-   Polars
-   Faker

### Inteligencia Artificial / recomendación

-   Scikit-learn
-   TF-IDF
-   Similitud del Coseno
-   MinMaxScaler
-   Weighted Sum Model / Scoring Model

### Geolocalización

-   Georef Argentina API
-   Geopy
-   Nominatim

### Comunicación

-   Requests

## Estructura del proyecto

``` text
TesisApp/
├── app.db
├── cpau.db
├── ieric.db
├── app_frontend.py
├── main.py
└── bbdd_5_de_junio.py
```

### Descripción de los archivos

  -----------------------------------------------------------------------
  Archivo                             Función
  ----------------------------------- -----------------------------------
  `main.py`                           Backend/API desarrollado con
                                      FastAPI y motor de recomendación.

  `app_frontend.py`                   Interfaz de usuario desarrollada
                                      con Streamlit.

  `bbdd_5_de_junio.py`                Script para regenerar las tres
                                      bases de datos sintéticas.

  `app.db`                            Base SQLite sintética de la
                                      aplicación.

  `cpau.db`                           Base SQLite sintética que simula
                                      datos del CPAU.

  `ieric.db`                          Base SQLite sintética que simula
                                      datos del IERIC.
  -----------------------------------------------------------------------

## Instalación

Se requiere Python 3.12 o compatible con las dependencias utilizadas.

Instalar las dependencias:

``` bash
python -m pip install -r requirements.txt
```

## Ejecución

El proyecto utiliza dos procesos: backend y frontend.

### 1. Ejecutar el backend

Desde la carpeta `TesisApp`:

``` bash
python -m uvicorn main:app --reload
```

El backend quedará disponible en:

``` text
http://127.0.0.1:8000
```

### 2. Ejecutar el frontend

En otra terminal, desde la misma carpeta:

``` bash
python -m streamlit run app_frontend.py
```

Streamlit abrirá la interfaz en el navegador.

### Bases de datos

Las bases de datos se entregan **generadas y listas para utilizar**.

Normalmente no es necesario ejecutar `bbdd_5_de_junio.py`.

El script se incluye únicamente para regenerar `app.db`, `cpau.db` e
`ieric.db` en caso de pérdida o corrupción de los archivos.

> La ejecución del script elimina y vuelve a generar las tres bases de
> datos existentes en la carpeta.

## Limitaciones de esta versión

Esta versión corresponde a una demo funcional desarrollada dentro del
alcance académico del Trabajo Final Integrador.

Entre sus principales limitaciones se encuentran:

-   utilización de datos sintéticos;
-   cinco especialidades modeladas;
-   componente NLP limitado por la cantidad de categorías y vocabulario
    disponible;
-   ausencia de una evaluación experimental completa del recomendador
    mediante métricas como Precision, Recall o NDCG;
-   geolocalización GPS del trabajador simulada mediante coordenadas
    estáticas;
-   frontend implementado con Streamlit para facilitar el desarrollo de
    la demo;
-   ausencia de autenticación y autorización de usuarios;
-   ausencia de integración con bases institucionales oficiales en
    tiempo real;
-   ausencia de infraestructura de producción y pruebas de escalabilidad
    con múltiples usuarios simultáneos.

## Mejoras futuras

Entre las mejoras previstas se encuentran:

-   incorporar los alcances profesionales del IERIC como texto adicional
    de los perfiles para ampliar la capacidad del componente NLP;
-   desarrollar notebooks de análisis exploratorio y evaluación del
    recomendador;
-   comparar el modelo híbrido con baselines simples, como ranking por
    estrellas o por distancia;
-   incorporar métricas de evaluación como Precision@K, Recall@K y
    NDCG@K;
-   implementar geolocalización GPS real para los trabajadores;
-   mantener el ingreso manual de la ubicación de la obra para los
    arquitectos y sumar la obtención de ubicación actual como
    alternativa durante la búsqueda;
-   reemplazar o ampliar la interfaz Streamlit mediante una aplicación
    web o móvil;
-   implementar autenticación y autorización;
-   integrar servicios institucionales oficiales cuando corresponda;
-   evaluar escalabilidad y rendimiento en infraestructura de
    producción.

## Consideraciones sobre privacidad

Las bases de datos incluidas en el repositorio contienen **datos
sintéticos generados artificialmente**.

No se incluyen bases institucionales reales ni datos personales reales.
La utilización de estructuras de datos de referencia tuvo como objetivo
aportar realismo al modelo sin depender de scraping ni publicar
información personal.

## Autor

**Maximiliano Marchetti**

Trabajo Final Integrador\
Tecnicatura Superior en Ciencia de Datos e Inteligencia Artificial\
IFTS N.º 33

## Licencia

Este repositorio corresponde a un proyecto académico. No se establece
una licencia de software para reutilización comercial en esta versión.

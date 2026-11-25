# GUIOS EVAL

Sistema web para evaluar si un software es apropiado para ser adoptado por una organización.
Es la **versión nueva de GUIOS PRO FLOSS**, la herramienta prototipo de la tesis de Víctor Rea
sobre la guía GUIOS para la adopción de software libre, y fue desarrollada por el **Grupo 5 de
Procesos y Calidad de Software (UNEMI, 2026)** a partir del diseño preliminar del parcial I.

## Qué corrige y qué agrega respecto de GUIOS PRO

| Problema en GUIOS PRO (2022) | Solución en GUIOS EVAL |
|---|---|
| Todos los valores arrancaban en 1, por eso la ponderación salía 1 y casi todo terminaba en Debilidad o Amenaza | Lo no evaluado queda como *sin evaluar* y no cuenta como "No cumple" |
| Importancia relativa calculada con un promedio | Tabla de la Figura 5.10 de la tesis (`engine.TABLA_IR`) |
| Errores de código: `a, b, c = False`, formato de la ponderación, recomendaciones A y C cruzadas | Motor de cálculo reescrito y probado (`pruebas/`) |
| Importancias sugeridas distintas a la Tabla 5.3 | Catálogo inicial idéntico a las Tablas 5.1, 5.3 y 5.4 (18 factores, 61 subfactores) |
| Factores y subfactores fijos en archivos CSV | Catálogo versionado: agregar, editar, desactivar y eliminar factores y subfactores |
| Sin inicio de sesión ni historial | Usuarios con contraseña, 6 roles, historial y auditoría de cada acción |
| Un solo decisor | Varios decisores con consenso (mediana de la ID, media de la PS) y aviso de desacuerdo |
| Ingreso de subfactores lento (3 clics por factor) | Un clic por subfactor con guardado automático y progreso visible |
| Recomendación genérica | Recomendación A/B/C con los factores, subfactores y acciones que la causan, y explicación paso a paso del cálculo |

Además: flujo de estados (borrador, en curso, en revisión, cerrada, cancelada), decisión humana
con comentario obligatorio, reapertura como revisión nueva (RF-15), comparación de evaluaciones
(RF-10), informe imprimible en PDF, exportación CSV y umbral FODA configurable (RF-14).

## Importancia sugerida calculada con la literatura 2020-2025

En GUIOS PRO la importancia sugerida (IS) de cada factor estaba fija, copiada de la Tabla 5.3 de la tesis (corpus 2008-2019, conteo manual). GUIOS EVAL agrega el módulo **Calibración bibliográfica** (menú Administración), que repite ese cálculo de forma automática:

1. Corpus: estudios de OpenAlex cuyo título trata de software libre (`"open source" OR "free software" OR "FLOSS" OR "FOSS" OR "libre"`), cuyo resumen habla de adopción o migración y que pertenecen a los subcampos de sistemas de información y software. Ventana configurable, por defecto 2020-2025 (336 estudios el 25/11/2026).
2. Citas del factor (c): estudios del corpus que mencionan los términos del factor (editables).
3. r = c / n, con n = número de subfactores (Ecuación 5.1).
4. IL = cuartil de r entre todos los factores (Ecuación 5.2, percentil lineal).
5. IS = Figura 5.10 (IE, IL), con IE = 3 por defecto y editable por factor.

Validación: con los datos de la Tabla 5.3 el motor reproduce las 18 IL y las 18 IS de la tesis (`test_reproduce_tabla_5_3`).
La calibración se aplica creando una versión nueva del catálogo (v3 en los datos de ejemplo); las evaluaciones anteriores conservan su copia. Sin internet se usa la corrida guardada en `datos/openalex_2020_2025.json`.

## Asistente de IA, sensibilidad y exportación (versión 2.1)

- **Asistente de IA (RF-13, optativo).** En el paso de subfactores, *Sugerir con IA* propone una respuesta por subfactor con justificación, porcentaje de confianza y fuentes (solo DOI reales de la calibración en OpenAlex; si la IA inventa una referencia, se descarta). El evaluador acepta o descarta cada sugerencia; lo aceptado queda marcado como «IA» y registrado en auditoría. En el resultado, la IA redacta el resumen ejecutivo y un plan de acción con entregables, plazos y responsables; el sistema verifica que el texto no contradiga la recomendación calculada. La recomendación A, B o C siempre la calcula el motor GUIOS.
- **Proveedores con respaldo automático:** Groq (gpt-oss-120b) → Gemini → IA local con Ollama (sin internet) → motor de reglas sin IA. El modo se elige en Configuración.
- **Claves:** se leen del archivo `claves_guios.env`, en la raíz del proyecto (junto a `LEEME.txt`), que crea `instalar.bat` con este formato:
  ```
  GROQ_API_KEY=...
  GEMINI_API_KEY=...
  GMAIL_USER=...            (opcional, para enviar códigos)
  GMAIL_APP_PASSWORD=...
  ```
  El archivo está en `.gitignore`, pero si subes el proyecto arrastrando archivos en la web de GitHub, **no lo incluyas**.
- **IA local sin internet:** la instala `instalar.bat` (Ollama y el modelo qwen2.5:3b, unos 2 GB); si ya están, no los reinstala.
- **Análisis de sensibilidad:** en el resultado, el sistema simula cada respuesta posible y muestra el camino mínimo para mejorar la recomendación, las respuestas que la empeorarían y los factores cerca del umbral.
- **Acciones rápidas:** marcar todos los subfactores pendientes de un factor con un valor.
- **Exportación:** informe PDF directo, Excel con colores (resumen, factores, matriz FODA, subfactores con su origen, plan y sensibilidad) y CSV.
- **Calibración:** vista previa de la consulta y botón *Probar consulta* por factor.

## Cómo ejecutarlo

Requisito: Python 3.10 o superior.

**Windows:** la primera vez, doble clic en `instalar.bat` (librerías, IA local y verificación). Después, doble clic en `iniciar.bat` para abrir el sistema. Para volver a los datos iniciales, cierra el sistema y borra `datos/guios_eval.db`: se crea de nuevo con el catálogo de la tesis y los usuarios de prueba.

**Manual:**
```
pip install -r requirements.txt
python -m guios
```
Abrir http://127.0.0.1:5000

## Para tus compañeros (sin tus claves)

1. Descargar el repositorio (botón **Code → Download ZIP**) y descomprimirlo.
2. Instalar Python 3.10 o superior marcando **Add Python to PATH**.
3. Doble clic en `instalar.bat`. En el paso 2 elige cómo usar la IA:
   1. *Ya tengo mis claves*: pide la de Groq y la de Gemini, una por una, y las valida.
   2. *Quiero crearlas gratis*: muestra la página oficial de Groq (console.groq.com/keys) y de Gemini (aistudio.google.com/apikey), las abre en el navegador y luego pide cada clave.
   3. *No quiero claves*: instala la IA local sin internet.
4. Doble clic en `iniciar.bat`.

Cada persona usa sus propias claves; no se comparten. Sin claves ni IA local, el sistema funciona igual con el motor de reglas.

## Usuarios de prueba

Contraseña de todos: `guios2026`

| Correo | Rol |
|---|---|
| admin@guios.edu.ec | Administrador de plataforma |
| catalogo@guios.edu.ec | Administrador de catálogo |
| lider@guios.edu.ec | Líder de evaluación |
| evaluador@guios.edu.ec, evaluador2@guios.edu.ec | Evaluadores (decisores) |
| revisor@guios.edu.ec | Revisor / decisor final |
| auditor@guios.edu.ec | Auditor / lector |

## Estructura

```
iniciar.bat            abre el sistema (uso diario)
instalar.bat           librerías, IA local y verificación (primera vez)
requirements.txt       librerías de Python
guios/                 código del sistema
  app.py               servidor web: pantallas, permisos por rol y flujo de estados
  motor.py             cálculos de la guía GUIOS (IR, PM, FODA, recomendación, IL, IS, sensibilidad)
  base_datos.py        esquema SQLite, datos iniciales y auditoría
  literatura.py        calibración bibliográfica con OpenAlex
  ia.py                asistente de IA (Groq, Gemini, Ollama)
  exportar.py          informe PDF y Excel
  templates/  static/  pantallas, estilos, JavaScript y fuentes
datos/                 catálogo de la tesis, corrida de OpenAlex 2020-2025 y base guios_eval.db
pruebas/               pruebas automatizadas (test_guios.py) y verificar.py
```

## Pruebas

```
python -m pytest -q pruebas        (17 pruebas)
python pruebas/verificar.py        (verificación completa, también la hace instalar.bat)
```

## Referencia

Rea, V. (s. f.). *GUIOSPRO_FLOSS* [Repositorio de código fuente]. GitHub. https://github.com/victorreadoctorado/GUIOSPRO_FLOSS

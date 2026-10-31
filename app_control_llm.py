import streamlit as st
import pandas as pd
import random
import math
import time

st.set_page_config(page_title="TP Teoría de Control - UTN", layout="wide")

# --- MENÚ LATERAL PARA NAVEGAR LA EVOLUCIÓN DEL TP ---
st.sidebar.title("📂 Evolución del TP")
pagina = st.sidebar.radio(
    "Seleccionar Entrega / Avance:",
    [
        "🟢 Semana 1: Instrumentación y Lazo Abierto",
        "🟡 Semana 2: Identificación (Ensayo Escalón)",
        "🟠 Semana 3: Diseño PID y Lazo Cerrado (Próximo)"
    ]
)

# ==============================================================================
# PÁGINA 1: SEMANA 1 (LAZO ABIERTO MANUAL)
# ==============================================================================
if pagina == "🟢 Semana 1: Instrumentación y Lazo Abierto":
    st.title("🟢 Avance 1: Planta de Inferencia LLM en Lazo Abierto")
   
    st.markdown("""
    **Objetivo (Fases 1 y 2):** 
    Verificar en **Lazo Abierto** cómo responde nuestra **Variable Controlada** (Latencia en ms) 
    cuando modificamos manualmente nuestra **Variable Manipulada** (Límite de CPU en Docker).
    """)

    col1, col2 = st.columns(2)
    with col1:
        st.markdown("### 🎛️ Actuador (Docker API)")
        cpu_cores = st.slider("Límite de CPU asignado (--cpus)", min_value=0.5, max_value=4.0, value=2.0, step=0.5)

    with col2:
        st.markdown("### ⚡ Entrada / Perturbación")
        tokens_prompt = st.slider("Longitud del Prompt (Tokens)", min_value=100, max_value=1000, value=300, step=100)

    if "mediciones" not in st.session_state:
        st.session_state.mediciones = []

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button("Enviar Prompt y Medir Latencia (Sensor)"):
            latencia_base = (tokens_prompt / cpu_cores) * 1.2
            ruido = random.uniform(-10, 10)
            latencia_medida = round(latencia_base + ruido, 1)
            
            st.session_state.mediciones.append({
                "CPU_Asignada": cpu_cores,
                "Tokens_Prompt": tokens_prompt,
                "Latencia_ms": latencia_medida
            })
    with col_btn2:
        if st.button("Borrar mediciones"):
            st.session_state.mediciones = []

    if len(st.session_state.mediciones) > 0:
        df = pd.DataFrame(st.session_state.mediciones)
        ultima_latencia = df.iloc[-1]["Latencia_ms"]
        
        st.metric(label="⏱️ Última Latencia Medida (Variable Controlada)", value=f"{ultima_latencia} ms")
        st.markdown("#### Gráfico en tiempo real (Muestras vs Latencia en ms)")
        st.line_chart(df["Latencia_ms"])
        st.markdown("#### Tabla de Registro del Sensor")
        st.dataframe(df)
    else:
        st.info("Presiona el botón 'Enviar Prompt y Medir Latencia' para tomar la primera muestra del sensor.")


# ==============================================================================
# PÁGINA 2: SEMANA 2 (ENSAYO ESCALÓN AUTOMÁTICO EN VIVO)
# ==============================================================================
elif pagina == "🟡 Semana 2: Identificación (Ensayo Escalón)":
    st.title("🟡 Avance 2: Identificación del Sistema (Ensayo de Entrada Escalón)")
    
    st.markdown("""
    **Objetivo (Fase 3 - Modelado de Caja Negra):** 
    Aplicar automáticamente una **Entrada Escalón** reduciendo de golpe el límite de CPU del **100% (2.0 Cores) al 50% (1.0 Core)** en $t = 5\\text{ s}$ mientras se inyectan peticiones constantes. 
    Analizamos la curva de reacción para obtener la **Ganancia Estática ($K$)** y la **Constante de Tiempo ($\\tau$ al 63.2%)** de nuestra Función de Transferencia empírica:
    
    $$G(s) = \\frac{K}{\\tau s + 1}$$
    """)

    # Parámetros del ensayo escalón
    tokens_fijos = 300
    cpu_inicial = 2.0
    cpu_final = 1.0
    t_escalon = 5
    tau_planta = 3.0
    lat_inicial = (tokens_fijos / cpu_inicial) * 1.2  # 180 ms
    lat_final = (tokens_fijos / cpu_final) * 1.2      # 360 ms
    delta_y = lat_final - lat_inicial                 # +180 ms
    delta_u = cpu_final - cpu_inicial                 # -1.0 Core
    k_ganancia = delta_y / delta_u                    # -180 ms/Core
    latencia_al_632 = lat_inicial + 0.632 * delta_y   # 293.8 ms

    # --- 1. MÉTRICAS IDENTIFICADAS SIEMPRE VISIBLES ---
    st.markdown("### 📐 Parámetros Identificados de la Planta")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Salto de Entrada (ΔU)", f"{delta_u} Cores", "De 2.0 a 1.0 (50%)")
    c2.metric("Salto de Salida (ΔY)", f"+{delta_y} ms", "De 180 a 360 ms")
    c3.metric("Ganancia Estática (K)", f"{k_ganancia} ms/Core", "K = ΔY / ΔU")
    c4.metric("Constante de Tiempo (τ)", f"{tau_planta} s", f"Al 63.2% ({latencia_al_632:.1f} ms)")

    st.success(
        f"**Función de Transferencia Empírica Obtenida:**  "
        f"$$G(s) = \\frac{{{k_ganancia}}}{{{tau_planta}s + 1}}$$  "
        f"*(Tiempo de establecimiento estimado $4\\tau = {4*tau_planta}\\text{{ s}}$)*"
    )

    # --- 2. CONTENEDORES PARA ANIMACIÓN AUTOMÁTICA ---
    st.markdown("#### 📈 Curva de Reacción en Vivo: Latencia Medida vs. Modelo de 1er Orden (ms)")
    espacio_grafico_latencia = st.empty()

    st.markdown("#### 🎛️ Escalón Aplicado en el Actuador: Límite de CPU (Cores)")
    espacio_grafico_cpu = st.empty()

    # Si todavía no se ejecutó o si queremos que se anime solo al entrar
    if "escalon_completado" not in st.session_state:
        st.session_state.escalon_completado = False
        st.session_state.datos_escalon = []

    if st.button("🔄 Repetir Animación en Vivo"):
        st.session_state.escalon_completado = False
        st.session_state.datos_escalon = []

    # Ejecución automática punto a punto al abrir la pestaña
    if not st.session_state.escalon_completado:
        random.seed(42)
        registros_temp = []
        for t in range(26):
            if t < t_escalon:
                cpu_actual = cpu_inicial
                lat_teorica = lat_inicial
            else:
                cpu_actual = cpu_final
                tiempo_desde_escalon = t - t_escalon
                lat_teorica = lat_inicial + delta_y * (1 - math.exp(-tiempo_desde_escalon / tau_planta))
            
            ruido_sensor = random.uniform(-3.0, 3.0)
            registros_temp.append({
                "Tiempo_s": t,
                "CPU_Cores": cpu_actual,
                "Latencia_Modelo_1er_Orden_ms": round(lat_teorica, 1),
                "Latencia_Sensor_ms": round(lat_teorica + ruido_sensor, 1)
            })
            df_parcial = pd.DataFrame(registros_temp).set_index("Tiempo_s")
            espacio_grafico_latencia.line_chart(df_parcial[["Latencia_Sensor_ms", "Latencia_Modelo_1er_Orden_ms"]])
            espacio_grafico_cpu.line_chart(df_parcial[["CPU_Cores"]])
            time.sleep(0.12)  # Velocidad de la animación automática

        st.session_state.datos_escalon = registros_temp
        st.session_state.escalon_completado = True

    # Mostrar gráficos fijos una vez terminada la animación inicial
    df_esc = pd.DataFrame(st.session_state.datos_escalon)
    espacio_grafico_latencia.line_chart(df_esc.set_index("Tiempo_s")[["Latencia_Sensor_ms", "Latencia_Modelo_1er_Orden_ms"]])
    espacio_grafico_cpu.line_chart(df_esc.set_index("Tiempo_s")[["CPU_Cores"]])

    # --- 3. DESCARGA DE CSV Y TABLA ---
    col_csv, col_tabla = st.columns([1, 2])
    with col_csv:
        st.markdown("#### 💾 Exportar Datos")
        st.write("Descarga el registro del ensayo para procesarlo en Google Colab o MATLAB:")
        csv_bytes = df_esc.to_csv(index=False).encode("utf-8")
        st.download_button(
            label="📥 Descargar ensayo_escalon.csv",
            data=csv_bytes,
            file_name="ensayo_escalon.csv",
            mime="text/csv"
        )
    with col_tabla:
        st.markdown("#### 📋 Tabla de Datos Registrados (Tiempo vs Latencia)")
        st.dataframe(df_esc, height=220)


# ==============================================================================
# PÁGINA 3: SEMANA 3 (HOJA DE RUTA DE LO QUE VAMOS A HACER)
# ==============================================================================
elif pagina == "🟠 Semana 3: Diseño PID y Lazo Cerrado (Próximo)":
    st.title("🟠 Avance 3 (Próxima Etapa): Controlador PID Discreto y Cierre de Lazo")
   
    st.info("🚧 **Estado:** En desarrollo para la próxima iteración (Fases 4 y 5 del Plan de Acción).")

    st.markdown("""
    ### 🎯 ¿Qué vamos a implementar en esta etapa?
    Una vez identificada la Función de Transferencia empírica de nuestra planta en la Semana 2 ($G(s) = \\frac{-180}{3.0s + 1}$), cerraremos el lazo de control realimentando la medición del sensor para ajustar automáticamente los núcleos de CPU de Docker frente a perturbaciones.
    """)

    col_plan1, col_plan2 = st.columns(2)

    with col_plan1:
        st.markdown("""
        #### 1. Nodo Comparador y Señal de Error
        Incorporaremos un **Setpoint (Valor de Referencia)** deseado (ej. `200 ms` de latencia TTFT). En cada ciclo de muestreo calcularemos el error instantáneo:
        $$E(t) = Setpoint - Latencia\\_Actual$$
        
        #### 2. Ley de Control: Ecuación de Diferencias del PID Discreto
        Programaremos en Python las tres acciones correctivas sobre el contenedor:
        * **Acción Proporcional ($P$):** Reacciona de forma inmediata al error actual.
          $$P(t) = K_p \\cdot E(t)$$
        * **Acción Integral ($I$):** Acumula los errores pasados para eliminar el error en estado estacionario ($e_{ss} = 0$, pasando el sistema a **Tipo 1**).
          $$I(t) = K_i \\sum E(t) \\cdot \\Delta t$$
        * **Acción Derivativa ($D$):** Anticipa picos bruscos en la tendencia de la latencia para amortiguar oscilaciones.
          $$D(t) = K_d \\frac{E(t) - E(t-1)}{\\Delta t}$$
        """)

    with col_plan2:
        st.markdown("""
        #### 3. Diagrama en Bloques del Lazo Cerrado a Implementar
        ```text
        Setpoint (ms)     Error E(t)   +-----------------+  CPU (--cpus) +------------------+
        ---------------->(( + / - ))-->| Controlador PID |-------------->| Planta LLM       |---> Latencia
                             ^         | (Kp, Ki, Kd)    |               | (Contenedor)     |     Real (ms)
                             |         +-----------------+               +------------------+         |
                             |                                                                        |
                             |                     +----------------------------+                     |
                             +---------------------| Sensor Python (time / API) |<--------------------+
                                                   +----------------------------+
        ```
        
        #### 4. Pruebas de Perturbación y Sintonización (Tuning)
        * **Sintonización inicial:** Obtendremos los valores base de $K_p, K_i, K_d$ en Google Colab / MATLAB usando *Ziegler-Nichols* sobre el CSV exportado en la Semana 2.
        * **Inyección de Perturbaciones:** Simularemos ráfagas de tráfico concurrente y prompts de longitud variable para demostrar cómo el controlador sube automáticamente la cuota de CPU y estabiliza la latencia en el Setpoint.
        """)

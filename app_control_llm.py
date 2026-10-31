import streamlit as st
import pandas as pd
import random
import math

st.set_page_config(page_title="TP Teoría de Control - UTN", layout="wide")

# --- MENÚ LATERAL PARA NAVEGAR LA EVOLUCIÓN DEL TP ---
st.sidebar.title("📂 Evolución del TP")
st.sidebar.markdown("**Autores:** Boldrini Lucas y Bru Nicolás\n\n**Cátedra:** Teoría de Control - UTN")
pagina = st.sidebar.radio(
    "Seleccionar Entrega / Avance:",
    [
        "🟢 Semana 1: Instrumentación y Lazo Abierto",
        "🟡 Semana 2: Identificación (Ensayo Escalón)"
    ]
)

# ==============================================================================
# PÁGINA 1: SEMANA 1 (TU CÓDIGO ACTUAL DE LAZO ABIERTO)
# ==============================================================================
if pagina == "🟢 Semana 1: Instrumentación y Lazo Abierto":
    st.title("🟢 Avance 1: Planta de Inferencia LLM en Lazo Abierto")
    st.subheader("Teoría de Control - UTN | Boldrini Lucas y Bru Nicolás")

    st.markdown("""
    **Objetivo (Fases 1 y 2):** 
    Verificar en **Lazo Abierto** cómo responde nuestra **Variable Controlada** (Latencia en ms) 
    cuando modificamos manualmente nuestra **Variable Manipulada** (Límite de CPU en Docker).
    """)

    # --- 1. ACTUADOR (Variable Manipulada) y PERTURBACIÓN ---
    col1, col2 = st.columns(2)

    with col1:
        st.markdown("### 🎛️ Actuador (Docker API)")
        cpu_cores = st.slider("Límite de CPU asignado (--cpus)", min_value=0.5, max_value=4.0, value=2.0, step=0.5)

    with col2:
        st.markdown("### ⚡ Entrada / Perturbación")
        tokens_prompt = st.slider("Longitud del Prompt (Tokens)", min_value=100, max_value=1000, value=300, step=100)

    # --- 2. PLANTA Y SENSOR (Variable Controlada) ---
    if "mediciones" not in st.session_state:
        st.session_state.mediciones = []

    col_btn1, col_btn2 = st.columns([1, 4])
    with col_btn1:
        if st.button("Enviar Prompt y Medir Latencia (Sensor)"):
            # Fórmula simple de la planta: a menos CPU y más tokens, tarda más milisegundos
            latencia_base = (tokens_prompt / cpu_cores) * 1.2
            ruido = random.uniform(-10, 10)  # Pequeña variación natural del SO
            latencia_medida = round(latencia_base + ruido, 1)
            
            st.session_state.mediciones.append({
                "CPU_Asignada": cpu_cores,
                "Tokens_Prompt": tokens_prompt,
                "Latencia_ms": latencia_medida
            })
    with col_btn2:
        if st.button("Borrar mediciones"):
            st.session_state.mediciones = []

    # --- 3. VISUALIZACIÓN DE DATOS ---
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
# PÁGINA 2: SEMANA 2 (IDENTIFICACIÓN DEL SISTEMA - ENSAYO ESCALÓN)
# ==============================================================================
elif pagina == "🟡 Semana 2: Identificación (Ensayo Escalón)":
    st.title("🟡 Avance 2: Identificación del Sistema (Ensayo de Entrada Escalón)")
    st.subheader("Teoría de Control - UTN | Boldrini Lucas y Bru Nicolás")

    st.markdown("""
    **Objetivo (Fase 3 - Modelado de Caja Negra):** 
    Aplicar una **Entrada Escalón** reduciendo de golpe el límite de CPU del **100% (2.0 Cores) al 50% (1.0 Core)** de forma sostenida mientras inyectamos peticiones constantes. 
    Analizamos la curva exponencial de primer orden resultante para obtener la **Ganancia Estática ($K$)** y la **Constante de Tiempo ($\\tau$ al 63.2%)** de nuestra Función de Transferencia empírica:
    
    $$G(s) = \\frac{K}{\\tau s + 1}$$
    """)

    # Parámetros fijos y simples del ensayo escalón
    tokens_fijos = 300
    cpu_inicial = 2.0  # 100% del régimen operativo base
    cpu_final = 1.0    # 50% tras aplicar el escalón en t = 5s
    t_escalon = 5      # Segundo exacto donde ocurre el cambio brusco de CPU
    tau_planta = 3.0   # Constante de tiempo física simulada del contenedor (segundos)

    if "datos_escalon" not in st.session_state:
        st.session_state.datos_escalon = []

    if st.button("🚀 Ejecutar Ensayo Escalón (Bajar CPU de 2.0 a 1.0 Cores de golpe)", type="primary"):
        random.seed(42)  # Para que la curva sea reproducible frente al profesor
        registros = []
        
        # Latencia estacionaria inicial (con 2.0 cores) y final (con 1.0 core)
        lat_inicial = (tokens_fijos / cpu_inicial) * 1.2  # 180 ms
        lat_final = (tokens_fijos / cpu_final) * 1.2      # 360 ms
        delta_lat = lat_final - lat_inicial               # +180 ms de salto

        # Simulamos 25 segundos tomando 1 muestra por segundo
        for t in range(26):
            if t < t_escalon:
                cpu_actual = cpu_inicial
                lat_teorica = lat_inicial
            else:
                cpu_actual = cpu_final
                # Respuesta exponencial de 1er orden: y(t) = y_ini + Δy * (1 - e^(-(t - t0)/τ))
                tiempo_desde_escalon = t - t_escalon
                lat_teorica = lat_inicial + delta_lat * (1 - math.exp(-tiempo_desde_escalon / tau_planta))
            
            ruido_sensor = random.uniform(-3.0, 3.0)
            registros.append({
                "Tiempo_s": t,
                "CPU_Cores": cpu_actual,
                "Latencia_Modelo_1er_Orden_ms": round(lat_teorica, 1),
                "Latencia_Sensor_ms": round(lat_teorica + ruido_sensor, 1)
            })
            
        st.session_state.datos_escalon = registros

    # Si ya se corrió el ensayo, mostramos los cálculos de K y Tau, el gráfico y el botón CSV
    if len(st.session_state.datos_escalon) > 0:
        df_esc = pd.DataFrame(st.session_state.datos_escalon)

        # --- 1. CÁLCULO DE K Y TAU (MÉTODO DEL 63.2%) ---
        y_ini = 180.0
        y_fin = 360.0
        delta_y = y_fin - y_ini                 # +180 ms
        delta_u = cpu_final - cpu_inicial       # -1.0 Core
        
        # Ganancia estática K = ΔY / ΔU
        k_ganancia = delta_y / delta_u          # -180 ms/Core
        
        # Valor de latencia al alcanzar el 63.2% del cambio total
        latencia_al_632 = y_ini + 0.632 * delta_y  # 180 + 113.76 = 293.8 ms

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

        # --- 2. GRÁFICOS NATIVOS DE STREAMLIT ---
        st.markdown("#### 📈 Curva de Reacción: Latencia Medida vs. Curva Exponencial de 1er Orden (ms)")
        st.line_chart(df_esc.set_index("Tiempo_s")[["Latencia_Sensor_ms", "Latencia_Modelo_1er_Orden_ms"]])

        st.markdown("#### 🎛️ Escalón Aplicado en el Actuador: Límite de CPU (Cores)")
        st.line_chart(df_esc.set_index("Tiempo_s")[["CPU_Cores"]])

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
    else:
        st.info("👆 Haz clic en el botón 'Ejecutar Ensayo Escalón' para inyectar el cambio brusco de CPU y calcular K y τ.")

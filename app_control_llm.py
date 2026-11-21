import streamlit as st
import pandas as pd
import numpy as np
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

st.set_page_config(page_title="TP Teoría de Control - UTN", layout="wide")

# --- INICIALIZACIÓN DEL ESTADO DE LA SIMULACIÓN EN TIEMPO REAL ---
if "running" not in st.session_state:
    st.session_state.running = False
if "step" not in st.session_state:
    st.session_state.step = 0
if "perturb_remaining" not in st.session_state:
    st.session_state.perturb_remaining = 0
if "integral_error" not in st.session_state:
    st.session_state.integral_error = 0.0
if "prev_error" not in st.session_state:
    st.session_state.prev_error = 0.0
if "current_y" not in st.session_state:
    st.session_state.current_y = 200.0
if "history" not in st.session_state:
    st.session_state.history = []

# --- BARRA LATERAL: NAVEGACIÓN Y TABLERO DE CONTROL ---
st.sidebar.title("🎛️ Tablero de Control")
st.sidebar.markdown(
    "**Proyecto:** Control de Lazo Cerrado para Latencia en Inferencia LLM\n\n"
    "**Autores:** Boldrini Lucas y Bru Nicolás\n\n"
    "**Cátedra:** Teoría de Control - UTN"
)

pagina = st.sidebar.radio(
    "Navegación del Proyecto:",
    [
        "🟢 1. Simulador en Tiempo Real y QoS",
        "🌐 2. Análisis del Modelo IoT",
    ]
)

st.sidebar.divider()

# Controles del Tablero
st.sidebar.subheader("1. Referencia y QoS (SLA)")
ref_val = st.sidebar.slider("Valor de Referencia R(t) / Setpoint (ms)", 100, 500, 200, step=10)
qos_max = st.sidebar.slider("Umbral Falla QoS / Latencia Máx (ms)", 250, 800, 350, step=10)

st.sidebar.subheader("2. Configurar Perturbación Z(t)")
pert_amp = st.sidebar.slider("Amplitud de Perturbación (+ms carga)", 50, 400, 180, step=10)
pert_dur = st.sidebar.slider("Duración de Perturbación (ciclos)", 3, 30, 10, step=1)

st.sidebar.subheader("3. Constantes de Control (Kp, Ki, Kv)")
modo_lazo = st.sidebar.selectbox(
    "Modo del Sistema:",
    ["Lazo Cerrado (Con Corrección)", "Lazo Abierto (Sin Corrección - Se desequilibra)"]
)

perfil_k = st.sidebar.selectbox(
    "Caso de Prueba (Corrección por K):",
    [
        "Personalizado (Usar sliders)",
        "Solo Kp (Proporcional - Queda error estable)",
        "Kp + Ki (Elimina error en estado estable)",
        "PID Completo (Kp + Ki + Kv amortiguado)"
    ]
)

if perfil_k == "Solo Kp (Proporcional - Queda error estable)":
    kp, ki, kv = 0.012, 0.000, 0.000
    st.sidebar.caption("🔒 Activo: Kp=0.012 | Ki=0.000 | Kv=0.000")
elif perfil_k == "Kp + Ki (Elimina error en estado estable)":
    kp, ki, kv = 0.008, 0.004, 0.000
    st.sidebar.caption("🔒 Activo: Kp=0.008 | Ki=0.004 | Kv=0.000")
elif perfil_k == "PID Completo (Kp + Ki + Kv amortiguado)":
    kp, ki, kv = 0.008, 0.003, 0.006
    st.sidebar.caption("🔒 Activo: Kp=0.008 | Ki=0.003 | Kv=0.006")
else:
    kp = st.sidebar.slider("Constante Proporcional (Kp)", 0.000, 0.030, 0.008, step=0.001, format="%.3f")
    ki = st.sidebar.slider("Constante Integral (Ki)", 0.000, 0.015, 0.003, step=0.001, format="%.3f")
    kv = st.sidebar.slider("Constante Kv / Derivativa (velocidad)", 0.000, 0.020, 0.004, step=0.001, format="%.3f")


# ==============================================================================
# PÁGINA 1: SIMULACIÓN EN TIEMPO REAL, SEÑALES INDEPENDIENTES Y QoS
# ==============================================================================
if pagina == "🟢 1. Simulador en Tiempo Real y QoS":
    st.title("🟢 Sistema de Control de Lazo Cerrado para Regulación de Latencia en Servidores LLM")
    st.markdown("""
    **Variable Controlada (VC):** Latencia de inferencia / TTFT (ms) | **Variable Manipulada (VM):** Cuota de CPU en Docker (`--cpus`).  
    Cada señal del lazo se grafica de forma **independiente** para observar cómo responde el sistema ante perturbaciones y cómo aporta cada constante (**$K_p, K_i, K_v$**) a la corrección.
    """)

    # --- BOTONERA DE EJECUCIÓN EN LÍNEA ---
    c_btn1, c_btn2, c_btn3, c_btn4 = st.columns(4)
    with c_btn1:
        if st.button("▶️ Iniciar / Correr en línea", type="primary", use_container_width=True):
            st.session_state.running = True
    with c_btn2:
        if st.button("⏸️ Detener Simulación", use_container_width=True):
            st.session_state.running = False
    with c_btn3:
        if st.button("⚡ Generar Perturbación Ahora", use_container_width=True):
            st.session_state.perturb_remaining = pert_dur
            st.session_state.running = True
    with c_btn4:
        if st.button("🔄 Reiniciar Todo", use_container_width=True):
            st.session_state.running = False
            st.session_state.step = 0
            st.session_state.perturb_remaining = 0
            st.session_state.integral_error = 0.0
            st.session_state.prev_error = 0.0
            st.session_state.current_y = float(ref_val)
            st.session_state.history = []
            st.rerun()

    # --- FUNCIÓN QUE AVANZA UN CICLO DE RELOJ ---
    def avanzar_un_paso():
        st.session_state.step += 1
        t = st.session_state.step

        if st.session_state.perturb_remaining > 0:
            z_t = float(pert_amp)
            st.session_state.perturb_remaining -= 1
        else:
            z_t = 0.0

        y_actual = st.session_state.current_y
        error = ref_val - y_actual

        if modo_lazo == "Lazo Cerrado (Con Corrección)":
            st.session_state.integral_error = np.clip(st.session_state.integral_error + error, -600.0, 600.0)
            velocidad_error = error - st.session_state.prev_error

            # Desglose de cada acción de control (signo invertido porque +CPU baja la latencia)
            p_term = -(kp * error)
            i_term = -(ki * st.session_state.integral_error)
            d_term = -(kv * velocidad_error)

            accion_control = p_term + i_term + d_term
            u_cpu = float(np.clip(2.0 + accion_control, 0.5, 4.0))
            st.session_state.prev_error = error
        else:
            p_term, i_term, d_term = 0.0, 0.0, 0.0
            u_cpu = 2.0

        latencia_objetivo_planta = ref_val * (2.0 / u_cpu) + z_t
        inercia = 0.35
        ruido = np.random.normal(0, 2.5)
        nueva_y = (1 - inercia) * y_actual + inercia * latencia_objetivo_planta + ruido
        st.session_state.current_y = max(30.0, nueva_y)

        en_falla_qos = st.session_state.current_y > qos_max

        st.session_state.history.append({
            "Tiempo": t,
            "Referencia": ref_val,
            "Umbral_QoS": qos_max,
            "Retroalimentacion": round(st.session_state.current_y, 1),
            "Perturbacion": z_t,
            "Error": round(error, 1),
            "Salida_Controlador": round(u_cpu, 2),
            "Accion_P": round(p_term, 3),
            "Accion_I": round(i_term, 3),
            "Accion_D": round(d_term, 3),
            "Falla_QoS": en_falla_qos
        })
        if len(st.session_state.history) > 80:
            st.session_state.history.pop(0)

    if len(st.session_state.history) == 0:
        st.session_state.current_y = float(ref_val)
        for _ in range(5):
            avanzar_un_paso()

    # --- INDICADORES SUPERIORES DE ESTADO Y QoS ---
    ultimo = st.session_state.history[-1]
    k1, k2, k3, k4, k5 = st.columns(5)
    k1.metric("Retroalimentación Ym(t)", f"{ultimo['Retroalimentacion']} ms", f"{round(ultimo['Retroalimentacion'] - ref_val, 1)} ms vs Ref", delta_color="inverse")
    k2.metric("Perturbación Z(t)", f"+{ultimo['Perturbacion']} ms", f"Restan {st.session_state.perturb_remaining} s" if st.session_state.perturb_remaining > 0 else "Normalidad")
    k3.metric("Salida Controlador U(t)", f"{ultimo['Salida_Controlador']} CPUs", "Docker --cpus")
    k4.metric("Constantes Activas", f"Kp:{kp} | Ki:{ki} | Kv:{kv}")

    if ultimo["Falla_QoS"]:
        k5.error(f"🚨 **FALLA DE QoS (SLA VIOLADO)**\nLatencia > {qos_max} ms")
    elif ultimo["Perturbacion"] > 0:
        k5.warning("⚠️ **SISTEMA PERTURBADO**\nCorrigiendo dentro de QoS")
    else:
        k5.success("✅ **QoS NORMAL (OK)**\nSistema en Equilibrio")

    # --- SEÑALES INDEPENDIENTES DEL SISTEMA DE CONTROL ---
    df = pd.DataFrame(st.session_state.history)

    fig = make_subplots(
        rows=6, cols=1, shared_xaxes=True,
        vertical_spacing=0.045,
        subplot_titles=(
            "1. Valor de Referencia R(t) - Setpoint (ms)",
            "2. Señal de Retroalimentación / Variable Controlada Ym(t) y Umbral QoS (ms)",
            "3. Señal de Error E(t) = R(t) - Ym(t) (ms)",
            "4. Salida del Controlador / Actuador U(t) - CPUs Asignadas (Cores)",
            "5. Desglose de Corrección por Constante (Aporte de Kp, Ki y Kv en CPUs)",
            "6. Señal de Perturbación Z(t) - Sobrecarga Inyectada (ms)"
        )
    )

    # 1. Valor de Referencia independiente
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Referencia"], name="Referencia R(t)", line=dict(color="#2ecc71", width=2.5, shape="hv")), row=1, col=1)

    # 2. Señal de Retroalimentación (Sensor) + límite QoS
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Retroalimentacion"], name="Retroalimentación Ym(t)", line=dict(color="#2980b9", width=3), mode="lines+markers"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Umbral_QoS"], name="Límite Falla QoS", line=dict(color="#e74c3c", dash="dot", width=2)), row=2, col=1)
    df_fallas = df[df["Falla_QoS"] == True]
    if len(df_fallas) > 0:
        fig.add_trace(go.Scatter(x=df_fallas["Tiempo"], y=df_fallas["Retroalimentacion"], name="Falla QoS", mode="markers", marker=dict(color="red", size=10, symbol="x")), row=2, col=1)

    # 3. Señal de Error
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Error"], name="Error E(t)", line=dict(color="#9b59b6", width=2)), row=3, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="gray", row=3, col=1)

    # 4. Salida del Controlador (CPUs totales)
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Salida_Controlador"], name="Salida Controlador U(t)", line=dict(color="#16a085", width=2.5, shape="hv"), fill="tozeroy"), row=4, col=1)

    # 5. Desglose de corrección por cada K
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Accion_P"], name="Corrección Kp (P)", line=dict(color="#3498db", width=2)), row=5, col=1)
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Accion_I"], name="Corrección Ki (I)", line=dict(color="#f39c12", width=2)), row=5, col=1)
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Accion_D"], name="Corrección Kv (D)", line=dict(color="#e74c3c", width=1.5, dash="dot")), row=5, col=1)
    fig.add_hline(y=0, line_dash="dash", line_color="gray", row=5, col=1)

    # 6. Perturbación independiente
    fig.add_trace(go.Scatter(x=df["Tiempo"], y=df["Perturbacion"], name="Perturbación Z(t)", line=dict(color="#e67e22", width=2.5, shape="hv"), fill="tozeroy"), row=6, col=1)

    fig.update_layout(height=1050, margin=dict(l=20, r=20, t=40, b=20), showlegend=True)
    fig.update_xaxes(title_text="Tiempo en línea (ciclos)", row=6, col=1)

    st.plotly_chart(fig, use_container_width=True)

    if st.session_state.running:
        time.sleep(0.4)
        avanzar_un_paso()
        st.rerun()


# ==============================================================================
# PÁGINA 2: ANÁLISIS DEL MODELO IoT SIMPLIFICADO
# ==============================================================================
elif pagina == "🌐 2. Análisis del Modelo IoT":
    st.title("🌐 Análisis del Modelo IoT")
    
    st.info("**Estado Actual:** En su configuración local dentro de una sola PC, el sistema opera como un lazo cerrado local y **no responde todavía al modelo IoT**.")

    st.markdown("""
    ### ¿Qué hay que incorporar para que SÍ responda al Modelo IoT?
    Para evolucionar nuestra planta de IA hacia un **Sistema de Control Basado en Red (NCS)** bajo arquitectura **IoT**, proponemos incorporar:

    * **A. Separación en Nodos Físicos (Edge + Cloud):** Incorporar una **Raspberry Pi o segunda PC** en la red local que opere como nodo de borde (*Edge Node* / Sondas de medición y generador de tráfico), separada del Servidor donde corre la Planta LLM.
    * **B. Broker de Mensajería MQTT (Capa de Comunicación IoT):** Incorporar un broker **(MQTT)** entre los bloques del lazo de control:
      * El **Sensor** publica la telemetría en el tópico `utn/tdc/planta_llm/latencia_ttft`.
      * El **Controlador PID** (alojado en la nube o en otro nodo) se suscribe a ese tópico, calcula la ley de control en función de $K_p, K_i, K_v$ y publica el comando en `utn/tdc/actuador_docker/cpu_limit`.
    * **C. Agente Actuador IoT:** Suscripto al tópico MQTT en el servidor que recibe el payload JSON y ejecuta la orden sobre la API de Docker (`--cpus`).
    """)

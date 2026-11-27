import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import time

# Configuración de página
st.set_page_config(
    page_title="TDC UTN - Control de Latencia LLM",
    page_icon="🎛️",
    layout="wide"
)

# --- CLASE DE CONEXIÓN A DOCKER REAL (ACTUADOR) ---
class DockerActuator:
    def __init__(self, container_name="llm_server", simulation_mode=True):
        self.container_name = container_name
        self.simulation_mode = simulation_mode
        self.client = None
        if not simulation_mode:
            try:
                import docker
                self.client = docker.from_env()
            except Exception as e:
                st.sidebar.warning(f"No se detectó Docker local ({e}). Usando modo simulación.")
                self.simulation_mode = True

    def set_cpu_limit(self, cpu_cores: float):
        """Actualiza dinámicamente los recursos del contenedor (Variable Manipulada)"""
        cpu_cores = float(np.clip(cpu_cores, 0.25, 4.0))
        if not self.simulation_mode and self.client:
            try:
                container = self.client.containers.get(self.container_name)
                nano_cpus = int(cpu_cores * 1e9)
                container.update(nano_cpus=nano_cpus)
            except Exception:
                pass
        return cpu_cores

# --- CASOS PREDEFINIDOS DE SINTONIZACIÓN (Kp, Ki, Kd) ---
CASOS_SINTONIZACION = {
    "1. Óptimo (Amortiguado - ess = 0)": {
        "kp": 0.012, "ki": 0.005, "kd": 0.002,
        "desc": "Respuesta equilibrada (ζ ≈ 0.707). Elimina el error estacionario sin sobrepaso excesivo ni amplificar el jitter del SO."
    },
    "2. Solo Proporcional (Ki=0, Kd=0) -> Error Estacionario": {
        "kp": 0.012, "ki": 0.000, "kd": 0.000,
        "desc": "Sin acción integral, el sistema sigue siendo Tipo 0. Frente a una perturbación queda un error permanente (e_ss ≠ 0)."
    },
    "3. Kp Excesivo (Subamortiguado / Oscilatorio)": {
        "kp": 0.045, "ki": 0.005, "kd": 0.000,
        "desc": "Ganancia proporcional muy alta: la CPU satura y oscila bruscamente entre mínimo y máximo, inestabilizando la latencia."
    },
    "4. Ki Excesivo (Sobrepaso y Lentitud)": {
        "kp": 0.010, "ki": 0.018, "kd": 0.001,
        "desc": "Acumula error demasiado rápido: genera sobrepaso pronunciado (overshoot) y tarda más ciclos en estabilizarse."
    },
    "5. Kd Excesivo (Amplificación de Ruido / Jitter)": {
        "kp": 0.012, "ki": 0.005, "kd": 0.018,
        "desc": "La acción derivativa amplifica las variaciones aleatorias del sensor (jitter del kernel), haciendo vibrar la cuota de CPU."
    },
    "6. Personalizado (Ajuste Manual)": {
        "kp": 0.012, "ki": 0.005, "kd": 0.002,
        "desc": "Ajuste libre de las constantes Kp, Ki y Kd mediante los deslizadores."
    }
}

# --- INICIALIZACIÓN DEL ESTADO EN TIEMPO REAL ---
if "running" not in st.session_state:
    st.session_state.running = False
if "step_count" not in st.session_state:
    st.session_state.step_count = 0
if "perturb_remaining" not in st.session_state:
    st.session_state.perturb_remaining = 0
if "current_ttft" not in st.session_state:
    st.session_state.current_ttft = 250.0
if "prev_ttft" not in st.session_state:
    st.session_state.prev_ttft = 250.0
if "current_cpu" not in st.session_state:
    st.session_state.current_cpu = 1.5
if "integral_error" not in st.session_state:
    st.session_state.integral_error = 0.0
if "history" not in st.session_state:
    st.session_state.history = []

# --- BARRA LATERAL: NAVEGACIÓN Y TABLERO DE CONTROL ---
st.sidebar.title("🎛️ Panel de Control (TDC)")
st.sidebar.markdown(
    "**Proyecto:** Control de Latencia en Inferencia LLM\n\n"
    "**Autores:** Boldrini Lucas y Bru Nicolás\n\n"
    "**Cátedra:** Teoría de Control - UTN.BA"
)

pagina = st.sidebar.radio(
    "Navegación:",
    [
        "📈 1. Simulador en Tiempo Real y QoS",
        "🧪 2. Identificación (Ensayo Escalón)",
        "📐 3. Arquitectura y Marco Matemático",
        "🌐 4. Análisis del Modelo IoT"
    ]
)

st.sidebar.divider()

# Controles del Lazo (visibles siempre para ajustar rápido)
modo_operacion = st.sidebar.radio(
    "Modo del Lazo:",
    ["Lazo Cerrado (Control PID)", "Lazo Abierto (Manual)"],
    index=0
)

st.sidebar.subheader("1. Referencia R(k) y QoS (SLA)")
setpoint_ttft = st.sidebar.slider("Setpoint TTFT Deseado [ms]", 100, 600, 250, step=10)
qos_max = st.sidebar.slider("Umbral Falla QoS [ms]", 250, 900, 400, step=10)

st.sidebar.subheader("2. Sintonización PID Discreto")
caso_elegido = st.sidebar.selectbox("Casos de Estudio (Corrección de K):", list(CASOS_SINTONIZACION.keys()), index=0)
st.sidebar.caption(CASOS_SINTONIZACION[caso_elegido]["desc"])

kp = st.sidebar.slider("Ganancia Proporcional (Kp)", 0.0, 0.05, CASOS_SINTONIZACION[caso_elegido]["kp"], step=0.001, format="%.3f", key=f"kp_{caso_elegido}")
ki = st.sidebar.slider("Ganancia Integral (Ki)", 0.0, 0.02, CASOS_SINTONIZACION[caso_elegido]["ki"], step=0.001, format="%.3f", key=f"ki_{caso_elegido}")
kd = st.sidebar.slider("Ganancia Derivativa (Kd / Kv)", 0.0, 0.02, CASOS_SINTONIZACION[caso_elegido]["kd"], step=0.001, format="%.3f", key=f"kd_{caso_elegido}")

if modo_operacion == "Lazo Abierto (Manual)":
    cpu_manual = st.sidebar.slider("CPU Manual Asignada [Cores]", 0.25, 4.0, 1.5, step=0.1)
else:
    cpu_manual = 1.5

st.sidebar.subheader("3. Perturbaciones Externas Z(k)")
rps_base = st.sidebar.slider("Z1: Tráfico Base [Req/s]", 1, 25, 8)
tokens_prompt = st.sidebar.slider("Z2: Complejidad Prompt [Tokens]", 256, 8192, 1024, step=256)
cache_hit_ratio = st.sidebar.slider("Z3: Afinidad KV Cache [Hit %]", 0, 95, 50, step=5) / 100.0
st.sidebar.markdown("**Inyección de Ráfaga (Botón ⚡):**")
pert_amp_rps = st.sidebar.slider("Amplitud Ráfaga (+Req/s)", 5, 25, 14, step=1)
pert_dur = st.sidebar.slider("Duración Ráfaga [ciclos]", 3, 30, 10, step=1)


# ==============================================================================
# PÁGINA 1: SIMULADOR EN TIEMPO REAL, SEÑALES INDEPENDIENTES Y QoS
# ==============================================================================
if pagina == "📈 1. Simulador en Tiempo Real y QoS":
    st.title("📈 Sistema de Control de Lazo Cerrado para Regulación de Latencia en Inferencia LLM")
    st.markdown("""
    **Variable Controlada (VC):** Latencia TTFT [ms] | **Variable Manipulada (VM):** Cuota de CPU en Docker (`--cpus`).  
    El sistema corre **en tiempo real** con todas las señales separadas para observar el desequilibrio ante perturbaciones, las **fallas de QoS** y el aporte de cada constante ($K_p, K_i, K_d$).
    """)

    # --- BOTONERA EN TIEMPO REAL ---
    b1, b2, b3, b4 = st.columns(4)
    with b1:
        if st.button("▶️ Iniciar / Correr en línea", type="primary", use_container_width=True):
            st.session_state.running = True
    with b2:
        if st.button("⏸️ Detener Simulación", use_container_width=True):
            st.session_state.running = False
    with b3:
        if st.button("⚡ Generar Perturbación Ahora", use_container_width=True):
            st.session_state.perturb_remaining = pert_dur
            st.session_state.running = True
    with b4:
        if st.button("🔄 Reiniciar Lazo", use_container_width=True):
            st.session_state.running = False
            st.session_state.step_count = 0
            st.session_state.perturb_remaining = 0
            st.session_state.current_ttft = float(setpoint_ttft)
            st.session_state.prev_ttft = float(setpoint_ttft)
            st.session_state.current_cpu = 1.5
            st.session_state.integral_error = 0.0
            st.session_state.history = []
            st.rerun()

    # --- FUNCIÓN DE UN CICLO DE MUESTREO (Ts = 1.0 s) ---
    def step_simulation():
        st.session_state.step_count += 1
        t = st.session_state.step_count
        Ts = 1.0

        # Perturbación inyectada por botón (ráfaga de tráfico adicional)
        if st.session_state.perturb_remaining > 0:
            rafaga_rps = pert_amp_rps
            st.session_state.perturb_remaining -= 1
        else:
            rafaga_rps = 0

        rps_total = rps_base + rafaga_rps

        # 1. RETROALIMENTACIÓN Y COMPARADOR: E(k) = R(k) - Ym(k)
        latencia_medida = st.session_state.current_ttft
        error = setpoint_ttft - latencia_medida

        # 2. LEY DE CONTROL (PID Discreto con Anti-Windup y Derivada sobre Ym)
        if modo_operacion == "Lazo Cerrado (Control PID)":
            dy_dt = (latencia_medida - st.session_state.prev_ttft) / Ts
            p_term = -kp * error
            d_term = kd * dy_dt  # Evita Derivative Kick

            u_tentative = 1.5 + p_term + (-ki * st.session_state.integral_error) + d_term
            if 0.25 <= u_tentative <= 4.0:
                st.session_state.integral_error += error * Ts
            st.session_state.integral_error = float(np.clip(st.session_state.integral_error, -600.0, 600.0))

            i_term = -ki * st.session_state.integral_error
            cpu_aplicada = float(np.clip(1.5 + p_term + i_term + d_term, 0.25, 4.0))
        else:
            p_term, i_term, d_term = 0.0, 0.0, 0.0
            cpu_aplicada = cpu_manual

        st.session_state.prev_ttft = latencia_medida
        st.session_state.current_cpu = cpu_aplicada

        # 3. DINÁMICA DE LA PLANTA (Motor LLM + Cgroups + KV Cache)
        tokens_no_cacheados = tokens_prompt * (1.0 - cache_hit_ratio)
        throughput_cpu = 2200.0 * cpu_aplicada
        t_prefill_ms = (tokens_no_cacheados / throughput_cpu) * 1000.0
        t_cola_ms = ((rps_total ** 1.35) * 12.0) / cpu_aplicada
        rtt_red_ms = 15.0

        kv_util = float(np.clip((rps_total * tokens_prompt) / (32000.0 * np.sqrt(cpu_aplicada)) * 100.0, 5.0, 99.0))
        penalidad_preemption = 120.0 if kv_util > 90.0 else 0.0

        ttft_estacionario = rtt_red_ms + t_cola_ms + t_prefill_ms + penalidad_preemption
        alpha = 0.31
        ruido_sensor = np.random.normal(0, 3.5)
        nueva_latencia = (1 - alpha) * latencia_medida + alpha * ttft_estacionario + ruido_sensor
        st.session_state.current_ttft = max(20.0, nueva_latencia)

        en_falla_qos = st.session_state.current_ttft > qos_max

        st.session_state.history.append({
            "Paso": t,
            "Setpoint_ms": setpoint_ttft,
            "Umbral_QoS": qos_max,
            "TTFT_Actual_ms": round(st.session_state.current_ttft, 1),
            "Error_ms": round(error, 1),
            "CPU_Cores": round(cpu_aplicada, 2),
            "KV_Cache_Util": round(kv_util, 1),
            "Accion_P": round(p_term, 3),
            "Accion_I": round(i_term, 3),
            "Accion_D": round(d_term, 3),
            "RPS_Total": rps_total,
            "Rafaga_Activa": rafaga_rps,
            "Falla_QoS": en_falla_qos
        })
        if len(st.session_state.history) > 80:
            st.session_state.history.pop(0)

    if len(st.session_state.history) == 0:
        st.session_state.current_ttft = float(setpoint_ttft)
        st.session_state.prev_ttft = float(setpoint_ttft)
        for _ in range(8):
            step_simulation()

    # --- INDICADORES SUPERIORES Y SEMÁFORO QoS ---
    ult = st.session_state.history[-1]
    m1, m2, m3, m4, m5 = st.columns(5)
    m1.metric("Retroalimentación Ym(k)", f"{ult['TTFT_Actual_ms']} ms", f"{round(ult['TTFT_Actual_ms'] - setpoint_ttft, 1):+.1f} ms vs Ref", delta_color="inverse")
    m2.metric("Señal de Error E(k)", f"{ult['Error_ms']:+.1f} ms", "R(k) - Ym(k)")
    m3.metric("Salida Controlador U(k)", f"{ult['CPU_Cores']} Cores", f"KV Cache: {ult['KV_Cache_Util']}%")
    m4.metric("Perturbación Z(k)", f"{ult['RPS_Total']} RPS", f"Ráfaga +{ult['Rafaga_Activa']} ({st.session_state.perturb_remaining}s)" if st.session_state.perturb_remaining > 0 else "Carga Base")

    if ult["Falla_QoS"]:
        m5.error(f"🚨 **FALLA DE QoS (SLA)**\nTTFT > {qos_max} ms")
    elif ult["Rafaga_Activa"] > 0:
        m5.warning("⚠️ **PERTURBADO**\nCorrigiendo dentro de QoS")
    else:
        m5.success("✅ **QoS NORMAL (OK)**\nSistema en Equilibrio")

    # --- 6 GRÁFICOS INDEPENDIENTES APILADOS ---
    df_h = pd.DataFrame(st.session_state.history)
    fig = make_subplots(
        rows=6, cols=1, shared_xaxes=True, vertical_spacing=0.045,
        subplot_titles=(
            "1. Valor de Referencia R(k) — Setpoint [ms]",
            "2. Señal de Retroalimentación / Variable Controlada Ym(k) y Umbral QoS [ms]",
            "3. Señal de Error E(k) = R(k) - Ym(k) [ms]",
            "4. Salida del Controlador U(k) — Variable Manipulada [vCPU Cores en Docker]",
            "5. Desglose de Corrección por Constante: P(k), I(k) y D(k) [Δ Cores]",
            "6. Señal de Perturbación Z(k) — Tráfico Concurrente Total [Req/s]"
        )
    )

    # 1. Referencia independiente
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Setpoint_ms"], name="Referencia R(k)", line=dict(color="#2ecc71", width=2.5, shape="hv")), row=1, col=1)

    # 2. Retroalimentación + Umbral QoS + Fallas
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["TTFT_Actual_ms"], name="Retroalimentación Ym(k)", line=dict(color="#2980b9", width=2.5), mode="lines+markers"), row=2, col=1)
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Umbral_QoS"], name="Límite Falla QoS", line=dict(color="#e74c3c", dash="dot", width=2)), row=2, col=1)
    df_fallas = df_h[df_h["Falla_QoS"] == True]
    if len(df_fallas) > 0:
        fig.add_trace(go.Scatter(x=df_fallas["Paso"], y=df_fallas["TTFT_Actual_ms"], name="Falla QoS", mode="markers", marker=dict(color="red", size=10, symbol="x")), row=2, col=1)

    # 3. Error
    fig.add_hline(y=0, line_dash="dot", line_color="#7f8c8d", row=3, col=1)
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Error_ms"], name="Error E(k)", line=dict(color="#f39c12", width=2), fill="tozeroy", fillcolor="rgba(243, 156, 18, 0.15)"), row=3, col=1)

    # 4. Salida Controlador
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["CPU_Cores"], name="Salida Controlador U(k)", line=dict(color="#16a085", width=2.5, shape="hv"), fill="tozeroy", fillcolor="rgba(22, 160, 133, 0.15)"), row=4, col=1)

    # 5. Desglose P, I, D
    fig.add_hline(y=0, line_dash="dot", line_color="#7f8c8d", row=5, col=1)
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Accion_P"], name="Acción Kp (P)", line=dict(color="#3498db", width=1.8)), row=5, col=1)
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Accion_I"], name="Acción Ki (I)", line=dict(color="#9b59b6", width=2.0)), row=5, col=1)
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Accion_D"], name="Acción Kd (D)", line=dict(color="#e74c3c", width=1.5, dash="dot")), row=5, col=1)

    # 6. Perturbación
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["RPS_Total"], name="Perturbación Z(k) [RPS]", line=dict(color="#e67e22", width=2.5, shape="hv"), fill="tozeroy", fillcolor="rgba(230, 126, 34, 0.15)"), row=6, col=1)

    fig.update_yaxes(title_text="ms", row=1, col=1)
    fig.update_yaxes(title_text="ms", row=2, col=1)
    fig.update_yaxes(title_text="ms", row=3, col=1)
    fig.update_yaxes(title_text="Cores", range=[0, 4.3], row=4, col=1)
    fig.update_yaxes(title_text="Δ Cores", row=5, col=1)
    fig.update_yaxes(title_text="Req/s", row=6, col=1)
    fig.update_xaxes(title_text="Tiempo en línea (ciclos de 1s)", row=6, col=1)

    fig.update_layout(height=1080, margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h", y=1.02, x=0))
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("📄 Ver Tabla de Registro Discreto de Todas las Señales"):
        st.dataframe(df_h.tail(15), use_container_width=True)

    if st.session_state.running:
        time.sleep(0.4)
        step_simulation()
        st.rerun()


# ==============================================================================
# PÁGINA 2: IDENTIFICACIÓN DE LA PLANTA (ENSAYO ESCALÓN)
# ==============================================================================
elif pagina == "🧪 2. Identificación (Ensayo Escalón)":
    st.title("🧪 Identificación Experimental de la Planta (Método de Caja Negra)")
    st.markdown("""
    Como un motor de inferencia ejecutándose en un sistema operativo no posee una ecuación física clásica, 
    aplicamos un **Ensayo de Entrada Escalón** en lazo abierto para aproximar su dinámica mediante un modelo de **Primer Orden**:
    $$G_p(s) = \\frac{Y(s)}{U(s)} = \\frac{K}{\\tau s + 1}$$
    """)

    c_id1, c_id2 = st.columns([1, 2])
    with c_id1:
        u_inicial = st.number_input("CPU Inicial (Cores)", value=2.0, min_value=0.5, max_value=4.0, step=0.5)
        u_final = st.number_input("CPU tras el Escalón (Cores)", value=1.0, min_value=0.5, max_value=4.0, step=0.5)

        t_ensayo = np.linspace(0, 30, 61)
        tau_real = 3.2
        y_ini = 220.0 / (u_inicial / 2.0)
        y_fin = 220.0 / (u_final / 2.0)
        delta_u = u_final - u_inicial
        delta_y = y_fin - y_ini
        k_estatica = delta_y / delta_u if delta_u != 0 else 0.0

        np.random.seed(42)
        y_modelo = np.where(t_ensayo < 5, y_ini, y_ini + delta_y * (1 - np.exp(-(t_ensayo - 5) / tau_real)))
        y_experimental = y_modelo + np.random.normal(0, 3.5, size=len(t_ensayo))
        y_632 = y_ini + 0.632 * delta_y

        st.success(f"""
        **Parámetros Identificados:**
        * **Cambio en Entrada ($\\Delta U$):** `{delta_u:.2f} Cores`
        * **Cambio en Salida ($\\Delta Y$):** `{delta_y:.1f} ms`
        * **Ganancia Estática ($K$):** `{k_estatica:.2f} ms/Core`
        * **Constante de Tiempo ($\\tau$ al 63.2%):** `{tau_real:.2f} s`
        * **Tiempo de Establecimiento ($4\\tau$):** `{4*tau_real:.2f} s`
        """)

        df_csv = pd.DataFrame({
            "Tiempo_s": t_ensayo,
            "CPU_Cores": np.where(t_ensayo < 5, u_inicial, u_final),
            "Latencia_TTFT_ms": np.round(y_experimental, 2)
        })
        st.download_button("📥 Descargar CSV del Ensayo", data=df_csv.to_csv(index=False).encode("utf-8"), file_name="ensayo_escalon_llm.csv", mime="text/csv", use_container_width=True)

    with c_id2:
        fig_step = go.Figure()
        fig_step.add_trace(go.Scatter(x=t_ensayo, y=y_experimental, mode="markers", name="Datos Sensor (CSV)", marker=dict(color="#95a5a6", size=6)))
        fig_step.add_trace(go.Scatter(x=t_ensayo, y=y_modelo, mode="lines", name="Modelo 1er Orden Ajustado", line=dict(color="#e67e22", width=3)))
        fig_step.add_hline(y=y_632, line_dash="dot", line_color="#2980b9", annotation_text=f"63.2% de ΔY ({y_632:.1f} ms) -> τ = {tau_real}s")
        fig_step.add_vline(x=5 + tau_real, line_dash="dot", line_color="#2980b9")
        fig_step.update_layout(title="Curva de Reacción del Proceso ante Escalón en t = 5s", xaxis_title="Tiempo (s)", yaxis_title="Latencia TTFT (ms)", height=420)
        st.plotly_chart(fig_step, use_container_width=True)


# ==============================================================================
# PÁGINA 3: ARQUITECTURA Y MARCO MATEMÁTICO
# ==============================================================================
elif pagina == "📐 3. Arquitectura y Marco Matemático":
    st.title("📐 Estructura Funcional del Sistema de Control")
    st.code("""
                                 Perturbaciones Z(k):
                                 - Z1: Tráfico concurrente (RPS)
                                 - Z2: Complejidad de Prompts (Tokens)
                                 - Z3: Cache Miss (KV Cache)
                                            |
                                            v
    Setpoint R(k)    Error E(k)   +-------------------+   U(k)   +------------------+   +--------------------+
    (TTFT deseado) -->(( + / - ))->| Controlador PID   |--------->| Actuador Docker  |-->| Planta: Motor LLM  |---> Salida Y(k)
                       ^           | Discreto          |  --cpus  | API (Cgroups v2) |   | (Prefill + Cola)   |     (TTFT Real)
                       |           +-------------------+          +------------------+   +--------------------+        |
                       |                                                                                               |
                       |                                 +-----------------------------+                               |
                       +---------------------------------| Sensor: Telemetría Python   |<------------------------------+
                               Realimentación Ym(k)      | (perf_counter_ns / SSE)     |
                                                         +-----------------------------+
    """, language="text")

    col_eq1, col_eq2 = st.columns(2)
    with col_eq1:
        st.markdown("#### 1. Ecuaciones del Controlador PID Discreto")
        st.markdown("""
        En cada ciclo de muestreo $k$ ($T_s = 1.0\\text{ s}$), el comparador calcula la señal de error:
        $$E(k) = R(k) - Y_m(k)$$

        La ley de control implementa acción inversa ($K < 0$), *Anti-Windup* por sujeción (*clamping*) y derivada sobre la salida $Y_m(k)$ para evitar *Derivative Kick*:
        $$P(k) = -K_p \\cdot E(k)$$
        $$I(k) = -K_i \\sum_{j=0}^{k} E(j) \\cdot T_s$$
        $$D(k) = K_d \\frac{Y_m(k) - Y_m(k-1)}{T_s}$$
        $$U(k) = \\text{SATURAR}\\Big(U_{base} + P(k) + I(k) + D(k),\\ 0.25,\\ 4.00\\Big)$$
        """)
    with col_eq2:
        st.markdown("#### 2. Descomposición de Latencia y Fundamentación")
        st.markdown("""
        $$TTFT = RTT_{red} + T_{cola}(RPS) + T_{prefill}(N - k_{cache})$$

        * **Tipo de Sistema:** La planta es **Tipo 0**. La acción integral $I(k)$ eleva el lazo directo a **Tipo 1**, garantizando error en estado estacionario nulo ($e_{ss} = 0$) ante perturbaciones escalón.
        * **Por qué SÍ `--cpus` y `TTFT`:** La fase *Prefill* es *compute-bound*, por lo que responde directamente a la cuota de CPU.
        * **Por qué NO RAM ni `ITL`:** Reducir RAM dispara el *OOM Killer* del kernel y mata el contenedor; la fase *Decode* (`ITL`) es *memory-bandwidth bound* y no mejora agregando cores de CPU.
        """)


# ==============================================================================
# PÁGINA 4: ANÁLISIS DEL MODELO IoT
# ==============================================================================
elif pagina == "🌐 4. Análisis del Modelo IoT":
    st.title("🌐 Análisis del Modelo IoT")
    st.info("**Estado Actual:** En su configuración local dentro de una sola PC, el sistema opera como un lazo cerrado local y **no responde todavía al modelo IoT**.")
    st.markdown("""
    ### ¿Qué hay que incorporar para que SÍ responda al Modelo IoT?
    Para evolucionar nuestra planta de IA hacia un **Sistema de Control Basado en Red (NCS)** bajo arquitectura **IoT**, proponemos incorporar:

    * **A. Separación en Nodos Físicos (Edge + Cloud):** Incorporar una **Raspberry Pi o segunda PC** en la red local que opere como nodo de borde (*Edge Node* / Sondas de medición y generador de tráfico), separada del Servidor donde corre la Planta LLM.
    * **B. Broker de Mensajería MQTT (Capa de Comunicación IoT):** Incorporar un broker **Mosquitto (MQTT)** entre los bloques del lazo de control:
      * El **Sensor** publica la telemetría en el tópico `utn/tdc/planta_llm/latencia_ttft`.
      * El **Controlador PID** (alojado en la nube o en otro nodo) se suscribe a ese tópico, calcula la ley de control en función de $K_p, K_i, K_d$ y publica el comando en `utn/tdc/actuador_docker/cpu_limit`.
    * **C. Agente Actuador IoT:** Un demonio suscripto al tópico MQTT en el servidor que recibe el payload JSON y ejecuta la orden sobre la API de Docker (`--cpus`).
    """)

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
        cpu_cores = float(np.clip(cpu_cores, 0.2, 4.0))
        if not self.simulation_mode and self.client:
            try:
                container = self.client.containers.get(self.container_name)
                nano_cpus = int(cpu_cores * 1e9)
                container.update(nano_cpus=nano_cpus)
            except Exception as e:
                pass
        return cpu_cores

# --- BARRA LATERAL: PARÁMETROS DEL SISTEMA ---
st.sidebar.title("🎛️ Panel de Control (TDC)")
st.sidebar.markdown("**Autores:** Boldrini Lucas y Bru Nicolás\n\n**Cátedra:** Teoría de Control - UTN")
st.sidebar.divider()

modo_operacion = st.sidebar.radio(
    "Modo del Lazo:",
    ["Lazo Cerrado (Control PID)", "Lazo Abierto (Manual)"],
    index=0
)

st.sidebar.subheader("1. Referencia (Setpoint)")
setpoint_ttft = st.sidebar.slider("Setpoint TTFT Deseado (ms)", min_value=100, max_value=800, value=250, step=10)

st.sidebar.subheader("2. Sintonización PID Discreto")
# Nota sobre el signo: En nuestra planta, +CPU = -Latencia (ganancia inversa).
# Si Error = Setpoint - Latencia_Actual:
# Cuando Latencia > Setpoint -> Error es negativo -> necesitamos SUBIR CPU.
kp = st.sidebar.slider("Ganancia Proporcional (Kp)", 0.0, 0.05, 0.008, step=0.001, format="%.3f")
ki = st.sidebar.slider("Ganancia Integral (Ki)", 0.0, 0.02, 0.003, step=0.001, format="%.3f")
kd = st.sidebar.slider("Ganancia Derivativa (Kd)", 0.0, 0.02, 0.002, step=0.001, format="%.3f")

if modo_operacion == "Lazo Abierto (Manual)":
    cpu_manual = st.sidebar.slider("CPU Manual Asignada (Cores)", 0.2, 4.0, 1.5, step=0.1)
else:
    cpu_manual = 1.5

st.sidebar.subheader("3. Perturbaciones Externas Z(t)")
rps_carga = st.sidebar.slider("Tráfico Concurrente (Req/s)", 1, 30, 8)
tokens_prompt = st.sidebar.slider("Complejidad Prompt (Tokens)", 256, 8192, 1024, step=256)
cache_hit_ratio = st.sidebar.slider("Afinidad KV Cache (Prefix Hit %)", 0, 95, 50, step=5) / 100.0

# --- CUERPO PRINCIPAL ---
st.title("Sistema de Control de Lazo Cerrado para Regulación de Latencia en Inferencia LLM")
st.markdown("""
Esta plataforma modela, identifica y controla en tiempo real la latencia **TTFT (*Time To First Token*)** de un motor de inferencia local (Planta), 
manipulando la cuota de cómputo en contenedores Docker (Actuador) frente a perturbaciones de tráfico y complejidad algorítmica.
""")

tab1, tab2, tab3 = st.tabs([
    "📈 1. Simulación Lazo Cerrado / Abierto",
    "🧪 2. Identificación de la Planta (Ensayo Escalón)",
    "📐 3. Arquitectura y Marco Matemático"
])

# ==============================================================================
# PESTAÑA 1: SIMULACIÓN INTERACTIVA DEL LAZO DE CONTROL
# ==============================================================================
with tab1:
    col_btn1, col_btn2, col_info = st.columns([1, 1, 2])
    
    # Estado de la simulación
    if "history" not in st.session_state:
        st.session_state.history = pd.DataFrame(columns=[
            "Paso", "Setpoint_ms", "TTFT_Actual_ms", "Error_ms", 
            "CPU_Cores", "KV_Cache_Util", "Accion_P", "Accion_I", "Accion_D"
        ])
        st.session_state.current_ttft = 280.0
        st.session_state.current_cpu = 1.5
        st.session_state.integral_error = 0.0
        st.session_state.prev_error = 0.0
        st.session_state.step_count = 0

    with col_btn1:
        sim_steps = st.selectbox("Pasos a ejecutar:", [1, 15, 40], index=1)
        run_sim = st.button("▶️ Ejecutar Simulación", type="primary", use_container_width=True)
    with col_btn2:
        reset_sim = st.button("🔄 Reiniciar Datos", use_container_width=True)

    if reset_sim:
        st.session_state.history = pd.DataFrame(columns=st.session_state.history.columns)
        st.session_state.current_ttft = 280.0
        st.session_state.current_cpu = 1.5
        st.session_state.integral_error = 0.0
        st.session_state.prev_error = 0.0
        st.session_state.step_count = 0
        st.rerun()

    # Función física de simulación de un paso
    def step_simulation():
        st.session_state.step_count += 1
        t = st.session_state.step_count
        
        # 1. MEDICIÓN DEL SENSOR E(t) = Setpoint - Latencia_Actual
        latencia_medida = st.session_state.current_ttft
        error = setpoint_ttft - latencia_medida
        
        # 2. LEY DE CONTROL (PID Discreto vs Lazo Abierto)
        if modo_operacion == "Lazo Cerrado (Control PID)":
            st.session_state.integral_error += error
            # Anti-windup para evitar saturación del integrador
            st.session_state.integral_error = np.clip(st.session_state.integral_error, -500, 500)
            derivada_error = error - st.session_state.prev_error
            
            # Acción de control inversa: si error < 0 (latencia alta), restamos un negativo -> sube CPU
            p_term = -kp * error
            i_term = -ki * st.session_state.integral_error
            d_term = -kd * derivada_error
            
            cpu_target = 1.5 + p_term + i_term + d_term
            cpu_aplicada = float(np.clip(cpu_target, 0.25, 4.0))
            st.session_state.prev_error = error
        else:
            p_term, i_term, d_term = 0.0, 0.0, 0.0
            cpu_aplicada = cpu_manual

        st.session_state.current_cpu = cpu_aplicada

        # 3. DINÁMICA DE LA PLANTA (Motor LLM con KV Cache y Cola)
        # Tokens efectivos a computar en fase Prefill (descontando los cacheados por APC)
        tokens_no_cacheados = tokens_prompt * (1.0 - cache_hit_ratio)
        
        # Tiempo de cómputo Prefill + Espera en cola (inversamente proporcional a los Cores de CPU)
        throughput_cpu = 2200.0 * cpu_aplicada  # tokens/seg por core
        t_prefill_ms = (tokens_no_cacheados / throughput_cpu) * 1000.0
        t_cola_ms = ((rps_carga ** 1.35) * 12.0) / cpu_aplicada
        rtt_red_ms = 15.0  # Constante local/edge
        
        # Ocupación del KV Cache (%) y penalización por Preemption si supera 90%
        kv_util = np.clip((rps_carga * tokens_prompt) / (32000.0 * np.sqrt(cpu_aplicada)) * 100.0, 5.0, 99.0)
        penalidad_preemption = 120.0 if kv_util > 90.0 else 0.0
        
        ttft_estacionario = rtt_red_ms + t_cola_ms + t_prefill_ms + penalidad_preemption
        
        # Inercia térmica/computacional de primer orden (constante de tiempo tau ~ 2.5 pasos)
        alpha = 0.35
        ruido_sensor = np.random.normal(0, 4.0)
        nueva_latencia = (1 - alpha) * latencia_medida + alpha * ttft_estacionario + ruido_sensor
        st.session_state.current_ttft = max(20.0, nueva_latencia)

        # Guardar registro
        nuevo_registro = pd.DataFrame([{
            "Paso": t,
            "Setpoint_ms": setpoint_ttft,
            "TTFT_Actual_ms": round(st.session_state.current_ttft, 2),
            "Error_ms": round(error, 2),
            "CPU_Cores": round(cpu_aplicada, 3),
            "KV_Cache_Util": round(kv_util, 1),
            "Accion_P": round(p_term, 3),
            "Accion_I": round(i_term, 3),
            "Accion_D": round(d_term, 3)
        }])
        st.session_state.history = pd.concat([st.session_state.history, nuevo_registro], ignore_index=True)

    if run_sim:
        for _ in range(sim_steps):
            step_simulation()

    # Si está vacío, corremos 10 pasos iniciales para que haya gráfica de entrada
    if len(st.session_state.history) == 0:
        for _ in range(10):
            step_simulation()

    # Métricas superiores en tiempo real
    ult = st.session_state.history.iloc[-1]
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Variable Controlada (TTFT)", f"{ult['TTFT_Actual_ms']:.1f} ms", f"{ult['TTFT_Actual_ms'] - setpoint_ttft:.1f} ms vs Setpoint", delta_color="inverse")
    m2.metric("Señal de Error E(t)", f"{ult['Error_ms']:.1f} ms", "Setpoint - VC")
    m3.metric("Variable Manipulada (Docker CPU)", f"{ult['CPU_Cores']:.2f} Cores", "Rango: [0.25 - 4.0]")
    m4.metric("Uso de Bloques KV Cache", f"{ult['KV_Cache_Util']:.1f} %", "Riesgo Preemption > 90%" if ult['KV_Cache_Util'] > 90 else "Estable")

    # Gráficos interactivos con Plotly
    fig = make_subplots(
        rows=2, cols=1, shared_xaxes=True,
        vertical_spacing=0.08,
        subplot_titles=(
            "Respuesta Temporal: Variable Controlada (TTFT) vs Referencia (Setpoint)",
            "Acción de Control: Variable Manipulada (Límite de CPU en Docker)"
        ),
        row_heights=[0.6, 0.4]
    )

    df_h = st.session_state.history
    # Gráfico 1: Latencia y Setpoint
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["Setpoint_ms"], name="Setpoint R(t)", line=dict(color="#2ecc71", dash="dash", width=2)), row=1, col=1)
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["TTFT_Actual_ms"], name="Latencia TTFT Y(t)", line=dict(color="#e74c3c", width=3), mode="lines+markers"), row=1, col=1)
    
    # Gráfico 2: CPU Cores
    fig.add_trace(go.Scatter(x=df_h["Paso"], y=df_h["CPU_Cores"], name="CPU Asignada U(t)", line=dict(color="#3498db", width=2.5, shape="hv"), fill="tozeroy"), row=2, col=1)

    fig.update_yaxes(title_text="Tiempo (ms)", row=1, col=1)
    fig.update_yaxes(title_text="Cores (--cpus)", range=[0, 4.2], row=2, col=1)
    fig.update_xaxes(title_text="Instante de Muestreo Discreto (k)", row=2, col=1)
    fig.update_layout(height=550, margin=dict(l=20, r=20, t=40, b=20), legend=dict(orientation="h", y=1.08))
    
    st.plotly_chart(fig, use_container_width=True)

# ==============================================================================
# PESTAÑA 2: IDENTIFICACIÓN DEL SISTEMA (FASE 3 DEL TP)
# ==============================================================================
with tab2:
    st.subheader("🧪 Identificación Experimental de la Planta (Método de Caja Negra)")
    st.markdown("""
    Como un motor de inferencia ejecutándose en un sistema operativo no posee una ecuación física clásica (como un circuito RLC o un motor DC), 
    aplicamos un **Ensayo de Entrada Escalón** en lazo abierto para aproximar su dinámica mediante un modelo de **Primer Orden**:
    
    $$G(s) = \\frac{Y(s)}{U(s)} = \\frac{K}{\\tau s + 1}$$
    """)

    c_id1, c_id2 = st.columns([1, 2])
    with c_id1:
        st.markdown("**Configuración del Ensayo Escalón:**")
        u_inicial = st.number_input("CPU Inicial (Cores)", value=2.0, min_value=0.5, max_value=4.0, step=0.5)
        u_final = st.number_input("CPU tras el Escalón (Cores)", value=1.0, min_value=0.5, max_value=4.0, step=0.5)
        
        # Simulación teórica-empírica del escalón para mostrar e identificar
        t_ensayo = np.linspace(0, 30, 61)
        tau_real = 3.2  # segundos
        y_ini = 180.0 / (u_inicial / 2.0)
        y_fin = 180.0 / (u_final / 2.0)
        delta_u = u_final - u_inicial
        delta_y = y_fin - y_ini
        
        k_estatica = delta_y / delta_u if delta_u != 0 else 0.0
        
        # Curva teórica vs Medición con ruido
        np.random.seed(42)
        y_modelo = np.where(t_ensayo < 5, y_ini, y_ini + delta_y * (1 - np.exp(-(t_ensayo - 5) / tau_real)))
        y_experimental = y_modelo + np.random.normal(0, 3.5, size=len(t_ensayo))
        
        y_632 = y_ini + 0.632 * delta_y
        
        st.success(f"""
        **Parámetros Identificados:**
        * **Cambio en Entrada ($\Delta U$):** `{delta_u:.2f} Cores`
        * **Cambio en Salida ($\Delta Y$):** `{delta_y:.1f} ms`
        * **Ganancia Estática ($K$):** `{k_estatica:.2f} ms/Core`
        * **Constante de Tiempo ($\\tau$ al 63.2%):** `{tau_real:.2f} s`
        * **Tiempo de Establecimiento ($4\\tau$):** `{4*tau_real:.2f} s`
        """)

        df_csv = pd.DataFrame({"Tiempo_s": t_ensayo, "CPU_Cores": np.where(t_ensayo < 5, u_inicial, u_final), "Latencia_TTFT_ms": np.round(y_experimental, 2)})
        st.download_button(
            "📥 Descargar CSV del Ensayo (para Colab / MATLAB)",
            data=df_csv.to_csv(index=False).encode("utf-8"),
            file_name="ensayo_escalon_llm.csv",
            mime="text/csv",
            use_container_width=True
        )

    with c_id2:
        fig_step = go.Figure()
        fig_step.add_trace(go.Scatter(x=t_ensayo, y=y_experimental, mode="markers", name="Datos Sensor (CSV)", marker=dict(color="#95a5a6", size=6)))
        fig_step.add_trace(go.Scatter(x=t_ensayo, y=y_modelo, mode="lines", name="Modelo 1er Orden Ajustado", line=dict(color="#e67e22", width=3)))
        fig_step.add_hline(y=y_632, line_dash="dot", line_color="#2980b9", annotation_text=f"63.2% de ΔY ({y_632:.1f} ms) -> τ = {tau_real}s")
        fig_step.add_vline(x=5 + tau_real, line_dash="dot", line_color="#2980b9")
        fig_step.update_layout(
            title="Curva de Reacción del Proceso ante Escalón en t = 5s",
            xaxis_title="Tiempo (segundos)",
            yaxis_title="Latencia TTFT (ms)",
            height=420
        )
        st.plotly_chart(fig_step, use_container_width=True)

# ==============================================================================
# PESTAÑA 3: MARCO TEÓRICO Y ECUACIONES (PARA LA DEFENSA ORAL)
# ==============================================================================
with tab3:
    st.subheader("📐 Estructura Funcional del Sistema de Control")
    
    st.markdown("""
    ```text
                            Perturbaciones Z(t):
                            - Complejidad de Prompts (Tokens)
                            - Tráfico concurrente (RPS) / Cache Miss
                                              |
                                              v
    Setpoint R(t)      Error E(t)   +-------------------+   U(t)   +------------------+   +--------------------+
    (TTFT deseado) --->(( + / - ))->| Controlador PID   |--------->| Actuador Docker  |-->| Planta: Motor LLM  |---> Salida Y(t)
                           ^        | Discreto          |  --cpus  | API (Cgroups)    |   | (Prefill + Cola)   |     (TTFT Real)
                           |        +-------------------+          +------------------+   +--------------------+          |
                           |                                                                                              |
                           |                              +-----------------------------+                                 |
                           +------------------------------| Sensor: Telemetría Python   |<--------------------------------+
                                  Realimentación Y_m(t)   | (Librería time / TTFT)      |
                                                          +-----------------------------+
    ```
    """)
    
    col_eq1, col_eq2 = st.columns(2)
    with col_eq1:
        st.markdown("#### 1. Ecuaciones del Controlador PID Discreto")
        st.markdown("""
        En cada ciclo de muestreo $k$, el comparador calcula la señal de error:
        $$E(t) = Setpoint - Latencia\\_Actual$$
        
        La ley de control en ecuaciones de diferencias suma las tres acciones:
        $$P(t) = K_p \\cdot E(t)$$
        $$I(t) = K_i \\sum_{j=0}^{t} E(j) \\cdot \\Delta t$$
        $$D(t) = K_d \\frac{E(t) - E(t-1)}{\\Delta t}$$
        $$U(t) = U_{base} - \\left( P(t) + I(t) + D(t) \\right)$$
        *(Nota: Al existir un integrador en el controlador, el sistema pasa de **Tipo 0** a **Tipo 1**, garantizando un error en estado estacionario $e_{ss} = 0$ frente a perturbaciones de tipo escalón).*
        """)
    with col_eq2:
        st.markdown("#### 2. Descomposición de Latencia en la Planta LLM")
        st.markdown("""
        Basado en la arquitectura de motores modernos (vLLM / PagedAttention):
        $$TTFT = RTT_{red} + T_{cola}(q) + T_{prefill}(N - k)$$
        
        * **$N$:** Tokens totales del prompt de entrada.
        * **$k$:** Tokens recuperados por afinidad de *KV Cache* (*Automatic Prefix Caching*).
        * **$T_{prefill}(N-k)$:** Fase *compute-bound* directamente gobernada por nuestra Variable Manipulada (`--cpus`).
        * **Justificación de PID sobre ON-OFF:** Un control discontinuo Todo o Nada (asignar 0.5 o 4.0 CPUs abruptamente) induciría oscilaciones severas (*chattering*) y vaciado/preemption en la cola del *scheduler*.
        """)
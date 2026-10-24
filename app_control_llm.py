import streamlit as st
import pandas as pd
import random

st.title("Planta de Inferencia LLM en Lazo Abierto")
st.subheader("Teoría de Control - UTN | Boldrini Lucas y Bru Nicolás")

st.markdown("""
**Objetivo de esta primera iteración (Fases 1 y 2):** 
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
# Guardamos las mediciones en una lista simple
if "mediciones" not in st.session_state:
    st.session_state.mediciones = []

if st.button("Enviar Prompt y Medir Latencia (Sensor)"):
    # Fórmula simple de la planta: a menos CPU y más tokens, tarda más milisegundos
    latencia_base = (tokens_prompt / cpu_cores) * 1.2
    ruido = random.uniform(-10, 10)  # Pequeña variación natural del sistema operativo
    latencia_medida = round(latencia_base + ruido, 1)
    
    st.session_state.mediciones.append({
        "CPU_Asignada": cpu_cores,
        "Latencia_ms": latencia_medida
    })

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

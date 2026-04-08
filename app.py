import streamlit as st
import pandas as pd
import numpy as np
import yfinance as yf
from datetime import date, timedelta
import plotly.graph_objects as go

st.set_page_config(page_title="Portfolio vs Benchmark", layout="wide")
st.title("Administración de Carteras - Simulador de Portfolio")

# --- Parámetros del ejercicio ---
ACTIVOS = ["GLD", "SPY", "TLT"]
BENCHMARK = {"GLD": 0.25, "SPY": 0.25, "TLT": 0.25, "Cash": 0.25}
FECHA_INICIO = date(2026, 4, 15)
FECHA_FIN = date(2026, 6, 10)
FECHAS_REBALANCEO = [
    date(2026, 4, 15),
    date(2026, 4, 29),
    date(2026, 5, 6),
    date(2026, 5, 27),
]

# --- Descarga de precios ---
@st.cache_data(ttl=3600)
def descargar_precios(inicio, fin):
    """Descarga precios de cierre ajustados desde Yahoo Finance."""
    # Pedir un poco antes por si el inicio cae en feriado
    inicio_ext = inicio - timedelta(days=5)
    fin_ext = fin + timedelta(days=3)
    datos = yf.download(ACTIVOS, start=inicio_ext, end=fin_ext, auto_adjust=True)
    precios = datos["Close"] if "Close" in datos.columns.get_level_values(0) else datos
    precios = precios[ACTIVOS].dropna()
    return precios


# --- Sidebar: configurar pesos por fecha de rebalanceo ---
st.sidebar.header("Configuración de Cartera")
st.sidebar.markdown("Definí los pesos (%) para cada fecha de rebalanceo.")

pesos_por_fecha = {}
for i, fecha in enumerate(FECHAS_REBALANCEO):
    etiqueta = "Inicio" if i == 0 else f"Rebalanceo {i}"
    st.sidebar.subheader(f"{etiqueta}: {fecha.strftime('%d/%m/%Y')}")

    cols = st.sidebar.columns(4)
    pesos = {}
    for j, activo in enumerate(ACTIVOS):
        default = 25.0
        pesos[activo] = cols[j].number_input(
            activo, min_value=0.0, max_value=100.0, value=default,
            step=1.0, key=f"{activo}_{i}"
        )
    # Cash es el residuo
    cash = 100.0 - sum(pesos.values())
    cash = max(0.0, round(cash, 2))
    pesos["Cash"] = cash
    cols[3].metric("Cash", f"{cash:.1f}%")

    total = sum(pesos.values())
    if abs(total - 100.0) > 0.01:
        st.sidebar.error(f"Los pesos suman {total:.1f}% (deben sumar 100%)")

    pesos_por_fecha[fecha] = {k: v / 100.0 for k, v in pesos.items()}

# --- Lógica de cálculo ---
def calcular_performance(precios, pesos_por_fecha, es_benchmark=False):
    """
    Calcula serie de retorno acumulado de un portfolio.
    pesos_por_fecha: dict {date: {activo: peso}}
    Si es_benchmark, no rebalancea (usa pesos iniciales y deja correr).
    """
    fechas_reb = sorted(pesos_por_fecha.keys())
    fechas_precio = precios.index

    # Valor del portfolio normalizado a 100
    valor_portfolio = pd.Series(index=fechas_precio, dtype=float)
    valor_portfolio.iloc[0] = np.nan  # se llena abajo

    # Encontrar primer dia disponible >= fecha_inicio
    primera_fecha = fechas_precio[fechas_precio >= pd.Timestamp(fechas_reb[0])][0]
    idx_inicio = fechas_precio.get_loc(primera_fecha)

    valor_actual = 100.0
    # Holdings: cuantas "unidades" de cada activo tengo
    holdings = {}

    for idx in range(idx_inicio, len(fechas_precio)):
        hoy = fechas_precio[idx].date()

        # Verificar si hay rebalanceo hoy
        rebalancear = False
        if es_benchmark:
            # Solo al inicio
            if idx == idx_inicio:
                rebalancear = True
                pesos_hoy = pesos_por_fecha[fechas_reb[0]]
        else:
            for fr in fechas_reb:
                if hoy >= fr and (fr not in holdings or fr == hoy):
                    # Buscar la fecha de rebalanceo mas reciente <= hoy
                    pass
            # Encontrar pesos vigentes
            pesos_vigentes = None
            for fr in reversed(fechas_reb):
                if hoy >= fr:
                    pesos_vigentes = pesos_por_fecha[fr]
                    break
            if pesos_vigentes is None:
                continue
            # Rebalancear si es dia de rebalanceo o primer dia
            if hoy in [f for f in fechas_reb] or idx == idx_inicio:
                rebalancear = True
                pesos_hoy = pesos_vigentes

        if rebalancear:
            # Calcular valor actual antes de rebalancear (si no es primer dia)
            if holdings:
                valor_actual = 0.0
                for activo in ACTIVOS:
                    precio_hoy = precios.loc[fechas_precio[idx], activo]
                    valor_actual += holdings.get(activo, 0) * precio_hoy
                valor_actual += holdings.get("Cash", 0)

            # Asignar nuevos holdings segun pesos
            holdings = {}
            for activo in ACTIVOS:
                precio_hoy = precios.loc[fechas_precio[idx], activo]
                monto_activo = valor_actual * pesos_hoy.get(activo, 0)
                holdings[activo] = monto_activo / precio_hoy if precio_hoy > 0 else 0
            holdings["Cash"] = valor_actual * pesos_hoy.get("Cash", 0)

        # Calcular valor del dia
        valor_dia = holdings.get("Cash", 0)
        for activo in ACTIVOS:
            precio_hoy = precios.loc[fechas_precio[idx], activo]
            valor_dia += holdings.get(activo, 0) * precio_hoy
        valor_portfolio.iloc[idx] = valor_dia

    return valor_portfolio.dropna()


# --- Main ---
st.markdown("---")

# Verificar si hay datos disponibles (antes del 15/04 no habrá)
hoy = date.today()
if hoy < FECHA_INICIO:
    dias_sim = st.sidebar.slider("Días de simulación histórica", 30, 365, 60, step=10)
    st.warning(f"El ejercicio empieza el {FECHA_INICIO.strftime('%d/%m/%Y')}. "
               f"Mostrando simulación con últimos {dias_sim} días para prueba.")
    fecha_sim_inicio = hoy - timedelta(days=dias_sim)
    fecha_sim_fin = hoy
    precios = descargar_precios(fecha_sim_inicio, fecha_sim_fin)

    if precios.empty:
        st.error("No se pudieron descargar precios. Verificar conexión.")
        st.stop()

    # Remapear fechas de rebalanceo a fechas reales disponibles
    fechas_disponibles = precios.index
    n = len(fechas_disponibles)
    # Distribuir 4 fechas de rebalanceo equiespaciadas
    indices_reb = [0, n // 4, n // 2, 3 * n // 4]
    fechas_reb_sim = [fechas_disponibles[i].date() for i in indices_reb]

    pesos_sim = {}
    for i, fecha_orig in enumerate(FECHAS_REBALANCEO):
        pesos_sim[fechas_reb_sim[i]] = pesos_por_fecha[fecha_orig]

    benchmark_pesos = {fechas_reb_sim[0]: BENCHMARK}

    portfolio_val = calcular_performance(precios, pesos_sim, es_benchmark=False)
    benchmark_val = calcular_performance(precios, benchmark_pesos, es_benchmark=True)

else:
    precios = descargar_precios(FECHA_INICIO, min(hoy, FECHA_FIN))
    if precios.empty:
        st.error("No se pudieron descargar precios.")
        st.stop()

    benchmark_pesos = {FECHA_INICIO: BENCHMARK}
    portfolio_val = calcular_performance(precios, pesos_por_fecha, es_benchmark=False)
    benchmark_val = calcular_performance(precios, benchmark_pesos, es_benchmark=True)

# --- Gráfico de performance ---
col1, col2 = st.columns([3, 1])

with col1:
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=portfolio_val.index, y=portfolio_val.values,
        name="Tu Portfolio", line=dict(color="#2196F3", width=2.5)
    ))
    fig.add_trace(go.Scatter(
        x=benchmark_val.index, y=benchmark_val.values,
        name="Benchmark (25/25/25/25)", line=dict(color="#FF9800", width=2, dash="dash")
    ))
    fig.update_layout(
        title="Performance: Portfolio vs Benchmark",
        yaxis_title="Valor (base 100)",
        xaxis_title="Fecha",
        hovermode="x unified",
        template="plotly_white",
        height=500,
    )
    st.plotly_chart(fig, use_container_width=True)

# --- Métricas ---
with col2:
    st.subheader("Métricas")

    def calcular_metricas(serie):
        retorno_total = (serie.iloc[-1] / serie.iloc[0] - 1) * 100
        retornos_diarios = serie.pct_change().dropna()
        vol_diaria = retornos_diarios.std()
        sharpe = (retornos_diarios.mean() / vol_diaria * np.sqrt(252)) if vol_diaria > 0 else 0
        drawdown = (serie / serie.cummax() - 1)
        max_dd = drawdown.min() * 100
        return retorno_total, sharpe, max_dd

    ret_p, sharpe_p, dd_p = calcular_metricas(portfolio_val)
    ret_b, sharpe_b, dd_b = calcular_metricas(benchmark_val)

    st.metric("Retorno Portfolio", f"{ret_p:.2f}%", delta=f"{ret_p - ret_b:+.2f}% vs bench")
    st.metric("Retorno Benchmark", f"{ret_b:.2f}%")
    st.metric("Sharpe Portfolio", f"{sharpe_p:.2f}")
    st.metric("Sharpe Benchmark", f"{sharpe_b:.2f}")
    st.metric("Max Drawdown Portfolio", f"{dd_p:.2f}%")
    st.metric("Max Drawdown Benchmark", f"{dd_b:.2f}%")

    if ret_p > ret_b:
        st.success("Tu portfolio SUPERA al benchmark")
    elif ret_p < ret_b:
        st.error("Tu portfolio NO supera al benchmark")
    else:
        st.info("Empate con el benchmark")

# --- Tabla de pesos ---
st.markdown("---")
st.subheader("Resumen de Pesos por Fecha")

resumen = []
for fecha in FECHAS_REBALANCEO:
    p = pesos_por_fecha[fecha]
    resumen.append({
        "Fecha": fecha.strftime("%d/%m/%Y"),
        "GLD %": f"{p['GLD']*100:.1f}",
        "SPY %": f"{p['SPY']*100:.1f}",
        "TLT %": f"{p['TLT']*100:.1f}",
        "Cash %": f"{p['Cash']*100:.1f}",
    })
df_resumen = pd.DataFrame(resumen)
st.dataframe(df_resumen, use_container_width=True, hide_index=True)

# --- Precios actuales ---
st.subheader("Últimos Precios")
if not precios.empty:
    ultimo = precios.iloc[-1]
    cols_precio = st.columns(3)
    for i, activo in enumerate(ACTIVOS):
        cols_precio[i].metric(activo, f"${ultimo[activo]:.2f}")

# --- Texto para el mail ---
st.markdown("---")
st.subheader("Texto para el mail")
fecha_actual = FECHAS_REBALANCEO[0]  # default primera fecha
fecha_sel = st.selectbox("Fecha de entrega", [f.strftime("%d/%m/%Y") for f in FECHAS_REBALANCEO])
for f in FECHAS_REBALANCEO:
    if f.strftime("%d/%m/%Y") == fecha_sel:
        fecha_actual = f
        break

p = pesos_por_fecha[fecha_actual]
texto_mail = f"""Buenas,

Mi posicionamiento de cartera para la fecha {fecha_actual.strftime('%d/%m/%Y')}:

- GLD: {p['GLD']*100:.0f}%
- SPY: {p['SPY']*100:.0f}%
- TLT: {p['TLT']*100:.0f}%
- Cash: {p['Cash']*100:.0f}%

Justificación: [completar]

Saludos,
Agustín González"""

st.code(texto_mail, language=None)

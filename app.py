"""
Système Intelligent de Tracking GPS & DVRP Dynamique — Alger
==============================================================

Corrections apportées par rapport à la version générée initialement :

1. BUG BLOQUANT : `np.random.choice(events_pool, p=...)` sur une liste de dicts
   plantait toujours. → corrigé dans event_handler.py (tirage par index).
2. BUG DE SÉCURITÉ DES THREADS : le callback MQTT écrivait directement dans
   st.session_state depuis un thread réseau. → corrigé via une queue.Queue
   thread-safe, vidée uniquement depuis le thread principal (mqtt_manager.py).
3. BUG D'ALIGNEMENT D'INDEX : après avoir filtré `active_orders` par le temps
   écoulé, l'ancien index du DataFrame ne correspondait plus aux positions
   utilisées par OR-Tools (`route[i]`). → corrigé avec `.reset_index(drop=True)`.
4. MANQUE : aucune contrainte de capacité — un camion pouvait se voir assigner
   un poids illimité. → ajout d'une vraie contrainte de capacité (kg).
5. PERFORMANCE : chaque interaction relançait des appels réseau OSRM.
   → mise en cache (st.cache_data, TTL 5 min) dans dvrp_engine.py.
6. ROBUSTESSE : gestion du cas où OR-Tools ne trouve aucune solution
   (capacité totale insuffisante) au lieu de faire planter l'affichage.
7. MQTT désormais optionnel (case à cocher) plutôt que connecté d'office à
   chaque rechargement de page, ce qui évitait d'accumuler des connexions.
"""

import time
from datetime import datetime

import folium
import pandas as pd
import streamlit as st
from streamlit_folium import st_folium

from benchmark_loader import get_real_algiers_dataset, generate_solomon_benchmark
from dvrp_engine import get_osrm_distance_matrix, get_osrm_route_shape, solve_dvrp_ortools
from event_handler import process_dynamic_event, trigger_random_event
from mqtt_manager import MQTTBridge

st.set_page_config(page_title="DVRP Logistique & Tracking Alger", page_icon="🚚", layout="wide")

# ----------------------------------------------------------------------------
# 1. ÉTAT DE SESSION
# ----------------------------------------------------------------------------
if "logs" not in st.session_state:
    st.session_state.logs = []
if "mqtt_events" not in st.session_state:
    st.session_state.mqtt_events = []
if "mqtt_bridge" not in st.session_state:
    st.session_state.mqtt_bridge = None


def log_event(message: str) -> None:
    st.session_state.logs.insert(0, f"[{datetime.now().strftime('%H:%M:%S')}] {message}")
    st.session_state.logs = st.session_state.logs[:30]


# ----------------------------------------------------------------------------
# 2. EN-TÊTE
# ----------------------------------------------------------------------------
st.title("🚚 Tracking GPS & Optimisation Dynamique des Tournées (DVRP)")
st.caption("Alger — livraison de produits frais / express — OSRM + Google OR-Tools + MQTT")
st.markdown("---")

# ----------------------------------------------------------------------------
# 3. BARRE LATÉRALE
# ----------------------------------------------------------------------------
st.sidebar.header("📁 Jeu de données")
dataset_choice = st.sidebar.selectbox(
    "Source de données",
    ["Cas réel : livraisons Grand Alger", "Benchmark synthétique (type Solomon)"],
)

st.sidebar.header("🕹 Contrôle de la simulation")
num_vehicles = st.sidebar.slider("Camions frigorifiques disponibles", 1, 4, 2)
vehicle_capacity = st.sidebar.slider("Capacité par camion (kg)", 100, 1000, 400, step=50)
sim_time = st.sidebar.slider("Temps écoulé dans la journée (min)", 0, 180, 45, step=15)

st.sidebar.markdown("---")
st.sidebar.header("🚨 Événements dynamiques")
manual_event_type = st.sidebar.selectbox(
    "Déclencher un événement",
    ["AUCUN", "NEW_ORDER", "CANCEL_ORDER", "TRAFFIC_JAM", "ROAD_CLOSED",
     "BREAKDOWN", "TEMP_ALERT", "GEOFENCE_VIOLATION", "CLIENT_ABSENT"],
)
if st.sidebar.button("⚠️ Appliquer l'événement"):
    decision = process_dynamic_event(manual_event_type, {"vehicle_id": "V1"})
    log_event(f"{manual_event_type} → {decision['action']} ({decision['message']})")

st.sidebar.markdown("---")
st.sidebar.header("📡 MQTT (télémétrie temps réel)")
st.sidebar.caption("Broker public de démonstration — non sécurisé, à usage pédagogique uniquement.")
mqtt_enabled = st.sidebar.checkbox("Activer la connexion MQTT", value=False)

if mqtt_enabled and st.session_state.mqtt_bridge is None:
    bridge = MQTTBridge()
    if bridge.start():
        st.session_state.mqtt_bridge = bridge
        st.sidebar.success("Connecté au broker MQTT.")
    else:
        st.sidebar.error("Connexion MQTT impossible (réseau indisponible).")
elif not mqtt_enabled and st.session_state.mqtt_bridge is not None:
    st.session_state.mqtt_bridge.stop()
    st.session_state.mqtt_bridge = None

if st.session_state.mqtt_bridge is not None:
    # On vide la queue thread-safe UNIQUEMENT ici, dans le thread principal Streamlit.
    new_events = st.session_state.mqtt_bridge.drain_events()
    st.session_state.mqtt_events.extend(new_events)
    st.session_state.mqtt_events = st.session_state.mqtt_events[-50:]

    st.sidebar.subheader("Envoyer une commande")
    target_v = st.sidebar.selectbox("Véhicule cible", [f"V{i + 1}" for i in range(num_vehicles)])
    cmd_type = st.sidebar.selectbox("Commande", ["UPDATE_ROUTE", "STOP_ALERT", "REROUTE_TRAFFIC"])
    if st.sidebar.button("Envoyer la commande MQTT"):
        st.session_state.mqtt_bridge.send_command(target_v, {"command": cmd_type, "timestamp": time.time()})
        st.sidebar.info(f"Commande {cmd_type} envoyée à {target_v}")

st.sidebar.markdown("---")
auto_run = st.sidebar.toggle("▶️ Simulation temps réel (auto-refresh)", value=False)
sim_speed = st.sidebar.slider("Fréquence de rafraîchissement (sec)", 2, 10, 3)

# ----------------------------------------------------------------------------
# 4. CHARGEMENT & FILTRAGE DES COMMANDES
# ----------------------------------------------------------------------------
if dataset_choice.startswith("Cas réel"):
    depot_coords, df_orders = get_real_algiers_dataset()
else:
    depot_coords, df_orders = generate_solomon_benchmark()

# Commandes "visibles" à l'instant t de la simulation (release_time <= sim_time)
active_orders = df_orders[df_orders["release_time"] <= sim_time].reset_index(drop=True)

if len(active_orders) == 0:
    st.info("Aucune commande active à cet instant — avancez le curseur « Temps écoulé ».")
    st.stop()

coords_list = [depot_coords] + list(zip(active_orders["lat"], active_orders["lon"]))
demands = [0] + active_orders["demand_kg"].astype(int).tolist()
vehicle_capacities = [vehicle_capacity] * num_vehicles

# ----------------------------------------------------------------------------
# 5. CALCUL DVRP (OSRM + OR-Tools, avec capacité)
# ----------------------------------------------------------------------------
with st.spinner("Calcul des distances et optimisation des tournées..."):
    dist_matrix = get_osrm_distance_matrix(tuple(coords_list))
    optimized_routes = solve_dvrp_ortools(dist_matrix, demands, vehicle_capacities)

total_demand = int(active_orders["demand_kg"].sum())
total_capacity = vehicle_capacity * num_vehicles
if not optimized_routes:
    st.error(
        f"⚠️ Aucune tournée réalisable : {total_demand} kg de commandes pour seulement "
        f"{total_capacity} kg de capacité totale. Augmentez le nombre de véhicules ou "
        f"la capacité par véhicule dans la barre latérale."
    )
    st.stop()

# ----------------------------------------------------------------------------
# 6. INDICATEURS CLÉS (KPI)
# ----------------------------------------------------------------------------
k1, k2, k3, k4 = st.columns(4)
k1.metric("📋 Commandes visibles", f"{len(active_orders)} / {len(df_orders)}")
k2.metric("📦 Volume total", f"{total_demand} kg", delta=f"capacité {total_capacity} kg")
k3.metric("🚛 Camions mobilisés", len(optimized_routes))
k4.metric("⏱️ Horloge simulation", f"+{sim_time} min")

if st.session_state.logs:
    st.info(f"Dernier événement : {st.session_state.logs[0]}")

st.markdown("---")

# ----------------------------------------------------------------------------
# 7. CARTE & DÉTAILS
# ----------------------------------------------------------------------------
col_map, col_details = st.columns([2, 1])

with col_map:
    st.subheader("🗺 Carte des tournées optimisées (réseau routier réel OSRM)")
    m = folium.Map(location=depot_coords, zoom_start=11, tiles="OpenStreetMap")

    folium.Marker(
        depot_coords,
        popup="<b>Dépôt Central — Oued Smar</b>",
        icon=folium.Icon(color="black", icon="home", prefix="fa"),
    ).add_to(m)

    priority_color = {"URGENTE": "red", "HAUTE": "orange", "NORMALE": "blue"}
    for _, row in active_orders.iterrows():
        folium.Marker(
            [row["lat"], row["lon"]],
            popup=(f"<b>{row['client']}</b><br>Charge: {row['demand_kg']} kg<br>"
                   f"Temp. max: {row['temp_max']}°C<br>Fenêtre: {row['time_window']}"),
            tooltip=row["id"],
            icon=folium.Icon(color=priority_color.get(row["priority"], "blue"),
                              icon="shopping-cart", prefix="fa"),
        ).add_to(m)

    route_colors = ["blue", "green", "purple", "orange", "darkred", "cadetblue"]
    for v_idx, route in enumerate(optimized_routes):
        color = route_colors[v_idx % len(route_colors)]
        for i in range(len(route) - 1):
            p1 = coords_list[route[i]]
            p2 = coords_list[route[i + 1]]
            path = get_osrm_route_shape(tuple(p1), tuple(p2))
            folium.PolyLine(path, color=color, weight=4, opacity=0.85,
                             tooltip=f"Camion V{v_idx + 1}").add_to(m)

    st_folium(m, width="100%", height=520, key="dvrp_map")

with col_details:
    st.subheader("📦 Commandes actives")
    st.dataframe(
        active_orders[["id", "client", "demand_kg", "priority", "type"]],
        hide_index=True,
        use_container_width=True,
        height=260,
    )

    st.subheader("🚚 Tournées calculées")
    for v_idx, route in enumerate(optimized_routes):
        stops = [active_orders.iloc[node - 1]["client"] for node in route if node != 0]
        load = sum(active_orders.iloc[node - 1]["demand_kg"] for node in route if node != 0)
        st.markdown(f"**Camion V{v_idx + 1}** — {load}/{vehicle_capacity} kg")
        st.caption(" → ".join(["Dépôt"] + stops + ["Dépôt"]) if stops else "Aucun arrêt")

    st.subheader("📡 Télémétrie MQTT")
    if st.session_state.mqtt_bridge is None:
        st.caption("MQTT désactivé — cochez la case dans la barre latérale pour l'activer.")
    elif st.session_state.mqtt_events:
        for event in reversed(st.session_state.mqtt_events[-5:]):
            st.json(event, expanded=False)
    else:
        st.caption("En attente de télémétrie sur `fleet/telemetry/+`...")

    st.subheader("📋 Journal des décisions DVRP")
    st.text_area("Historique", value="\n".join(st.session_state.logs[:10]), height=150, label_visibility="collapsed")

# ----------------------------------------------------------------------------
# 8. BOUCLE DE SIMULATION TEMPS RÉEL
# ----------------------------------------------------------------------------
if auto_run:
    event = trigger_random_event()
    if event["type"] != "Aucun":
        log_event(f"{event['type']} — {event['desc']}")
    time.sleep(sim_speed)
    st.rerun()

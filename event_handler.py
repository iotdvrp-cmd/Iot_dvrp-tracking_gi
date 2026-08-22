"""
Gestion des événements dynamiques du DVRP.

Correctif important : la version d'origine appelait
    np.random.choice(events_pool, p=[...])
sur une LISTE DE DICTIONNAIRES. np.random.choice exige un tableau de valeurs
scalaires (nombres, strings...) — cet appel plantait systématiquement
(ValueError: a must be 1-dimensional). On tire maintenant un INDEX pondéré,
puis on va chercher le dict correspondant : c'est la façon correcte de faire.
"""

import numpy as np

EVENTS_POOL = [
    {"type": "Aucun", "level": "INFO", "desc": "Fonctionnement normal"},
    {"type": "Nouvelle demande", "level": "GLOBAL", "desc": "Nouveau client prioritaire apparu !"},
    {"type": "Accident / Embouteillage", "level": "LOCAL", "desc": "Route bloquée sur l'itinéraire"},
    {"type": "Alerte Température", "level": "URGENT", "desc": "Rupture de chaîne du froid"},
    {"type": "Sortie Geofence + Arrêt", "level": "ALERTE", "desc": "Véhicule hors zone et à l'arrêt !"},
    {"type": "Panne Véhicule", "level": "GLOBAL", "desc": "Panne critique sur un véhicule"},
]
_WEIGHTS = [0.5, 0.15, 0.15, 0.1, 0.05, 0.05]


def trigger_random_event() -> dict:
    """Tire un événement aléatoire pondéré (corrige le bug np.random.choice sur des dicts)."""
    idx = int(np.random.choice(len(EVENTS_POOL), p=_WEIGHTS))
    return EVENTS_POOL[idx]


# Matrice de décision : quel type d'événement MQTT/capteur déclenche quelle action DVRP.
# Complète la version d'origine qui laissait certains cas (GEOFENCE_VIOLATION, GPS_LOST,
# GPS_UPDATE) non gérés et provoquait donc une action "None" par défaut silencieuse.
EVENT_RULES = {
    "NEW_ORDER":          {"action": "GLOBAL_REOPTIM", "alert_level": "HIGH",
                            "message": "Nouvelle commande : réoptimisation globale des tournées (OR-Tools)."},
    "CANCEL_ORDER":       {"action": "LOCAL_REOPTIM",  "alert_level": "MEDIUM",
                            "message": "Commande annulée : suppression de l'arrêt et recalcul de l'itinéraire."},
    "MODIFY_QUANTITY":    {"action": "LOCAL_REOPTIM",  "alert_level": "MEDIUM",
                            "message": "Quantité modifiée : vérification de la capacité du véhicule."},
    "TRAFFIC_JAM":        {"action": "LOCAL_REOPTIM",  "alert_level": "MEDIUM",
                            "message": "Embouteillage : calcul d'un itinéraire alternatif."},
    "ROAD_CLOSED":        {"action": "GLOBAL_REOPTIM", "alert_level": "HIGH",
                            "message": "Route fermée : re-planification élargie des tournées."},
    "BREAKDOWN":           {"action": "GLOBAL_REOPTIM", "alert_level": "HIGH",
                            "message": "Panne véhicule : redistribution des clients restants."},
    "TEMP_ALERT":         {"action": "LOCAL_REOPTIM",  "alert_level": "URGENT",
                            "message": "Alerte température : livraison passée en priorité absolue."},
    "GEOFENCE_VIOLATION": {"action": "ALERT_ONLY",     "alert_level": "WARNING",
                            "message": "Sortie de zone autorisée : alerte superviseur."},
    "CLIENT_ABSENT":      {"action": "LOCAL_REOPTIM",  "alert_level": "MEDIUM",
                            "message": "Client absent : passage au suivant, réordonnancement de la tournée."},
    "GPS_LOST":           {"action": "NONE",           "alert_level": "WARNING",
                            "message": "Signal GPS perdu : dernière position connue conservée."},
    "GPS_UPDATE":         {"action": "NONE",           "alert_level": "INFO",
                            "message": "Mise à jour GPS standard."},
}


def process_dynamic_event(event_type: str, event_data: dict | None = None) -> dict:
    """Évalue l'importance d'un événement et détermine l'action DVRP requise."""
    event_data = event_data or {}
    rule = EVENT_RULES.get(event_type, {"action": "NONE", "alert_level": "INFO", "message": "Événement inconnu."})
    decision = dict(rule)
    decision["event_type"] = event_type
    decision["vehicle_id"] = event_data.get("vehicle_id", "N/A")
    return decision

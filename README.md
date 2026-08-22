# 🚚 DVRP & Tracking GPS Temps Réel — Alger

Application Streamlit de suivi GPS et de ré-optimisation dynamique de tournées de
livraison (DVRP), avec calcul d'itinéraires réels (OSRM), optimisation exacte
(Google OR-Tools, avec contrainte de capacité), et télémétrie temps réel (MQTT).

## Installation locale

```bash
git clone <votre-repo>
cd dvrp-tracking
python -m venv venv
source venv/bin/activate      # Windows : venv\Scripts\activate
pip install -r requirements.txt
streamlit run app.py
```

## Simuler des données GPS/IoT en direct (optionnel)

Dans un second terminal :

```bash
python simulate_iot_publisher.py
```

Puis, dans l'application, cochez « Activer la connexion MQTT » dans la barre latérale.

## Déploiement sur Streamlit Community Cloud

1. Poussez ce dossier sur un dépôt GitHub public (ou privé si vous avez un compte payant).
2. Allez sur https://share.streamlit.io
3. Connectez votre compte GitHub, sélectionnez le dépôt et pointez sur `app.py`.
4. Cliquez sur **Deploy**.

## Limites à connaître (usage démonstration / pédagogique)

- **OSRM public (`router.project-osrm.org`)** : serveur de démonstration gratuit,
  débit limité et sans garantie de disponibilité. Pour un usage en production,
  hébergez votre propre instance OSRM ou utilisez un service payant
  (OpenRouteService, Mapbox, Google Routes API...).
- **Broker MQTT public (`broker.hivemq.com`)** : accessible à tout le monde,
  sans authentification. Ne jamais y envoyer de données sensibles réelles.
  Pour un vrai projet, utilisez un broker privé (HiveMQ Cloud, EMQX, AWS IoT...).
- **Résolution OR-Tools** : limitée à 5 secondes de recherche pour rester
  réactive dans l'interface ; sur de très grosses instances (>200 clients),
  augmentez `time_limit_s` dans `dvrp_engine.py`.

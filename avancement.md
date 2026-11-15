# Avancement du projet Ember

Dernière vérification : 15 novembre 2026

## État général

Le prototype Streamlit fonctionne avec des données synthétiques (« mock ») stockées en Parquet et interrogées avec DuckDB. Les données mock servent à développer et tester l’interface ; elles ne représentent pas des observations réelles de feux.

Le mode par défaut est `mock`. Le réglage `DATA_MODE` accepte `mock` ou `real` et affiche une bannière de démonstration sur les deux pages en mode mock. Attention : passer `DATA_MODE=real` enlève la bannière, mais ne transforme ni ne remplace les données. Il faudra pointer les chemins Parquet de `app/config.py` vers les vrais fichiers et valider ceux-ci avant toute interprétation scientifique.

## Déjà implémenté

### Données de démonstration

- Génération des fichiers `grid_monthly.parquet`, `calibration.parquet` et `validation.parquet` dans `data/processed/`.
- Schéma conforme aux colonnes et types indiqués dans `SPEC.txt`.
- Couverture de démonstration : Cameroun, cellules de 0,1 degré, de 2000-01 à 2026-10.
- Données clairsemées : seules les cellules-mois avec un compte positif sont écrites. Une zone volontairement vide est conservée pour tester le cas sans activité.
- Saisonnalité synthétique avec un pic marqué pendant la saison sèche dans le nord, et bruit annuel modéré. Les comptes harmonisés ne présentent pas de saut de niveau marqué en 2012.
- Les derniers mois de démonstration sont marqués provisoires. Les sources MODIS/VIIRS simulées suivent la convention du projet.
- Les valeurs de `calibration.parquet` et `validation.parquet` sont des exemples synthétiques, pas des résultats scientifiques.

### Application et analyses

- Application Streamlit multipage avec page principale et page **Method**.
- Sélection d’une zone par dessin Folium (rectangle ou polygone), par coordonnées de boîte, ou avec **Try Cameroon** ; **Clear area** retire la sélection. Une seule zone active est conservée.
- Sélection de la période par année et mois, avec le début et la fin du jeu de données comme valeurs initiales.
- Requêtes DuckDB sur Parquet, mises en cache par zone et période. Pour un polygone, les candidats sont d’abord filtrés par son rectangle englobant, puis les centres des cellules sont testés avec Shapely.
- Appartenance spatiale évaluée au centre de la cellule : `(cell_lat + 0.05, cell_lon + 0.05)`.
- Refus des zones de plus de 2 000 000 km² à l’aide d’une approximation équirectangulaire ; une note indique que l’estimation est approximative.
- Calendrier mensuel zéro-rempli, avec les années en lignes, les mois en colonnes, l’échelle viridis, le compte et la source au survol, les mois provisoires marqués et la période Terra-only signalée.
- Profil saisonnier : médiane et intervalle p25-p75 par mois, avec le mois de pic dans le titre.
- Carte d’anomalie pour le dernier mois présent dans les données avant le mois courant. Le calcul exclut l’année testée de la référence ; le ratio, le percentile, le statut provisoire et le libellé textuel/coloré sont affichés. Si la médiane de référence vaut zéro, le libellé est « no baseline ».
- Téléchargement CSV du calendrier ; le nom comprend la zone et la période.
- États d’interface : aucune zone sélectionnée, chargement, absence de feux formulée en texte et erreur avec action de réessai.
- Page **Method** : les sept étapes de `SPEC.txt`, la formule de calibration, le tableau lu depuis le Parquet de validation, une explication de `r` et MAPE, les trois limites connues et une mention TODO pour le texte exact de citation.
- En mode mock, la bannière générale est visible sur les deux pages et le tableau de validation porte la légende « PLACEHOLDER values from synthetic data. Not a real validation result. » En mode real, ces avertissements de démonstration sont masqués.

## Vérifications exécutées

Le 15 novembre 2026, `python scripts/check_data.py` a réussi. Le script contrôle notamment les schémas Parquet, les doublons, les sommes directes DuckDB, les polygones, la limite de superficie, le cas sans feux, le mode de données et les bannières avec AppTest.

Valeurs obtenues lors de cette exécution :

- Validation : une ligne `Cameroon mock`, années de réserve `2018,2020`, `r = 0.830`, `MAPE = 24.7`. Ces deux mesures sont des placeholders.
- Moyenne des totaux annuels 2006-2011 : `4348.67` ; 2012-2017 : `4450.25` ; différence relative : `2.34 %`.
- Les trois calendriers comparés aux sommes directes DuckDB concordent : `130.00 = 130.00`, `865.80 = 865.80` et `94.83 = 94.83`.
- Total du polygone rectangle du Cameroun et de sa boîte : `117003.15` chacun. Total du triangle inclus : `40337.14`.
- Polygone océanique sans cellule active : total `0.00`, requête terminée sans erreur.
- Exemple de polygone trop grand : environ `22,462,190 km²`, refus explicite.
- Les AppTests confirment la bannière en mode mock sur les deux pages et son absence en mode real sur les deux pages. Le mode invalide produit une erreur qui indique les deux valeurs acceptées.
- `pip check` et les diagnostics éditeur ont également été exécutés lors de la dernière validation ; aucun conflit de dépendance ni erreur sur les fichiers vérifiés.

Ces vérifications établissent le comportement du prototype et de ses données de test ; elles ne valident pas encore la qualité d’une harmonisation réelle.

## À faire

### Données réelles et validation scientifique

- Récupérer auprès du coéquipier les fichiers Parquet réels, vérifier leurs schémas, leurs valeurs manquantes et leurs périodes de couverture, puis adapter `PARQUET_PATHS` dans `app/config.py`.
- Contrôler que les règles de calibration, les facteurs `k`, les valeurs `n_modis`/`n_viirs`, les indicateurs provisoires et la validation ont été produits conformément à la méthode convenue.
- Remplacer les valeurs de démonstration du tableau de validation par les résultats réels, après vérification indépendante.
- Ajouter le texte exact de citation fourni par NASA FIRMS ; il est volontairement laissé en TODO et n’a pas été inventé.
- Mesurer la performance avec le jeu réel, notamment la cible SPEC de moins de 3 secondes pour une requête de taille pays.
- Compléter les tests d’accessibilité et vérifier les contrôles clavier sur les navigateurs cibles.

### Fonctionnalités SPEC restantes

- **P1 F8 partiel :** l’entrée d’une boîte latitude/longitude existe ; la saisie rayon n’est pas implémentée.
- **P1 F9 :** graphique des totaux annuels avec ligne de tendance.
- **P1 F10 :** choix entre deux palettes adaptées au daltonisme.
- **P1 F11 :** téléchargement des hotspots individuels en CSV.
- **P1 F12 :** raccourci ou liste de pays.

Le périmètre explicitement reporté reste reporté : graphique annuel, changement de palette, export des hotspots individuels et liste de pays. Le rapport **Method** et l’export CSV du calendrier sont, eux, déjà présents.

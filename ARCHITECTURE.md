# Architecture de l'Outil de Migration EPG

## Vue d'Ensemble

L'outil de migration EPG est conçu pour extraire de manière ciblée des EPG et leurs dépendances depuis une fabric ACI, contrairement au reverse engineering complet qui extrait TOUTE la configuration.

## Différences avec le Reverse Engineering Complet

| Aspect | Reverse Engineering | Migration EPG |
|--------|-------------------|---------------|
| **Scope** | Toute la fabric | EPG sélectionnés uniquement |
| **Input** | Aucun (extraction complète) | Liste d'EPG (epg_list.yml) |
| **Filtrage** | Exclut tenants système | Filtre par EPG + relations |
| **Use Case** | Backup, documentation | Migration ciblée |
| **Taille output** | Large (toute la config) | Réduit (EPG + dépendances) |

## Architecture du Code

```
migration/
├── extract_epg_migration.py        # Script principal (orchestrateur)
├── migration_tasks/                # Logique d'extraction (copié de reverse)
│   ├── base_task.py                # Classe de base pour extraction
│   ├── epg.py                      # Logique spécifique EPG
│   ├── bd.py                       # Logique Bridge Domain
│   ├── domain_to_vlan_pool.py      # Logique Domain-Pool
│   └── ...                         # Autres tâches
├── aci_mapping.yml                 # Mapping attributs ACI ↔ CSV (copié)
├── epg_list.yml                    # Configuration: liste des EPG
├── csv_out/                        # CSV générés (sortie)
└── epg_migration.xlsx              # Excel final (sortie)
```

## Workflow du Script

### Phase 1: Initialisation
```
1. Charger epg_list.yml
   ├─ Lire la liste des EPG demandés
   └─ Validation: tenant, ap, epg requis

2. Charger inventory.yml
   ├─ Récupérer credentials ACI
   └─ Validation: hostname, username, password

3. Charger aci_mapping.yml
   └─ Mapping attributs ACI → CSV
```

### Phase 2: Extraction ACI
```
4. Connexion APIC
   ├─ POST /api/aaaLogin.json
   └─ Récupération token de session

5. Extraction configuration
   ├─ GET /api/node/mo/uni.json?query-target=subtree...
   ├─ Toute la configuration en JSON
   └─ Sauvegarde en mémoire (self.aci_data)
```

### Phase 3: Identification des Objets Liés
```
6. Pour chaque EPG demandé:
   ├─ Trouver l'objet fvAEPg correspondant (recherche récursive)
   ├─ Extraire tenant, ap (depuis DN)
   ├─ Extraire BD lié (fvRsBd dans children)
   └─ Extraire domains liés (fvRsDomAtt dans children)

7. Pour chaque BD trouvé:
   ├─ Trouver l'objet fvBD correspondant
   └─ Extraire VRF lié (fvRsCtx dans children)

8. Pour chaque Domain trouvé:
   ├─ Trouver la relation infraRsVlanNs (phys) ou l3extRsVlanNs (l3dom)
   └─ Extraire VLAN Pool lié (depuis tDn)

9. Pour chaque Domain trouvé:
   ├─ Trouver les relations infraRsDomP
   └─ Extraire AEP parents (depuis DN)

Résultat: Sets d'objets filtrés
   ├─ filtered_objects['epg']        = {dn1, dn2, ...}
   ├─ filtered_objects['bd']         = {tenant/bd1, tenant/bd2, ...}
   ├─ filtered_objects['domain']     = {(type, name), ...}
   ├─ filtered_objects['vlan_pool']  = {pool1, pool2, ...}
   └─ filtered_objects['aep']        = {aep1, aep2, ...}
```

### Phase 4: Génération CSV
```
10. Créer templates CSV vides
    ├─ Depuis aci_fabric_empty.xlsx (préféré)
    └─ Ou depuis ../csv/ (fallback)

11. Pour chaque type d'objet (tenant, vrf, bd, epg, domain, ...):
    ├─ Charger la classe de tâche (migration_tasks/*.py)
    ├─ Exécuter extract() → trouve tous les objets du type
    ├─ Exécuter get_rows() → convertit en lignes CSV
    ├─ Filtrer avec filter_task_data() → ne garde que les objets liés
    └─ Écrire dans csv_out/[type].csv

Exemple pour EPG:
   migration_tasks.epg.EpgTask
   ├─ extract() → trouve tous fvAEPg
   ├─ get_rows() → convertit en {tenant, ap, epg, bd, ...}
   ├─ filter_task_data() → garde seulement les EPG dans filtered_objects['epg']
   └─ Écrit dans csv_out/epg.csv
```

### Phase 5: Génération Excel
```
12. Créer epg_migration.xlsx
    ├─ Pour chaque CSV dans csv_out/
    ├─ Lire le CSV
    ├─ Créer un onglet Excel
    └─ Écrire les données

Résultat:
   epg_migration.xlsx avec un onglet par type d'objet
```

## Classes et Modules

### EPGMigrationExtractor (extract_epg_migration.py)
**Responsabilité**: Orchestration complète du processus

**Attributs principaux**:
- `aci_data` : Configuration ACI complète (JSON)
- `epg_list` : Liste des EPG à extraire
- `filtered_objects` : Sets d'objets identifiés pour migration
- `mapping` : Mapping attributs ACI ↔ CSV

**Méthodes principales**:
| Méthode | Rôle |
|---------|------|
| `load_epg_list()` | Charge epg_list.yml |
| `extract_from_apic()` | Connexion + extraction ACI |
| `identify_related_objects()` | Trouve BD, Domain, Pool, AEP liés |
| `generate_csv_templates()` | Crée CSV vides |
| `populate_csvs()` | Remplit CSV avec données filtrées |
| `filter_task_data()` | Filtre les lignes selon filtered_objects |
| `generate_excel()` | CSV → Excel |

### BaseTask (migration_tasks/base_task.py)
**Responsabilité**: Extraction générique d'objets ACI

**Méthodes**:
- `extract()` : Recherche récursive d'objets par classe ACI
- `get_rows()` : Conversion objets ACI → lignes CSV
- `_find_objects_recursive()` : Parcours récursif du JSON

### Tâches Spécialisées
Héritent de `BaseTask` pour logique personnalisée:

**epg.py (EpgTask)**:
- Extrait AP depuis DN
- Extrait BD depuis enfant fvRsBd

**domain_to_vlan_pool.py (DomainToVlanPoolTask)**:
- Parse le DN pour trouver domain type
- Parse le tDn pour trouver pool name

## Flux de Données

```
┌─────────────────┐
│  epg_list.yml   │  (Input: Liste EPG)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  APIC REST API  │  (Extraction: Toute la config)
└────────┬────────┘
         │
         ▼
┌─────────────────┐
│  aci_data.json  │  (En mémoire: Config complète)
└────────┬────────┘
         │
         ▼
┌─────────────────────────┐
│ identify_related_objects│  (Analyse: Graphe de dépendances)
└────────┬────────────────┘
         │
         ▼
┌──────────────────────┐
│ filtered_objects     │  (Filtrage: EPG + dépendances)
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ migration_tasks/*.py │  (Extraction: Par type d'objet)
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ filter_task_data()   │  (Filtrage: Lignes à garder)
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│   csv_out/*.csv      │  (Output: CSV filtrés)
└────────┬─────────────┘
         │
         ▼
┌──────────────────────┐
│ epg_migration.xlsx   │  (Output final: Excel)
└──────────────────────┘
```

## Graphe de Dépendances ACI

Le script suit ces relations ACI:

```
Tenant
  └─ Application Profile (AP)
       └─ Endpoint Group (EPG)  ← Point d'entrée
            ├─ fvRsBd → Bridge Domain (BD)
            │    ├─ fvRsCtx → VRF
            │    ├─ fvSubnet → Subnets
            │    └─ fvRsBDToOut → L3Out
            │
            └─ fvRsDomAtt → Domain (Physical/L3)
                 ├─ infraRsVlanNs → VLAN Pool
                 │    └─ fvnsEncapBlk → Encap Blocks
                 │
                 └─ ← infraRsDomP ← AEP
                      └─ infraRsAttEntP → EPG (optionnel)
```

## Filtrage Intelligent

Le filtrage se fait en 2 passes:

**Passe 1: Identification (identify_related_objects)**
- Trouve les EPG demandés
- Remonte la chaîne de dépendances
- Peuple `filtered_objects`

**Passe 2: Extraction (filter_task_data)**
- Pour chaque ligne CSV générée
- Vérifie si l'objet est dans `filtered_objects`
- Ne garde que les lignes pertinentes

Exemple pour `domain_to_vlan_pool.csv`:
```python
# Ligne générée par DomainToVlanPoolTask
row = {'domain': 'PHY_DOM', 'domain_type': 'phys', 'vlan_pool': 'POOL1'}

# Filtrage
keep = (row['domain_type'], row['domain']) in filtered_objects['domain'] and \
       row['vlan_pool'] in filtered_objects['vlan_pool']

# Résultat: Garde seulement si domain ET pool sont liés aux EPG
```

## Avantages de cette Architecture

✅ **Réutilisation du code**: migration_tasks = copie de reverse_tasks
✅ **Filtrage précis**: Seuls les objets liés sont extraits
✅ **Scalabilité**: Fonctionne avec 1 EPG comme avec 100
✅ **Maintenabilité**: Logique séparée (extraction vs filtrage)
✅ **Extensibilité**: Facile d'ajouter de nouveaux types d'objets

## Limites Connues

⚠️ **Wildcards non supportés** : Pas de support pour `epg: "*"` (à implémenter)
⚠️ **Filtrage par tags** : Pas de support des tags ACI (à implémenter)
⚠️ **Validation EPG** : Pas de vérification si l'EPG existe avant extraction
⚠️ **Contracts** : Les contracts ne sont pas extraits automatiquement

## Améliorations Futures

1. **Support wildcards** : Permettre `ap: "*"` pour tous les AP
2. **Validation préalable** : Vérifier l'existence des EPG avant extraction complète
3. **Extraction contracts** : Inclure les contracts liés aux EPG
4. **Mode incrémental** : Ajouter des EPG sans tout ré-extraire
5. **Comparaison** : Comparer config ACI vs CSV existants
6. **Dry-run** : Mode simulation sans extraction réelle

## Dépendances

**Python 3.8+**
- `pandas` : Manipulation CSV/Excel
- `openpyxl` : Écriture Excel
- `pyyaml` : Lecture YAML
- `requests` : API REST ACI
- `urllib3` : Gestion SSL

## Performance

**Temps d'exécution** (approximatif):
- Connexion APIC: 1-2s
- Extraction config: 10-60s (selon taille fabric)
- Identification objets: 5-10s
- Génération CSV: 5-10s
- Génération Excel: 2-5s

**Total**: ~30-90 secondes pour une extraction typique

**Optimisations possibles**:
- Cache de la config ACI (éviter re-téléchargement)
- Extraction ciblée (query par EPG au lieu de toute la config)
- Parallélisation des tâches

## Sécurité

✅ **SSL désactivé** : urllib3.disable_warnings (APIC souvent avec certificat auto-signé)
⚠️ **Credentials en clair** : inventory.yml contient password (utiliser Ansible Vault en production)
✅ **Lecture seule** : Aucune modification de l'ACI
✅ **Session temporaire** : Token APIC expire après utilisation

## Support et Contributions

Ce code est inspiré du reverse engineering complet (`reverse/`) mais optimisé pour la migration ciblée.

Pour toute modification, privilégier:
1. Modification dans `reverse/` si applicable à tout le reverse
2. Modification dans `migration/` si spécifique à la migration EPG

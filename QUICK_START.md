# 🚀 Guide de Démarrage Rapide - Migration EPG

## Utilisation en 3 étapes

### Étape 1: Configurer la liste des EPG

Éditez `epg_list.yml` et ajoutez vos EPG:

```yaml
---
epgs:
  - tenant: Production
    ap: App1
    epg: Web_EPG

  - tenant: Production
    ap: App1
    epg: App_EPG
```

### Étape 2: Exécuter l'extraction

```bash
cd /home/jfg/ai/aci/ansible_csv/migration
python3 extract_epg_migration.py
```

### Étape 3: Utiliser les résultats

Les fichiers générés sont prêts à l'emploi:

**Option A: Déployer avec Ansible**
```bash
cd migration
# Copier le fichier Excel dans le répertoire parent
cp epg_migration.xlsx ../

# Générer un déploiement depuis l'Excel
cd ..
python3 excel_to_csv_simple.py epg_migration.xlsx

# Déployer
cd epg_migration/
ansible-playbook epg_migration.yml -i inventory.yml
```

**Option B: Utiliser les CSV directement**
```bash
# Les CSV sont dans migration/csv_out/
ls -lh migration/csv_out/
```

## 📊 Ce qui est extrait automatiquement

Pour chaque EPG demandé, le script extrait:

✅ **EPG** (Endpoint Group)
- Configuration complète
- Description, priorité, etc.

✅ **Bridge Domain** lié à l'EPG
- Configuration BD
- Subnets (si présents)
- Relations BD → L3Out (si présentes)

✅ **Physical/L3 Domains** liés à l'EPG
- Tous les domains attachés à l'EPG
- Type de domain (phys, l3dom)

✅ **VLAN Pools** liés aux domains
- Pools de VLANs utilisés
- Blocs d'encapsulation (ranges)
- Mode d'allocation (static/dynamic)

✅ **AEP** (Attachable Entity Profiles) liés
- AEP connectés aux domains
- Relations AEP → Domain
- Relations AEP → EPG

✅ **VRF** lié au Bridge Domain
- Contexte VRF utilisé par le BD

✅ **Application Profile** parent de l'EPG

✅ **Tenant** parent

## 🔍 Relations extraites

Le script extrait également toutes les relations:
- `epg_to_domain.csv` - EPG → Domain
- `domain_to_vlan_pool.csv` - Domain → VLAN Pool
- `aep_to_domain.csv` - AEP → Domain
- `aep_to_epg.csv` - AEP → EPG (si présentes)
- `bd_to_l3out.csv` - BD → L3Out (si présentes)

## 📁 Fichiers générés

```
migration/
├── csv_out/                    # CSV générés
│   ├── tenant.csv              # 1 ligne par tenant trouvé
│   ├── vrf.csv                 # VRFs liés
│   ├── ap.csv                  # Application Profiles
│   ├── bd.csv                  # Bridge Domains
│   ├── bd_subnet.csv           # Subnets des BD
│   ├── epg.csv                 # EPG demandés
│   ├── domain.csv              # Domains liés
│   ├── domain_to_vlan_pool.csv # Relations Domain-Pool
│   ├── vlan_pool.csv           # VLAN Pools
│   ├── vlan_pool_encap_block.csv # Blocs VLAN
│   ├── aep.csv                 # AEP
│   ├── aep_to_domain.csv       # Relations AEP-Domain
│   ├── epg_to_domain.csv       # Relations EPG-Domain
│   └── ...
└── epg_migration.xlsx          # Excel final (tous les CSV)
```

## 🎯 Exemple complet

### Scénario: Migrer 2 EPG de Production

**1. Configurer `epg_list.yml`:**
```yaml
---
epgs:
  - tenant: Production
    ap: WebApp
    epg: Frontend_EPG

  - tenant: Production
    ap: WebApp
    epg: Backend_EPG
```

**2. Exécuter:**
```bash
python3 extract_epg_migration.py
```

**3. Résultat attendu:**
```
================================================================================
 EPG MIGRATION EXTRACTOR - ACI to CSV/Excel
================================================================================

📋 Chargement de la liste des EPG...
✅ 2 EPG(s) à extraire
   - Production/WebApp/Frontend_EPG
   - Production/WebApp/Backend_EPG

🔑 Connexion à https://192.168.0.245 en tant que admin...
✅ Authentification réussie

📥 Téléchargement de la configuration ACI (cela peut prendre du temps)...
✅ Configuration téléchargée

🔍 Identification des objets liés aux EPG...
   ✅ Tenants: 1
   ✅ Application Profiles: 1
   ✅ EPG: 2
   ✅ Bridge Domains: 2
   ✅ VRFs: 1
   ✅ Domains: 1
   ✅ VLAN Pools: 1
   ✅ AEP: 1

📝 Génération des templates CSV...
✅ Templates CSV créés dans migration/csv_out/

📊 Extraction et filtrage des données...
   ✅ tenant                         -> 1 lignes
   ✅ vrf                            -> 1 lignes
   ✅ ap                             -> 1 lignes
   ✅ bd                             -> 2 lignes
   ✅ epg                            -> 2 lignes
   ✅ domain                         -> 1 lignes
   ✅ domain_to_vlan_pool            -> 1 lignes
   ✅ vlan_pool                      -> 1 lignes
   ✅ vlan_pool_encap_block          -> 1 lignes
   ✅ aep                            -> 1 lignes
   ✅ aep_to_domain                  -> 1 lignes
   ✅ epg_to_domain                  -> 2 lignes

✅ Total: 15 lignes extraites

📁 Génération du fichier Excel: migration/epg_migration.xlsx
🎉 Fichier Excel généré avec succès!

================================================================================
✅ EXTRACTION TERMINÉE AVEC SUCCÈS!
================================================================================
📂 Fichiers CSV: migration/csv_out/
📊 Fichier Excel: migration/epg_migration.xlsx
```

## ⚙️ Configuration avancée

### Utiliser des wildcards

Pour extraire TOUS les EPG d'une Application Profile:

```yaml
epgs:
  - tenant: Production
    ap: WebApp
    epg: "*"
```

> Note: La fonctionnalité wildcard nécessite une modification du script (à implémenter si besoin)

## 🔧 Troubleshooting

### "Fichier inventory.yml introuvable"
→ Assurez-vous que `../inventory.yml` existe avec les credentials ACI

### "0 EPG trouvés"
→ Vérifiez les noms exacts (tenant/ap/epg) dans l'ACI

### "Authentification échouée"
→ Vérifiez les credentials dans `inventory.yml`

### "ImportError: No module named 'pandas'"
→ Installez les dépendances: `pip3 install pandas openpyxl pyyaml requests`

## 📚 Documentation complète

Voir [README.md](README.md) pour plus de détails.

## 🆘 Support

En cas de problème:
1. Vérifier les prérequis (credentials, liste EPG)
2. Consulter les logs du script
3. Vérifier la connectivité à l'APIC

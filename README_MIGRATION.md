# EPG Migration Tool - Guide d'Utilisation

## ✅ 100% AUTONOME - Aucune Dépendance!

Le répertoire `migration/` est maintenant **totalement autonome**:
- ❌ Plus besoin d'inventory.yml
- ❌ Aucune dépendance externe
- ✅ Demande les credentials de manière interactive
- ✅ Portable - peut être copié n'importe où

---

## 📋 Prérequis

**Bibliothèques Python requises:**
```bash
pip install pandas openpyxl requests pyyaml urllib3
```

---

## 🚀 Utilisation

### 1. Lister tous les EPG de la fabric

Pour voir tous les EPG disponibles avec leurs noms exacts:

```bash
python3 list_all_epgs.py
```

**Le script va demander:**
```
================================================================================
 CONNEXION À L'ACI FABRIC
================================================================================

🌐 Adresse IP de l'APIC: 192.168.0.245
👤 Nom d'utilisateur: admin
🔒 Mot de passe: ********
```

**Résultat:**
```
================================================================================
TOUS LES EPG DANS VOTRE FABRIC ACI (hors tenants système):
================================================================================

📦 Tenant: Production
  📁 AP: Database_AP
     - DBServers_EPG
  📁 AP: ERP_AP
     - AppServers_EPG
...
```

---

### 2. Préparer la liste des EPG à extraire

Éditer `epg_list.yml` avec les EPG que vous voulez migrer:

```yaml
---
tenant: Production
ap: Database_AP
epgs:
  - DBServers_EPG

---
tenant: Production
ap: ERP_AP
epgs:
  - AppServers_EPG

---
tenant: Development
ap: DevApp_AP
epgs:
  - DevApp_EPG
```

**⚠️ Important:** Utilisez les noms EXACTS affichés par `list_all_epgs.py`

---

### 3. Extraire la configuration

Lancer l'extraction:

```bash
python3 extract_epg_migration.py
```

**Le script va demander:**
```
================================================================================
 EPG MIGRATION EXTRACTOR - Version Simplifiée
================================================================================

📋 Chargement de la liste des EPG...
✅ 3 EPG(s) à extraire:
   - Production/Database_AP/DBServers_EPG
   - Production/ERP_AP/AppServers_EPG
   - Development/DevApp_AP/DevApp_EPG

================================================================================
 CONNEXION À L'ACI FABRIC
================================================================================

🌐 Adresse IP de l'APIC: 192.168.0.245
👤 Nom d'utilisateur: admin
🔒 Mot de passe: ********
```

**Ensuite le script va:**
1. Se connecter à l'APIC
2. Télécharger la configuration
3. Extraire les EPG et leurs dépendances:
   - Bridge Domains (avec VRF)
   - Physical Domains
   - VLAN Pools et Encap Blocks
   - AEPs (Attachable Entity Profiles)
   - Interface Policy Groups
   - Toutes les relations entre ces objets

---

## 📂 Fichiers Générés

Après l'extraction, vous trouverez:

### CSV (dans csv_out/)
```
csv_out/
├── epg.csv                              # EPGs extraits
├── bd.csv                               # Bridge Domains
├── domain.csv                           # Physical/L3 Domains
├── vlan_pool.csv                        # VLAN Pools
├── vlan_pool_encap_block.csv           # VLAN Ranges
├── aep.csv                              # Attachable Entity Profiles
├── interface_policy_leaf_policy_gr.csv # Interface Policy Groups
├── epg_to_domain.csv                   # Relations EPG → Domain
├── domain_to_vlan_pool.csv             # Relations Domain → Pool
├── aep_to_domain.csv                   # Relations AEP → Domain
└── aep_to_epg.csv                      # Relations AEP → EPG
```

### Excel
```
epg_migration.xlsx    # Tous les CSV dans un seul fichier Excel
                      # (1 onglet par type d'objet)
```

---

## 🔐 Sécurité

- Le mot de passe est **masqué** pendant la saisie (utilise `getpass`)
- Les credentials ne sont **jamais sauvegardés** sur disque
- Ils sont uniquement utilisés en mémoire pendant l'exécution
- SSL warnings désactivés (normal pour ACI avec certificats auto-signés)

---

## 📊 Objets Extraits

| Type d'Objet | Description | Filtrage |
|--------------|-------------|----------|
| EPG | Endpoint Groups demandés | ✅ Liste epg_list.yml |
| Bridge Domain | BDs liés aux EPGs | ✅ Uniquement ceux liés |
| VRF | Contextes de routage | ✅ Via BD |
| Domain | Domaines physiques/L3 | ✅ Uniquement ceux liés aux EPGs |
| VLAN Pool | Pools de VLANs | ✅ Via Domains |
| Encap Block | Ranges de VLANs | ✅ Via Pools |
| AEP | Profils d'entité | ✅ Via Domains |
| Policy Group | Groupes de politiques | ✅ Via AEPs |

**Le script extrait UNIQUEMENT les objets liés aux EPGs demandés, pas toute la fabric!**

---

## 🎯 Exemple Complet

```bash
# 1. Lister les EPG disponibles
python3 list_all_epgs.py
# → Entrer IP: 192.168.0.245
# → Entrer user: admin
# → Entrer pass: ********
# → Note les noms exacts des EPGs

# 2. Éditer epg_list.yml avec les EPGs choisis
nano epg_list.yml

# 3. Lancer l'extraction
python3 extract_epg_migration.py
# → Entrer IP: 192.168.0.245
# → Entrer user: admin
# → Entrer pass: ********
# → Attendre l'extraction...

# 4. Vérifier les résultats
ls -lh csv_out/
ls -lh epg_migration.xlsx

# 5. Les CSV sont prêts pour déploiement avec Ansible!
```

---

## 🔧 Compatibilité

Les CSV générés sont **100% compatibles** avec les playbooks Ansible du projet principal:
- Mêmes noms de colonnes
- Même structure
- Validés contre les task files

Vous pouvez copier les CSV générés dans le projet principal et lancer les playbooks de déploiement directement!

---

## ❓ Dépannage

### Erreur de connexion
```
❌ Échec authentification: ...
```
**Solution:** Vérifier IP, username, password

### EPG non trouvé
```
⚠️  EPG non trouvé: Production/Database_AP/DBServers_EPG
```
**Solution:** Utiliser `list_all_epgs.py` pour obtenir le nom EXACT

### Aucun Policy Group trouvé
```
✅ Interface Policy Groups: 0
```
**Solution:** Normal si aucun Policy Group n'est lié aux AEPs dans votre fabric

---

## 📦 Portabilité

Ce répertoire est **100% portable**:

```bash
# Copier sur une autre machine
scp -r migration/ user@autre-machine:/path/

# Utiliser immédiatement
cd /path/migration/
python3 extract_epg_migration.py
```

Aucune configuration ou dépendance externe nécessaire!

---

**Date:** 2025-12-04  
**Status:** ✅ 100% Autonome - Aucune Dépendance  
**Version:** 2.0 - Interactive Credentials

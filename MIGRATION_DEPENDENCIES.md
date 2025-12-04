# Dépendances du Répertoire Migration

## Analyse des Dépendances

### ✅ Dépendance UNIQUE au Projet Principal

Le répertoire `migration/` a **UNE SEULE** dépendance externe:

```
migration/
    └── ../inventory.yml  ← SEULE DÉPENDANCE
```

**Fichiers concernés:**
- `extract_epg_migration.py` (ligne 28)
- `list_all_epgs.py` (ligne 13)

**Raison:** Les deux scripts ont besoin des credentials ACI (hostname, username, password) pour se connecter à l'APIC.

---

### ❌ Aucune Dépendance Vers:

- ✅ **production_ready/** - Jamais touché ni lu
- ✅ **tasks/** - Jamais lu directement (seulement respecte la structure des colonnes)
- ✅ **csv/** - Jamais lu (génère ses propres CSV dans csv_out/)
- ✅ **excel_to_csv_simple.py** - Pas utilisé
- ✅ Autres scripts du projet principal

---

### 🔄 Fichiers Autonomes dans migration/

```
migration/
├── extract_epg_migration.py       # Script principal ✅
├── list_all_epgs.py                # Script utilitaire ✅
├── epg_list.yml                    # Config EPG à extraire ✅
├── csv_out/                        # CSV générés ✅
│   ├── epg.csv
│   ├── bd.csv
│   ├── domain.csv
│   ├── vlan_pool.csv
│   ├── vlan_pool_encap_block.csv
│   ├── aep.csv
│   ├── interface_policy_leaf_policy_gr.csv
│   ├── epg_to_domain.csv
│   ├── domain_to_vlan_pool.csv
│   ├── aep_to_domain.csv
│   └── aep_to_epg.csv
└── epg_migration.xlsx              # Excel généré ✅
```

---

### 📦 Dépendances Python

```python
import os
import sys
import json
import yaml
import pandas as pd
import requests
import urllib3
import re
from pathlib import Path
from collections import defaultdict
```

**Ces bibliothèques sont standards et probablement déjà installées pour le projet principal.**

---

### 🎯 Alignement Architectural

Le répertoire `migration/` **respecte** la structure des CSV du projet principal:

| CSV Migration | Task Principal | Alignement |
|---------------|----------------|------------|
| epg.csv | ../tasks/epg.yml | ✅ Colonnes identiques |
| bd.csv | ../tasks/bd.yml | ✅ Colonnes identiques |
| vlan_pool.csv | ../tasks/vlan_pool.yml | ✅ Colonnes identiques |
| interface_policy_leaf_policy_gr.csv | ../tasks/interface_policy_leaf_policy_gr.yml | ✅ Colonnes identiques |
| ... | ... | ✅ Tous validés |

**MAIS:** Les fichiers dans `../tasks/` ne sont **JAMAIS lus** par les scripts de migration.
La compatibilité est assurée par **conception** (hardcodé dans le script).

---

### 🚀 Portabilité

**Le répertoire migration/ peut être copié ailleurs si:**

1. ✅ Vous créez un fichier `inventory.yml` local avec:
```yaml
all:
  vars:
    aci_hostname: "YOUR_APIC_IP"
    aci_username: "YOUR_USERNAME"
    aci_password: "YOUR_PASSWORD"
```

2. ✅ Ou vous modifiez les scripts pour lire les credentials ailleurs

**Exemple de modification pour autonomie complète:**

```python
# Dans extract_epg_migration.py, ligne 28:
# AVANT:
self.inventory_file = os.path.join(self.base_dir, '../inventory.yml')

# APRÈS (autonome):
self.inventory_file = os.path.join(self.base_dir, 'inventory.yml')
```

Puis créer `migration/inventory.yml` avec les credentials.

---

### 📊 Résumé

| Aspect | Status | Commentaire |
|--------|--------|-------------|
| Dépendances externes | 1 seule | ../inventory.yml |
| Lecture fichiers projet | ❌ Non | Totalement autonome |
| Écriture fichiers projet | ❌ Non | Écrit seulement dans csv_out/ |
| Respect architecture | ✅ Oui | Structure CSV compatible |
| Portabilité | ⚠️ Partielle | Besoin de inventory.yml |
| Indépendance production_ready/ | ✅ Totale | Jamais touché |

---

### ✅ Conclusion

Le répertoire `migration/` est **quasi-autonome** avec une seule dépendance légère vers `../inventory.yml`.

**Pour le rendre 100% autonome:**
```bash
# Copier inventory.yml dans migration/
cp ../inventory.yml migration/

# Modifier les scripts pour lire le fichier local
sed -i "s|'../inventory.yml'|'inventory.yml'|g" migration/*.py
```

Après cette modification, `migration/` serait **totalement indépendant** et portable.

---

**Date:** 2025-12-04  
**Status:** ✅ Autonomie confirmée (1 seule dépendance externe)

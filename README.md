# ACI Migration Tool

🚀 Outil autonome d'extraction de configuration ACI pour migration d'EPG

## 📋 Description

Cet outil permet d'extraire de manière ciblée la configuration d'EPG (Endpoint Groups) spécifiques depuis un fabric Cisco ACI, avec toutes leurs dépendances (Bridge Domains, VLANs, Domains, AEPs, Policy Groups).

**Parfait pour:**
- Migration d'EPG entre fabrics ACI
- Backup de configuration ciblée
- Documentation de configuration
- Clonage de configuration EPG

## ✨ Fonctionnalités

- ✅ **100% Autonome** - Aucune dépendance externe
- ✅ **Credentials Interactifs** - Demande IP/user/password au démarrage
- ✅ **Filtrage Intelligent** - Extrait UNIQUEMENT les objets liés aux EPGs demandés
- ✅ **Export Multi-format** - CSV + Excel
- ✅ **Compatibilité Ansible** - CSV prêts pour déploiement
- ✅ **Sécurisé** - Password masqué, jamais sauvegardé

## 📦 Objets Extraits

| Objet | Description |
|-------|-------------|
| EPG | Endpoint Groups |
| Bridge Domain | avec VRF |
| Domain | Physical/L3 |
| VLAN Pool | avec Encap Blocks |
| AEP | Attachable Entity Profiles |
| Interface Policy Groups | avec toutes les policies (CDP, LLDP, etc.) |

**+ Toutes les relations entre ces objets**

## 🚀 Installation

```bash
# Cloner le repository
git clone https://github.com/JFGrenier07/Aci-Migration-.git
cd Aci-Migration-

# Installer les dépendances Python
pip install pandas openpyxl requests pyyaml urllib3
```

## 📖 Utilisation Rapide

### Choix du Mode

Le script supporte **2 modes** d'extraction:

1. **🌐 Mode LIVE** - Connexion directe à l'APIC
2. **📦 Mode BACKUP** - Lecture d'un fichier JSON local

---

### Mode 1: Connexion LIVE à l'APIC

#### 1. Lister les EPG disponibles (optionnel)

```bash
python3 list_all_epgs.py
```

**Le script demande:**
```
🌐 Adresse IP de l'APIC: 192.168.0.245
👤 Nom d'utilisateur: admin
🔒 Mot de passe: ********
```

#### 2. Éditer la liste des EPG à extraire

```yaml
# epg_list.yml
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
```

#### 3. Lancer l'extraction

```bash
python3 extract_epg_migration.py
```

**Le script demande:**
```
MODE D'EXTRACTION
1. 🌐 Connexion LIVE à l'APIC
2. 📦 Backup JSON (fichier local)

Choisir le mode (1 ou 2): 1

CONNEXION À L'ACI FABRIC
🌐 Adresse IP de l'APIC: 192.168.0.245
👤 Nom d'utilisateur: admin
🔒 Mot de passe: ********
```

**Résultat:**
- CSV dans `csv_out/` (11 fichiers)
- Excel `epg_migration.xlsx` (10 onglets)

---

### Mode 2: Depuis un Backup JSON ou tar.gz

#### 1. Préparer le fichier de backup

Place ton snapshot ACI dans le répertoire:
```
migration/
├── extract_epg_migration.py
├── fabric_snapshot.json      ← Backup JSON direct
├── fabric_snapshot.tar.gz    ← OU snapshot ACI complet
└── epg_list.yml
```

**Formats supportés:**
- `.json` - Fichier JSON direct (format API ACI)
- `.tar.gz` ou `.tgz` - Archive de snapshot ACI (extraction automatique)

#### 2. Éditer epg_list.yml

Même chose que mode Live - liste tes EPG.

#### 3. Lancer l'extraction

```bash
python3 extract_epg_migration.py
```

**Le script demande:**
```
MODE D'EXTRACTION
1. 🌐 Connexion LIVE à l'APIC
2. 📦 Backup JSON (fichier local)

Choisir le mode (1 ou 2): 2

CHARGEMENT DEPUIS BACKUP
📁 Chemin du fichier (JSON ou tar.gz): fabric_snapshot.tar.gz
```

**Avantages du mode Backup:**
- ✅ Pas besoin de credentials
- ✅ Travail hors ligne
- ✅ Tests sans accès à la fabric
- ✅ Plus rapide (pas de connexion réseau)

**Résultat:** Identique au mode Live!

## 📂 Fichiers du Projet

### ✅ Fichiers Essentiels (tout ce dont vous avez besoin!)

| Fichier | Description | Requis? |
|---------|-------------|---------|
| `extract_epg_migration.py` | **Script principal** d'extraction | ✅ **OBLIGATOIRE** |
| `epg_list.yml` | **Configuration** des EPG à extraire | ✅ **OBLIGATOIRE** |
| `list_all_epgs.py` | Utilitaire pour lister tous les EPG | 🔵 **Recommandé** |
| `README.md` | Ce guide | 📖 Documentation |
| `.gitignore` | Config Git | ⚙️ Git seulement |

### 📁 Répertoires

```
Aci-Migration-/
├── extract_epg_migration.py    ← Script principal
├── list_all_epgs.py            ← Liste les EPG (optionnel)
├── epg_list.yml                ← Votre config
├── csv_out/                    ← Créé automatiquement (résultats CSV)
└── epg_migration.xlsx          ← Créé automatiquement (résultat Excel)
```

**C'est tout!** Pas de fichiers compliqués, pas de configuration cachée.

## 🔐 Sécurité

- Password masqué pendant la saisie (`getpass`)
- Credentials jamais sauvegardés sur disque
- Utilisation en mémoire uniquement
- SSL warnings désactivés (normal pour certificats auto-signés ACI)

## 🎯 Exemple Complet

```bash
# 1. Lister les EPG
python3 list_all_epgs.py
# → Noter les noms exacts

# 2. Éditer epg_list.yml
nano epg_list.yml

# 3. Extraire
python3 extract_epg_migration.py
# → Entrer credentials
# → Attendre extraction

# 4. Vérifier résultats
ls csv_out/
ls -lh epg_migration.xlsx
```

## 🧪 Tests

Testé avec:
- ✅ Cisco ACI 5.x
- ✅ Cisco ACI 6.x
- ✅ Python 3.8+
- ✅ Multiple fabrics

## 🤝 Contribution

Les contributions sont les bienvenues! N'hésitez pas à:
- 🐛 Signaler des bugs
- 💡 Proposer des améliorations
- 📝 Améliorer la documentation

## 📝 License

MIT License - Libre d'utilisation

## 👤 Auteur

**JF Grenier**
- GitHub: [@JFGrenier07](https://github.com/JFGrenier07)
- Tool: Développé avec Claude Code

## 🔄 Version

**Version actuelle: 2.2** (2025-12-07)

### Nouveautés v2.2
- ✅ Support L3Out complet (Standard + Floating)
- ✅ BGP Peer Floating avec extraction correcte node_id et vlan
- ✅ ExtEPG avec contracts (provider/consumer)
- ✅ Route Control (profiles, contexts, match rules)
- ✅ Filtrage BD→L3Out pour cohérence référentielle

### Fonctionnalités
- ✅ Credentials interactifs (IP/user/password)
- ✅ 100% autonome (aucune dépendance externe)
- ✅ Support tar.gz (extraction automatique des snapshots ACI)
- ✅ Dual-mode: Live APIC ou Backup local
- ✅ Support Interface Policy Groups
- ✅ Export CSV + Excel (27 onglets)

## ⭐ Support

Si cet outil vous est utile, n'oubliez pas de mettre une ⭐ sur GitHub!

---

**Status:** ✅ Production Ready  
**Date:** 2025-12-04  
**Développé avec:** Claude Code + ❤️

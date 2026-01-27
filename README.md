# ACI Migration Tool

Outil de migration de services EPG et L3Out entre fabrics Cisco ACI.

## Vue d'ensemble

Ce projet automatise la migration de configuration ACI en 3 etapes :

```
┌─────────────────────┐     ┌──────────────────────┐     ┌──────────────────────────┐
│  1. EXTRACTION      │     │  2. CONVERSION       │     │  3. DEPLOIEMENT          │
│                     │     │                      │     │                          │
│ extract_migration.py│ ──> │ fabric_converter.py  │ ──> │ aci-fabric-automation    │
│                     │     │                      │     │ (projet separe)          │
│ Fabric SOURCE       │     │ Adapte les valeurs   │     │ Deploie sur la fabric    │
│ -> Excel            │     │ -> Excel converti    │     │ DESTINATION via Ansible  │
└─────────────────────┘     └──────────────────────┘     └──────────────────────────┘
```

**Extraction** : Se connecte a l'APIC (ou lit un backup JSON) et extrait les EPG demandes avec toutes leurs dependances, ainsi que les L3Out (standard et floating) avec leur configuration BGP complete.

**Conversion** : Prend le fichier Excel extrait et remplace les valeurs (tenants, VRFs, node IDs, paths, etc.) pour correspondre a la fabric de destination.

**Deploiement** : Le fichier Excel converti est utilise par notre projet [aci-fabric-automation](https://github.com/JFGrenier07/aci-fabric-automation) pour deployer la configuration sur la nouvelle fabric via Ansible.

## Installation

```bash
git clone https://github.com/JFGrenier07/Aci-Migration-.git
cd Aci-Migration-

pip install pandas openpyxl requests pyyaml urllib3
```

## Fichier de configuration : `extraction_list.yml`

Ce fichier definit ce qui sera extrait de la fabric source. Il contient deux types d'entrees :

### Entrees EPG

Chaque bloc definit un tenant, un Application Profile et la liste des EPG a extraire.
L'outil extrait automatiquement toutes les dependances : Bridge Domains, VRFs, subnets,
VLAN pools, domains, AEPs, contracts, filters, interface policies.

```yaml
---
tenant: Production
ap: Database_AP
epgs:
  - DBServers_EPG
  - AppServers_EPG

---
tenant: Autre_Tenant
ap: Web_AP
epgs:
  - WebFrontend_EPG
```

### Entrees L3Out

Chaque bloc definit un L3Out a extraire avec son type (standard ou floating).
L'outil extrait la configuration complete : node profiles, logical nodes, interface profiles,
BGP peers, external EPGs, external subnets, contracts, floating SVIs, route control.

```yaml
---
floating: no
tenant: Production
l3out: L3Out_Prod_Standard

---
floating: yes
tenant: Production
l3out: L3Out_Prod_Floating
```

Le parametre `floating` indique le type de L3Out :
- `no` : L3Out standard (interfaces physiques/SVI)
- `yes` : L3Out floating (floating SVI avec paths secondaires)

### Exemple complet

```yaml
# === EPGs a extraire ===
---
tenant: PROD-TN
ap: PROD-ANP
epgs:
  - RL00001-EPG
  - RL00002-EPG

# === L3Out standard ===
---
floating: no
tenant: PROD-TN
l3out: L3Out-PROD-Standard

# === L3Out floating ===
---
floating: yes
tenant: PROD-TN
l3out: L3Out-PROD-Floating
```

## Etape 1 : Extraction (`extract_migration.py`)

```bash
python3 extract_migration.py
```

Le script demande le nom du fichier Excel de sortie, puis le mode d'extraction.

### Mode 1 - Connexion LIVE a l'APIC

Le script se connecte directement a l'APIC via API REST pour extraire la configuration.

```
Nom du fichier Excel de sortie [epg_migration.xlsx]:
MODE D'EXTRACTION
[1] Connexion LIVE a l'APIC
[2] Backup JSON (fichier local)

Choisir le mode: 1
Adresse IP de l'APIC: 192.168.0.245
Nom d'utilisateur: admin
Mot de passe: ********
```

### Mode 2 - Depuis un backup JSON ou tar.gz

Pour travailler hors ligne ou sans acces a la fabric.

```
Choisir le mode: 2
Chemin du fichier (JSON ou tar.gz): fabric_snapshot.tar.gz
```

Formats supportes : `.json` (API ACI) ou `.tar.gz` / `.tgz` (snapshot ACI).

### Objets extraits

| Categorie | Objets |
|-----------|--------|
| Infrastructure | VLAN Pools, Encap Blocks, Domains, AEPs |
| Tenant/BD | Bridge Domains, Subnets, BD-to-L3Out |
| EPG | EPGs, EPG-to-Domain, AEP-to-EPG |
| L3Out Standard | Node Profiles, Logical Nodes, Interface Profiles, Interfaces, BGP Peers, BGP Protocol Profiles |
| L3Out Floating | Floating SVIs, Floating SVI Paths, Secondary IPs, Floating SVI Path Sec, Floating BGP Peers, VPC Members |
| L3Out Externe | External EPGs, External Subnets, ExtEPG-to-Contract |
| Route Control | Match Rules, Match Route Destinations, Route Control Profiles, Route Control Contexts |
| Contracts | Contracts, Subjects, Filters |
| Interface Policies | CDP, LLDP, MCP, Link Level, Port Channel, Spanning Tree, Leaf Profiles, Policy Groups |

### Resultat

- `csv_out/` : fichiers CSV intermediaires (generes automatiquement, un par type d'objet)
- `epg_migration.xlsx` : fichier Excel avec un onglet par type d'objet (jusqu'a 34 onglets)

## Etape 2 : Conversion (`fabric_converter.py`)

Prend le fichier Excel de l'etape 1 et remplace les valeurs pour la fabric de destination.

```bash
python3 fabric_converter.py
```

```
Fichier Excel source: epg_migration.xlsx

MODE DE CONVERSION
[1] Wizard interactif (etape par etape)
[2] Fichier de configuration (texte plat)

Choix [1]:
```

### Mode 1 - Wizard interactif

Le wizard pose les questions une par une. A chaque etape, entrez la nouvelle valeur
ou appuyez sur Entree pour garder la valeur existante.

**Les 7 etapes du wizard :**

| Etape | Description |
|-------|-------------|
| 1. Tenants | Mapping automatique Tenant → VRF → AP (convention -TN / -VRF / -ANP) |
| 2. L3Out (BD) | L3Out references par les Bridge Domains |
| 3. L3Out unifie | Node IDs, Node Profiles, Interface Profiles, Path EPs, Local AS |
| 4. Route Control | Match Rules, Route Control Profiles, Route Control Contexts |
| 5. Routage BD | Option pour desactiver le routage de tous les Bridge Domains |
| 6. Descriptions VLAN | Coller des lignes au format `VLAN,DESCRIPTION` |
| 7. Interface Config | Conversion Interface Profile → interface_config avec descriptions |

### Mode 2 - Fichier de configuration

Pour les migrations repetitives, le fichier de configuration evite de repasser
par le wizard a chaque fois.

**Etape A - Generer le template :**

```bash
python3 fabric_converter.py
# Entrer le fichier Excel
# Choisir [2] puis [A]
```

Cela genere un fichier `.cfg` pre-rempli avec toutes les valeurs trouvees dans le Excel.
Exemple de contenu :

```ini
[TENANTS]
PROD-TN = PROD-TN

[NODE_IDS]
101 = 101

[PATH_EPS]
topology/pod-1/paths-101/pathep-[eth1/1] = topology/pod-1/paths-101/pathep-[eth1/1]

[OPTIONS]
disable_bd_routing = false

[VLAN_DESCRIPTIONS]
# Collez vos lignes au format VLAN,DESCRIPTION
200,RL00001_10.1.1.1/24_Serveur_Web

[INTERFACE_CONFIG_DESCRIPTIONS]
# Meme format que le wizard : NOM_LEAF  NO_INTERFACE  DESCRIPTION
SF22-127  3  VPZESX1011-onb2-p1-vmnic2
```

Le format est simple : `source = destination`. Modifiez uniquement la partie droite
(destination). Si source et destination sont identiques, aucune conversion n'est appliquee.

**Etape B - Appliquer le fichier :**

Une fois le fichier `.cfg` modifie, relancez le script pour l'appliquer :

```bash
python3 fabric_converter.py
# Entrer le fichier Excel
# Choisir [2] puis [B]
# Entrer le chemin du fichier .cfg
```

Le script charge le fichier, affiche un resume des changements, demande confirmation,
puis genere le fichier Excel converti.

### Resultat

Le fichier `{nom}_converted.xlsx` est pret pour le deploiement.

## Etape 3 : Deploiement

Pour deployer la configuration convertie sur la fabric de destination, utilisez notre projet
**[aci-fabric-automation](https://github.com/JFGrenier07/aci-fabric-automation)**.

Ce projet utilise Ansible pour configurer automatiquement la fabric ACI
a partir des fichiers CSV generes par cet outil de migration.

## Structure du projet

```
Aci-Migration-/
├── extract_migration.py     # Extraction de la config EPG + L3Out depuis ACI
├── fabric_converter.py      # Conversion des valeurs pour la nouvelle fabric
├── extraction_list.yml      # Liste des EPG et L3Out a extraire
├── csv_out/                 # CSV intermediaires (genere automatiquement)
└── README.md
```

## Securite

- Mot de passe masque pendant la saisie (`getpass`)
- Credentials jamais sauvegardes sur disque
- Utilisation en memoire uniquement

## Compatibilite

- Cisco ACI 5.x / 6.x
- Python 3.8+

## Auteur

**JF Grenier** - [@JFGrenier07](https://github.com/JFGrenier07)

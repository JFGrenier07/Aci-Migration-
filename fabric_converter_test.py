#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de conversion de fabric ACI - Version 4.
Convertit un fichier Excel d'une fabric source vers une fabric destination
en modifiant les paramètres clés (tenant, VRF, AP, node_id, path, etc.)

V4:
- Menu: [1] Wizard interactif  [2] Fichier de configuration
- Fichier config = texte plat (INI-style), simple copier-coller
- Correction bug path_ep collision avec interface_config
- Toutes les fonctionnalités du wizard V3 conservées
"""

import os
import re
import sys
import yaml
import json
import tarfile
import tempfile
import shutil
import pandas as pd
from pathlib import Path
from collections import defaultdict
from datetime import datetime


# =============================================================================
# FONCTIONS DE CHARGEMENT DE BACKUP ACI
# =============================================================================

def get_latest_backup(fabric_path: str) -> str:
    """
    Trouve le fichier backup tar.gz le plus récent dans un répertoire.

    Format attendu: *-YYYY-MM-DDTHH-MM-SS.tar.gz
    """
    if not os.path.isdir(fabric_path):
        raise FileNotFoundError(f"Répertoire non trouvé: {fabric_path}")

    date_pattern = re.compile(r'(\d{4}-\d{2}-\d{2}T\d{2}-\d{2}-\d{2})\.tar\.gz$')

    backups = []
    for filename in os.listdir(fabric_path):
        if filename.endswith('.tar.gz'):
            match = date_pattern.search(filename)
            if match:
                date_str = match.group(1)
                try:
                    backup_date = datetime.strptime(date_str, '%Y-%m-%dT%H-%M-%S')
                    backups.append({
                        'filename': filename,
                        'path': os.path.join(fabric_path, filename),
                        'date': backup_date
                    })
                except ValueError:
                    continue

    if not backups:
        raise FileNotFoundError(f"Aucun backup tar.gz trouvé dans: {fabric_path}")

    backups.sort(key=lambda x: x['date'], reverse=True)
    return backups[0]['path']


def load_backup(backup_path: str) -> dict:
    """
    Charge un backup ACI depuis un fichier tar.gz.
    """
    if not os.path.exists(backup_path):
        raise FileNotFoundError(f"Fichier non trouvé: {backup_path}")

    temp_dir = None
    try:
        temp_dir = tempfile.mkdtemp(prefix='aci_backup_')

        with tarfile.open(backup_path, 'r:gz') as tar:
            tar.extractall(path=temp_dir)

        # Chercher le fichier JSON principal
        json_file = None
        for root, dirs, files in os.walk(temp_dir):
            for file in files:
                if file.endswith('_1.json'):
                    json_file = os.path.join(root, file)
                    break
            if json_file:
                break

        if not json_file:
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith('.json') and not file.endswith('.md5'):
                        json_file = os.path.join(root, file)
                        break
                if json_file:
                    break

        if not json_file:
            raise ValueError(f"Aucun fichier JSON trouvé dans l'archive: {backup_path}")

        with open(json_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        # Construire l'index pour accélérer les recherches
        data['_index'] = build_class_index(data)

        return data

    finally:
        if temp_dir and os.path.exists(temp_dir):
            shutil.rmtree(temp_dir)


def build_class_index(aci_data: dict) -> dict:
    """Construit un index de tous les objets par classe ACI."""
    index = {}

    def index_recursive(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key not in ('attributes', 'children') and isinstance(value, dict):
                    if 'attributes' in value or 'children' in value:
                        if key not in index:
                            index[key] = []
                        index[key].append(value)
                if isinstance(value, (dict, list)):
                    index_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                index_recursive(item)

    if 'imdata' in aci_data:
        for item in aci_data['imdata']:
            index_recursive(item)
    else:
        index_recursive(aci_data)

    return index


def find_objects(aci_data: dict, target_class: str) -> list:
    """Recherche tous les objets d'une classe ACI spécifique (insensible à la casse)."""
    target_lower = target_class.lower()

    # Chercher dans l'index (avec correspondance insensible à la casse)
    if '_index' in aci_data:
        # Chercher la clé exacte d'abord
        if target_class in aci_data['_index']:
            return aci_data['_index'][target_class]
        # Sinon chercher en ignorant la casse
        for key in aci_data['_index']:
            if key.lower() == target_lower:
                return aci_data['_index'][key]
        return []

    found = []
    def search_recursive(obj):
        if isinstance(obj, dict):
            for key, value in obj.items():
                if key.lower() == target_lower:
                    found.append(value)
                if isinstance(value, (dict, list)):
                    search_recursive(value)
        elif isinstance(obj, list):
            for item in obj:
                search_recursive(item)

    if 'imdata' in aci_data:
        for item in aci_data['imdata']:
            search_recursive(item)
    else:
        search_recursive(aci_data)

    return found


def get_object_attribute(obj: dict, attr_name: str, default: str = '') -> str:
    """Récupère un attribut d'un objet ACI de manière sécurisée."""
    return obj.get('attributes', {}).get(attr_name, default)


# =============================================================================
# FONCTIONS DE SÉLECTION DE TENANT
# =============================================================================

def find_all_tenants(aci_data: dict) -> list:
    """Trouve tous les tenants dans le backup."""
    tenants = find_objects(aci_data, 'fvTenant')
    return [get_object_attribute(t, 'name', '') for t in tenants if get_object_attribute(t, 'name', '')]


def group_tenants_by_prefix(tenants: list) -> dict:
    """
    Groupe les tenants par préfixe (avant -OL ou -UL).
    Ex: MIAMI-PROD-OL-TN et MIAMI-PROD-UL-TN -> préfixe = MIAMI-PROD
    """
    groups = {}

    for tenant in tenants:
        tenant_upper = tenant.upper()

        ol_match = re.search(r'^(.+)-OL-(.+)$', tenant_upper)
        ul_match = re.search(r'^(.+)-UL-(.+)$', tenant_upper)

        if ol_match:
            prefix = ol_match.group(1)
            suffix = ol_match.group(2)
            if prefix not in groups:
                groups[prefix] = {'overlay': None, 'underlay': None, 'suffix': suffix}
            groups[prefix]['overlay'] = tenant

        elif ul_match:
            prefix = ul_match.group(1)
            suffix = ul_match.group(2)
            if prefix not in groups:
                groups[prefix] = {'overlay': None, 'underlay': None, 'suffix': suffix}
            groups[prefix]['underlay'] = tenant

    # Garder seulement les groupes complets
    complete_groups = {}
    for prefix, group in groups.items():
        if group['overlay'] and group['underlay']:
            complete_groups[prefix] = group

    return complete_groups


# =============================================================================
# FONCTIONS DE RECHERCHE L3OUT
# =============================================================================

def find_ns_l3out(aci_data: dict, tenant_ol: str) -> str:
    """
    Trouve le L3Out Nord-Sud dans le tenant overlay.
    Le premier mot commence par 'B' et contient '-NS-' dans le nom.
    """
    l3outs = find_objects(aci_data, 'l3extOut')
    tenant_ol_upper = tenant_ol.upper()

    for l3out in l3outs:
        dn = get_object_attribute(l3out, 'dn', '').upper()
        name = get_object_attribute(l3out, 'name', '')

        # Vérifier que c'est dans le bon tenant (insensible à la casse)
        if f'/TN-{tenant_ol_upper}/' not in dn:
            continue

        # Vérifier: premier mot commence par B ET contient -NS-
        name_upper = name.upper()
        first_word = name_upper.split('-')[0] if '-' in name_upper else name_upper

        if first_word.startswith('B') and '-NS-' in name_upper:
            return name

    return ''


def find_dci_l3out(aci_data: dict, tenant: str) -> str:
    """Trouve le L3Out DCI dans un tenant donné (commence par 'DCI')."""
    l3outs = find_objects(aci_data, 'l3extOut')
    tenant_upper = tenant.upper()

    for l3out in l3outs:
        dn = get_object_attribute(l3out, 'dn', '').upper()
        name = get_object_attribute(l3out, 'name', '')

        # Vérifier que c'est dans le bon tenant (insensible à la casse)
        if f'/TN-{tenant_upper}/' not in dn:
            continue

        if name.upper().startswith('DCI'):
            return name

    return ''


# =============================================================================
# FONCTIONS DE MAPPING NODE ID / LEAF NAME
# =============================================================================

def find_all_node_ids(aci_data: dict) -> dict:
    """
    Trouve tous les node IDs et leurs noms de leaf depuis fabricNodeIdentP.

    Returns:
        Dict {node_id: leaf_name}
    """
    nodes = find_objects(aci_data, 'fabricNodeIdentP')
    result = {}

    for node in nodes:
        node_id = get_object_attribute(node, 'nodeId', '')
        name = get_object_attribute(node, 'name', '')

        if node_id and name:
            result[node_id] = name

    return result


def match_node_ids_by_last_digits(excel_node_ids: list, backup_node_ids: dict, digits: int = 2) -> dict:
    """
    Mappe les node IDs de l'Excel aux node IDs du backup par les derniers chiffres.

    Args:
        excel_node_ids: Liste des node IDs de l'Excel
        backup_node_ids: Dict {node_id: leaf_name} du backup
        digits: Nombre de chiffres à matcher (défaut: 2)

    Returns:
        Dict {excel_node_id: {'backup_node_id': xxx, 'leaf_name': xxx}}
    """
    result = {}

    for excel_id in excel_node_ids:
        excel_id_str = str(excel_id)
        excel_suffix = excel_id_str[-digits:] if len(excel_id_str) >= digits else excel_id_str

        for backup_id, leaf_name in backup_node_ids.items():
            backup_id_str = str(backup_id)
            backup_suffix = backup_id_str[-digits:] if len(backup_id_str) >= digits else backup_id_str

            if excel_suffix == backup_suffix:
                result[excel_id_str] = {
                    'backup_node_id': backup_id,
                    'leaf_name': leaf_name
                }
                break

    return result


def extract_node_profile_suffix(node_profile_name: str) -> str:
    """
    Extrait les 2 derniers chiffres du numéro de leaf dans un node profile.

    Ex: SF22-121-NP → 21
        SF22-2221-NP → 21
        SFXX-127-NP → 27
    """
    # Chercher le pattern après SFXX- (ou similaire)
    match = re.search(r'SF\d+-(\d+)-NP$', node_profile_name.upper())
    if match:
        leaf_num = match.group(1)
        return leaf_num[-2:] if len(leaf_num) >= 2 else leaf_num

    return ''


# =============================================================================
# FONCTIONS ROUTE CONTROL SITE IDENTIFIERS
# =============================================================================

def find_site_identifiers(names: list) -> set:
    """
    Trouve les identifiants de site (DES, DRV, VRN, etc.) dans une liste de noms.
    """
    site_ids = set()
    patterns = ['DES', 'DRV', 'VRN']

    for name in names:
        name_upper = name.upper()
        for pattern in patterns:
            if pattern in name_upper:
                site_ids.add(pattern)

    return site_ids


def replace_site_identifier(name: str, old_id: str, new_id: str) -> str:
    """Remplace un identifiant de site dans un nom."""
    return re.sub(re.escape(old_id), new_id, name, flags=re.IGNORECASE)


class FabricConverter:
    def __init__(self, excel_file):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.excel_file = excel_file
        self.extraction_list_file = os.path.join(self.base_dir, 'extraction_list.yml')
        self.fabric_paths_file = os.path.join(self.base_dir, 'fabric_paths.yml')

        # Nom du fichier de sortie
        excel_path = Path(excel_file)
        self.output_excel = str(excel_path.parent / f"{excel_path.stem}_converted.xlsx")

        # Données Excel
        self.excel_data = {}  # Dict des DataFrames par onglet

        # Données de la fabric de destination
        self.fabric_paths = {}  # Dict {fabric_name: path}
        self.dest_fabric_name = None
        self.dest_fabric_path = None
        self.dest_backup_path = None
        self.dest_aci_data = None  # Données ACI chargées

        # Groupe de tenant sélectionné (OL/UL)
        self.tenant_group = None  # Dict avec overlay_tenant, underlay_tenant, etc.

        # Node IDs du backup destination
        self.dest_node_ids = {}  # Dict {node_id: leaf_name}

        # Site identifier pour Route Control
        self.site_identifier_old = None
        self.site_identifier_new = 'VRN'

        # Mappings de conversion - Globaux
        self.tenant_mapping = {}
        self.vrf_mapping = {}
        self.ap_mapping = {}
        self.l3out_mapping = {}  # Pour bd_to_l3out

        # Mappings L3Out UNIFIÉS (tous les onglets)
        self.node_id_mapping = {}
        self.node_profile_mapping = {}
        self.int_profile_mapping = {}
        self.path_ep_mapping = {}
        self.local_as_mapping = {}

        # Mappings Route Control
        self.match_rule_mapping = {}
        self.route_control_profile_mapping = {}
        self.route_control_context_mapping = {}

        # Options supplémentaires
        self.disable_bd_routing = False
        self.vlan_descriptions = []  # Liste de tuples (vlan, description)
        self.vlan_pool_descriptions = {}  # Dict {pool_name: description} pour auto-génération

        # Interface config data (pour mode config file)
        self.interface_config_enabled = False
        self.interface_config_method = 'odd_even'  # 'odd_even' ou 'manual'
        self.interface_config_type = 'switch_port'
        self.interface_config_profile_to_node = {}
        self.interface_config_interfaces = []  # Liste de (profile, policy_group, interfaces_str)
        self.interface_config_node_to_leaf = {}
        self.interface_config_descriptions = []  # Lignes brutes

        # Colonnes à convertir par type
        self.tenant_columns = ['tenant']
        self.vrf_columns = ['vrf']
        self.ap_columns = ['ap']
        self.node_id_columns = ['node_id']
        self.node_profile_columns = ['node_profile', 'logical_node_profile', 'node_profile_name']
        self.int_profile_columns = ['interface_profile', 'logical_interface_profile', 'interface_profile_name']
        self.path_ep_columns = ['path_ep', 'path', 'interface', 'tDn']
        self.local_as_columns = ['local_as', 'local_asn', 'asn', 'local_as_number']

        # Colonnes Route Control
        self.match_rule_columns = ['match_rule']
        self.route_control_profile_columns = ['route_control_profile', 'route_control_profile_import', 'route_control_profile_export']
        self.route_control_context_columns = ['route_control_context']

    def load_excel(self):
        """Charge le fichier Excel source"""
        print(f"\n📂 Chargement du fichier Excel: {self.excel_file}")

        if not os.path.exists(self.excel_file):
            print(f"❌ Fichier non trouvé: {self.excel_file}")
            sys.exit(1)

        excel = pd.ExcelFile(self.excel_file)
        for sheet_name in excel.sheet_names:
            self.excel_data[sheet_name] = pd.read_excel(excel, sheet_name=sheet_name)

        print(f"✅ {len(self.excel_data)} onglets chargés")
        return True

    def load_extraction_list(self):
        """Charge la liste d'extraction (optionnel)"""
        if not os.path.exists(self.extraction_list_file):
            return None

        with open(self.extraction_list_file, 'r', encoding='utf-8') as f:
            docs = list(yaml.safe_load_all(f))

        return docs

    def load_fabric_paths(self):
        """Charge la configuration des chemins de fabric."""
        if not os.path.exists(self.fabric_paths_file):
            print(f"   ⚠️  Fichier {self.fabric_paths_file} non trouvé")
            return False

        with open(self.fabric_paths_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        self.fabric_paths = config.get('fabrics', {})
        return bool(self.fabric_paths)

    def select_destination_fabric(self):
        """Affiche les fabrics disponibles et demande à l'utilisateur de choisir."""
        print("\n" + "=" * 60)
        print("🏭 SÉLECTION DE LA FABRIC DE DESTINATION")
        print("=" * 60)

        if not self.fabric_paths:
            print("❌ Aucune fabric configurée dans fabric_paths.yml")
            return False

        # Afficher la liste
        print("\nFabrics disponibles:\n")
        fabric_list = list(self.fabric_paths.items())
        for i, (name, path) in enumerate(fabric_list, 1):
            print(f"  {i}) {name}")
            print(f"     → {path}")
            print()

        # Demander le choix
        while True:
            try:
                choice = input("Votre choix: ").strip()
                index = int(choice) - 1

                if 0 <= index < len(fabric_list):
                    self.dest_fabric_name, self.dest_fabric_path = fabric_list[index]
                    break
                else:
                    print("❌ Choix invalide. Réessayez.")
            except ValueError:
                print("❌ Entrez un numéro valide.")

        print(f"\n✅ Fabric sélectionnée: {self.dest_fabric_name}")
        return True

    def load_destination_backup(self):
        """Charge le backup le plus récent de la fabric de destination."""
        print("\n" + "-" * 60)
        print("📦 CHARGEMENT DU BACKUP")
        print("-" * 60)

        try:
            self.dest_backup_path = get_latest_backup(self.dest_fabric_path)
            backup_filename = os.path.basename(self.dest_backup_path)
            print(f"   Backup trouvé: {backup_filename}")

            print("   Chargement en cours...")
            self.dest_aci_data = load_backup(self.dest_backup_path)
            print("   ✅ Backup chargé avec succès")

            # Charger les node IDs
            self.dest_node_ids = find_all_node_ids(self.dest_aci_data)
            print(f"   ✅ {len(self.dest_node_ids)} nodes trouvés")

            return True

        except FileNotFoundError as e:
            print(f"   ❌ {e}")
            return False
        except Exception as e:
            print(f"   ❌ Erreur: {e}")
            return False

    def select_tenant_group(self):
        """Affiche les groupes de tenants (OL/UL) et demande de choisir."""
        print("\n" + "=" * 60)
        print("🏢 SÉLECTION DU TENANT")
        print("=" * 60)

        # Trouver tous les tenants
        tenants = find_all_tenants(self.dest_aci_data)

        if not tenants:
            print("\n❌ Aucun tenant trouvé dans le backup.")
            return False

        # Grouper par préfixe
        groups = group_tenants_by_prefix(tenants)

        if not groups:
            print("\n❌ Aucun groupe de tenants OL/UL trouvé.")
            print("   Tenants trouvés:")
            for t in tenants[:10]:
                print(f"   - {t}")
            return False

        # Afficher les groupes
        print("\nGroupes de tenants disponibles:\n")

        group_list = list(groups.items())
        for i, (prefix, group) in enumerate(group_list, 1):
            print(f"  {i}) {prefix}")
            print(f"      ├── Overlay:  {group['overlay']}")
            print(f"      └── Underlay: {group['underlay']}")
            print()

        # Demander le choix
        while True:
            try:
                choice = input("Votre choix: ").strip()
                index = int(choice) - 1

                if 0 <= index < len(group_list):
                    prefix, group = group_list[index]
                    break
                else:
                    print("❌ Choix invalide. Réessayez.")
            except ValueError:
                print("❌ Entrez un numéro valide.")

        # Construire les noms VRF et ANP
        suffix = group.get('suffix', 'TN')

        overlay_tenant = group['overlay']
        underlay_tenant = group['underlay']

        overlay_vrf = overlay_tenant.replace(f'-{suffix}', '-VRF')
        underlay_vrf = underlay_tenant.replace(f'-{suffix}', '-VRF')

        overlay_anp = overlay_tenant.replace(f'-{suffix}', '-ANP')
        underlay_anp = underlay_tenant.replace(f'-{suffix}', '-ANP')

        self.tenant_group = {
            'prefix': prefix,
            'overlay_tenant': overlay_tenant,
            'underlay_tenant': underlay_tenant,
            'overlay_vrf': overlay_vrf,
            'underlay_vrf': underlay_vrf,
            'overlay_anp': overlay_anp,
            'underlay_anp': underlay_anp,
        }

        print(f"\n✅ Groupe sélectionné: {prefix}")
        print(f"   Overlay:  {overlay_tenant} / {overlay_vrf} / {overlay_anp}")
        print(f"   Underlay: {underlay_tenant} / {underlay_vrf} / {underlay_anp}")

        return True

    def auto_map_tenants_from_group(self, unique_values):
        """
        Mappe automatiquement les tenants/VRF/AP depuis le groupe sélectionné.
        """
        if not self.tenant_group:
            return

        print("\n" + "=" * 60)
        print("🔄 MAPPING AUTOMATIQUE TENANT/VRF/AP")
        print("=" * 60)

        # Trouver les tenants OL et UL dans l'Excel
        for tenant in unique_values.get('tenants', []):
            tenant_upper = tenant.upper()

            if '-OL-' in tenant_upper:
                dest = self.tenant_group['overlay_tenant']
                self.tenant_mapping[tenant] = dest
                print(f"   Tenant OL: {tenant} → {dest}")

                # VRF et ANP associés
                src_base = tenant.replace('-OL-TN', '').replace('-ol-tn', '')
                src_vrf = f"{src_base}-OL-VRF"
                src_anp = f"{src_base}-OL-ANP"

                for vrf in unique_values.get('vrfs', []):
                    if vrf.upper() == src_vrf.upper():
                        self.vrf_mapping[vrf] = self.tenant_group['overlay_vrf']
                        print(f"   VRF OL:    {vrf} → {self.tenant_group['overlay_vrf']}")

                for ap in unique_values.get('aps', []):
                    if ap.upper() == src_anp.upper():
                        self.ap_mapping[ap] = self.tenant_group['overlay_anp']
                        print(f"   ANP OL:    {ap} → {self.tenant_group['overlay_anp']}")

            elif '-UL-' in tenant_upper:
                dest = self.tenant_group['underlay_tenant']
                self.tenant_mapping[tenant] = dest
                print(f"   Tenant UL: {tenant} → {dest}")

                # VRF et ANP associés
                src_base = tenant.replace('-UL-TN', '').replace('-ul-tn', '')
                src_vrf = f"{src_base}-UL-VRF"
                src_anp = f"{src_base}-UL-ANP"

                for vrf in unique_values.get('vrfs', []):
                    if vrf.upper() == src_vrf.upper():
                        self.vrf_mapping[vrf] = self.tenant_group['underlay_vrf']
                        print(f"   VRF UL:    {vrf} → {self.tenant_group['underlay_vrf']}")

                for ap in unique_values.get('aps', []):
                    if ap.upper() == src_anp.upper():
                        self.ap_mapping[ap] = self.tenant_group['underlay_anp']
                        print(f"   ANP UL:    {ap} → {self.tenant_group['underlay_anp']}")

    def auto_map_l3outs(self):
        """
        Mappe automatiquement les L3Outs depuis le backup destination.
        """
        if not self.dest_aci_data or not self.tenant_group:
            return

        print("\n" + "=" * 60)
        print("🔗 MAPPING AUTOMATIQUE L3OUT")
        print("=" * 60)

        # Trouver les L3Outs dans le backup destination
        tenant_ol = self.tenant_group['overlay_tenant']
        tenant_ul = self.tenant_group['underlay_tenant']

        print(f"   Recherche dans tenant OL: {tenant_ol}")
        print(f"   Recherche dans tenant UL: {tenant_ul}")

        # Debug: afficher tous les L3Outs trouvés
        all_l3outs = find_objects(self.dest_aci_data, 'l3extOut')
        print(f"   Total L3Outs trouvés dans backup: {len(all_l3outs)}")

        if all_l3outs:
            print("   Liste des L3Outs:")
            for l3out in all_l3outs[:10]:  # Limiter à 10 pour l'affichage
                name = get_object_attribute(l3out, 'name', '?')
                dn = get_object_attribute(l3out, 'dn', '?')
                print(f"      • {name} (dn: {dn[:60]}...)")

        ns_l3out = find_ns_l3out(self.dest_aci_data, tenant_ol)
        dci_ol_l3out = find_dci_l3out(self.dest_aci_data, tenant_ol)
        dci_ul_l3out = find_dci_l3out(self.dest_aci_data, tenant_ul)

        print("\n   Résultats de la recherche:")
        if ns_l3out:
            print(f"   ✅ N/S L3Out (overlay): {ns_l3out}")
        else:
            print(f"   ❌ N/S L3Out: non trouvé (cherche: 1er mot commence par B ET contient -NS-)")
        if dci_ol_l3out:
            print(f"   ✅ DCI L3Out (overlay): {dci_ol_l3out}")
        else:
            print(f"   ❌ DCI L3Out (overlay): non trouvé (cherche: commence par DCI)")
        if dci_ul_l3out:
            print(f"   ✅ DCI L3Out (underlay): {dci_ul_l3out}")
        else:
            print(f"   ❌ DCI L3Out (underlay): non trouvé (cherche: commence par DCI)")

        # Stocker pour utilisation dans collect_bd_to_l3out_mappings
        self._backup_l3outs = {
            'ns': ns_l3out,
            'dci_ol': dci_ol_l3out,
            'dci_ul': dci_ul_l3out
        }

    def auto_map_node_ids(self):
        """
        Mappe automatiquement les Node IDs par les 2 derniers chiffres.
        """
        if not self.dest_node_ids:
            return False

        print("\n" + "=" * 60)
        print("🖥️  MAPPING AUTOMATIQUE NODE IDs")
        print("=" * 60)

        # Demander si même position de leaf
        print("\nLa fabric de destination utilise la même position de leaf?")
        print("[1] Oui - Mapper par les 2 derniers chiffres")
        print("[2] Non - Saisie manuelle")
        print("\nChoix [1]: ", end="", flush=True)
        choice = input().strip()

        if choice == '2':
            print("   → Mode manuel sélectionné")
            return False

        # Récupérer les node IDs de l'Excel
        excel_node_ids = list(self.find_all_values(self.node_id_columns).keys())

        if not excel_node_ids:
            print("   ⚠️  Aucun node ID trouvé dans l'Excel")
            return False

        # Mapper par les 2 derniers chiffres
        mapping = match_node_ids_by_last_digits(excel_node_ids, self.dest_node_ids)

        if not mapping:
            print("   ⚠️  Aucun mapping trouvé")
            return False

        # Afficher pour confirmation
        print("\n   Mapping auto-détecté:")
        for excel_id, info in mapping.items():
            print(f"   • Excel {excel_id} → Backup {info['backup_node_id']} (Leaf: {info['leaf_name']})")

        print("\nConfirmer ce mapping? [O/n]: ", end="", flush=True)
        confirm = input().strip().lower()

        if confirm in ['n', 'non', 'no']:
            print("   → Mode manuel sélectionné")
            return False

        # Appliquer le mapping
        for excel_id, info in mapping.items():
            self.node_id_mapping[excel_id] = info['backup_node_id']

        print(f"\n   ✅ {len(mapping)} node IDs mappés automatiquement")
        return True

    def auto_map_node_profiles(self):
        """
        Mappe automatiquement les Node Profiles depuis les leaf names.
        """
        if not self.node_id_mapping or not self.dest_node_ids:
            return

        print("\n" + "-" * 60)
        print("📋 MAPPING AUTOMATIQUE NODE PROFILES")
        print("-" * 60)

        # Récupérer les node profiles de l'Excel
        excel_node_profiles = list(self.find_all_values(self.node_profile_columns).keys())

        if not excel_node_profiles:
            print("   ⚠️  Aucun node profile trouvé dans l'Excel")
            return

        # Pour chaque node profile Excel, extraire les 2 derniers chiffres
        # et trouver la leaf correspondante dans le backup
        for np in excel_node_profiles:
            suffix = extract_node_profile_suffix(np)
            if not suffix:
                continue

            # Chercher la leaf qui se termine par ces 2 chiffres
            for node_id, leaf_name in self.dest_node_ids.items():
                # Extraire les 2 derniers chiffres du node_id
                node_suffix = str(node_id)[-2:] if len(str(node_id)) >= 2 else str(node_id)

                if suffix == node_suffix:
                    # Construire le nouveau node profile
                    dest_np = f"{leaf_name}-NP"
                    self.node_profile_mapping[np] = dest_np
                    print(f"   • {np} → {dest_np}")
                    break

        print(f"\n   ✅ {len(self.node_profile_mapping)} node profiles mappés")

    def handle_route_control_site_identifiers(self):
        """
        Gère le remplacement des identifiants de site dans Route Control.
        """
        # Récupérer tous les noms Route Control
        rc_profiles = list(self.find_all_values(self.route_control_profile_columns).keys())
        rc_contexts = list(self.find_all_values(self.route_control_context_columns).keys())
        match_rules = list(self.find_all_values(self.match_rule_columns).keys())

        all_names = rc_profiles + rc_contexts + match_rules

        if not all_names:
            return

        # Chercher les identifiants de site
        site_ids = find_site_identifiers(all_names)

        if not site_ids:
            return

        print("\n" + "-" * 60)
        print("🏷️  IDENTIFIANTS DE SITE ROUTE CONTROL")
        print("-" * 60)

        print(f"\n   Identifiants trouvés: {', '.join(site_ids)}")

        # Demander le nouvel identifiant
        print(f"\n   Par quel identifiant remplacer? [VRN]: ", end="", flush=True)
        new_id = input().strip().upper()

        if not new_id:
            new_id = 'VRN'

        self.site_identifier_new = new_id
        self.site_identifier_old = list(site_ids)[0] if len(site_ids) == 1 else None

        if len(site_ids) > 1:
            print(f"\n   Plusieurs identifiants trouvés. Lequel remplacer?")
            for i, sid in enumerate(site_ids, 1):
                print(f"   {i}) {sid}")
            print(f"\n   Choix [1]: ", end="", flush=True)
            choice = input().strip()
            try:
                idx = int(choice) - 1 if choice else 0
                self.site_identifier_old = list(site_ids)[idx]
            except (ValueError, IndexError):
                self.site_identifier_old = list(site_ids)[0]

        print(f"\n   ✅ Remplacement: {self.site_identifier_old} → {self.site_identifier_new}")

    def truncate_value(self, value, max_len=25):
        """Tronque une valeur si trop longue"""
        s = str(value) if pd.notna(value) else ''
        if len(s) > max_len:
            return s[:max_len-3] + "..."
        return s

    def format_row_display(self, row, headers, max_cols=6):
        """Formate une ligne pour affichage avec troncature"""
        parts = []
        for i, (val, hdr) in enumerate(zip(row, headers)):
            if i >= max_cols:
                parts.append("...")
                break
            truncated = self.truncate_value(val, 20)
            parts.append(f"{hdr}={truncated}")
        return " | ".join(parts)

    def find_all_values(self, column_list, exclude_sheets=None):
        """
        Trouve les valeurs uniques dans TOUS les onglets.
        Retourne un dict avec les valeurs et leur contexte.
        exclude_sheets: liste d'onglets à exclure de la recherche
        """
        values_with_context = {}
        exclude_sheets = exclude_sheets or []

        for sheet_name, df in self.excel_data.items():
            # Ignorer les onglets exclus
            if sheet_name in exclude_sheets:
                continue
            columns_lower = [str(c).lower() for c in df.columns]

            for col_name in column_list:
                if col_name in columns_lower:
                    idx = columns_lower.index(col_name)
                    real_col = df.columns[idx]

                    for _, row in df.iterrows():
                        val = row[real_col]
                        if pd.notna(val):
                            val_str = str(val).strip()
                            # Pour les node_id, normaliser en int
                            if col_name == 'node_id':
                                try:
                                    val_str = str(int(float(val_str)))
                                except (ValueError, TypeError):
                                    continue

                            if val_str and val_str not in values_with_context:
                                values_with_context[val_str] = []

                            if val_str:
                                # Ajouter le contexte
                                context = {
                                    'sheet_name': sheet_name,
                                    'headers': list(df.columns),
                                    'row': row.tolist()
                                }
                                # Éviter les doublons de contexte
                                existing_sheets = [c['sheet_name'] for c in values_with_context.get(val_str, [])]
                                if sheet_name not in existing_sheets:
                                    values_with_context[val_str].append(context)

        return values_with_context

    def display_value_context_improved(self, value, contexts):
        """Affiche le contexte d'une valeur de manière améliorée"""
        if not contexts:
            return

        print(f"\n   {'─' * 56}")
        print(f"   📍 Valeur: [{value}]")

        for ctx in contexts[:3]:  # Limiter à 3 contextes
            print(f"      ┌─ Onglet: {ctx['sheet_name']}")
            # Afficher seulement les colonnes pertinentes (premières colonnes)
            headers_display = ctx['headers'][:8]
            if len(ctx['headers']) > 8:
                headers_display = headers_display + ['...']
            print(f"      │  Colonnes: {', '.join(str(h) for h in headers_display)}")
            # Afficher la ligne formatée
            row_display = self.format_row_display(ctx['row'], ctx['headers'])
            print(f"      └─ Données: {row_display}")

        if len(contexts) > 3:
            print(f"      ... et {len(contexts) - 3} autre(s) onglet(s)")

    def discover_global_values(self):
        """Découvre les valeurs globales (tenant, vrf, ap)"""
        unique_values = {
            'tenants': set(),
            'vrfs': set(),
            'aps': set()
        }

        for sheet_name, df in self.excel_data.items():
            columns = [str(c).lower() for c in df.columns]

            for col in self.tenant_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    unique_values['tenants'].update(df[real_col].dropna().unique())

            for col in self.vrf_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    unique_values['vrfs'].update(df[real_col].dropna().unique())

            for col in self.ap_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    unique_values['aps'].update(df[real_col].dropna().unique())

        for key in unique_values:
            unique_values[key] = sorted([str(v) for v in unique_values[key] if v and str(v).strip()])

        return unique_values

    def extract_base_name(self, name, suffix):
        """Extrait le nom de base en enlevant le suffixe"""
        if name.endswith(suffix):
            return name[:-len(suffix)]
        return name

    def prompt_mapping(self, prompt_text, source_value, default=None):
        """Demande un mapping à l'utilisateur"""
        if default:
            print(f"   {prompt_text} [{source_value}] → [{default}]: ", end="", flush=True)
        else:
            print(f"   {prompt_text} [{source_value}] → : ", end="", flush=True)

        user_input = input().strip()

        if not user_input:
            return default if default else source_value
        return user_input

    def collect_global_mappings(self, unique_values, skip_auto_mapped=False):
        """Collecte les mappings globaux (tenant → auto VRF/AP)"""
        # Tenants avec dérivation automatique VRF/AP
        # Filtrer les tenants déjà mappés si skip_auto_mapped est actif
        remaining_tenants = [t for t in unique_values['tenants'] if t not in self.tenant_mapping]

        if remaining_tenants:
            print("\n" + "=" * 60)
            print("🏢 CONVERSION DES TENANTS (avec VRF et AP automatiques)")
            print("=" * 60)
            print("Convention: XXXXX-TN → XXXXX-VRF, XXXXX-ANP")
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for tenant in remaining_tenants:
                dest_tenant = self.prompt_mapping("Tenant", tenant, tenant)
                self.tenant_mapping[tenant] = dest_tenant

                # Dériver automatiquement VRF et AP
                if tenant != dest_tenant:
                    # Extraire le nom de base du tenant source
                    src_base = self.extract_base_name(tenant, '-TN')
                    if src_base == tenant:  # Pas de suffixe -TN
                        src_base = tenant

                    # Extraire le nom de base du tenant destination
                    dest_base = self.extract_base_name(dest_tenant, '-TN')
                    if dest_base == dest_tenant:  # Pas de suffixe -TN
                        dest_base = dest_tenant

                    # Mapper VRF: chercher src_base-VRF → dest_base-VRF
                    src_vrf = f"{src_base}-VRF"
                    dest_vrf = f"{dest_base}-VRF"
                    if src_vrf in unique_values['vrfs'] and src_vrf not in self.vrf_mapping:
                        self.vrf_mapping[src_vrf] = dest_vrf
                        print(f"      ↳ VRF auto: {src_vrf} → {dest_vrf}")

                    # Mapper AP: chercher src_base-ANP → dest_base-ANP
                    src_ap = f"{src_base}-ANP"
                    dest_ap = f"{dest_base}-ANP"
                    if src_ap in unique_values['aps'] and src_ap not in self.ap_mapping:
                        self.ap_mapping[src_ap] = dest_ap
                        print(f"      ↳ AP auto:  {src_ap} → {dest_ap}")

        # VRFs restants (non mappés automatiquement)
        remaining_vrfs = [v for v in unique_values['vrfs'] if v not in self.vrf_mapping]
        if remaining_vrfs:
            print("\n" + "=" * 60)
            print("🌐 CONVERSION DES VRFs (non mappés automatiquement)")
            print("=" * 60)
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for vrf in remaining_vrfs:
                dest = self.prompt_mapping("VRF", vrf, vrf)
                self.vrf_mapping[vrf] = dest

        # APs restants (non mappés automatiquement)
        remaining_aps = [a for a in unique_values['aps'] if a not in self.ap_mapping]
        if remaining_aps:
            print("\n" + "=" * 60)
            print("📦 CONVERSION DES APPLICATION PROFILES (non mappés automatiquement)")
            print("=" * 60)
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for ap in remaining_aps:
                dest = self.prompt_mapping("AP", ap, ap)
                self.ap_mapping[ap] = dest

    def collect_bd_to_l3out_mappings(self):
        """Collecte les mappings L3Out depuis l'onglet bd_to_l3out"""
        # Vérifier si l'onglet existe
        if 'bd_to_l3out' not in self.excel_data:
            return

        df = self.excel_data['bd_to_l3out']
        columns_lower = [str(c).lower() for c in df.columns]

        # Trouver la colonne l3out
        l3out_col = None
        for col_name in ['l3out', 'l3out_name']:
            if col_name in columns_lower:
                idx = columns_lower.index(col_name)
                l3out_col = df.columns[idx]
                break

        if l3out_col is None:
            return

        # Extraire les L3Out uniques
        unique_l3outs = df[l3out_col].dropna().unique()
        unique_l3outs = sorted([str(v) for v in unique_l3outs if v and str(v).strip()])

        if not unique_l3outs:
            return

        print("\n" + "=" * 60)
        print("🔗 CONVERSION DES L3OUT (bd_to_l3out)")
        print("=" * 60)
        print("L3Out référencés par les Bridge Domains")

        # Récupérer les suggestions du backup (si disponible)
        backup_l3outs = getattr(self, '_backup_l3outs', {})

        # Afficher les L3Outs trouvés dans le backup
        if backup_l3outs and any(backup_l3outs.values()):
            print("\n   📦 L3Outs trouvés dans le backup destination:")
            if backup_l3outs.get('ns'):
                print(f"      • N/S (Overlay):  {backup_l3outs['ns']}")
            if backup_l3outs.get('dci_ol'):
                print(f"      • DCI (Overlay):  {backup_l3outs['dci_ol']}")
            if backup_l3outs.get('dci_ul'):
                print(f"      • DCI (Underlay): {backup_l3outs['dci_ul']}")
        else:
            print("\n   ⚠️  Aucun L3Out trouvé dans le backup (mode manuel)")

        print("\n   (Appuyez sur Entrée pour utiliser la suggestion du backup)")

        # Afficher le contexte pour chaque L3Out
        for l3out in unique_l3outs:
            # Trouver les BDs qui référencent ce L3Out
            mask = df[l3out_col] == l3out
            matching_rows = df[mask]

            print(f"\n   {'─' * 56}")

            # Détecter le tenant associé (OL ou UL)
            tenant_context = ""
            if 'tenant' in columns_lower:
                tenants = matching_rows['tenant'].tolist()
                if tenants:
                    first_tenant = str(tenants[0]).upper()
                    if '-OL-' in first_tenant:
                        tenant_context = " (Overlay)"
                    elif '-UL-' in first_tenant:
                        tenant_context = " (Underlay)"

            # Déterminer la suggestion depuis le backup
            suggestion = l3out  # Par défaut: garder la même valeur
            l3out_upper = l3out.upper()
            l3out_type = ""

            if backup_l3outs:
                # Détecter le type de L3Out par le nom source
                first_word = l3out_upper.split('-')[0] if '-' in l3out_upper else l3out_upper

                if first_word.startswith('B') and '-NS-' in l3out_upper:
                    # C'est un L3Out N/S (toujours dans Overlay)
                    l3out_type = "N/S"
                    if backup_l3outs.get('ns'):
                        suggestion = backup_l3outs['ns']
                elif l3out_upper.startswith('DCI'):
                    # C'est un L3Out DCI - vérifier OL ou UL par le tenant associé
                    if '-OL-' in l3out_upper or tenant_context == " (Overlay)":
                        l3out_type = "DCI-OL"
                        if backup_l3outs.get('dci_ol'):
                            suggestion = backup_l3outs['dci_ol']
                    else:
                        l3out_type = "DCI-UL"
                        if backup_l3outs.get('dci_ul'):
                            suggestion = backup_l3outs['dci_ul']

            # Affichage amélioré avec type détecté
            type_info = f" [{l3out_type}]" if l3out_type else ""
            print(f"   📍 L3Out Excel: {l3out}{type_info}{tenant_context}")
            print(f"      → Suggestion Backup: {suggestion}")

            # Afficher les BDs qui utilisent ce L3Out
            bd_col = None
            for col_name in ['bd', 'bridge_domain']:
                if col_name in columns_lower:
                    idx = columns_lower.index(col_name)
                    bd_col = df.columns[idx]
                    break

            if bd_col:
                bd_list = matching_rows[bd_col].tolist()
                tenant_list = matching_rows['tenant'].tolist() if 'tenant' in columns_lower else []
                if bd_list:
                    print(f"      BDs: {', '.join(str(b) for b in bd_list[:3])}", end="")
                    if len(bd_list) > 3:
                        print(f" ... (+{len(bd_list) - 3})")
                    else:
                        print()

            dest = self.prompt_mapping("L3Out", l3out, suggestion)
            self.l3out_mapping[l3out] = dest

    def _is_overlay_context(self, l3out: str, df, matching_rows) -> bool:
        """Détermine si le L3Out est dans un contexte Overlay basé sur les BDs."""
        # Vérifier si les BDs/tenants associés contiennent -OL-
        if 'tenant' in [c.lower() for c in df.columns]:
            for tenant in matching_rows['tenant'].tolist():
                if '-OL-' in str(tenant).upper():
                    return True
        return False

    def collect_l3out_mappings(self):
        """Collecte les mappings L3Out pour TOUS les onglets (unifié)"""
        print("\n" + "=" * 60)
        print("🔌 CONVERSIONS L3OUT (tous les onglets)")
        print("=" * 60)

        # Node IDs (filtrer ceux déjà auto-mappés)
        node_ids = self.find_all_values(self.node_id_columns)
        remaining_node_ids = {k: v for k, v in node_ids.items() if k not in self.node_id_mapping}
        if remaining_node_ids:
            print(f"\n{'─' * 60}")
            print(f"🖥️  NODE IDs")
            print(f"{'─' * 60}")

            for node_id, contexts in sorted(remaining_node_ids.items()):
                self.display_value_context_improved(node_id, contexts)
                dest = self.prompt_mapping("Node ID", node_id, node_id)
                self.node_id_mapping[node_id] = dest
        elif self.node_id_mapping:
            print(f"\n   ✅ Tous les Node IDs déjà mappés automatiquement ({len(self.node_id_mapping)})")

        # Node Profiles (filtrer ceux déjà auto-mappés)
        node_profiles = self.find_all_values(self.node_profile_columns)
        remaining_node_profiles = {k: v for k, v in node_profiles.items() if k not in self.node_profile_mapping}
        if remaining_node_profiles:
            print(f"\n{'─' * 60}")
            print(f"📋 NODE PROFILES")
            print(f"{'─' * 60}")

            for np, contexts in sorted(remaining_node_profiles.items()):
                self.display_value_context_improved(np, contexts)
                dest = self.prompt_mapping("Node Profile", np, np)
                self.node_profile_mapping[np] = dest
        elif self.node_profile_mapping:
            print(f"\n   ✅ Tous les Node Profiles déjà mappés automatiquement ({len(self.node_profile_mapping)})")

        # Interface Profiles (L3Out seulement - exclure les onglets Leaf Interface)
        exclude_leaf_sheets = ['interface_policy_leaf_profile', 'access_port_to_int_policy_leaf']
        int_profiles = self.find_all_values(self.int_profile_columns, exclude_sheets=exclude_leaf_sheets)
        remaining_int_profiles = {k: v for k, v in int_profiles.items() if k not in self.int_profile_mapping}
        if remaining_int_profiles:
            print(f"\n{'─' * 60}")
            print(f"🔌 INTERFACE PROFILES")
            print(f"{'─' * 60}")

            for ip, contexts in sorted(remaining_int_profiles.items()):
                self.display_value_context_improved(ip, contexts)
                dest = self.prompt_mapping("Interface Profile", ip, ip)
                self.int_profile_mapping[ip] = dest

        # Path EPs
        path_eps = self.find_all_values(self.path_ep_columns)
        if path_eps:
            print(f"\n{'─' * 60}")
            print(f"🛤️  PATH EPs")
            print(f"{'─' * 60}")

            for path, contexts in sorted(path_eps.items()):
                self.display_value_context_improved(path, contexts)
                dest = self.prompt_mapping("Path EP", path, path)
                self.path_ep_mapping[path] = dest

        # Local AS
        local_as_values = self.find_all_values(self.local_as_columns)
        if local_as_values:
            print(f"\n{'─' * 60}")
            print(f"🔢 LOCAL AS")
            print(f"{'─' * 60}")

            for las, contexts in sorted(local_as_values.items()):
                self.display_value_context_improved(las, contexts)
                dest = self.prompt_mapping("Local AS", las, las)
                self.local_as_mapping[las] = dest

    def collect_route_control_mappings(self):
        """Collecte les mappings Route Control pour tous les onglets"""
        print("\n" + "=" * 60)
        print("🛣️  CONVERSIONS ROUTE CONTROL")
        print("=" * 60)

        # Si un remplacement de site identifier est configuré, l'afficher
        if self.site_identifier_old and self.site_identifier_new:
            print(f"\n   💡 Remplacement automatique: {self.site_identifier_old} → {self.site_identifier_new}")

        # Match Rules
        match_rules = self.find_all_values(self.match_rule_columns)
        if match_rules:
            print(f"\n{'─' * 60}")
            print(f"📏 MATCH RULES")
            print(f"{'─' * 60}")

            for mr, contexts in sorted(match_rules.items()):
                self.display_value_context_improved(mr, contexts)

                # Appliquer le remplacement de site identifier si configuré
                default_val = mr
                if self.site_identifier_old and self.site_identifier_new:
                    default_val = replace_site_identifier(mr, self.site_identifier_old, self.site_identifier_new)

                dest = self.prompt_mapping("Match Rule", mr, default_val)
                self.match_rule_mapping[mr] = dest

        # Route Control Profiles
        rc_profiles = self.find_all_values(self.route_control_profile_columns)
        if rc_profiles:
            print(f"\n{'─' * 60}")
            print(f"📋 ROUTE CONTROL PROFILES")
            print(f"{'─' * 60}")

            for rcp, contexts in sorted(rc_profiles.items()):
                self.display_value_context_improved(rcp, contexts)

                # Appliquer le remplacement de site identifier si configuré
                default_val = rcp
                if self.site_identifier_old and self.site_identifier_new:
                    default_val = replace_site_identifier(rcp, self.site_identifier_old, self.site_identifier_new)

                dest = self.prompt_mapping("Route Control Profile", rcp, default_val)
                self.route_control_profile_mapping[rcp] = dest

        # Route Control Contexts
        rc_contexts = self.find_all_values(self.route_control_context_columns)
        if rc_contexts:
            print(f"\n{'─' * 60}")
            print(f"🔀 ROUTE CONTROL CONTEXTS")
            print(f"{'─' * 60}")

            for rcc, contexts in sorted(rc_contexts.items()):
                self.display_value_context_improved(rcc, contexts)

                # Appliquer le remplacement de site identifier si configuré
                default_val = rcc
                if self.site_identifier_old and self.site_identifier_new:
                    default_val = replace_site_identifier(rcc, self.site_identifier_old, self.site_identifier_new)

                dest = self.prompt_mapping("Route Control Context", rcc, default_val)
                self.route_control_context_mapping[rcc] = dest

    def apply_conversions(self):
        """Applique les conversions à tous les onglets"""
        print("\n" + "=" * 60)
        print("⚙️  APPLICATION DES CONVERSIONS")
        print("=" * 60)

        total_changes = 0

        for sheet_name, df in self.excel_data.items():
            sheet_changes = 0
            columns = [str(c).lower() for c in df.columns]

            # Conversion Tenants
            for col in self.tenant_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.tenant_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion VRFs
            for col in self.vrf_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.vrf_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion APs
            for col in self.ap_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.ap_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion L3Out (pour bd_to_l3out)
            if sheet_name == 'bd_to_l3out':
                for col_name in ['l3out', 'l3out_name']:
                    if col_name in columns:
                        idx = columns.index(col_name)
                        real_col = df.columns[idx]
                        for src, dest in self.l3out_mapping.items():
                            if src != dest:
                                mask = df[real_col] == src
                                count = mask.sum()
                                if count > 0:
                                    df.loc[mask, real_col] = dest
                                    sheet_changes += count

            # Conversion Node IDs (tous les onglets)
            for col in self.node_id_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.node_id_mapping.items():
                        if src != dest:
                            mask = df[real_col].astype(str).str.strip() == str(src).strip()
                            count = mask.sum()
                            if count > 0:
                                try:
                                    df.loc[mask, real_col] = int(dest)
                                except ValueError:
                                    df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Node Profiles (tous les onglets)
            for col in self.node_profile_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.node_profile_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Interface Profiles (tous les onglets)
            for col in self.int_profile_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.int_profile_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Path EPs (tous les onglets SAUF interface_config)
            # BUG FIX: 'interface' est dans path_ep_columns mais aussi colonne de interface_config
            if sheet_name != 'interface_config':
                for col in self.path_ep_columns:
                    if col in columns:
                        idx = columns.index(col)
                        real_col = df.columns[idx]
                        for src, dest in self.path_ep_mapping.items():
                            if src != dest:
                                mask = df[real_col] == src
                                count = mask.sum()
                                if count > 0:
                                    df.loc[mask, real_col] = dest
                                    sheet_changes += count

            # Conversion Local AS (tous les onglets)
            for col in self.local_as_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.local_as_mapping.items():
                        if src != dest:
                            mask = df[real_col].astype(str) == src
                            count = mask.sum()
                            if count > 0:
                                try:
                                    df.loc[mask, real_col] = int(dest)
                                except ValueError:
                                    df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Match Rules (tous les onglets)
            for col in self.match_rule_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.match_rule_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Route Control Profiles (tous les onglets)
            for col in self.route_control_profile_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.route_control_profile_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Route Control Contexts (tous les onglets)
            for col in self.route_control_context_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in self.route_control_context_mapping.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            if sheet_changes > 0:
                print(f"   📝 {sheet_name}: {sheet_changes} modifications")
                total_changes += sheet_changes

        print(f"\n📊 Total: {total_changes} modifications appliquées")
        return total_changes

    def save_excel(self):
        """Sauvegarde le fichier Excel converti"""
        print(f"\n💾 Sauvegarde du fichier: {self.output_excel}")

        with pd.ExcelWriter(self.output_excel, engine='openpyxl') as writer:
            for sheet_name, df in self.excel_data.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        print(f"✅ Fichier sauvegardé: {self.output_excel}")

    def show_summary(self):
        """Affiche un résumé des mappings configurés"""
        print("\n" + "=" * 60)
        print("📋 RÉSUMÉ DES CONVERSIONS")
        print("=" * 60)

        def show_mapping(title, mapping, indent=""):
            changes = {k: v for k, v in mapping.items() if k != v}
            if changes:
                print(f"{indent}{title}:")
                for src, dest in changes.items():
                    print(f"{indent}   {src} → {dest}")
                return True
            return False

        # Global
        print("\n🌍 GLOBAL:")
        has_global = False
        has_global |= show_mapping("Tenants", self.tenant_mapping, "   ")
        has_global |= show_mapping("VRFs", self.vrf_mapping, "   ")
        has_global |= show_mapping("Application Profiles", self.ap_mapping, "   ")
        if not has_global:
            print("   (aucun changement)")

        # BD to L3Out
        print("\n🔗 BD TO L3OUT:")
        has_bd_l3out = show_mapping("L3Out", self.l3out_mapping, "   ")
        if not has_bd_l3out:
            print("   (aucun changement)")

        # L3Out unifié
        print("\n🔌 L3OUT (tous les onglets):")
        has_l3out = False
        has_l3out |= show_mapping("Node IDs", self.node_id_mapping, "   ")
        has_l3out |= show_mapping("Node Profiles", self.node_profile_mapping, "   ")
        has_l3out |= show_mapping("Interface Profiles", self.int_profile_mapping, "   ")
        has_l3out |= show_mapping("Path EPs", self.path_ep_mapping, "   ")
        has_l3out |= show_mapping("Local AS", self.local_as_mapping, "   ")
        if not has_l3out:
            print("   (aucun changement)")

        # Route Control
        print("\n🛣️  ROUTE CONTROL:")
        has_rc = False
        has_rc |= show_mapping("Match Rules", self.match_rule_mapping, "   ")
        has_rc |= show_mapping("Route Control Profiles", self.route_control_profile_mapping, "   ")
        has_rc |= show_mapping("Route Control Contexts", self.route_control_context_mapping, "   ")
        if not has_rc:
            print("   (aucun changement)")

        # Options supplémentaires
        print("\n⚙️  OPTIONS SUPPLÉMENTAIRES:")
        if self.disable_bd_routing:
            print("   🔀 Routage BD: sera désactivé pour tous les BD")
        else:
            print("   🔀 Routage BD: pas de modification")

        if self.vlan_descriptions:
            print(f"   📝 Descriptions VLAN: {len(self.vlan_descriptions)} entrée(s) à modifier")
            for vlan, desc in self.vlan_descriptions[:5]:  # Afficher les 5 premières
                circuit = desc.split('_')[0] if '_' in desc else desc
                print(f"      • VLAN {vlan}: {circuit} → {desc[:40]}{'...' if len(desc) > 40 else ''}")
            if len(self.vlan_descriptions) > 5:
                print(f"      ... et {len(self.vlan_descriptions) - 5} autre(s)")
        else:
            print("   📝 Descriptions VLAN: pas de modification")

    def collect_bd_routing_option(self):
        """Demande si l'utilisateur veut désactiver le routage des BD"""
        print("\n" + "=" * 60)
        print("🔀 OPTION ROUTAGE BD")
        print("=" * 60)
        print("Désactiver le routage pour tous les Bridge Domains?")
        print("(Mettra enable_routing = false dans l'onglet bd)")
        print("\nDésactiver le routage? [o/N]: ", end="", flush=True)

        response = input().strip().lower()
        self.disable_bd_routing = response in ['o', 'oui', 'y', 'yes']

        if self.disable_bd_routing:
            print("   ✅ Le routage sera désactivé pour tous les BD")
        else:
            print("   ℹ️  Le routage ne sera pas modifié")

    def collect_vlan_pool_auto_descriptions(self):
        """Auto-génère les descriptions des VLAN Pool basées sur le nom"""
        print("\n" + "=" * 60)
        print("📝 AUTO-GÉNÉRATION DES DESCRIPTIONS VLAN POOL")
        print("=" * 60)

        if 'vlan_pool' not in self.excel_data:
            print("   ⚠️  Onglet vlan_pool non trouvé - étape ignorée")
            return

        print("Voulez-vous auto-générer les descriptions des VLAN Pools?")
        print("Règles appliquées:")
        print("   • Premier mot avant '-' ou '_' = nom du serveur")
        print("   • Si contient P1 ou P2 → nom_SEGMENTS_VLAN")
        print("   • Si contient P3 ou P4 (sans L3O) → nom_VTEP")
        print("   • Si contient P3 ou P4 avec L3O → nom_L3OUT")
        print("\nAuto-générer les descriptions? [o/N]: ", end="", flush=True)

        response = input().strip().lower()
        if response not in ['o', 'oui', 'y', 'yes']:
            print("   ℹ️  Aucune modification des descriptions VLAN Pool")
            return

        vlan_pool_df = self.excel_data['vlan_pool']
        columns_lower = [str(c).lower() for c in vlan_pool_df.columns]

        # Trouver les colonnes pool et description
        pool_col = None
        desc_col = None
        for col in ['pool', 'pool_name', 'name', 'vlan_pool']:
            if col in columns_lower:
                pool_col = vlan_pool_df.columns[columns_lower.index(col)]
                break
        for col in ['description', 'descr', 'desc']:
            if col in columns_lower:
                desc_col = vlan_pool_df.columns[columns_lower.index(col)]
                break

        if not pool_col:
            print("   ⚠️  Colonne 'pool' non trouvée dans vlan_pool")
            return
        if not desc_col:
            print("   ⚠️  Colonne 'description' non trouvée dans vlan_pool")
            return

        print("\n" + "-" * 60)
        print("VLAN Pools détectés - Validez ou modifiez chaque description")
        print("-" * 60)

        import re
        generated_descriptions = {}

        for idx, row in vlan_pool_df.iterrows():
            pool_name = str(row[pool_col]).strip()
            if not pool_name or pool_name == 'nan':
                continue

            # Extraire le premier mot avant - ou _
            match = re.match(r'^([^-_]+)', pool_name)
            server_name = match.group(1) if match else pool_name

            # Déterminer le type basé sur P1/P2/P3/P4/L3O
            pool_upper = pool_name.upper()
            has_p1_p2 = 'P1' in pool_upper or 'P2' in pool_upper
            has_p3_p4 = 'P3' in pool_upper or 'P4' in pool_upper
            has_l3o = 'L3O' in pool_upper

            # Générer la description
            if has_p3_p4 and has_l3o:
                auto_desc = f"{server_name}_L3OUT"
            elif has_p3_p4:
                auto_desc = f"{server_name}_VTEP"
            elif has_p1_p2:
                auto_desc = f"{server_name}_SEGMENTS_VLAN"
            else:
                auto_desc = ""  # Pas de règle applicable

            if auto_desc:
                print(f"\n   Pool: {pool_name}")
                print(f"   Description auto: {auto_desc}")
                print(f"   → Confirmer ou modifier [{auto_desc}]: ", end="", flush=True)

                user_input = input().strip()
                final_desc = user_input if user_input else auto_desc
                generated_descriptions[pool_name] = final_desc
                print(f"   ✅ Description: {final_desc}")

        if generated_descriptions:
            self.vlan_pool_descriptions = generated_descriptions
            print(f"\n✅ {len(generated_descriptions)} description(s) VLAN Pool configurée(s)")
        else:
            print("\n   ℹ️  Aucun VLAN Pool correspondant aux règles")

    def apply_vlan_pool_descriptions(self):
        """Applique les descriptions auto-générées aux VLAN Pools"""
        if not self.vlan_pool_descriptions:
            return 0

        if 'vlan_pool' not in self.excel_data:
            return 0

        vlan_pool_df = self.excel_data['vlan_pool']
        columns_lower = [str(c).lower() for c in vlan_pool_df.columns]

        pool_col = None
        desc_col = None
        for col in ['pool', 'pool_name', 'name', 'vlan_pool']:
            if col in columns_lower:
                pool_col = vlan_pool_df.columns[columns_lower.index(col)]
                break
        for col in ['description', 'descr', 'desc']:
            if col in columns_lower:
                desc_col = vlan_pool_df.columns[columns_lower.index(col)]
                break

        if not pool_col or not desc_col:
            return 0

        count = 0
        for pool_name, description in self.vlan_pool_descriptions.items():
            mask = vlan_pool_df[pool_col] == pool_name
            if mask.any():
                vlan_pool_df.loc[mask, desc_col] = description
                count += 1

        if count > 0:
            print(f"   ✅ {count} description(s) VLAN Pool appliquée(s)")

        return count

    def collect_encap_block_split(self):
        """Split les VLAN encap blocks en ranges vers des VLANs individuels"""
        print("\n" + "=" * 60)
        print("📋 SPLIT DES VLAN POOL ENCAP BLOCKS")
        print("=" * 60)

        if 'vlan_pool_encap_block' not in self.excel_data:
            print("   ⚠️  Onglet vlan_pool_encap_block non trouvé - étape ignorée")
            return

        encap_df = self.excel_data['vlan_pool_encap_block']
        columns_lower = [str(c).lower() for c in encap_df.columns]

        # Trouver les colonnes
        start_col = None
        end_col = None
        pool_col = None
        mode_col = None
        desc_col = None

        for col in ['block_start', 'start', 'from']:
            if col in columns_lower:
                start_col = encap_df.columns[columns_lower.index(col)]
                break
        for col in ['block_end', 'end', 'to']:
            if col in columns_lower:
                end_col = encap_df.columns[columns_lower.index(col)]
                break
        for col in ['pool', 'pool_name', 'vlan_pool']:
            if col in columns_lower:
                pool_col = encap_df.columns[columns_lower.index(col)]
                break
        for col in ['pool_allocation_mode', 'allocation_mode', 'mode']:
            if col in columns_lower:
                mode_col = encap_df.columns[columns_lower.index(col)]
                break
        for col in ['description', 'descr', 'desc']:
            if col in columns_lower:
                desc_col = encap_df.columns[columns_lower.index(col)]
                break

        if not start_col or not end_col:
            print("   ⚠️  Colonnes block_start/block_end non trouvées")
            return

        # Détecter les ranges (block_start != block_end)
        ranges_found = []
        for idx, row in encap_df.iterrows():
            try:
                start = int(row[start_col])
                end = int(row[end_col])
                if start != end:
                    pool_name = row[pool_col] if pool_col else 'Unknown'
                    vlan_count = end - start + 1
                    ranges_found.append({
                        'idx': idx,
                        'pool': pool_name,
                        'start': start,
                        'end': end,
                        'count': vlan_count
                    })
            except (ValueError, TypeError):
                continue

        if not ranges_found:
            print("   ℹ️  Aucun range détecté - tous les encap blocks sont déjà individuels")
            return

        print("Voulez-vous splitter les ranges en VLANs individuels?")
        print("Cela permet d'appliquer une description différente par VLAN.\n")
        print("Pools avec ranges détectés:")
        total_vlans = 0
        for r in ranges_found:
            print(f"   • {r['pool']}: {r['start']}-{r['end']} ({r['count']} VLANs)")
            total_vlans += r['count']
        print(f"\n   Total: {total_vlans} VLANs seront créés")

        print("\nSplitter les ranges? [o/N]: ", end="", flush=True)
        response = input().strip().lower()

        if response not in ['o', 'oui', 'y', 'yes']:
            print("   ℹ️  Les ranges ne seront pas splittés")
            return

        # Créer les nouvelles lignes
        print(f"\n🔄 Split en cours...")
        new_rows = []

        for idx, row in encap_df.iterrows():
            try:
                start = int(row[start_col])
                end = int(row[end_col])
            except (ValueError, TypeError):
                new_rows.append(row.to_dict())
                continue

            if start == end:
                # Pas un range, garder tel quel
                new_rows.append(row.to_dict())
            else:
                # Splitter le range
                for vlan in range(start, end + 1):
                    new_row = row.to_dict()
                    new_row[start_col] = vlan
                    new_row[end_col] = vlan
                    new_rows.append(new_row)

        # Remplacer le DataFrame
        new_df = pd.DataFrame(new_rows)
        self.excel_data['vlan_pool_encap_block'] = new_df

        print(f"   ✅ {len(ranges_found)} range(s) splittés en {len(new_df)} lignes individuelles")
        print(f"   📝 Vous pourrez maintenant appliquer des descriptions par VLAN")

    def collect_vlan_descriptions(self):
        """Collecte les descriptions à modifier basées sur VLAN"""
        print("\n" + "=" * 60)
        print("📝 MODIFICATION DES DESCRIPTIONS PAR VLAN")
        print("=" * 60)
        print("Voulez-vous modifier des descriptions basées sur VLAN?")
        print("\nModifier des descriptions? [o/N]: ", end="", flush=True)

        response = input().strip().lower()
        if response not in ['o', 'oui', 'y', 'yes']:
            print("   ℹ️  Aucune modification de description")
            return

        print("\n" + "-" * 60)
        print("Format attendu: VLAN,RLXXXXX_XXX.XXX.XXX.XXX/XX_DESCRIPTION")
        print("Exemple: 200,RL00001_10.1.1.1/24_Serveur_Web")
        print("-" * 60)
        print("Collez vos lignes puis appuyez sur Entrée (ligne vide pour terminer):\n")

        lines = []
        while True:
            try:
                line = input()
                if not line.strip():
                    break
                lines.append(line.strip())
            except EOFError:
                break

        if not lines:
            print("   ℹ️  Aucune ligne fournie")
            return

        # Parser les lignes
        print(f"\n🔍 Analyse de {len(lines)} ligne(s)...")

        for line in lines:
            if ',' not in line:
                print(f"   ⚠️  Ligne ignorée (pas de virgule): {line[:50]}...")
                continue

            parts = line.split(',', 1)  # Split sur la première virgule seulement
            vlan_str = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ''

            try:
                vlan = int(vlan_str)
            except ValueError:
                print(f"   ⚠️  VLAN invalide: {vlan_str}")
                continue

            if not description:
                print(f"   ⚠️  Description vide pour VLAN {vlan}")
                continue

            self.vlan_descriptions.append((vlan, description))
            print(f"   ✅ VLAN {vlan}: {description[:50]}{'...' if len(description) > 50 else ''}")

        print(f"\n📊 {len(self.vlan_descriptions)} entrée(s) à traiter")

    def apply_vlan_descriptions(self):
        """Applique les modifications de descriptions basées sur VLAN"""
        if not self.vlan_descriptions:
            return 0

        print("\n" + "=" * 60)
        print("📝 APPLICATION DES DESCRIPTIONS PAR VLAN")
        print("=" * 60)

        total_changes = 0

        # Charger l'onglet vlan_pool_encap_block
        if 'vlan_pool_encap_block' not in self.excel_data:
            print("   ⚠️  Onglet vlan_pool_encap_block non trouvé")
            return 0

        vlan_df = self.excel_data['vlan_pool_encap_block']
        vlan_columns = [str(c).lower() for c in vlan_df.columns]

        # Trouver les colonnes block_start et block_end
        start_col = None
        end_col = None
        desc_col = None

        for col in ['block_start', 'from', 'start']:
            if col in vlan_columns:
                start_col = vlan_df.columns[vlan_columns.index(col)]
                break

        for col in ['block_end', 'to', 'end']:
            if col in vlan_columns:
                end_col = vlan_df.columns[vlan_columns.index(col)]
                break

        for col in ['description', 'descr']:
            if col in vlan_columns:
                desc_col = vlan_df.columns[vlan_columns.index(col)]
                break

        if not start_col or not end_col:
            print("   ⚠️  Colonnes block_start/block_end non trouvées")
            return 0

        for vlan, description in self.vlan_descriptions:
            print(f"\n   🔍 Traitement VLAN {vlan}...")

            # Extraire le numéro de circuit (tout avant le premier _)
            circuit = description.split('_')[0] if '_' in description else description
            bd_name = f"{circuit}-BD"
            epg_name = f"{circuit}-EPG"

            print(f"      Circuit: {circuit} → BD: {bd_name}, EPG: {epg_name}")

            # 1. Vérifier si VLAN est dans une plage et modifier vlan_pool_encap_block
            vlan_found = False
            for idx, row in vlan_df.iterrows():
                try:
                    start = int(row[start_col])
                    end = int(row[end_col])
                    if start <= vlan <= end:
                        vlan_found = True
                        if desc_col:
                            vlan_df.at[idx, desc_col] = description
                            print(f"      ✅ vlan_pool_encap_block: description mise à jour")
                            total_changes += 1
                        break
                except (ValueError, TypeError):
                    continue

            if not vlan_found:
                print(f"      ⚠️  VLAN {vlan} non trouvé dans les plages")
                continue

            # 2. Modifier la description dans l'onglet bd
            if 'bd' in self.excel_data:
                bd_df = self.excel_data['bd']
                bd_columns = [str(c).lower() for c in bd_df.columns]

                bd_col_name = None
                bd_desc_col = None

                for col in ['bd', 'name', 'bridge_domain']:
                    if col in bd_columns:
                        bd_col_name = bd_df.columns[bd_columns.index(col)]
                        break

                for col in ['description', 'descr']:
                    if col in bd_columns:
                        bd_desc_col = bd_df.columns[bd_columns.index(col)]
                        break

                if bd_col_name and bd_desc_col:
                    mask = bd_df[bd_col_name] == bd_name
                    if mask.any():
                        bd_df.loc[mask, bd_desc_col] = description
                        print(f"      ✅ bd: description mise à jour pour {bd_name}")
                        total_changes += 1

            # 3. Modifier la description dans l'onglet epg
            if 'epg' in self.excel_data:
                epg_df = self.excel_data['epg']
                epg_columns = [str(c).lower() for c in epg_df.columns]

                epg_col_name = None
                epg_desc_col = None

                for col in ['epg', 'name']:
                    if col in epg_columns:
                        epg_col_name = epg_df.columns[epg_columns.index(col)]
                        break

                for col in ['description', 'descr']:
                    if col in epg_columns:
                        epg_desc_col = epg_df.columns[epg_columns.index(col)]
                        break

                if epg_col_name and epg_desc_col:
                    mask = epg_df[epg_col_name] == epg_name
                    if mask.any():
                        epg_df.loc[mask, epg_desc_col] = description
                        print(f"      ✅ epg: description mise à jour pour {epg_name}")
                        total_changes += 1

            # 4. Modifier la description dans l'onglet bd_subnet
            if 'bd_subnet' in self.excel_data:
                subnet_df = self.excel_data['bd_subnet']
                subnet_columns = [str(c).lower() for c in subnet_df.columns]

                subnet_bd_col = None
                subnet_desc_col = None

                for col in ['bd', 'bridge_domain']:
                    if col in subnet_columns:
                        subnet_bd_col = subnet_df.columns[subnet_columns.index(col)]
                        break

                for col in ['description', 'descr']:
                    if col in subnet_columns:
                        subnet_desc_col = subnet_df.columns[subnet_columns.index(col)]
                        break

                if subnet_bd_col and subnet_desc_col:
                    mask = subnet_df[subnet_bd_col] == bd_name
                    if mask.any():
                        subnet_df.loc[mask, subnet_desc_col] = description
                        print(f"      ✅ bd_subnet: description mise à jour pour {bd_name}")
                        total_changes += 1

        print(f"\n📊 Total descriptions modifiées: {total_changes}")
        return total_changes

    def apply_bd_routing_disable(self):
        """Désactive le routage pour tous les BD"""
        if not self.disable_bd_routing:
            return 0

        if 'bd' not in self.excel_data:
            print("   ⚠️  Onglet bd non trouvé")
            return 0

        bd_df = self.excel_data['bd']
        columns = [str(c).lower() for c in bd_df.columns]

        routing_col = None
        for col in ['enable_routing', 'unicast_route', 'routing']:
            if col in columns:
                routing_col = bd_df.columns[columns.index(col)]
                break

        if not routing_col:
            print("   ⚠️  Colonne enable_routing non trouvée dans l'onglet bd")
            return 0

        # Mettre toutes les valeurs à false
        count = len(bd_df)
        bd_df[routing_col] = 'false'

        print(f"   ✅ Routage désactivé pour {count} Bridge Domain(s)")
        return count

    def create_routing_enable_excel(self):
        """Crée un fichier Excel pour réactiver le routage des BD"""
        if not self.disable_bd_routing:
            return

        if 'bd' not in self.excel_data:
            return

        # Nom du fichier: BD-{nom_original}-routing_enable.xlsx
        excel_path = Path(self.excel_file)
        routing_enable_file = str(excel_path.parent / f"BD-{excel_path.stem}-routing_enable.xlsx")

        bd_df = self.excel_data['bd'].copy()
        columns_lower = [str(c).lower() for c in bd_df.columns]

        # Trouver la colonne enable_routing
        routing_col = None
        for col in ['enable_routing', 'unicast_route', 'routing']:
            if col in columns_lower:
                routing_col = bd_df.columns[columns_lower.index(col)]
                break

        if not routing_col:
            print("   ⚠️  Impossible de créer le fichier routing_enable - colonne non trouvée")
            return

        # Supprimer les colonnes inutiles (description, arp_flooding, l2_unknown_unicast)
        columns_to_drop = []
        for col in bd_df.columns:
            col_lower = str(col).lower()
            if col_lower in ['description', 'descr', 'desc', 'arp_flooding', 'l2_unknown_unicast', 'unknown_unicast']:
                columns_to_drop.append(col)
        if columns_to_drop:
            bd_df = bd_df.drop(columns=columns_to_drop)

        # Mettre toutes les valeurs à true (format Ansible standard)
        bd_df[routing_col] = 'true'

        # Créer le fichier Excel avec seulement l'onglet bd
        with pd.ExcelWriter(routing_enable_file, engine='openpyxl') as writer:
            bd_df.to_excel(writer, sheet_name='bd', index=False)

        print(f"   📁 Fichier routing_enable créé: {routing_enable_file}")
        print(f"      → Utilisez ce fichier pour réactiver le routage après les travaux")

    def _extract_leaf_ids_from_profile(self, profile_name):
        """
        Extrait les identifiants de leaf d'un nom d'Interface Profile.

        Patterns supportés:
        - SF22-121-LIP → ['121'] (single leaf)
        - SF22-121-122-LIP → ['121', '122'] (VPC)
        - SF22-121-22-LIP → ['121', '22'] (VPC format court)

        Args:
            profile_name: Nom du profile (ex: SF22-121-LIP)

        Returns:
            Liste des identifiants de leaf, ou None si pattern non reconnu
        """
        # Enlever le suffixe -LIP
        if not profile_name.upper().endswith('-LIP'):
            return None

        base_name = profile_name[:-4]  # Enlever -LIP

        # Pattern: FABRIC-LEAF ou FABRIC-LEAF1-LEAF2
        # Ex: SF22-121 ou SF22-121-122 ou SF22-121-22
        parts = base_name.split('-')

        if len(parts) < 2:
            return None

        # Le premier élément est le fabric (SF22), les suivants sont les leafs
        leaf_ids = []
        for part in parts[1:]:
            # Vérifier si c'est un nombre (leaf id)
            if part.isdigit():
                leaf_ids.append(part)

        return leaf_ids if leaf_ids else None

    def _auto_map_profiles_to_nodes(self, interface_profiles, available_node_ids, is_vpc=False):
        """
        Auto-mappe les Interface Profiles aux Node IDs.

        Logique:
        - Extraire les leaf IDs de chaque profile
        - Trier tous les leaf IDs uniques
        - Mapper au node_ids triés (plus petit → plus petit)

        Args:
            interface_profiles: Liste des noms de profiles
            available_node_ids: Liste des node_ids disponibles
            is_vpc: True si VPC (profiles avec 2 leafs)

        Returns:
            Dict {profile_name: node_id} pour single leaf
            Dict {profile_name: [node_id1, node_id2]} pour VPC
            Ou None si échec
        """
        # Extraire tous les leaf IDs et leur association avec les profiles
        profile_leaf_map = {}  # profile -> list of leaf_ids
        all_leaf_ids = set()

        for profile in interface_profiles:
            leaf_ids = self._extract_leaf_ids_from_profile(profile)
            if leaf_ids:
                profile_leaf_map[profile] = leaf_ids
                all_leaf_ids.update(leaf_ids)

        if not all_leaf_ids:
            return None

        # Trier les leaf IDs numériquement
        sorted_leaf_ids = sorted(all_leaf_ids, key=lambda x: int(x))

        # Trier les node_ids
        sorted_node_ids = sorted([str(n) for n in available_node_ids])

        # Créer le mapping leaf_id → node_id
        leaf_to_node = {}
        for i, leaf_id in enumerate(sorted_leaf_ids):
            if i < len(sorted_node_ids):
                leaf_to_node[leaf_id] = sorted_node_ids[i]

        # Créer le mapping profile → node(s)
        profile_to_node = {}
        for profile, leaf_ids in profile_leaf_map.items():
            if is_vpc and len(leaf_ids) >= 2:
                # VPC: mapper les 2 leafs aux 2 nodes
                nodes = []
                for lid in sorted(leaf_ids, key=lambda x: int(x)):
                    if lid in leaf_to_node:
                        nodes.append(leaf_to_node[lid])
                if len(nodes) == 2:
                    profile_to_node[profile] = nodes
            else:
                # Single leaf: mapper à 1 node
                if leaf_ids[0] in leaf_to_node:
                    profile_to_node[profile] = leaf_to_node[leaf_ids[0]]

        return profile_to_node, leaf_to_node

    def _display_and_confirm_mapping(self, profile_to_node, is_vpc=False):
        """
        Affiche le mapping auto-détecté et permet la modification.

        Args:
            profile_to_node: Dict du mapping profile → node(s)
            is_vpc: True si VPC

        Returns:
            Dict modifié du mapping
        """
        print("\n" + "-" * 60)
        print("🔄 AUTO-MAPPING INTERFACE PROFILE → NODE ID")
        print("-" * 60)

        # Afficher le mapping avec numéros
        profiles_list = list(profile_to_node.keys())
        for i, profile in enumerate(profiles_list, 1):
            node_val = profile_to_node[profile]
            if isinstance(node_val, list):
                print(f"   {i}. {profile} → {', '.join(node_val)} (VPC)")
            else:
                print(f"   {i}. {profile} → {node_val}")

        # Permettre la modification
        while True:
            print(f"\nModifier un mapping? Entrez le numéro (1-{len(profiles_list)}) ou Entrée pour continuer: ", end="", flush=True)
            choice = input().strip()

            if not choice:
                break

            try:
                idx = int(choice) - 1
                if 0 <= idx < len(profiles_list):
                    profile = profiles_list[idx]
                    current = profile_to_node[profile]

                    if isinstance(current, list):
                        print(f"   Nouveaux Node IDs pour {profile} (séparés par virgule) [{', '.join(current)}]: ", end="", flush=True)
                        new_val = input().strip()
                        if new_val:
                            new_nodes = [n.strip() for n in new_val.split(',')]
                            profile_to_node[profile] = new_nodes
                            print(f"   ✅ Modifié: {profile} → {', '.join(new_nodes)}")
                    else:
                        print(f"   Nouveau Node ID pour {profile} [{current}]: ", end="", flush=True)
                        new_val = input().strip()
                        if new_val:
                            profile_to_node[profile] = new_val
                            print(f"   ✅ Modifié: {profile} → {new_val}")
                else:
                    print("   ⚠️  Numéro invalide")
            except ValueError:
                print("   ⚠️  Entrée invalide")

        return profile_to_node

    def _detect_policy_groups(self, access_port_df):
        """
        Détecte les policy groups P1_P2, P3, P4 depuis les données existantes.

        Cherche les patterns:
        - {CLUSTER}-P1_P2-IPG → P1_P2 (ports impairs, les 2 leafs)
        - {CLUSTER}-P3-IPG → P3 (ports pairs, petite leaf)
        - {CLUSTER}-P4-IPG → P4 (ports pairs, grosse leaf)

        Returns:
            Tuple (cluster_name, ipg_p1p2, ipg_p3, ipg_p4) ou (None, None, None, None) si non détecté
        """
        policy_groups = access_port_df['policy_group'].dropna().unique().tolist()

        # Chercher les patterns
        ipg_p1p2 = None
        ipg_p3 = None
        ipg_p4 = None
        cluster_name = None

        for pg in policy_groups:
            pg_upper = str(pg).upper()
            if '-P1_P2-IPG' in pg_upper:
                ipg_p1p2 = pg
                # Extraire le cluster name
                idx = pg_upper.index('-P1_P2-IPG')
                cluster_name = pg[:idx]
            elif '-P3-IPG' in pg_upper:
                ipg_p3 = pg
            elif '-P4-IPG' in pg_upper:
                ipg_p4 = pg

        if ipg_p1p2 and ipg_p3 and ipg_p4:
            return (cluster_name, ipg_p1p2, ipg_p3, ipg_p4)

        return (None, None, None, None)

    def _collect_odd_even_interfaces(self, profile_to_node, interface_type, access_port_df):
        """
        Collecte les interfaces avec la logique paire/impaire.

        Règles:
        - Ports IMPAIRS → P1_P2-IPG (les 2 leafs)
        - Ports PAIRS (petite leaf/node) → P3-IPG
        - Ports PAIRS (grosse leaf/node) → P4-IPG

        Args:
            profile_to_node: Dict {interface_profile: node_id} ou {profile: [node1, node2]} pour VPC
            interface_type: 'switch_port' ou 'pc_or_vpc'
            access_port_df: DataFrame access_port_to_int_policy_leaf

        Returns:
            Liste de dicts pour interface_config ou None si échec
        """
        print("\n" + "-" * 60)
        print("📐 LOGIQUE PAIRE/IMPAIRE")
        print("-" * 60)

        # 1. Détecter les policy groups
        cluster_name, ipg_p1p2, ipg_p3, ipg_p4 = self._detect_policy_groups(access_port_df)

        if ipg_p1p2 and ipg_p3 and ipg_p4:
            print(f"\n✅ Policy Groups détectés:")
            print(f"   • Cluster: {cluster_name}")
            print(f"   • P1_P2-IPG (impairs): {ipg_p1p2}")
            print(f"   • P3-IPG (pairs petite leaf): {ipg_p3}")
            print(f"   • P4-IPG (pairs grosse leaf): {ipg_p4}")
        else:
            # Demander le nom du cluster
            print("\n⚠️  Policy Groups non détectés automatiquement")
            print("\nEntrez le nom du cluster (ex: SERVER106): ", end="", flush=True)
            cluster_name = input().strip().upper()

            if not cluster_name:
                print("❌ Nom de cluster requis")
                return None

            # Générer les noms de policy groups
            ipg_p1p2 = f"{cluster_name}-P1_P2-IPG"
            ipg_p3 = f"{cluster_name}-P3-IPG"
            ipg_p4 = f"{cluster_name}-P4-IPG"

            print(f"\n   Policy Groups générés:")
            print(f"   • P1_P2-IPG: {ipg_p1p2}")
            print(f"   • P3-IPG: {ipg_p3}")
            print(f"   • P4-IPG: {ipg_p4}")

        # 2. Collecter les node_ids depuis profile_to_node
        all_nodes = set()
        for val in profile_to_node.values():
            if isinstance(val, list):
                all_nodes.update(val)
            else:
                all_nodes.add(val)
        sorted_nodes = sorted([str(n) for n in all_nodes])

        # 3. Collecter les descriptions d'interfaces (DIRECTEMENT)
        print("\n" + "-" * 60)
        print("📋 DESCRIPTIONS DES INTERFACES")
        print("-" * 60)
        print("\nFormat: LEAF_NAME  PORT_NUMBER  DESCRIPTION")
        print("Exemple: SFXX-XXX  3  SERVER101-vmnic2")
        print("\n💡 Les leafs seront auto-mappées aux node_ids:")
        print(f"   Node IDs disponibles: {', '.join(sorted_nodes)}")
        print("   Plus petit nom de leaf → plus petit node_id")
        print("-" * 60)
        print("Collez vos lignes puis appuyez 2 fois sur Entrée:\n")

        description_lines = []
        empty_line_count = 0
        while True:
            try:
                line = input()
                if not line.strip():
                    empty_line_count += 1
                    if empty_line_count >= 2:
                        break
                else:
                    empty_line_count = 0
                    description_lines.append(line.strip())
            except EOFError:
                break

        if not description_lines:
            print("❌ Aucune description fournie")
            return None

        print(f"\n   ✅ {len(description_lines)} lignes reçues")

        # 4. Parser les descriptions et extraire les leafs
        leaf_data = {}  # leaf_name -> list of (port, description)

        for line in description_lines:
            parts = line.split()
            if len(parts) < 3:
                continue

            leaf_name = parts[0].upper()
            try:
                port_num = int(parts[1])
            except ValueError:
                continue

            description = ' '.join(parts[2:])

            if leaf_name not in leaf_data:
                leaf_data[leaf_name] = []
            leaf_data[leaf_name].append((port_num, description))

        if not leaf_data:
            print("❌ Aucune interface parsée")
            return None

        # 5. Auto-mapping: trier les leafs et mapper aux node_ids triés
        sorted_leaves = sorted(leaf_data.keys())

        print(f"\n🔍 Leafs détectées: {', '.join(sorted_leaves)}")

        # Créer le mapping automatique
        auto_leaf_to_node = {}
        for i, leaf in enumerate(sorted_leaves):
            if i < len(sorted_nodes):
                auto_leaf_to_node[leaf] = sorted_nodes[i]

        print(f"\n   Auto-mapping leaf → node:")
        for leaf, node in auto_leaf_to_node.items():
            print(f"   • {leaf} → {node}")

        # 6. Identifier smallest et largest node
        if len(sorted_nodes) >= 2:
            smallest_node = sorted_nodes[0]
            largest_node = sorted_nodes[-1]
        else:
            smallest_node = sorted_nodes[0] if sorted_nodes else None
            largest_node = sorted_nodes[0] if sorted_nodes else None

        print(f"\n   Plus petite leaf ({sorted_leaves[0] if sorted_leaves else 'N/A'}) → node {smallest_node} → P3-IPG")
        print(f"   Plus grosse leaf ({sorted_leaves[-1] if sorted_leaves else 'N/A'}) → node {largest_node} → P4-IPG")

        # 7. Appliquer la logique paire/impaire
        interface_mappings = []

        for leaf_name, ports_data in leaf_data.items():
            node_id = auto_leaf_to_node.get(leaf_name)

            if not node_id:
                print(f"   ⚠️  Leaf '{leaf_name}' non mappée, ignorée")
                continue

            for port_num, description in ports_data:
                # Logique paire/impaire
                if port_num % 2 == 1:
                    # Port impair → P1_P2-IPG
                    policy_group = ipg_p1p2
                elif node_id == smallest_node:
                    # Port pair, plus petit node → P3-IPG
                    policy_group = ipg_p3
                else:
                    # Port pair, plus gros node → P4-IPG
                    policy_group = ipg_p4

                # Formater la description: (T:SRV E:{AVANT-TIRET} I:{APRÈS-TIRET})
                desc_upper = description.upper()
                if '-' in desc_upper:
                    first_dash = desc_upper.index('-')
                    e_part = desc_upper[:first_dash]
                    i_part = desc_upper[first_dash+1:]
                else:
                    e_part = desc_upper
                    i_part = ''
                formatted_desc = f"(T:SRV E:{e_part} I:{i_part})"

                interface_mappings.append({
                    'node': node_id,
                    'interface': f"1/{port_num}",
                    'policy_group': policy_group,
                    'role': 'leaf',
                    'port_type': 'access',
                    'interface_type': interface_type,
                    'admin_state': 'up',
                    'description': formatted_desc
                })

        # Trier par node puis par interface
        interface_mappings.sort(key=lambda x: (x['node'], int(x['interface'].split('/')[1]) if '/' in x['interface'] else 0))

        print(f"\n   ✅ {len(interface_mappings)} interfaces générées avec logique paire/impaire")

        # Afficher un résumé par policy group
        pg_counts = {}
        for m in interface_mappings:
            pg = m['policy_group']
            pg_counts[pg] = pg_counts.get(pg, 0) + 1

        print("\n   Répartition par Policy Group:")
        for pg, count in sorted(pg_counts.items()):
            print(f"   • {pg}: {count} interfaces")

        return interface_mappings

    def _finalize_interface_config(self, interface_mappings):
        """
        Finalise la création de l'onglet interface_config.

        Args:
            interface_mappings: Liste de dicts avec les données d'interface
        """
        if not interface_mappings:
            print("   ⚠️  Aucune interface à créer")
            return

        # Créer le DataFrame
        interface_config_df = pd.DataFrame(interface_mappings)
        columns_order = ['node', 'interface', 'policy_group', 'role', 'port_type',
                       'interface_type', 'admin_state', 'description']
        interface_config_df = interface_config_df[columns_order]

        # Ajouter le nouvel onglet interface_config
        self.excel_data['interface_config'] = interface_config_df

        # Supprimer les onglets sources
        if 'interface_policy_leaf_profile' in self.excel_data:
            del self.excel_data['interface_policy_leaf_profile']

        if 'access_port_to_int_policy_leaf' in self.excel_data:
            del self.excel_data['access_port_to_int_policy_leaf']

        print("\n" + "=" * 60)
        print("✅ INTERFACE_CONFIG GÉNÉRÉ")
        print("=" * 60)
        print(f"   • Lignes créées: {len(interface_mappings)}")
        print(f"   • Onglets sources supprimés: interface_policy_leaf_profile, access_port_to_int_policy_leaf")
        print(f"\n   Aperçu:")
        print(interface_config_df.to_string(index=False, max_rows=10))

    def collect_interface_config_mappings(self):
        """Collecte les mappings pour convertir Interface Profile → Interface Config"""
        print("\n" + "=" * 60)
        print("🔌 CONVERSION INTERFACE PROFILE → INTERFACE CONFIG")
        print("=" * 60)

        # Vérifier que les onglets existent
        if 'interface_policy_leaf_profile' not in self.excel_data:
            print("   ⚠️  Onglet 'interface_policy_leaf_profile' non trouvé - étape ignorée")
            return

        if 'access_port_to_int_policy_leaf' not in self.excel_data:
            print("   ⚠️  Onglet 'access_port_to_int_policy_leaf' non trouvé - étape ignorée")
            return

        # Demander si l'utilisateur veut faire cette conversion
        print("\nVoulez-vous convertir les Interface Profiles vers interface_config? [o/N]: ", end="", flush=True)
        choice = input().strip().lower()
        if choice not in ['o', 'oui', 'y', 'yes']:
            print("   → Conversion interface_config ignorée")
            return

        profile_df = self.excel_data['interface_policy_leaf_profile']
        access_port_df = self.excel_data['access_port_to_int_policy_leaf']

        # 1. Extraire les interface_profile uniques
        interface_profiles = profile_df['interface_profile'].dropna().unique().tolist()
        print(f"\n📋 Interface Profiles trouvés: {len(interface_profiles)}")
        for ip in interface_profiles:
            print(f"   • {ip}")

        # 2. Demander le type d'interface (AVANT le mapping pour déterminer si VPC)
        print("\n" + "-" * 60)
        print("🔧 TYPE D'INTERFACE")
        print("-" * 60)
        print("[1] Access (switch_port) - DÉFAUT")
        print("[2] PC/VPC (pc_or_vpc)")
        print("\nChoix [1]: ", end="", flush=True)
        type_choice = input().strip()

        if type_choice == '2':
            interface_type = 'pc_or_vpc'
            is_vpc = True
            print("   → Type sélectionné: pc_or_vpc")
        else:
            interface_type = 'switch_port'
            is_vpc = False
            print("   → Type sélectionné: switch_port")

        # 3. Auto-mapping Interface Profile → Node ID
        # Récupérer les node_ids depuis les mappings L3Out (déjà entrés)
        available_node_ids = list(self.node_id_mapping.values()) if self.node_id_mapping else []

        if not available_node_ids:
            # Fallback: demander les node_ids
            print("\n" + "-" * 60)
            print("📍 NODE IDs DISPONIBLES")
            print("-" * 60)
            print("Entrez les Node IDs séparés par virgule (ex: 2221, 2222): ", end="", flush=True)
            node_input = input().strip()
            if node_input:
                available_node_ids = [n.strip() for n in node_input.split(',')]

        if not available_node_ids:
            print("❌ Aucun Node ID disponible")
            return

        print(f"\n   Node IDs disponibles: {', '.join(available_node_ids)}")

        # Tenter l'auto-mapping
        auto_result = self._auto_map_profiles_to_nodes(interface_profiles, available_node_ids, is_vpc)

        if auto_result:
            profile_to_node, leaf_to_node_mapping = auto_result
            print(f"\n✅ Auto-mapping réussi ({len(profile_to_node)} profiles)")

            # Afficher et permettre la modification
            profile_to_node = self._display_and_confirm_mapping(profile_to_node, is_vpc)
        else:
            # Fallback: mapping manuel
            print("\n⚠️  Auto-mapping impossible (pattern non reconnu)")
            print("   → Passage en mode manuel")

            print("\n" + "-" * 60)
            print("📍 MAPPING INTERFACE PROFILE → NODE ID")
            print("-" * 60)
            profile_to_node = {}
            for profile in interface_profiles:
                if is_vpc:
                    print(f"\n'{profile}' → Node IDs (séparés par virgule): ", end="", flush=True)
                    node_input = input().strip()
                    if node_input:
                        nodes = [n.strip() for n in node_input.split(',')]
                        profile_to_node[profile] = nodes if len(nodes) > 1 else nodes[0]
                else:
                    print(f"\n'{profile}' → Node ID: ", end="", flush=True)
                    node_id = input().strip()
                    if node_id:
                        profile_to_node[profile] = node_id
                    else:
                        print(f"   ⚠️  Node ID vide, ce profile sera ignoré")

        if not profile_to_node:
            print("❌ Aucun mapping défini, conversion ignorée")
            return

        # 3b. Méthode d'assignation des interfaces
        print("\n" + "-" * 60)
        print("📐 MÉTHODE D'ASSIGNATION DES INTERFACES")
        print("-" * 60)
        print("[1] Logique paire/impaire (recommandé)")
        print("    • Ports IMPAIRS → P1_P2-IPG (les 2 leafs)")
        print("    • Ports PAIRS (petite leaf) → P3-IPG")
        print("    • Ports PAIRS (grosse leaf) → P4-IPG")
        print("[2] Saisie manuelle des interfaces")
        print("\nChoix [1]: ", end="", flush=True)
        method_choice = input().strip()

        if method_choice != '2':
            # Logique paire/impaire
            interface_mappings = self._collect_odd_even_interfaces(profile_to_node, interface_type, access_port_df)
            if interface_mappings:
                # Aller directement à la création du DataFrame (étape 7)
                self._finalize_interface_config(interface_mappings)
            return

        # 4. Regrouper les interfaces par (interface_profile, policy_group)
        print("\n" + "-" * 60)
        print("🔄 MAPPING DES INTERFACES PAR POLICY GROUP")
        print("-" * 60)

        grouped = {}
        for idx, row in access_port_df.iterrows():
            profile = str(row['interface_profile']) if pd.notna(row['interface_profile']) else ''
            policy_group = str(row['policy_group']) if pd.notna(row['policy_group']) else ''
            access_port_selector = str(row['access_port_selector']) if pd.notna(row['access_port_selector']) else ''
            from_port = row['from_port'] if pd.notna(row['from_port']) else ''
            to_port = row['to_port'] if pd.notna(row['to_port']) else ''
            description = str(row['description']) if pd.notna(row['description']) else ''

            if not profile or not policy_group:
                continue

            if profile not in profile_to_node:
                continue

            key = (profile, policy_group)
            if key not in grouped:
                grouped[key] = {
                    'interfaces': [],
                    'access_port_selector': access_port_selector,
                    'description': description
                }

            try:
                from_p = int(float(from_port))
                to_p = int(float(to_port))
                for port in range(from_p, to_p + 1):
                    interface = f"1/{port}"
                    if interface not in grouped[key]['interfaces']:
                        grouped[key]['interfaces'].append(interface)
            except (ValueError, TypeError):
                pass

        if not grouped:
            print("\n❌ Aucun groupe trouvé!")
            return

        # 5. Pour chaque groupe, demander les nouvelles interfaces
        interface_mappings = []

        for (profile, policy_group), data in grouped.items():
            node_val = profile_to_node[profile]
            interfaces = data['interfaces']
            access_port_selector = data['access_port_selector']
            description = data['description']

            # Déterminer si VPC (liste de nodes) ou single (string)
            if isinstance(node_val, list):
                node_display = ', '.join(node_val)
                node_list = node_val
            else:
                node_display = node_val
                node_list = [node_val]

            print(f"\n{'='*60}")
            print(f"📌 Interface Profile: {profile}")
            print(f"   Access Port Selector: {access_port_selector}")
            print(f"   Policy Group: {policy_group}")
            print(f"   Node destination: {node_display}" + (" (VPC)" if len(node_list) > 1 else ""))
            print(f"\n   Interfaces actuelles:")
            for iface in sorted(interfaces, key=lambda x: int(x.split('/')[1]) if '/' in x else 0):
                print(f"      • {iface}")

            print(f"\n   Entrez les nouvelles interfaces (séparées par virgule)")
            print(f"   Format: 1/1, 1/2, 1/3 ou eth1/1, eth1/2")
            print(f"   [Entrée vide = garder les mêmes interfaces]")
            print(f"\n   → ", end="", flush=True)

            new_interfaces_input = input().strip()

            if new_interfaces_input:
                new_interfaces = []
                for iface in new_interfaces_input.split(','):
                    iface = iface.strip()
                    if iface.lower().startswith('eth'):
                        iface = iface[3:]
                    if iface:
                        new_interfaces.append(iface)
            else:
                new_interfaces = interfaces

            # Créer les entrées - pour VPC, créer une entrée par node
            for node_id in node_list:
                for iface in new_interfaces:
                    interface_mappings.append({
                        'node': node_id,
                        'interface': iface,
                        'policy_group': policy_group,
                        'role': 'leaf',
                        'port_type': 'access',
                        'interface_type': interface_type,
                        'admin_state': 'up',
                        'description': description
                    })

        # 6. Mapping des descriptions personnalisées
        if interface_mappings:
            print("\n" + "=" * 60)
            print("📝 MAPPING DES DESCRIPTIONS")
            print("=" * 60)
            print("\nVoulez-vous ajouter des descriptions personnalisées? [o/N]: ", end="", flush=True)
            desc_choice = input().strip().lower()

            if desc_choice in ['o', 'oui', 'y', 'yes']:
                # 6a. Mapping Node ID → Nom de Leaf
                print("\n" + "-" * 60)
                print("🏷️  MAPPING NODE ID → NOM DE LEAF")
                print("-" * 60)

                # Obtenir les node_id uniques
                unique_nodes = list(set([m['node'] for m in interface_mappings]))
                node_to_leaf = {}

                for node in sorted(unique_nodes):
                    print(f"\n   Node '{node}' → Nom de Leaf (ex: SFXX-XXX): ", end="", flush=True)
                    leaf_name = input().strip().upper()
                    if leaf_name:
                        node_to_leaf[node] = leaf_name
                    else:
                        print(f"      ⚠️  Nom vide, ce node sera ignoré pour les descriptions")

                if node_to_leaf:
                    # 6b. Demander la liste de descriptions
                    print("\n" + "-" * 60)
                    print("📋 LISTE DES DESCRIPTIONS")
                    print("-" * 60)
                    print("\n   Format attendu par ligne:")
                    print("   {NOM_LEAF} {ESPACE(S)} {NO_INTERFACE} {ESPACE(S)} {DESCRIPTION}")
                    print("   Exemple: SFXX-XXX  3  VPZESX1011-onb2-p1-vmnic2")
                    print("\n   Collez votre liste puis appuyez 2 fois sur Entrée pour terminer:")
                    print("-" * 60)

                    description_lines = []
                    empty_line_count = 0
                    while True:
                        try:
                            line = input()
                            if not line.strip():
                                empty_line_count += 1
                                if empty_line_count >= 2:
                                    break
                            else:
                                empty_line_count = 0
                                description_lines.append(line.strip())
                        except EOFError:
                            break

                    print(f"\n   ✅ {len(description_lines)} lignes de description reçues")

                    # 6c. Parser et associer les descriptions
                    descriptions_map = {}  # (node, interface) → description formatée

                    for line in description_lines:
                        # Parser: LEAF  INTERFACE  DESCRIPTION
                        parts = line.split()
                        if len(parts) >= 3:
                            leaf = parts[0].upper()
                            try:
                                iface_num = int(parts[1])
                                iface = f"1/{iface_num}"
                            except ValueError:
                                continue

                            # Trouver le node_id correspondant au leaf
                            node_for_leaf = None
                            for node, leaf_name in node_to_leaf.items():
                                if leaf_name == leaf:
                                    node_for_leaf = node
                                    break

                            if node_for_leaf:
                                # Description = tout après le numéro d'interface
                                desc_text = ' '.join(parts[2:]).upper()

                                # Formater: (T:SRV E:{AVANT-TIRET} I:{APRÈS-TIRET})
                                if '-' in desc_text:
                                    first_dash = desc_text.index('-')
                                    e_part = desc_text[:first_dash]
                                    i_part = desc_text[first_dash+1:]
                                else:
                                    e_part = desc_text
                                    i_part = ''

                                formatted_desc = f"(T:SRV E:{e_part} I:{i_part})"
                                descriptions_map[(node_for_leaf, iface)] = formatted_desc

                    # 6d. Appliquer les descriptions aux interfaces
                    updated_count = 0
                    for mapping in interface_mappings:
                        key = (mapping['node'], mapping['interface'])
                        if key in descriptions_map:
                            mapping['description'] = descriptions_map[key]
                            updated_count += 1

                    print(f"\n   ✅ {updated_count} descriptions mises à jour")

        # 7. Créer le DataFrame et l'ajouter à l'Excel
        self._finalize_interface_config(interface_mappings)

    # =========================================================================
    # MODE FICHIER DE CONFIGURATION (texte plat INI-style)
    # =========================================================================

    def generate_config_file(self, output_file=None):
        """Génère un fichier de configuration pré-rempli depuis le Excel"""
        if output_file is None:
            excel_path = Path(self.excel_file)
            output_file = str(excel_path.parent / f"{excel_path.stem}_config.cfg")

        print(f"\n📝 Génération du fichier de configuration...")

        # Découvrir toutes les valeurs
        global_values = self.discover_global_values()

        # Découvrir les valeurs L3Out
        node_ids = self.find_all_values(self.node_id_columns)
        node_profiles = self.find_all_values(self.node_profile_columns)
        exclude_leaf_sheets = ['interface_policy_leaf_profile', 'access_port_to_int_policy_leaf']
        int_profiles = self.find_all_values(self.int_profile_columns, exclude_sheets=exclude_leaf_sheets)
        path_eps = self.find_all_values(self.path_ep_columns)
        local_as_values = self.find_all_values(self.local_as_columns)

        # Découvrir Route Control
        match_rules = self.find_all_values(self.match_rule_columns)
        rc_profiles = self.find_all_values(self.route_control_profile_columns)
        rc_contexts = self.find_all_values(self.route_control_context_columns)

        # Découvrir L3Out (bd_to_l3out)
        l3outs = []
        if 'bd_to_l3out' in self.excel_data:
            df = self.excel_data['bd_to_l3out']
            columns_lower = [str(c).lower() for c in df.columns]
            for col_name in ['l3out', 'l3out_name']:
                if col_name in columns_lower:
                    idx = columns_lower.index(col_name)
                    l3out_col = df.columns[idx]
                    l3outs = sorted([str(v) for v in df[l3out_col].dropna().unique() if v and str(v).strip()])
                    break

        # Découvrir interface profiles (pour interface_config)
        interface_profiles_list = []
        if 'interface_policy_leaf_profile' in self.excel_data:
            profile_df = self.excel_data['interface_policy_leaf_profile']
            interface_profiles_list = profile_df['interface_profile'].dropna().unique().tolist()

        # Écrire le fichier
        lines = []
        lines.append("# ============================================================")
        lines.append("# FABRIC CONVERTER - Fichier de configuration")
        lines.append(f"# Genere depuis: {os.path.basename(self.excel_file)}")
        lines.append("# ============================================================")
        lines.append("#")
        lines.append("# FORMAT:")
        lines.append("#   Sections [NOM]: contiennent des paires source = destination")
        lines.append("#   Modifiez la DESTINATION pour convertir (gardez identique = pas de changement)")
        lines.append("#   Sections paste: collez vos lignes telles quelles")
        lines.append("#")
        lines.append("# ============================================================")
        lines.append("")

        # TENANTS
        lines.append("[TENANTS]")
        lines.append("# Format: source = destination")
        for t in global_values['tenants']:
            lines.append(f"{t} = {t}")
        lines.append("")

        # VRFS
        lines.append("[VRFS]")
        lines.append("# Format: source = destination")
        for v in global_values['vrfs']:
            lines.append(f"{v} = {v}")
        lines.append("")

        # APS
        lines.append("[APS]")
        lines.append("# Format: source = destination")
        for a in global_values['aps']:
            lines.append(f"{a} = {a}")
        lines.append("")

        # L3OUT (bd_to_l3out)
        lines.append("[L3OUT]")
        lines.append("# L3Out references par les Bridge Domains")
        lines.append("# Format: source = destination")
        for l in l3outs:
            lines.append(f"{l} = {l}")
        lines.append("")

        # NODE_IDS
        lines.append("[NODE_IDS]")
        lines.append("# Format: source = destination")
        for nid in sorted(node_ids.keys()):
            lines.append(f"{nid} = {nid}")
        lines.append("")

        # NODE_PROFILES
        lines.append("[NODE_PROFILES]")
        lines.append("# Format: source = destination")
        for np in sorted(node_profiles.keys()):
            lines.append(f"{np} = {np}")
        lines.append("")

        # INTERFACE_PROFILES
        lines.append("[INTERFACE_PROFILES]")
        lines.append("# Interface Profiles L3Out (pas les Leaf profiles)")
        lines.append("# Format: source = destination")
        for ip in sorted(int_profiles.keys()):
            lines.append(f"{ip} = {ip}")
        lines.append("")

        # PATH_EPS
        lines.append("[PATH_EPS]")
        lines.append("# Format: source = destination")
        for pe in sorted(path_eps.keys()):
            lines.append(f"{pe} = {pe}")
        lines.append("")

        # LOCAL_AS
        lines.append("[LOCAL_AS]")
        lines.append("# Format: source = destination")
        for la in sorted(local_as_values.keys()):
            lines.append(f"{la} = {la}")
        lines.append("")

        # MATCH_RULES
        lines.append("[MATCH_RULES]")
        lines.append("# Format: source = destination")
        for mr in sorted(match_rules.keys()):
            lines.append(f"{mr} = {mr}")
        lines.append("")

        # ROUTE_CONTROL_PROFILES
        lines.append("[ROUTE_CONTROL_PROFILES]")
        lines.append("# Format: source = destination")
        for rcp in sorted(rc_profiles.keys()):
            lines.append(f"{rcp} = {rcp}")
        lines.append("")

        # ROUTE_CONTROL_CONTEXTS
        lines.append("[ROUTE_CONTROL_CONTEXTS]")
        lines.append("# Format: source = destination")
        for rcc in sorted(rc_contexts.keys()):
            lines.append(f"{rcc} = {rcc}")
        lines.append("")

        # OPTIONS
        lines.append("[OPTIONS]")
        lines.append("# disable_bd_routing: true ou false")
        lines.append("disable_bd_routing = false")
        lines.append("")

        # VLAN_DESCRIPTIONS
        lines.append("[VLAN_DESCRIPTIONS]")
        lines.append("# Collez vos lignes VLAN,DESCRIPTION (meme format que le wizard)")
        lines.append("# Exemple: 200,RL00001_10.1.1.1/24_Serveur_Web")
        lines.append("# Laissez vide si pas de modification")
        lines.append("")

        # INTERFACE_CONFIG
        lines.append("[INTERFACE_CONFIG]")
        lines.append("# Conversion Interface Profile -> interface_config")
        lines.append("# enabled: true ou false")
        lines.append("# method: odd_even (paire/impaire) ou manual (saisie manuelle)")
        lines.append("# interface_type: switch_port ou pc_or_vpc")
        lines.append("enabled = false")
        lines.append("method = odd_even")
        lines.append("interface_type = switch_port")
        lines.append("")

        # INTERFACE_CONFIG_PROFILE_TO_NODE
        lines.append("[INTERFACE_CONFIG_PROFILE_TO_NODE]")
        lines.append("# Format: profile = node_id")
        if interface_profiles_list:
            for ip in interface_profiles_list:
                lines.append(f"# {ip} = ")
        lines.append("")

        # INTERFACE_CONFIG_INTERFACES
        lines.append("[INTERFACE_CONFIG_INTERFACES]")
        lines.append("# Format: profile, policy_group, interfaces")
        lines.append("# Exemple: LeafProf_101, PG_Server, 1/1, 1/2, 1/3")
        lines.append("# Laissez vide = garder les interfaces depuis Excel")
        lines.append("")

        # INTERFACE_CONFIG_NODE_TO_LEAF
        lines.append("[INTERFACE_CONFIG_NODE_TO_LEAF]")
        lines.append("# Format: node_id = nom_leaf")
        lines.append("# Exemple: 201 = SFXX-XXX")
        lines.append("# (Utilise pour les descriptions personnalisees)")
        lines.append("")

        # INTERFACE_CONFIG_DESCRIPTIONS
        lines.append("[INTERFACE_CONFIG_DESCRIPTIONS]")
        lines.append("# Meme format que le wizard: NOM_LEAF  NO_INTERFACE  DESCRIPTION")
        lines.append("# Exemple: SFXX-XXX  3  VPZESX1011-onb2-p1-vmnic2")
        lines.append("# Collez vos lignes, 2 entrees vides = fin")
        lines.append("")

        # Écrire le fichier
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write('\n'.join(lines))

        print(f"\n✅ Fichier de configuration généré: {output_file}")
        print(f"   • {len(global_values['tenants'])} tenant(s)")
        print(f"   • {len(global_values['vrfs'])} VRF(s)")
        print(f"   • {len(global_values['aps'])} AP(s)")
        print(f"   • {len(l3outs)} L3Out(s)")
        print(f"   • {len(node_ids)} Node ID(s)")
        print(f"   • {len(path_eps)} Path EP(s)")
        print(f"\n💡 Modifiez les destinations dans le fichier, puis relancez avec l'option 'Charger'")

        return output_file

    def load_config_file(self, config_file):
        """Charge un fichier de configuration et remplit les mappings"""
        print(f"\n📂 Chargement du fichier de configuration: {config_file}")

        if not os.path.exists(config_file):
            print(f"❌ Fichier non trouvé: {config_file}")
            return False

        with open(config_file, 'r', encoding='utf-8') as f:
            content = f.read()

        # Parser les sections
        current_section = None
        section_data = defaultdict(list)

        for line in content.split('\n'):
            stripped = line.strip()

            # Ignorer les commentaires et lignes vides
            if not stripped or stripped.startswith('#'):
                continue

            # Détecter une section
            if stripped.startswith('[') and stripped.endswith(']'):
                current_section = stripped[1:-1]
                continue

            if current_section:
                section_data[current_section].append(stripped)

        # Parser les mappings source = destination
        def parse_mappings(section_name):
            mapping = {}
            for line in section_data.get(section_name, []):
                if '=' in line:
                    parts = line.split('=', 1)
                    src = parts[0].strip()
                    dest = parts[1].strip()
                    if src and dest:
                        mapping[src] = dest
            return mapping

        # Remplir les mappings
        self.tenant_mapping = parse_mappings('TENANTS')
        self.vrf_mapping = parse_mappings('VRFS')
        self.ap_mapping = parse_mappings('APS')
        self.l3out_mapping = parse_mappings('L3OUT')
        self.node_id_mapping = parse_mappings('NODE_IDS')
        self.node_profile_mapping = parse_mappings('NODE_PROFILES')
        self.int_profile_mapping = parse_mappings('INTERFACE_PROFILES')
        self.path_ep_mapping = parse_mappings('PATH_EPS')
        self.local_as_mapping = parse_mappings('LOCAL_AS')
        self.match_rule_mapping = parse_mappings('MATCH_RULES')
        self.route_control_profile_mapping = parse_mappings('ROUTE_CONTROL_PROFILES')
        self.route_control_context_mapping = parse_mappings('ROUTE_CONTROL_CONTEXTS')

        # Parser les options
        options = parse_mappings('OPTIONS')
        self.disable_bd_routing = options.get('disable_bd_routing', 'false').lower() in ['true', 'oui', 'yes', 'o']

        # Parser les descriptions VLAN
        for line in section_data.get('VLAN_DESCRIPTIONS', []):
            if ',' in line:
                parts = line.split(',', 1)
                vlan_str = parts[0].strip()
                description = parts[1].strip() if len(parts) > 1 else ''
                try:
                    vlan = int(vlan_str)
                    if description:
                        self.vlan_descriptions.append((vlan, description))
                except ValueError:
                    pass

        # Parser interface_config
        ic_options = parse_mappings('INTERFACE_CONFIG')
        self.interface_config_enabled = ic_options.get('enabled', 'false').lower() in ['true', 'oui', 'yes', 'o']
        self.interface_config_method = ic_options.get('method', 'odd_even').lower()
        self.interface_config_type = ic_options.get('interface_type', 'switch_port')

        self.interface_config_profile_to_node = parse_mappings('INTERFACE_CONFIG_PROFILE_TO_NODE')
        self.interface_config_node_to_leaf = parse_mappings('INTERFACE_CONFIG_NODE_TO_LEAF')

        # Parser interface config interfaces (format: profile, policy_group, interfaces...)
        for line in section_data.get('INTERFACE_CONFIG_INTERFACES', []):
            if ',' in line:
                self.interface_config_interfaces.append(line)

        # Parser interface config descriptions (lignes brutes)
        self.interface_config_descriptions = section_data.get('INTERFACE_CONFIG_DESCRIPTIONS', [])

        # Afficher le résumé
        changes_count = sum(1 for k, v in self.tenant_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.vrf_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.ap_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.l3out_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.node_id_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.node_profile_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.int_profile_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.path_ep_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.local_as_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.match_rule_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.route_control_profile_mapping.items() if k != v)
        changes_count += sum(1 for k, v in self.route_control_context_mapping.items() if k != v)

        print(f"\n✅ Configuration chargée:")
        print(f"   • {changes_count} mapping(s) avec changement")
        print(f"   • Routage BD: {'désactivé' if self.disable_bd_routing else 'pas de modification'}")
        print(f"   • Descriptions VLAN: {len(self.vlan_descriptions)} entrée(s)")
        print(f"   • Interface config: {'activé' if self.interface_config_enabled else 'désactivé'}")

        return True

    def _apply_odd_even_from_config(self, profile_to_node, interface_type, access_port_df):
        """
        Applique la logique paire/impaire depuis les données du fichier config.

        Args:
            profile_to_node: Dict {interface_profile: node_id}
            interface_type: 'switch_port' ou 'pc_or_vpc'
            access_port_df: DataFrame access_port_to_int_policy_leaf
        """
        # Vérifier que nous avons les données nécessaires
        if not self.interface_config_node_to_leaf:
            print("   ⚠️  Aucun mapping node→leaf défini dans [INTERFACE_CONFIG_NODE_TO_LEAF]")
            return

        if not self.interface_config_descriptions:
            print("   ⚠️  Aucune description définie dans [INTERFACE_CONFIG_DESCRIPTIONS]")
            return

        # Détecter les policy groups
        cluster_name, ipg_p1p2, ipg_p3, ipg_p4 = self._detect_policy_groups(access_port_df)

        if not (ipg_p1p2 and ipg_p3 and ipg_p4):
            print("   ⚠️  Policy Groups P1_P2/P3/P4 non détectés automatiquement")
            print("      Utilisez le mode wizard pour spécifier le nom du cluster")
            return

        print(f"   Policy Groups détectés:")
        print(f"   • {ipg_p1p2} (impairs)")
        print(f"   • {ipg_p3} (pairs, petite leaf)")
        print(f"   • {ipg_p4} (pairs, grosse leaf)")

        # Inverser le mapping: node_to_leaf → leaf_to_node
        node_to_leaf = self.interface_config_node_to_leaf
        leaf_to_node = {v.upper(): k for k, v in node_to_leaf.items()}

        # Parser les descriptions
        leaf_data = {}  # leaf_name -> list of (port, description)

        for line in self.interface_config_descriptions:
            parts = line.split()
            if len(parts) < 3:
                continue

            leaf_name = parts[0].upper()
            try:
                port_num = int(parts[1])
            except ValueError:
                continue

            description = ' '.join(parts[2:])

            if leaf_name not in leaf_data:
                leaf_data[leaf_name] = []
            leaf_data[leaf_name].append((port_num, description))

        if not leaf_data:
            print("   ⚠️  Aucune interface parsée depuis les descriptions")
            return

        # Trier les leafs et créer le mapping automatique
        sorted_leaves = sorted(leaf_data.keys())
        sorted_nodes = sorted([str(n) for n in node_to_leaf.keys()])

        # Recréer le mapping basé sur le tri
        auto_leaf_to_node = {}
        for i, leaf in enumerate(sorted_leaves):
            if i < len(sorted_nodes):
                auto_leaf_to_node[leaf] = sorted_nodes[i]

        print(f"\n   Mapping automatique leaf → node:")
        for leaf, node in auto_leaf_to_node.items():
            print(f"   • {leaf} → {node}")

        # Identifier smallest et largest node
        if len(sorted_nodes) >= 2:
            smallest_node = sorted_nodes[0]
            largest_node = sorted_nodes[-1]
        else:
            smallest_node = sorted_nodes[0] if sorted_nodes else None
            largest_node = sorted_nodes[0] if sorted_nodes else None

        print(f"\n   Plus petite leaf ({sorted_leaves[0] if sorted_leaves else 'N/A'}) → node {smallest_node} → P3-IPG")
        print(f"   Plus grosse leaf ({sorted_leaves[-1] if sorted_leaves else 'N/A'}) → node {largest_node} → P4-IPG")

        # Appliquer la logique paire/impaire
        interface_mappings = []

        for leaf_name, ports_data in leaf_data.items():
            node_id = auto_leaf_to_node.get(leaf_name)

            if not node_id:
                # Essayer de matcher avec leaf_to_node original
                node_id = leaf_to_node.get(leaf_name)

            if not node_id:
                print(f"   ⚠️  Leaf '{leaf_name}' non mappée, ignorée")
                continue

            for port_num, description in ports_data:
                # Logique paire/impaire
                if port_num % 2 == 1:
                    # Port impair → P1_P2-IPG
                    policy_group = ipg_p1p2
                elif node_id == smallest_node:
                    # Port pair, plus petit node → P3-IPG
                    policy_group = ipg_p3
                else:
                    # Port pair, plus gros node → P4-IPG
                    policy_group = ipg_p4

                # Formater la description: (T:SRV E:{AVANT-TIRET} I:{APRÈS-TIRET})
                desc_upper = description.upper()
                if '-' in desc_upper:
                    first_dash = desc_upper.index('-')
                    e_part = desc_upper[:first_dash]
                    i_part = desc_upper[first_dash+1:]
                else:
                    e_part = desc_upper
                    i_part = ''
                formatted_desc = f"(T:SRV E:{e_part} I:{i_part})"

                interface_mappings.append({
                    'node': node_id,
                    'interface': f"1/{port_num}",
                    'policy_group': policy_group,
                    'role': 'leaf',
                    'port_type': 'access',
                    'interface_type': interface_type,
                    'admin_state': 'up',
                    'description': formatted_desc
                })

        # Trier par node puis par interface
        interface_mappings.sort(key=lambda x: (x['node'], int(x['interface'].split('/')[1]) if '/' in x['interface'] else 0))

        # Afficher un résumé par policy group
        pg_counts = {}
        for m in interface_mappings:
            pg = m['policy_group']
            pg_counts[pg] = pg_counts.get(pg, 0) + 1

        print(f"\n   Répartition par Policy Group:")
        for pg, count in sorted(pg_counts.items()):
            print(f"   • {pg}: {count} interfaces")

        # Finaliser
        self._finalize_interface_config(interface_mappings)

    def apply_interface_config_from_file(self):
        """Applique la conversion interface_config depuis les données du fichier config"""
        if not self.interface_config_enabled:
            return

        if 'interface_policy_leaf_profile' not in self.excel_data:
            print("   ⚠️  Onglet 'interface_policy_leaf_profile' non trouvé - interface_config ignoré")
            return

        if 'access_port_to_int_policy_leaf' not in self.excel_data:
            print("   ⚠️  Onglet 'access_port_to_int_policy_leaf' non trouvé - interface_config ignoré")
            return

        if not self.interface_config_profile_to_node:
            print("   ⚠️  Aucun mapping profile→node défini - interface_config ignoré")
            return

        print("\n" + "=" * 60)
        print("🔌 APPLICATION INTERFACE_CONFIG (depuis fichier)")
        print("=" * 60)

        profile_to_node = self.interface_config_profile_to_node
        interface_type = self.interface_config_type
        access_port_df = self.excel_data['access_port_to_int_policy_leaf']

        # Vérifier la méthode
        if self.interface_config_method == 'odd_even':
            # Utiliser la logique paire/impaire
            print(f"   Méthode: logique paire/impaire")
            self._apply_odd_even_from_config(profile_to_node, interface_type, access_port_df)
            return

        print(f"   Méthode: manuelle")

        # Regrouper les interfaces par (interface_profile, policy_group)
        grouped = {}
        for idx, row in access_port_df.iterrows():
            profile = str(row['interface_profile']) if pd.notna(row['interface_profile']) else ''
            policy_group = str(row['policy_group']) if pd.notna(row['policy_group']) else ''
            access_port_selector = str(row['access_port_selector']) if pd.notna(row['access_port_selector']) else ''
            from_port = row['from_port'] if pd.notna(row['from_port']) else ''
            to_port = row['to_port'] if pd.notna(row['to_port']) else ''
            description = str(row['description']) if pd.notna(row['description']) else ''

            if not profile or not policy_group:
                continue

            if profile not in profile_to_node:
                continue

            key = (profile, policy_group)
            if key not in grouped:
                grouped[key] = {
                    'interfaces': [],
                    'access_port_selector': access_port_selector,
                    'description': description
                }

            try:
                from_p = int(float(from_port))
                to_p = int(float(to_port))
                for port in range(from_p, to_p + 1):
                    interface = f"1/{port}"
                    if interface not in grouped[key]['interfaces']:
                        grouped[key]['interfaces'].append(interface)
            except (ValueError, TypeError):
                pass

        if not grouped:
            print("   ⚠️  Aucun groupe trouvé!")
            return

        # Parser les overrides d'interfaces depuis le fichier config
        interface_overrides = {}  # (profile, policy_group) -> list of interfaces
        for line in self.interface_config_interfaces:
            parts = [p.strip() for p in line.split(',')]
            if len(parts) >= 3:
                profile = parts[0]
                pg = parts[1]
                ifaces = [p.strip() for p in parts[2:]]
                interface_overrides[(profile, pg)] = ifaces

        # Construire les interface_mappings
        interface_mappings = []
        for (profile, policy_group), data in grouped.items():
            node_id = profile_to_node[profile]

            # Utiliser les interfaces override si définies, sinon celles du Excel
            if (profile, policy_group) in interface_overrides:
                interfaces = interface_overrides[(profile, policy_group)]
            else:
                interfaces = data['interfaces']

            description = data['description']

            for iface in interfaces:
                # Nettoyer le format
                if iface.lower().startswith('eth'):
                    iface = iface[3:]
                interface_mappings.append({
                    'node': node_id,
                    'interface': iface,
                    'policy_group': policy_group,
                    'role': 'leaf',
                    'port_type': 'access',
                    'interface_type': interface_type,
                    'admin_state': 'up',
                    'description': description
                })

        # Appliquer les descriptions personnalisées
        if self.interface_config_node_to_leaf and self.interface_config_descriptions:
            node_to_leaf = self.interface_config_node_to_leaf
            descriptions_map = {}

            for line in self.interface_config_descriptions:
                parts = line.split()
                if len(parts) >= 3:
                    leaf = parts[0].upper()
                    try:
                        iface_num = int(parts[1])
                        iface = f"1/{iface_num}"
                    except ValueError:
                        continue

                    # Trouver le node_id correspondant au leaf
                    node_for_leaf = None
                    for node, leaf_name in node_to_leaf.items():
                        if leaf_name.upper() == leaf:
                            node_for_leaf = node
                            break

                    if node_for_leaf:
                        desc_text = ' '.join(parts[2:]).upper()

                        # Formater: (T:SRV E:{AVANT-TIRET} I:{APRÈS-TIRET})
                        if '-' in desc_text:
                            first_dash = desc_text.index('-')
                            e_part = desc_text[:first_dash]
                            i_part = desc_text[first_dash+1:]
                        else:
                            e_part = desc_text
                            i_part = ''

                        formatted_desc = f"(T:SRV E:{e_part} I:{i_part})"
                        descriptions_map[(node_for_leaf, iface)] = formatted_desc

            # Appliquer
            updated_count = 0
            for mapping in interface_mappings:
                key = (mapping['node'], mapping['interface'])
                if key in descriptions_map:
                    mapping['description'] = descriptions_map[key]
                    updated_count += 1

            if updated_count:
                print(f"   ✅ {updated_count} descriptions personnalisées appliquées")

        # Créer le DataFrame
        if interface_mappings:
            interface_config_df = pd.DataFrame(interface_mappings)
            columns_order = ['node', 'interface', 'policy_group', 'role', 'port_type',
                           'interface_type', 'admin_state', 'description']
            interface_config_df = interface_config_df[columns_order]

            self.excel_data['interface_config'] = interface_config_df

            if 'interface_policy_leaf_profile' in self.excel_data:
                del self.excel_data['interface_policy_leaf_profile']

            if 'access_port_to_int_policy_leaf' in self.excel_data:
                del self.excel_data['access_port_to_int_policy_leaf']

            print(f"   ✅ interface_config généré: {len(interface_mappings)} lignes")
            print(f"   • Onglets sources supprimés")

    # =========================================================================
    # MODES D'EXÉCUTION
    # =========================================================================

    def run_wizard(self):
        """Exécution en mode wizard interactif avec auto-mapping depuis backup"""
        # Charger la liste d'extraction (optionnel)
        self.load_extraction_list()

        # Découvrir les valeurs globales
        global_values = self.discover_global_values()

        # Afficher le résumé des onglets
        print("\n📊 Analyse du fichier Excel:")
        print(f"   • Tenants: {len(global_values['tenants'])}")
        print(f"   • VRFs: {len(global_values['vrfs'])}")
        print(f"   • Application Profiles: {len(global_values['aps'])}")
        print(f"   • Onglets: {len(self.excel_data)}")

        # =====================================================================
        # NOUVEAU: Workflow automatisé avec backup destination
        # =====================================================================

        # 0a. Charger la configuration des fabrics
        auto_mode = False
        if self.load_fabric_paths():
            # 0b. Sélection de la fabric de destination
            if self.select_destination_fabric():
                # 0c. Chargement du backup
                if self.load_destination_backup():
                    # 0d. Sélection du groupe de tenants
                    if self.select_tenant_group():
                        auto_mode = True

                        # 0e. Auto-mapping Tenant/VRF/AP
                        self.auto_map_tenants_from_group(global_values)

                        # 0f. Auto-mapping L3Outs (stocke les suggestions)
                        self.auto_map_l3outs()

                        # 0g. Auto-mapping Node IDs
                        auto_node_ids = self.auto_map_node_ids()

                        # 0h. Auto-mapping Node Profiles (si node IDs auto-mappés)
                        if auto_node_ids:
                            self.auto_map_node_profiles()

                        # 0i. Gestion des identifiants de site Route Control
                        self.handle_route_control_site_identifiers()

        # =====================================================================
        # Collecte des mappings (manuels ou complémentaires)
        # =====================================================================

        # 1. Collecte des mappings globaux restants (tenant → auto VRF/AP)
        self.collect_global_mappings(global_values, skip_auto_mapped=auto_mode)

        # 2. Collecte des mappings BD to L3Out (avec suggestions du backup)
        self.collect_bd_to_l3out_mappings()

        # 3. Collecte des mappings L3Out (UNIFIÉ - tous les onglets)
        self.collect_l3out_mappings()

        # 4. Collecte des mappings Route Control
        self.collect_route_control_mappings()

        # 5. Collecte option désactivation routage BD
        self.collect_bd_routing_option()

        # 5b. Collecte auto-génération descriptions VLAN Pool
        self.collect_vlan_pool_auto_descriptions()

        # 5c. Split des VLAN encap blocks (ranges → individuels)
        self.collect_encap_block_split()

        # 6. Collecte des descriptions par VLAN
        self.collect_vlan_descriptions()

        # 7. Collecte des mappings Interface Profile → Interface Config
        self.collect_interface_config_mappings()

        # Afficher le résumé
        self.show_summary()

        # Confirmation
        print("\n" + "=" * 60)
        print(f"📁 Fichier de sortie: {self.output_excel}")
        print("=" * 60)
        print("\nAppliquer les conversions? [O/n]: ", end="", flush=True)
        confirm = input().strip().lower()

        if confirm in ['n', 'no', 'non']:
            print("❌ Conversion annulée")
            return

        # Appliquer les conversions
        self.apply_conversions()

        # Appliquer les options supplémentaires
        if self.disable_bd_routing:
            print("\n" + "=" * 60)
            print("🔀 DÉSACTIVATION DU ROUTAGE BD")
            print("=" * 60)
            self.apply_bd_routing_disable()
            self.create_routing_enable_excel()

        if self.vlan_pool_descriptions:
            print("\n" + "=" * 60)
            print("📝 APPLICATION DES DESCRIPTIONS VLAN POOL")
            print("=" * 60)
            self.apply_vlan_pool_descriptions()

        if self.vlan_descriptions:
            self.apply_vlan_descriptions()

        # Sauvegarder
        self.save_excel()

        print("\n" + "=" * 60)
        print("✅ CONVERSION TERMINÉE!")
        print("=" * 60)
        print(f"📂 Fichier source: {self.excel_file}")
        print(f"📁 Fichier converti: {self.output_excel}")
        print("\n💡 Utilisez fabric_automation.py pour déployer sur la nouvelle fabric")

    def run_config(self, config_file):
        """Exécution en mode fichier de configuration"""
        # Charger le fichier config
        if not self.load_config_file(config_file):
            return

        # Afficher le résumé
        self.show_summary()

        # Confirmation
        print("\n" + "=" * 60)
        print(f"📁 Fichier de sortie: {self.output_excel}")
        print("=" * 60)
        print("\nAppliquer les conversions? [O/n]: ", end="", flush=True)
        confirm = input().strip().lower()

        if confirm in ['n', 'no', 'non']:
            print("❌ Conversion annulée")
            return

        # Appliquer interface_config si activé (AVANT apply_conversions pour le bug fix)
        if self.interface_config_enabled:
            self.apply_interface_config_from_file()

        # Appliquer les conversions
        self.apply_conversions()

        # Appliquer les options supplémentaires
        if self.disable_bd_routing:
            print("\n" + "=" * 60)
            print("🔀 DÉSACTIVATION DU ROUTAGE BD")
            print("=" * 60)
            self.apply_bd_routing_disable()
            self.create_routing_enable_excel()

        if self.vlan_pool_descriptions:
            print("\n" + "=" * 60)
            print("📝 APPLICATION DES DESCRIPTIONS VLAN POOL")
            print("=" * 60)
            self.apply_vlan_pool_descriptions()

        if self.vlan_descriptions:
            self.apply_vlan_descriptions()

        # Sauvegarder
        self.save_excel()

        print("\n" + "=" * 60)
        print("✅ CONVERSION TERMINÉE!")
        print("=" * 60)
        print(f"📂 Fichier source: {self.excel_file}")
        print(f"📁 Fichier converti: {self.output_excel}")
        print("\n💡 Utilisez fabric_automation.py pour déployer sur la nouvelle fabric")

    def run(self):
        """Exécution principale avec menu"""
        # Charger le fichier Excel
        self.load_excel()

        # Menu principal
        print("\n" + "=" * 60)
        print("📋 MODE DE CONVERSION")
        print("=" * 60)
        print("\n   [1] Wizard interactif (étape par étape)")
        print("   [2] Fichier de configuration (texte plat)")
        print("\nChoix [1]: ", end="", flush=True)
        mode = input().strip()

        if mode == '2':
            # Sous-menu fichier config
            print("\n" + "-" * 60)
            print("📄 FICHIER DE CONFIGURATION")
            print("-" * 60)
            print("\n   [A] Générer un template (pré-rempli depuis le Excel)")
            print("   [B] Charger un fichier existant et appliquer")
            print("\nChoix [A]: ", end="", flush=True)
            sub = input().strip().upper()

            if sub == 'B':
                # Charger un fichier existant
                print("\n📁 Fichier de configuration (.cfg): ", end="", flush=True)
                config_file = input().strip()
                if not config_file:
                    print("❌ Aucun fichier spécifié")
                    return
                if not os.path.exists(config_file):
                    print(f"❌ Fichier non trouvé: {config_file}")
                    return
                self.run_config(config_file)
            else:
                # Générer un template
                self.generate_config_file()
        else:
            # Mode wizard
            self.run_wizard()


def main():
    print("=" * 60)
    print("🔄 FABRIC CONVERTER V4 - Migration ACI")
    print("=" * 60)
    print("Convertit une configuration ACI d'une fabric vers une autre")
    print("• [1] Wizard interactif (étape par étape)")
    print("• [2] Fichier de configuration (texte plat, copier-coller)")
    print("")

    # Demander le fichier Excel source
    print("📁 Fichier Excel source: ", end="", flush=True)
    excel_file = input().strip()

    if not excel_file:
        print("❌ Aucun fichier spécifié")
        sys.exit(1)

    # Ajouter .xlsx si manquant
    if not excel_file.endswith('.xlsx'):
        excel_file += '.xlsx'

    if not os.path.exists(excel_file):
        print(f"❌ Fichier non trouvé: {excel_file}")
        sys.exit(1)

    # Lancer la conversion
    converter = FabricConverter(excel_file)
    converter.run()


if __name__ == "__main__":
    main()

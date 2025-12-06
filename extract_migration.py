#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script d'extraction EPG ciblée pour migration ACI.
Extrait UNIQUEMENT les EPG demandés et leurs dépendances directes.
"""

import os
import sys
import json
import yaml
import pandas as pd
import requests
import urllib3
import re
import getpass
import tarfile
import tempfile
import shutil
from pathlib import Path
from collections import defaultdict

# Désactiver les avertissements SSL
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)


class EPGMigrationExtractor:
    def __init__(self):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.csv_dir = os.path.join(self.base_dir, 'csv_out')
        self.extraction_list_file = os.path.join(self.base_dir, 'extraction_list.yml')
        self.output_excel = os.path.join(self.base_dir, 'epg_migration.xlsx')

        os.makedirs(self.csv_dir, exist_ok=True)

        # Données
        self.aci_data = {}
        self.epg_configs = []  # Liste des configs EPG demandés
        self.l3out_configs = []  # Liste des configs L3Out demandés

        # Collections d'objets trouvés - EPG (avec leurs données complètes)
        self.found_epgs = []
        self.found_bds = []
        self.found_domains = []
        self.found_vlan_pools = []
        self.found_encap_blocks = []
        self.found_aeps = []
        self.found_interface_policy_groups = []
        self.found_epg_to_domain = []
        self.found_domain_to_pool = []
        self.found_aep_to_domain = []
        self.found_aep_to_epg = []

        # Collections d'objets trouvés - L3Out
        self.found_l3outs = []
        self.found_l3out_node_profiles = []
        self.found_l3out_nodes = []
        self.found_l3out_int_profiles = []
        self.found_l3out_interfaces = []  # Standard L3Out
        self.found_l3out_floating_svis = []  # Floating L3Out
        self.found_l3out_floating_svi_paths = []
        self.found_l3out_floating_svi_secondary_ips = []
        self.found_l3out_floating_svi_path_sec = []
        self.found_l3out_bgp_peers = []  # Standard BGP
        self.found_l3out_bgp_peers_floating = []  # Floating BGP
        self.found_l3out_bgp_protocol_profiles = []
        self.found_l3out_extepgs = []
        self.found_l3out_extsubnets = []
        self.found_l3out_extepg_to_contract = []
        self.found_l3out_vpc_members = []
        self.found_bd_to_l3out = []
        self.found_match_rules = []
        self.found_match_route_dests = []
        self.found_route_control_profiles = []
        self.found_route_control_contexts = []

    def load_extraction_list(self):
        """Charge la liste d'extraction (EPG + L3Out) depuis le fichier YAML"""
        print("\n📋 Chargement de la liste d'extraction...")

        if not os.path.exists(self.extraction_list_file):
            print(f"❌ Fichier {self.extraction_list_file} introuvable.")
            sys.exit(1)

        with open(self.extraction_list_file, 'r', encoding='utf-8') as f:
            # Charger tous les documents YAML
            docs = list(yaml.safe_load_all(f))

        for doc in docs:
            if doc:  # Ignorer les documents vides
                # L3Out configuration (has 'floating' parameter)
                if 'floating' in doc:
                    tenant = doc.get('tenant')
                    l3out = doc.get('l3out')
                    floating = doc.get('floating')

                    # Normalize floating value
                    if isinstance(floating, str):
                        floating = floating.strip().lower() in ['yes', 'true', '1']

                    if tenant and l3out:
                        self.l3out_configs.append({
                            'tenant': tenant,
                            'l3out': l3out,
                            'floating': floating
                        })
                else:
                    # EPG configuration (existing format)
                    tenant = doc.get('tenant')
                    ap = doc.get('ap')
                    epgs = doc.get('epgs', [])

                    for epg in epgs:
                        self.epg_configs.append({
                            'tenant': tenant,
                            'ap': ap,
                            'epg': epg
                        })

        print(f"✅ {len(self.epg_configs)} EPG(s) à extraire:")
        for cfg in self.epg_configs:
            print(f"   - {cfg['tenant']}/{cfg['ap']}/{cfg['epg']}")

        print(f"✅ {len(self.l3out_configs)} L3Out(s) à extraire:")
        for cfg in self.l3out_configs:
            l3out_type = "Floating" if cfg['floating'] else "Standard"
            print(f"   - {cfg['tenant']}/{cfg['l3out']} ({l3out_type})")

    def choose_mode(self):
        """Demande le mode d'extraction"""
        print("\n" + "="*80)
        print(" MODE D'EXTRACTION")
        print("="*80)
        print("\n1. 🌐 Connexion LIVE à l'APIC")
        print("2. 📦 Backup JSON (fichier local)")

        while True:
            choice = input("\nChoisir le mode (1 ou 2): ").strip()
            if choice in ['1', '2']:
                return choice
            print("❌ Choix invalide. Entrer 1 ou 2.")

    def get_credentials(self):
        """Demande les credentials de manière interactive"""
        print("\n" + "="*80)
        print(" CONNEXION À L'ACI FABRIC")
        print("="*80)

        ip = input("\n🌐 Adresse IP de l'APIC: ").strip()
        if not ip:
            print("❌ Adresse IP requise")
            sys.exit(1)

        user = input("👤 Nom d'utilisateur: ").strip()
        if not user:
            print("❌ Nom d'utilisateur requis")
            sys.exit(1)

        password = getpass.getpass("🔒 Mot de passe: ")
        if not password:
            print("❌ Mot de passe requis")
            sys.exit(1)

        return {
            'ip': ip,
            'user': user,
            'password': password
        }

    def load_from_backup(self):
        """Charge la configuration depuis un fichier JSON ou tar.gz de backup"""
        print("\n" + "="*80)
        print(" CHARGEMENT DEPUIS BACKUP")
        print("="*80)

        backup_file = input("\n📁 Chemin du fichier (JSON ou tar.gz): ").strip()

        if not backup_file:
            print("❌ Chemin du fichier requis")
            sys.exit(1)

        # Si chemin relatif, l'ajouter au base_dir
        if not os.path.isabs(backup_file):
            backup_file = os.path.join(self.base_dir, backup_file)

        if not os.path.exists(backup_file):
            print(f"❌ Fichier non trouvé: {backup_file}")
            sys.exit(1)

        # Vérifier le type de fichier
        if backup_file.endswith('.tar.gz') or backup_file.endswith('.tgz'):
            # C'est une archive tar.gz
            self._load_from_targz(backup_file)
        elif backup_file.endswith('.json'):
            # C'est un fichier JSON direct
            self._load_from_json(backup_file)
        else:
            print(f"❌ Format non supporté. Utiliser .json ou .tar.gz")
            sys.exit(1)

    def _load_from_json(self, json_file):
        """Charge depuis un fichier JSON"""
        print(f"\n📥 Chargement de {os.path.basename(json_file)}...")
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            # Vérifier le format du JSON
            if 'polUni' in data:
                # Format hiérarchique (snapshot ACI) - convertir en format imdata
                print("   → Format détecté: Snapshot hiérarchique ACI")
                self.aci_data = self._convert_poluni_to_imdata(data)
            elif 'imdata' in data:
                # Format API standard
                print("   → Format détecté: API standard ACI")
                self.aci_data = data
            else:
                print("❌ Format JSON non reconnu (ni polUni ni imdata)")
                sys.exit(1)

            print("✅ Backup JSON chargé avec succès")
        except json.JSONDecodeError as e:
            print(f"❌ Erreur JSON: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Erreur lors du chargement: {e}")
            sys.exit(1)

    def _convert_poluni_to_imdata(self, data):
        """Convertit le format hiérarchique polUni en format imdata plat"""
        imdata = []

        def build_dn(class_name, attrs, parent_dn="uni"):
            """Construit le DN basé sur la classe et les attributs"""
            name = attrs.get('name', '')

            # Cas spéciaux qui nécessitent des attributs supplémentaires
            if class_name == 'fvnsVlanInstP':
                # VLAN Pool: uni/infra/vlanns-[NAME]-[ALLOCMODE]
                alloc_mode = attrs.get('allocMode', 'dynamic')
                if name:
                    return f"uni/infra/vlanns-[{name}]-{alloc_mode}"

            elif class_name == 'fvnsEncapBlk':
                # Encap Block: [PARENT_DN]/from-[FROM]-to-[TO]
                from_vlan = attrs.get('from', '')
                to_vlan = attrs.get('to', '')
                if from_vlan and to_vlan:
                    return f"{parent_dn}/from-[{from_vlan}]-to-[{to_vlan}]"

            # Relationship objects (pas de name, juste parent_dn + suffix)
            elif class_name == 'infraRsVlanNs':
                return f"{parent_dn}/rsvlanNs"
            elif class_name == 'l3extRsVlanNs':
                return f"{parent_dn}/rsvlanNs"
            elif class_name.startswith('fvRs') or class_name.startswith('infraRs'):
                # Autres relationships - construire DN générique
                rel_name = class_name[4:] if class_name.startswith('fvRs') else class_name[7:]
                rel_name = rel_name[0].lower() + rel_name[1:]  # Première lettre en minuscule
                return f"{parent_dn}/rs{rel_name}"

            # Mapping des classes vers leurs préfixes DN standard
            dn_prefixes = {
                'fvTenant': 'tn',
                'fvAp': 'ap',
                'fvAEPg': 'epg',
                'fvBD': 'BD',
                'fvCtx': 'ctx',
                'physDomP': 'phys',
                'l3extDomP': 'l3dom',
                'vmmDomP': 'vmmp',
                'infraAttEntityP': 'attentp',
                'infraAccPortGrp': 'accportgrp',
                'infraAccBndlGrp': 'accbundle',
            }

            if class_name in dn_prefixes and name:
                prefix = dn_prefixes[class_name]
                return f"{parent_dn}/{prefix}-{name}"

            return parent_dn

        def flatten_obj(obj, parent_dn="uni"):
            """Fonction récursive pour aplatir la hiérarchie"""
            if isinstance(obj, dict):
                # Parcourir toutes les clés de l'objet
                for key, value in obj.items():
                    # Ignorer les clés spéciales
                    if key in ['children', 'attributes']:
                        continue

                    if isinstance(value, dict):
                        # Si c'est un objet ACI (a des attributes), l'ajouter
                        if 'attributes' in value:
                            # Reconstruire le DN si vide
                            attrs = value['attributes']
                            if 'dn' in attrs and not attrs['dn']:
                                attrs['dn'] = build_dn(key, attrs, parent_dn)

                            current_dn = attrs.get('dn', parent_dn)

                            # Ajouter l'objet avec ses children intacts
                            imdata.append({key: value})

                            # Traiter les enfants récursivement avec le DN actuel
                            if 'children' in value and isinstance(value['children'], list):
                                for child in value['children']:
                                    flatten_obj(child, current_dn)
                        else:
                            # Traiter les autres clés récursivement
                            flatten_obj(value, parent_dn)

            elif isinstance(obj, list):
                for item in obj:
                    flatten_obj(item, parent_dn)

        # Commencer l'aplatissement depuis les enfants de polUni
        if 'polUni' in data and 'children' in data['polUni']:
            for child in data['polUni']['children']:
                flatten_obj(child, "uni")

        print(f"   → {len(imdata)} objets convertis du format hiérarchique")
        return {'imdata': imdata}

    def _load_from_targz(self, targz_file):
        """Charge depuis une archive tar.gz (snapshot ACI)"""
        print(f"\n📦 Extraction de {os.path.basename(targz_file)}...")

        temp_dir = None
        try:
            # Créer un répertoire temporaire
            temp_dir = tempfile.mkdtemp(prefix='aci_backup_')

            # Extraire l'archive
            with tarfile.open(targz_file, 'r:gz') as tar:
                tar.extractall(path=temp_dir)

            # Chercher le fichier JSON principal (généralement *_1.json)
            json_files = []
            for root, dirs, files in os.walk(temp_dir):
                for file in files:
                    if file.endswith('_1.json'):
                        json_files.append(os.path.join(root, file))

            if not json_files:
                # Si pas de *_1.json, chercher n'importe quel .json
                for root, dirs, files in os.walk(temp_dir):
                    for file in files:
                        if file.endswith('.json') and not file.endswith('.md5'):
                            json_files.append(os.path.join(root, file))

            if not json_files:
                print(f"❌ Aucun fichier JSON trouvé dans l'archive")
                sys.exit(1)

            # Utiliser le premier fichier trouvé (normalement le *_1.json)
            json_file = json_files[0]
            print(f"   → Fichier trouvé: {os.path.basename(json_file)}")

            # Charger le JSON
            self._load_from_json(json_file)

        except tarfile.TarError as e:
            print(f"❌ Erreur d'extraction: {e}")
            sys.exit(1)
        except Exception as e:
            print(f"❌ Erreur: {e}")
            sys.exit(1)
        finally:
            # Nettoyer le répertoire temporaire
            if temp_dir and os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)

    def login(self, session, url, user, password):
        """Authentification APIC"""
        login_url = f"{url}/api/aaaLogin.json"
        payload = {
            "aaaUser": {
                "attributes": {
                    "name": user,
                    "pwd": password
                }
            }
        }

        print(f"\n🔑 Connexion à {url}...")
        try:
            response = session.post(login_url, json=payload, verify=False, timeout=30)
            response.raise_for_status()
            print("✅ Authentification réussie")
            return True
        except Exception as e:
            print(f"❌ Échec authentification: {e}")
            return False

    def get_aci_config(self, session, url):
        """Récupère la configuration ACI"""
        api_url = f"{url}/api/node/mo/uni.json?query-target=subtree&rsp-subtree=full&rsp-prop-include=config-only"

        print("\n📥 Téléchargement de la configuration ACI...")
        try:
            response = session.get(api_url, verify=False, timeout=300)
            response.raise_for_status()
            print("✅ Configuration téléchargée")
            return response.json()
        except Exception as e:
            print(f"❌ Erreur: {e}")
            return None

    def extract_from_apic(self):
        """Extrait la configuration depuis l'APIC"""
        creds = self.get_credentials()
        base_url = f"https://{creds['ip']}"

        session = requests.Session()

        if not self.login(session, base_url, creds['user'], creds['password']):
            sys.exit(1)

        self.aci_data = self.get_aci_config(session, base_url)

        if not self.aci_data:
            sys.exit(1)

    def find_objects_recursive(self, data, target_class):
        """Recherche d'objets dans imdata (format API plat)"""
        found = []

        # Pour le format API, chercher seulement dans imdata au niveau supérieur
        if isinstance(data, dict) and 'imdata' in data:
            for item in data['imdata']:
                if isinstance(item, dict):
                    for key, value in item.items():
                        if key == target_class:
                            found.append(value)
        # Fallback pour d'autres structures (ne devrait plus être nécessaire)
        elif isinstance(data, dict):
            for key, value in data.items():
                if key == target_class:
                    found.append(value)
                if isinstance(value, (dict, list)):
                    found.extend(self.find_objects_recursive(value, target_class))
        elif isinstance(data, list):
            for item in data:
                found.extend(self.find_objects_recursive(item, target_class))

        return found

    def extract_tenant_from_dn(self, dn):
        """Extrait le nom du tenant depuis un DN"""
        match = re.search(r'/tn-([^/]+)', dn)
        return match.group(1) if match else None

    def extract_ap_from_dn(self, dn):
        """Extrait le nom de l'AP depuis un DN"""
        match = re.search(r'/ap-([^/]+)', dn)
        return match.group(1) if match else None

    def extract_bd_from_dn(self, dn):
        """Extrait le nom du BD depuis un DN"""
        match = re.search(r'/BD-([^/]+)', dn)
        return match.group(1) if match else None

    def _parse_path_dn(self, tDn):
        """Parse un tDn de path pour extraire pod_id, node_id, et interface"""
        path_info = {
            'pod_id': '',
            'node_id': '',
            'interface': ''
        }

        # Format: topology/pod-1/paths-101/pathep-[eth1/1]
        # ou: topology/pod-1/protpaths-101-102/pathep-[vpc-name]
        if '/pod-' in tDn:
            pod_match = re.search(r'/pod-(\d+)/', tDn)
            if pod_match:
                path_info['pod_id'] = pod_match.group(1)

        if '/paths-' in tDn:
            # Single node
            node_match = re.search(r'/paths-(\d+)/', tDn)
            if node_match:
                path_info['node_id'] = node_match.group(1)
        elif '/protpaths-' in tDn:
            # VPC (two nodes)
            nodes_match = re.search(r'/protpaths-(\d+)-(\d+)/', tDn)
            if nodes_match:
                path_info['node_id'] = f"{nodes_match.group(1)}-{nodes_match.group(2)}"

        if '/pathep-[' in tDn:
            int_match = re.search(r'/pathep-\[([^\]]+)\]', tDn)
            if int_match:
                path_info['interface'] = int_match.group(1)

        return path_info

    def identify_and_extract_objects(self):
        """Identifie et extrait les objets liés aux EPG demandés"""
        print("\n🔍 Extraction des objets liés...")

        # Trouver tous les EPG dans la config
        all_epgs = self.find_objects_recursive(self.aci_data, 'fvAEPg')

        # Garder trace des EPG trouvés
        found_epg_names = set()

        # Pour chaque EPG demandé
        for epg_cfg in self.epg_configs:
            tenant_name = epg_cfg['tenant']
            ap_name = epg_cfg['ap']
            epg_name = epg_cfg['epg']

            # Trouver l'EPG correspondant
            for epg_obj in all_epgs:
                attr = epg_obj.get('attributes', {})
                dn = attr.get('dn', '')

                if (f"tn-{tenant_name}/" in dn and
                    f"/ap-{ap_name}/" in dn and
                    attr.get('name') == epg_name):

                    # Extraire les infos de l'EPG
                    bd_name = None
                    children = epg_obj.get('children', [])

                    # Trouver le BD lié
                    for child in children:
                        if 'fvRsBd' in child:
                            bd_name = child['fvRsBd']['attributes'].get('tnFvBDName', '')

                    # Sauvegarder l'EPG
                    epg_data = {
                        'tenant': tenant_name,
                        'ap': ap_name,
                        'epg': epg_name,
                        'bd': bd_name,
                        'description': attr.get('descr', '')
                    }
                    self.found_epgs.append(epg_data)
                    found_epg_names.add(f"{tenant_name}/{ap_name}/{epg_name}")

                    # Trouver les domains liés (fvRsDomAtt)
                    for child in children:
                        if 'fvRsDomAtt' in child:
                            dom_attr = child['fvRsDomAtt']['attributes']
                            tDn = dom_attr.get('tDn', '')

                            domain_type = None
                            domain_name = None

                            if '/phys-' in tDn:
                                domain_type = 'phys'
                                match = re.search(r'/phys-([^/]+)', tDn)
                                if match:
                                    domain_name = match.group(1)
                            elif '/l3dom-' in tDn:
                                domain_type = 'l3dom'
                                match = re.search(r'/l3dom-([^/]+)', tDn)
                                if match:
                                    domain_name = match.group(1)

                            if domain_name:
                                # Sauvegarder la relation EPG -> Domain
                                self.found_epg_to_domain.append({
                                    'tenant': tenant_name,
                                    'ap': ap_name,
                                    'epg': epg_name,
                                    'domain': domain_name,
                                    'domain_type': domain_type
                                })

                                # Sauvegarder le domain
                                domain_data = {
                                    'domain': domain_name,
                                    'domain_type': domain_type
                                }
                                if domain_data not in self.found_domains:
                                    self.found_domains.append(domain_data)

                    # Trouver le BD pour extraire les infos
                    if bd_name:
                        all_bds = self.find_objects_recursive(self.aci_data, 'fvBD')
                        for bd_obj in all_bds:
                            bd_attr = bd_obj.get('attributes', {})
                            bd_dn = bd_attr.get('dn', '')

                            if (f"tn-{tenant_name}/" in bd_dn and
                                bd_attr.get('name') == bd_name):

                                # Extraire le VRF lié
                                vrf_name = ''
                                bd_children = bd_obj.get('children', [])
                                for bd_child in bd_children:
                                    if 'fvRsCtx' in bd_child:
                                        vrf_name = bd_child['fvRsCtx']['attributes'].get('tnFvCtxName', '')
                                    # Note: BD→L3Out extraction is done globally later in L3Out section

                                # Sauvegarder le BD avec tous les paramètres
                                self.found_bds.append({
                                    'tenant': tenant_name,
                                    'bd': bd_name,
                                    'vrf': vrf_name,
                                    'description': bd_attr.get('descr', ''),
                                    'enable_routing': 'true' if bd_attr.get('unicastRoute', 'yes') == 'yes' else 'false',
                                    'arp_flooding': 'true' if bd_attr.get('arpFlood', 'no') == 'yes' else 'false',
                                    'l2_unknown_unicast': bd_attr.get('unkMacUcastAct', 'proxy')
                                })
                                break

        # ====================================================================
        # EXTRACTION L3OUT
        # ====================================================================
        if self.l3out_configs:
            print("\n" + "="*80)
            print("🌐 EXTRACTION L3OUT")
            print("="*80)

            found_l3out_names = set()
            referenced_match_rules = set()  # Track which match_rules are referenced by route_control_context

            for l3out_cfg in self.l3out_configs:
                tenant_name = l3out_cfg['tenant']
                l3out_name = l3out_cfg['l3out']
                is_floating = l3out_cfg['floating']

                l3out_type_str = "Floating" if is_floating else "Standard"
                print(f"\n🔍 Extraction L3Out: {tenant_name}/{l3out_name} ({l3out_type_str})")

                # Find tenant first
                all_tenants = self.find_objects_recursive(self.aci_data, 'fvTenant')
                tenant_obj = None
                for tenant in all_tenants:
                    if tenant.get('attributes', {}).get('name') == tenant_name:
                        tenant_obj = tenant
                        break

                if not tenant_obj:
                    print(f"   ⚠️  Tenant non trouvé: {tenant_name}")
                    continue

                # Search L3Out in tenant
                tenant_l3outs = self.find_objects_recursive(tenant_obj, 'l3extOut')
                l3out_obj = None
                for l3out in tenant_l3outs:
                    if l3out.get('attributes', {}).get('name') == l3out_name:
                        l3out_obj = l3out
                        break

                if not l3out_obj:
                    print(f"   ⚠️  L3Out non trouvé: {l3out_name}")
                    continue

                # Extract L3Out base info
                l3out_attr = l3out_obj.get('attributes', {})
                l3out_children = l3out_obj.get('children', [])

                # Extract VRF and domain
                vrf_name = ''
                domain_name = ''
                route_control_profile = ''

                for l3out_child in l3out_children:
                    if 'l3extRsEctx' in l3out_child:
                        vrf_name = l3out_child['l3extRsEctx']['attributes'].get('tnFvCtxName', '')
                    elif 'l3extRsL3DomAtt' in l3out_child:
                        tDn = l3out_child['l3extRsL3DomAtt']['attributes'].get('tDn', '')
                        if '/l3dom-' in tDn:
                            match = re.search(r'/l3dom-([^/]+)', tDn)
                            if match:
                                domain_name = match.group(1)
                    elif 'rtctrlProfile' in l3out_child:
                        route_control_profile = l3out_child['rtctrlProfile']['attributes'].get('name', '')

                # Save L3Out
                self.found_l3outs.append({
                    'tenant': tenant_name,
                    'l3out': l3out_name,
                    'vrf': vrf_name,
                    'domain': domain_name,
                    'l3protocol': '',
                    'route_control': route_control_profile,
                    'description': l3out_attr.get('descr', '')
                })
                found_l3out_names.add(f"{tenant_name}/{l3out_name}")

                # Save L3Domain if found
                if domain_name:
                    domain_data = {
                        'domain': domain_name,
                        'domain_type': 'l3dom'
                    }
                    if domain_data not in self.found_domains:
                        self.found_domains.append(domain_data)

                # ================================================================
                # Extract Node Profiles - CRITICAL: Search in L3OUT_OBJ not tenant!
                # ================================================================
                node_profiles = self.find_objects_recursive(l3out_obj, 'l3extLNodeP')

                for np_obj in node_profiles:
                    np_attr = np_obj.get('attributes', {})
                    node_profile_name = np_attr.get('name', '')

                    if not node_profile_name:
                        continue

                    # Save Node Profile
                    self.found_l3out_node_profiles.append({
                        'tenant': tenant_name,
                        'l3out': l3out_name,
                        'node_profile': node_profile_name,
                        'target_dscp': np_attr.get('targetDscp', 'unspecified'),
                        'description': np_attr.get('descr', '')
                    })

                    # Extract children of node profile
                    np_children = np_obj.get('children', [])

                    for np_child in np_children:
                        # ========================================================
                        # Logical Nodes
                        # ========================================================
                        if 'l3extRsNodeL3OutAtt' in np_child:
                            node_attr = np_child['l3extRsNodeL3OutAtt']['attributes']
                            tDn = node_attr.get('tDn', '')
                            router_id = node_attr.get('rtrId', '')

                            # Extract node ID from tDn
                            node_id = ''
                            if '/node-' in tDn:
                                match = re.search(r'/node-(\d+)', tDn)
                                if match:
                                    node_id = match.group(1)

                            if node_id:
                                self.found_l3out_nodes.append({
                                    'tenant': tenant_name,
                                    'l3out': l3out_name,
                                    'node_profile': node_profile_name,
                                    'pod_id': '1',
                                    'node_id': node_id,
                                    'router_id': router_id,
                                    'router_id_as_loopback': 'no'
                                })

                        # ========================================================
                        # BGP Protocol Profile
                        # ========================================================
                        elif 'bgpProtP' in np_child:
                            bgp_prot_attr = np_child['bgpProtP']['attributes']
                            bgp_children = np_child['bgpProtP'].get('children', [])

                            bgp_timers_policy = ''
                            for bgp_child in bgp_children:
                                if 'bgpRsPeerPfxPol' in bgp_child:
                                    bgp_timers_policy = bgp_child['bgpRsPeerPfxPol']['attributes'].get('tnBgpPeerPfxPolName', '')

                            self.found_l3out_bgp_protocol_profiles.append({
                                'tenant': tenant_name,
                                'l3out': l3out_name,
                                'node_profile': node_profile_name,
                                'bgp_timers_policy': bgp_timers_policy,
                                'description': bgp_prot_attr.get('descr', '')
                            })

                        # ========================================================
                        # Interface Profiles
                        # ========================================================
                        elif 'l3extLIfP' in np_child:
                            if_profile_attr = np_child['l3extLIfP']['attributes']
                            if_profile_name = if_profile_attr.get('name', '')

                            if not if_profile_name:
                                continue

                            # Save Interface Profile
                            self.found_l3out_int_profiles.append({
                                'tenant': tenant_name,
                                'l3out': l3out_name,
                                'node_profile': node_profile_name,
                                'interface_profile': if_profile_name,
                                'description': if_profile_attr.get('descr', '')
                            })

                            # Extract interfaces from interface profile
                            if_profile_children = np_child['l3extLIfP'].get('children', [])

                            for if_child in if_profile_children:
                                # ================================================
                                # Standard L3Out Interface (routed interface/sub-interface)
                                # ================================================
                                if 'l3extRsPathL3OutAtt' in if_child and not is_floating:
                                    int_attr = if_child['l3extRsPathL3OutAtt']['attributes']
                                    tDn = int_attr.get('tDn', '')
                                    encap = int_attr.get('encap', 'unknown')
                                    if_inst_t = int_attr.get('ifInstT', '')

                                    # Extract path info
                                    path_info = self._parse_path_dn(tDn)

                                    # Extract IP address and BGP Peers
                                    ip_address = ''
                                    int_children = if_child['l3extRsPathL3OutAtt'].get('children', [])
                                    for int_c in int_children:
                                        if 'l3extIp' in int_c:
                                            ip_address = int_c['l3extIp']['attributes'].get('addr', '')
                                        elif 'bgpPeerP' in int_c:
                                            # BGP Peer for Standard L3Out
                                            peer_attr = int_c['bgpPeerP']['attributes']
                                            peer_ip = peer_attr.get('addr', '')

                                            if peer_ip:
                                                self.found_l3out_bgp_peers.append({
                                                    'tenant': tenant_name,
                                                    'l3out': l3out_name,
                                                    'node_profile': node_profile_name,
                                                    'interface_profile': if_profile_name,
                                                    'peer_ip': peer_ip,
                                                    'remote_as': peer_attr.get('asn', ''),
                                                    'description': peer_attr.get('descr', '')
                                                })

                                    self.found_l3out_interfaces.append({
                                        'tenant': tenant_name,
                                        'l3out': l3out_name,
                                        'node_profile': node_profile_name,
                                        'interface_profile': if_profile_name,
                                        'pod_id': path_info.get('pod_id', ''),
                                        'node_id': path_info.get('node_id', ''),
                                        'interface': path_info.get('interface', ''),
                                        'ip_address': ip_address,
                                        'encap': encap,
                                        'interface_type': if_inst_t,
                                        'description': int_attr.get('descr', '')
                                    })

                                # ================================================
                                # Floating SVI
                                # ================================================
                                elif 'l3extVirtualLIfP' in if_child and is_floating:
                                    svi_children = if_child['l3extVirtualLIfP'].get('children', [])

                                    for svi_child in svi_children:
                                        if 'l3extRsDynPathAtt' in svi_child:
                                            svi_attr = svi_child['l3extRsDynPathAtt']['attributes']
                                            encap = svi_attr.get('encap', 'unknown')
                                            floating_ip = svi_attr.get('floatingAddr', '')

                                            # Save Floating SVI
                                            self.found_l3out_floating_svis.append({
                                                'tenant': tenant_name,
                                                'l3out': l3out_name,
                                                'node_profile': node_profile_name,
                                                'interface_profile': if_profile_name,
                                                'pod_id': '1',
                                                'floating_ip': floating_ip,
                                                'encap': encap,
                                                'description': svi_attr.get('descr', '')
                                            })

                                            # Extract Floating SVI Paths
                                            path_children = svi_child['l3extRsDynPathAtt'].get('children', [])
                                            for path_child in path_children:
                                                if 'l3extMember' in path_child:
                                                    member_attr = path_child['l3extMember']['attributes']
                                                    side = member_attr.get('side', '')
                                                    ip_addr = member_attr.get('addr', '')

                                                    self.found_l3out_floating_svi_paths.append({
                                                        'tenant': tenant_name,
                                                        'l3out': l3out_name,
                                                        'node_profile': node_profile_name,
                                                        'interface_profile': if_profile_name,
                                                        'pod_id': '1',
                                                        'node_id': '',
                                                        'ip_address': ip_addr,
                                                        'encap': encap,
                                                        'side': side,
                                                        'description': member_attr.get('descr', '')
                                                    })

                                        # Secondary IPs for floating SVI
                                        elif 'l3extIp' in svi_child:
                                            ip_attr = svi_child['l3extIp']['attributes']
                                            secondary_ip = ip_attr.get('addr', '')

                                            if secondary_ip:
                                                self.found_l3out_floating_svi_secondary_ips.append({
                                                    'tenant': tenant_name,
                                                    'l3out': l3out_name,
                                                    'node_profile': node_profile_name,
                                                    'interface_profile': if_profile_name,
                                                    'pod_id': '',
                                                    'node_id': '',
                                                    'secondary_ip': secondary_ip,
                                                    'encap': '',
                                                    'description': ip_attr.get('descr', '')
                                                })

                # ================================================================
                # Extract BGP Peers for Floating L3Out (at interface profile level)
                # ================================================================
                if is_floating:
                    for np_obj in node_profiles:
                        np_children = np_obj.get('children', [])
                        for np_child in np_children:
                            if 'l3extLIfP' in np_child:
                                if_profile_name = np_child['l3extLIfP']['attributes'].get('name', '')
                                if_children = np_child['l3extLIfP'].get('children', [])

                                # First, try to find encap from l3extRsDynPathAtt in same interface profile
                                encap_vlan = ''
                                for if_child_scan in if_children:
                                    if 'l3extRsDynPathAtt' in if_child_scan:
                                        encap = if_child_scan['l3extRsDynPathAtt']['attributes'].get('encap', '')
                                        # Extract VLAN from encap (format: vlan-XXX or unknown)
                                        if encap and encap.startswith('vlan-'):
                                            encap_vlan = encap.replace('vlan-', '')

                                for if_child in if_children:
                                    if 'l3extVirtualLIfP' in if_child:
                                        virt_children = if_child['l3extVirtualLIfP'].get('children', [])
                                        for virt_child in virt_children:
                                            if 'bgpPeerP' in virt_child:
                                                peer_data = virt_child['bgpPeerP']
                                                peer_attr = peer_data['attributes']
                                                peer_ip = peer_attr.get('addr', '')

                                                if peer_ip:
                                                    # Extract remote_asn and local_as_number from children
                                                    remote_asn = ''
                                                    local_as_number = ''
                                                    peer_children = peer_data.get('children', [])
                                                    for peer_child in peer_children:
                                                        if 'bgpAsP' in peer_child:
                                                            remote_asn = peer_child['bgpAsP']['attributes'].get('asn', '')
                                                        elif 'bgpLocalAsnP' in peer_child:
                                                            local_as_number = peer_child['bgpLocalAsnP']['attributes'].get('localAsn', '')

                                                    self.found_l3out_bgp_peers_floating.append({
                                                        'tenant': tenant_name,
                                                        'l3out': l3out_name,
                                                        'node_profile': np_obj.get('attributes', {}).get('name', ''),
                                                        'interface_profile': if_profile_name,
                                                        'pod_id': '1',  # Default pod
                                                        'node_id': '',  # Not available without l3extMember
                                                        'vlan': encap_vlan,
                                                        'peer_ip': peer_ip,
                                                        'admin_state': peer_attr.get('adminSt', ''),
                                                        'ttl': peer_attr.get('ttl', ''),
                                                        'weight': peer_attr.get('weight', ''),
                                                        'remote_asn': remote_asn,
                                                        'local_as_number': local_as_number,
                                                        'bgp_controls': peer_attr.get('ctrl', ''),
                                                        'peer_controls': peer_attr.get('peerCtrl', ''),
                                                        'address_type_controls': peer_attr.get('addrTCtrl', '')
                                                    })

                # ================================================================
                # Extract ExtEPG, ExtSubnet, ExtEPG→Contract
                # ================================================================
                for l3out_child in l3out_children:
                    if 'l3extInstP' in l3out_child:
                        extepg_attr = l3out_child['l3extInstP']['attributes']
                        extepg_name = extepg_attr.get('name', '')

                        if not extepg_name:
                            continue

                        # Save ExtEPG
                        self.found_l3out_extepgs.append({
                            'tenant': tenant_name,
                            'l3out': l3out_name,
                            'extepg': extepg_name,
                            'description': extepg_attr.get('descr', '')
                        })

                        # Extract children of ExtEPG
                        extepg_children = l3out_child['l3extInstP'].get('children', [])

                        for extepg_child in extepg_children:
                            # ExtSubnet
                            if 'l3extSubnet' in extepg_child:
                                subnet_attr = extepg_child['l3extSubnet']['attributes']
                                subnet_ip = subnet_attr.get('ip', '')

                                if subnet_ip:
                                    self.found_l3out_extsubnets.append({
                                        'tenant': tenant_name,
                                        'l3out': l3out_name,
                                        'extepg': extepg_name,
                                        'network': subnet_ip,
                                        'scope': 'import-security',
                                        'description': subnet_attr.get('descr', '')
                                    })

                            # ExtEPG → Contract (Consumed)
                            elif 'fvRsCons' in extepg_child:
                                contract_name = extepg_child['fvRsCons']['attributes'].get('tnVzBrCPName', '')
                                if contract_name:
                                    self.found_l3out_extepg_to_contract.append({
                                        'tenant': tenant_name,
                                        'l3out': l3out_name,
                                        'extepg': extepg_name,
                                        'contract': contract_name,
                                        'contract_type': 'consumed'
                                    })

                            # ExtEPG → Contract (Provided)
                            elif 'fvRsProv' in extepg_child:
                                contract_name = extepg_child['fvRsProv']['attributes'].get('tnVzBrCPName', '')
                                if contract_name:
                                    self.found_l3out_extepg_to_contract.append({
                                        'tenant': tenant_name,
                                        'l3out': l3out_name,
                                        'extepg': extepg_name,
                                        'contract': contract_name,
                                        'contract_type': 'provided'
                                    })

                # ================================================================
                # Extract Route Control Objects
                # ================================================================
                for l3out_child in l3out_children:
                    if 'rtctrlProfile' in l3out_child:
                        profile_attr = l3out_child['rtctrlProfile']['attributes']
                        profile_name = profile_attr.get('name', '')

                        if not profile_name:
                            continue

                        # Save Route Control Profile
                        self.found_route_control_profiles.append({
                            'tenant': tenant_name,
                            'l3out': l3out_name,
                            'route_control_profile': profile_name,
                            'description': profile_attr.get('descr', '')
                        })

                        # Extract children of route control profile
                        profile_children = l3out_child['rtctrlProfile'].get('children', [])

                        for profile_child in profile_children:
                            # Match Rules
                            if 'rtctrlSubjP' in profile_child:
                                subj_attr = profile_child['rtctrlSubjP']['attributes']
                                match_rule_name = subj_attr.get('name', '')

                                if match_rule_name:
                                    self.found_match_rules.append({
                                        'tenant': tenant_name,
                                        'match_rule': match_rule_name,
                                        'description': subj_attr.get('descr', '')
                                    })

                            # Route Control Context
                            elif 'rtctrlCtxP' in profile_child:
                                ctx_attr = profile_child['rtctrlCtxP']['attributes']
                                ctx_name = ctx_attr.get('name', '')

                                if ctx_name:
                                    # Extract the referenced match_rule name from rtctrlRsCtxPToSubjP
                                    ctx_children = profile_child['rtctrlCtxP'].get('children', [])
                                    referenced_match_rule = ctx_name  # Default to context name

                                    for ctx_child in ctx_children:
                                        if 'rtctrlRsCtxPToSubjP' in ctx_child:
                                            # Found the relation to match_rule!
                                            rel_attr = ctx_child['rtctrlRsCtxPToSubjP']['attributes']
                                            match_rule_name = rel_attr.get('tnRtctrlSubjPName', '')
                                            if match_rule_name:
                                                referenced_match_rule = match_rule_name
                                                referenced_match_rules.add(match_rule_name)
                                                break

                                    # Route Control Context
                                    self.found_route_control_contexts.append({
                                        'tenant': tenant_name,
                                        'l3out': l3out_name,
                                        'route_control_profile': profile_name,
                                        'route_control_context': ctx_name,
                                        'match_rule': referenced_match_rule
                                    })

                                    # Extract Match Route Destinations (deprecated - should be in rtctrlSubjP)
                                    # Kept for backward compatibility if they exist at context level
                                    for ctx_child in ctx_children:
                                        if 'rtctrlMatchRtDest' in ctx_child:
                                            dest_attr = ctx_child['rtctrlMatchRtDest']['attributes']
                                            ip = dest_attr.get('ip', '')

                                            if ip:
                                                self.found_match_route_dests.append({
                                                    'tenant': tenant_name,
                                                    'match_rule': referenced_match_rule,
                                                    'ip': ip
                                                })

            # ================================================================
            # Extract ALL BD→L3Out relations for requested L3Outs
            # (Not just BDs linked to EPG, but ALL BDs in the fabric)
            # ================================================================
            print("\n🔍 Extraction complète BD→L3Out...")

            # Get list of requested L3Out names
            requested_l3out_names = [cfg['l3out'] for cfg in self.l3out_configs]

            # Clear existing bd_to_l3out (will repopulate with complete list)
            self.found_bd_to_l3out = []

            # Find ALL BDs in the fabric
            all_bds_in_fabric = self.find_objects_recursive(self.aci_data, 'fvBD')

            for bd_obj in all_bds_in_fabric:
                bd_attr = bd_obj.get('attributes', {})
                bd_dn = bd_attr.get('dn', '')
                bd_name = bd_attr.get('name', '')

                # Extract tenant name from DN
                tenant_from_dn = self.extract_tenant_from_dn(bd_dn)

                if not tenant_from_dn or not bd_name:
                    continue

                # Check BD children for L3Out relations
                bd_children = bd_obj.get('children', [])
                for bd_child in bd_children:
                    if 'fvRsBDToOut' in bd_child:
                        l3out_name_from_bd = bd_child['fvRsBDToOut']['attributes'].get('tnL3extOutName', '')

                        # Only include if it's one of our requested L3Outs
                        if l3out_name_from_bd in requested_l3out_names:
                            bd_to_l3out_data = {
                                'tenant': tenant_from_dn,
                                'bridge_domain': bd_name,
                                'l3out': l3out_name_from_bd
                            }

                            # Avoid duplicates
                            if bd_to_l3out_data not in self.found_bd_to_l3out:
                                self.found_bd_to_l3out.append(bd_to_l3out_data)

            print(f"   ✅ BD→L3Out: {len(self.found_bd_to_l3out)} relations trouvées")

            # ================================================================
            # Extract Match Rules and Match Route Destinations (tenant level)
            # ONLY for those referenced by Route Control Contexts
            # ================================================================
            print("\n🔍 Extraction Match Rules et Match Route Destinations (filtrés)...")
            print(f"   📋 Match Rules référencés par Route Control Context: {len(referenced_match_rules)}")

            # Match Rules are stored as rtctrlSubjP at tenant level in some configs
            all_match_rules_tenant = self.find_objects_recursive(self.aci_data, 'rtctrlSubjP')

            for rule_obj in all_match_rules_tenant:
                rule_attr = rule_obj.get('attributes', {})
                rule_dn = rule_attr.get('dn', '')
                rule_name = rule_attr.get('name', '')

                if not rule_name:
                    continue

                # FILTER: Only extract if this match_rule is referenced by a route_control_context
                if rule_name not in referenced_match_rules:
                    continue

                # Extract tenant from DN
                tenant_from_dn = self.extract_tenant_from_dn(rule_dn)

                if not tenant_from_dn:
                    continue

                # Check if this match rule is not already added
                if not any(r['match_rule'] == rule_name and r['tenant'] == tenant_from_dn for r in self.found_match_rules):
                    self.found_match_rules.append({
                        'tenant': tenant_from_dn,
                        'match_rule': rule_name,
                        'description': rule_attr.get('descr', '')
                    })

                # Extract Match Route Destinations from children
                rule_children = rule_obj.get('children', [])
                for rule_child in rule_children:
                    if 'rtctrlMatchRtDest' in rule_child:
                        dest_attr = rule_child['rtctrlMatchRtDest']['attributes']
                        ip = dest_attr.get('ip', '')

                        if ip:
                            dest_data = {
                                'tenant': tenant_from_dn,
                                'match_rule': rule_name,
                                'ip': ip
                            }

                            # Avoid duplicates
                            if dest_data not in self.found_match_route_dests:
                                self.found_match_route_dests.append(dest_data)

            print(f"   ✅ Match Rules extraits: {len(self.found_match_rules)}")
            print(f"   ✅ Match Route Destinations: {len(self.found_match_route_dests)}")

            # Summary
            if found_l3out_names:
                print(f"\n✅ L3Out extraits: {len(found_l3out_names)}")
                print(f"   ✅ Node Profiles: {len(self.found_l3out_node_profiles)}")
                print(f"   ✅ Logical Nodes: {len(self.found_l3out_nodes)}")
                print(f"   ✅ Interface Profiles: {len(self.found_l3out_int_profiles)}")
                print(f"   ✅ Interfaces (Standard): {len(self.found_l3out_interfaces)}")
                print(f"   ✅ Floating SVIs: {len(self.found_l3out_floating_svis)}")
                print(f"   ✅ Floating SVI Paths: {len(self.found_l3out_floating_svi_paths)}")
                print(f"   ✅ BGP Peers (Standard): {len(self.found_l3out_bgp_peers)}")
                print(f"   ✅ BGP Peers (Floating): {len(self.found_l3out_bgp_peers_floating)}")
                print(f"   ✅ BGP Protocol Profiles: {len(self.found_l3out_bgp_protocol_profiles)}")
                print(f"   ✅ ExtEPG: {len(self.found_l3out_extepgs)}")
                print(f"   ✅ ExtSubnet: {len(self.found_l3out_extsubnets)}")
                print(f"   ✅ ExtEPG→Contract: {len(self.found_l3out_extepg_to_contract)}")
                print(f"   ✅ BD→L3Out: {len(self.found_bd_to_l3out)}")
                print(f"   ✅ Route Control Profiles: {len(self.found_route_control_profiles)}")
                print(f"   ✅ Match Rules: {len(self.found_match_rules)}")
                print(f"   ✅ Route Control Contexts: {len(self.found_route_control_contexts)}")
                print(f"   ✅ Match Route Destinations: {len(self.found_match_route_dests)}")

        # Maintenant, pour chaque domain trouvé, trouver les VLAN pools
        all_dom_pool_rels = self.find_objects_recursive(self.aci_data, 'infraRsVlanNs')
        all_dom_pool_rels += self.find_objects_recursive(self.aci_data, 'l3extRsVlanNs')

        for domain in self.found_domains:
            domain_name = domain['domain']
            domain_type = domain['domain_type']

            for rel_obj in all_dom_pool_rels:
                rel_attr = rel_obj.get('attributes', {})
                dn = rel_attr.get('dn', '')
                tDn = rel_attr.get('tDn', '')

                if ((domain_type == 'phys' and f'/phys-{domain_name}/' in dn) or
                    (domain_type == 'l3dom' and f'/l3dom-{domain_name}/' in dn)):

                    # Extraire le pool name
                    pool_name = None
                    if 'vlanns-[' in tDn:
                        pool_name = tDn.split('vlanns-[')[1].split(']')[0]
                    elif 'vlanns-' in tDn:
                        parts = tDn.split('vlanns-')[1].split('-')
                        if len(parts) >= 2:
                            pool_name = '-'.join(parts[:-1])  # Enlever -static ou -dynamic

                    if pool_name:
                        # Déterminer le pool_allocation_mode
                        pool_mode = 'static'
                        if 'dynamic' in tDn:
                            pool_mode = 'dynamic'

                        # Sauvegarder la relation Domain -> Pool
                        self.found_domain_to_pool.append({
                            'domain': domain_name,
                            'domain_type': domain_type,
                            'vlan_pool': pool_name,
                            'pool_allocation_mode': pool_mode
                        })

                        # Sauvegarder le pool avec le bon format
                        pool_data = {
                            'pool': pool_name,
                            'pool_allocation_mode': pool_mode,
                            'description': ''
                        }
                        # Éviter les doublons
                        if not any(p['pool'] == pool_name for p in self.found_vlan_pools):
                            self.found_vlan_pools.append(pool_data)

        # Trouver les encap blocks pour chaque VLAN pool
        all_encap_blocks = self.find_objects_recursive(self.aci_data, 'fvnsEncapBlk')

        for pool in self.found_vlan_pools:
            pool_name = pool['pool']
            pool_mode = pool['pool_allocation_mode']

            for block_obj in all_encap_blocks:
                block_attr = block_obj.get('attributes', {})
                dn = block_attr.get('dn', '')

                # Vérifier si ce block appartient à notre pool
                if f"vlanns-[{pool_name}]" in dn or f"vlanns-{pool_name}-" in dn:
                    from_vlan = block_attr.get('from', '')
                    to_vlan = block_attr.get('to', '')

                    # Extraire les numéros de VLAN
                    from_match = re.search(r'vlan-(\d+)', from_vlan)
                    to_match = re.search(r'vlan-(\d+)', to_vlan)

                    if from_match and to_match:
                        self.found_encap_blocks.append({
                            'pool': pool_name,
                            'pool_allocation_mode': pool_mode,
                            'block_start': from_match.group(1),
                            'block_end': to_match.group(1),
                            'description': ''
                        })

        # Trouver les AEP liés aux domains
        all_aep_dom_rels = self.find_objects_recursive(self.aci_data, 'infraRsDomP')

        for rel_obj in all_aep_dom_rels:
            rel_attr = rel_obj.get('attributes', {})
            dn = rel_attr.get('dn', '')
            tDn = rel_attr.get('tDn', '')

            # Vérifier si ce domain est dans notre liste
            for domain in self.found_domains:
                domain_name = domain['domain']
                domain_type = domain['domain_type']

                if ((domain_type == 'phys' and f'/phys-{domain_name}' in tDn) or
                    (domain_type == 'l3dom' and f'/l3dom-{domain_name}' in tDn)):

                    # Extraire l'AEP
                    if '/infra/attentp-' in dn:
                        aep_name = dn.split('/attentp-')[1].split('/')[0]

                        # Sauvegarder l'AEP avec description
                        if not any(a['aep'] == aep_name for a in self.found_aeps):
                            self.found_aeps.append({
                                'aep': aep_name,
                                'description': ''
                            })

                        # Sauvegarder la relation AEP -> Domain
                        self.found_aep_to_domain.append({
                            'aep': aep_name,
                            'domain': domain_name,
                            'domain_type': domain_type
                        })

        # Trouver les relations AEP -> EPG (infraRsAttEntP)
        all_aep_epg_rels = self.find_objects_recursive(self.aci_data, 'infraRsAttEntP')

        for rel_obj in all_aep_epg_rels:
            rel_attr = rel_obj.get('attributes', {})
            tDn = rel_attr.get('tDn', '')
            dn = rel_attr.get('dn', '')

            # Vérifier si cet EPG est dans notre liste
            for epg in self.found_epgs:
                tenant = epg['tenant']
                ap = epg['ap']
                epg_name = epg['epg']

                if (f"tn-{tenant}/" in tDn and
                    f"/ap-{ap}/" in tDn and
                    f"/epg-{epg_name}" in tDn):

                    # Extraire l'AEP
                    if '/infra/attentp-' in dn:
                        aep_name = dn.split('/attentp-')[1].split('/')[0]

                        # Sauvegarder la relation
                        self.found_aep_to_epg.append({
                            'aep': aep_name,
                            'tenant': tenant,
                            'ap': ap,
                            'epg': epg_name,
                            'interface_mode': 'trunk'
                        })

        # Trouver les Interface Policy Groups associés aux AEPs
        print("\n🔍 Extraction des Interface Policy Groups...")

        # Chercher tous les types de policy groups
        all_access_port_pg = self.find_objects_recursive(self.aci_data, 'infraAccPortGrp')
        all_bundle_pg = self.find_objects_recursive(self.aci_data, 'infraAccBndlGrp')

        print(f"   📊 Total Policy Groups dans le fabric: {len(all_access_port_pg)} Access Port + {len(all_bundle_pg)} Bundle = {len(all_access_port_pg) + len(all_bundle_pg)}")

        # Combiner tous les policy groups
        all_policy_groups = []
        for pg in all_access_port_pg:
            all_policy_groups.append(('leaf', pg))
        for pg in all_bundle_pg:
            all_policy_groups.append(('bundle', pg))

        # Pour chaque policy group, vérifier s'il pointe vers un de nos AEPs
        for pg_type, pg_obj in all_policy_groups:
            pg_attr = pg_obj.get('attributes', {})
            pg_name = pg_attr.get('name', '')
            pg_children = pg_obj.get('children', [])

            # Chercher la relation vers AEP (infraRsAttEntP)
            linked_aep = None
            for child in pg_children:
                if 'infraRsAttEntP' in child:
                    tDn = child['infraRsAttEntP']['attributes'].get('tDn', '')
                    if '/infra/attentp-' in tDn:
                        aep_name = tDn.split('/attentp-')[1].split('/')[0]
                        # Vérifier si c'est un de nos AEPs
                        if any(a['aep'] == aep_name for a in self.found_aeps):
                            linked_aep = aep_name
                            break

            # Si ce policy group est lié à un de nos AEPs, l'extraire
            if linked_aep:
                # Déterminer le lag_type
                if pg_type == 'leaf':
                    lag_type = 'leaf'
                else:
                    # Pour bundle, vérifier si c'est link (PC) ou node (vPC)
                    lag_t = pg_attr.get('lagT', 'link')
                    lag_type = lag_t

                # Extraire les policies associées
                link_level_policy = ''
                cdp_policy = ''
                lldp_policy = ''
                mcp_policy = ''
                stp_interface_policy = ''
                port_channel_policy = ''
                l2_interface_policy = ''

                for child in pg_children:
                    if 'infraRsHIfPol' in child:
                        link_level_policy = child['infraRsHIfPol']['attributes'].get('tnFabricHIfPolName', '')
                    elif 'infraRsCdpIfPol' in child:
                        cdp_policy = child['infraRsCdpIfPol']['attributes'].get('tnCdpIfPolName', '')
                    elif 'infraRsLldpIfPol' in child:
                        lldp_policy = child['infraRsLldpIfPol']['attributes'].get('tnLldpIfPolName', '')
                    elif 'infraRsMcpIfPol' in child:
                        mcp_policy = child['infraRsMcpIfPol']['attributes'].get('tnMcpIfPolName', '')
                    elif 'infraRsStpIfPol' in child:
                        stp_interface_policy = child['infraRsStpIfPol']['attributes'].get('tnStpIfPolName', '')
                    elif 'infraRsLacpPol' in child:
                        port_channel_policy = child['infraRsLacpPol']['attributes'].get('tnLacpLagPolName', '')
                    elif 'infraRsL2IfPol' in child:
                        l2_interface_policy = child['infraRsL2IfPol']['attributes'].get('tnL2IfPolName', '')

                # Sauvegarder le policy group (éviter les doublons)
                pg_data = {
                    'policy_group': pg_name,
                    'aep': linked_aep,
                    'lag_type': lag_type,
                    'link_level_policy': link_level_policy,
                    'cdp_policy': cdp_policy,
                    'lldp_policy': lldp_policy,
                    'mcp_policy': mcp_policy,
                    'stp_interface_policy': stp_interface_policy,
                    'port_channel_policy': port_channel_policy,
                    'l2_interface_policy': l2_interface_policy,
                    'description': pg_attr.get('descr', '')
                }

                # Vérifier si ce policy group n'existe pas déjà
                if not any(p['policy_group'] == pg_name and p['aep'] == linked_aep for p in self.found_interface_policy_groups):
                    self.found_interface_policy_groups.append(pg_data)

        print(f"   ✅ Interface Policy Groups: {len(self.found_interface_policy_groups)}")

        # Vérifier quels EPG n'ont pas été trouvés
        print("\n🔍 Vérification des EPG...")
        for epg_cfg in self.epg_configs:
            epg_path = f"{epg_cfg['tenant']}/{epg_cfg['ap']}/{epg_cfg['epg']}"
            if epg_path not in found_epg_names:
                print(f"   ⚠️  EPG non trouvé: {epg_path}")

        # Afficher le résumé
        print(f"   ✅ EPG: {len(self.found_epgs)}")
        print(f"   ✅ Bridge Domains: {len(self.found_bds)}")
        print(f"   ✅ Domains: {len(self.found_domains)}")
        print(f"   ✅ VLAN Pools: {len(self.found_vlan_pools)}")
        print(f"   ✅ Encap Blocks: {len(self.found_encap_blocks)}")
        print(f"   ✅ AEP: {len(self.found_aeps)}")
        print(f"   ✅ Interface Policy Groups: {len(self.found_interface_policy_groups)}")
        print(f"   ✅ EPG→Domain: {len(self.found_epg_to_domain)}")
        print(f"   ✅ Domain→Pool: {len(self.found_domain_to_pool)}")
        print(f"   ✅ AEP→Domain: {len(self.found_aep_to_domain)}")
        print(f"   ✅ AEP→EPG: {len(self.found_aep_to_epg)}")

    def generate_csvs(self):
        """Génère les CSV"""
        print("\n📝 Génération des CSV...")

        # Nettoyer le répertoire CSV
        import glob
        for f in glob.glob(os.path.join(self.csv_dir, '*.csv')):
            os.remove(f)

        csv_data = {
            # EPG objects
            'epg': self.found_epgs,
            'bd': self.found_bds,
            'epg_to_domain': self.found_epg_to_domain,
            'aep_to_epg': self.found_aep_to_epg,

            # L3Out objects
            'l3out': self.found_l3outs,
            'l3out_logical_node_profile': self.found_l3out_node_profiles,
            'l3out_logical_node': self.found_l3out_nodes,
            'l3out_logical_interface_profile': self.found_l3out_int_profiles,
            'l3out_interface': self.found_l3out_interfaces,
            'l3out_floating_svi': self.found_l3out_floating_svis,
            'l3out_floating_svi_path': self.found_l3out_floating_svi_paths,
            'l3out_floating_svi_secondary_ip': self.found_l3out_floating_svi_secondary_ips,
            'l3out_floating_svi_path_sec': self.found_l3out_floating_svi_path_sec,
            'l3out_logical_interface_vpc_mem': self.found_l3out_vpc_members,
            'l3out_bgp_peer': self.found_l3out_bgp_peers,
            'l3out_bgp_peer_floating': self.found_l3out_bgp_peers_floating,
            'l3out_bgp_protocol_profile': self.found_l3out_bgp_protocol_profiles,
            'l3out_extepg': self.found_l3out_extepgs,
            'l3out_extsubnet': self.found_l3out_extsubnets,
            'l3out_extepg_to_contract': self.found_l3out_extepg_to_contract,
            'bd_to_l3out': self.found_bd_to_l3out,

            # Route Control objects
            'match_rule': self.found_match_rules,
            'match_route_destination': self.found_match_route_dests,
            'route_control_profile': self.found_route_control_profiles,
            'route_control_context': self.found_route_control_contexts,

            # Infrastructure objects (shared by EPG and L3Out)
            'domain': self.found_domains,
            'vlan_pool': self.found_vlan_pools,
            'vlan_pool_encap_block': self.found_encap_blocks,
            'aep': self.found_aeps,
            'interface_policy_leaf_policy_gr': self.found_interface_policy_groups,
            'domain_to_vlan_pool': self.found_domain_to_pool,
            'aep_to_domain': self.found_aep_to_domain
        }

        total_rows = 0
        for csv_name, data in csv_data.items():
            if data:
                df = pd.DataFrame(data)
                csv_path = os.path.join(self.csv_dir, f"{csv_name}.csv")
                df.to_csv(csv_path, index=False)
                print(f"   ✅ {csv_name:<30} -> {len(data)} lignes")
                total_rows += len(data)
            else:
                print(f"   ⚪ {csv_name:<30} -> 0 lignes")

        print(f"\n✅ Total: {total_rows} lignes")

    def generate_excel(self):
        """Génère le fichier Excel"""
        print(f"\n📊 Génération de l'Excel: {self.output_excel}")

        # Vérifier s'il y a des données à exporter
        csv_files = sorted([f for f in os.listdir(self.csv_dir) if f.endswith('.csv')])
        has_data = False

        # Vérifier si au moins un CSV contient des données
        for csv_file in csv_files:
            csv_path = os.path.join(self.csv_dir, csv_file)
            try:
                df = pd.read_csv(csv_path)
                if not df.empty:
                    has_data = True
                    break
            except:
                pass

        if not has_data:
            print("\n⚠️  Aucune donnée trouvée - Excel non généré")
            print("\n💡 Conseil: Vérifiez que les EPG dans epg_list.yml existent dans le backup")
            return

        sheets_written = 0
        with pd.ExcelWriter(self.output_excel, engine='openpyxl') as writer:
            for csv_file in csv_files:
                sheet_name = csv_file.replace('.csv', '')
                csv_path = os.path.join(self.csv_dir, csv_file)

                try:
                    df = pd.read_csv(csv_path)
                    if not df.empty:
                        df.to_excel(writer, sheet_name=sheet_name, index=False)
                        sheets_written += 1
                        print(f"   ✅ Onglet: {sheet_name}")
                except Exception as e:
                    pass

        print(f"\n🎉 Excel généré avec {sheets_written} onglets!")

    def run(self):
        """Exécution principale"""
        print("="*80)
        print(" EPG MIGRATION EXTRACTOR - Version 2.2")
        print("="*80)

        # Charger la liste des EPG et L3Out à extraire
        self.load_extraction_list()

        # Demander le mode d'extraction
        mode = self.choose_mode()

        # Charger la configuration selon le mode
        if mode == '1':
            # Mode Live: connexion à l'APIC
            self.extract_from_apic()
        else:
            # Mode Backup: charger depuis JSON
            self.load_from_backup()

        # Extraction des objets (identique pour les 2 modes)
        self.identify_and_extract_objects()
        self.generate_csvs()
        self.generate_excel()

        print("\n" + "="*80)
        print("✅ EXTRACTION TERMINÉE!")
        print("="*80)
        print(f"📂 CSV: {self.csv_dir}/")
        print(f"📊 Excel: {self.output_excel}")
        print()


if __name__ == "__main__":
    extractor = EPGMigrationExtractor()
    extractor.run()

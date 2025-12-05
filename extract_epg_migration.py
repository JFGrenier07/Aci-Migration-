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
        self.epg_list_file = os.path.join(self.base_dir, 'epg_list.yml')
        self.output_excel = os.path.join(self.base_dir, 'epg_migration.xlsx')

        os.makedirs(self.csv_dir, exist_ok=True)

        # Données
        self.aci_data = {}
        self.epg_configs = []  # Liste des configs EPG demandés

        # Collections d'objets trouvés (avec leurs données complètes)
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

    def load_epg_list(self):
        """Charge la liste des EPG (format YAML avec documents multiples)"""
        print("\n📋 Chargement de la liste des EPG...")

        if not os.path.exists(self.epg_list_file):
            print(f"❌ Fichier {self.epg_list_file} introuvable.")
            sys.exit(1)

        with open(self.epg_list_file, 'r', encoding='utf-8') as f:
            # Charger tous les documents YAML
            docs = list(yaml.safe_load_all(f))

        for doc in docs:
            if doc:  # Ignorer les documents vides
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
            'epg': self.found_epgs,
            'bd': self.found_bds,
            'domain': self.found_domains,
            'vlan_pool': self.found_vlan_pools,
            'vlan_pool_encap_block': self.found_encap_blocks,
            'aep': self.found_aeps,
            'interface_policy_leaf_policy_gr': self.found_interface_policy_groups,
            'epg_to_domain': self.found_epg_to_domain,
            'domain_to_vlan_pool': self.found_domain_to_pool,
            'aep_to_domain': self.found_aep_to_domain,
            'aep_to_epg': self.found_aep_to_epg
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
        print(" EPG MIGRATION EXTRACTOR - Version 2.1")
        print("="*80)

        # Charger la liste des EPG à extraire
        self.load_epg_list()

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

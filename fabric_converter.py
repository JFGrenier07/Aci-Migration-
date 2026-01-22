#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de conversion de fabric ACI - Version 4.
Convertit un fichier Excel d'une fabric source vers une fabric destination
en modifiant les parametres cles (tenant, VRF, AP, node_id, path, etc.)

V4:
- Menu principal: Wizard interactif ou mode YAML
- Generation de template YAML avec decouverte automatique
- Chargement de fichier YAML pour conversion sans interaction
- Interface professionnelle (box-drawing, sans emojis)
"""

import os
import sys
import yaml
import pandas as pd
from pathlib import Path
from collections import defaultdict


class FabricConverter:
    def __init__(self, excel_file):
        self.base_dir = os.path.dirname(os.path.abspath(__file__))
        self.excel_file = excel_file
        self.extraction_list_file = os.path.join(self.base_dir, 'extraction_list.yml')

        # Nom du fichier de sortie
        excel_path = Path(excel_file)
        self.output_excel = str(excel_path.parent / f"{excel_path.stem}_converted.xlsx")

        # Donnees Excel
        self.excel_data = {}  # Dict des DataFrames par onglet

        # Mappings de conversion - Globaux
        self.tenant_mapping = {}
        self.vrf_mapping = {}
        self.ap_mapping = {}
        self.l3out_mapping = {}  # Pour bd_to_l3out

        # Mappings L3Out UNIFIES (tous les onglets)
        self.node_id_mapping = {}
        self.node_profile_mapping = {}
        self.int_profile_mapping = {}
        self.path_ep_mapping = {}
        self.local_as_mapping = {}

        # Mappings Route Control
        self.match_rule_mapping = {}
        self.route_control_profile_mapping = {}
        self.route_control_context_mapping = {}

        # Options supplementaires
        self.disable_bd_routing = False
        self.vlan_descriptions = []  # Liste de tuples (vlan, description)

        # Interface config
        self.interface_config_enabled = False
        self.interface_config_type = 'switch_port'
        self.interface_config_profile_to_node = {}
        self.interface_config_mappings = []

        # Colonnes a convertir par type
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
        self.route_control_profile_columns = ['route_control_profile']
        self.route_control_context_columns = ['route_control_context']

    # =========================================================================
    # UI HELPERS
    # =========================================================================

    def print_header(self, title):
        """Affiche un header avec box-drawing"""
        width = 58
        print(f"\n+{'=' * width}+")
        print(f"|{title:^{width}}|")
        print(f"+{'=' * width}+")

    def print_section(self, step, total, title):
        """Affiche un titre de section [ETAPE X/Y]"""
        print(f"\n[ETAPE {step}/{total}] {title}")
        self.print_separator()

    def print_separator(self):
        """Affiche un separateur"""
        print("-" * 58)

    def print_info(self, msg):
        """Affiche un message d'info"""
        print(f"[+] {msg}")

    def print_warning(self, msg):
        """Affiche un avertissement"""
        print(f"[!] {msg}")

    def print_detail(self, msg):
        """Affiche un detail"""
        print(f"[>] {msg}")

    def print_item(self, msg):
        """Affiche un element de liste"""
        print(f"[*] {msg}")

    def print_error(self, msg):
        """Affiche une erreur"""
        print(f"[X] {msg}")

    def print_success(self, msg):
        """Affiche un succes"""
        print(f"[OK] {msg}")

    # =========================================================================
    # CORE LOGIC
    # =========================================================================

    def load_excel(self):
        """Charge le fichier Excel source"""
        print(f"\n[+] Chargement du fichier Excel: {self.excel_file}")

        if not os.path.exists(self.excel_file):
            self.print_error(f"Fichier non trouve: {self.excel_file}")
            sys.exit(1)

        excel = pd.ExcelFile(self.excel_file)
        for sheet_name in excel.sheet_names:
            self.excel_data[sheet_name] = pd.read_excel(excel, sheet_name=sheet_name)

        self.print_success(f"{len(self.excel_data)} onglets charges")
        return True

    def load_extraction_list(self):
        """Charge la liste d'extraction (optionnel)"""
        if not os.path.exists(self.extraction_list_file):
            return None

        with open(self.extraction_list_file, 'r', encoding='utf-8') as f:
            docs = list(yaml.safe_load_all(f))

        return docs

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
        exclude_sheets: liste d'onglets a exclure de la recherche
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
                                # Eviter les doublons de contexte
                                existing_sheets = [c['sheet_name'] for c in values_with_context.get(val_str, [])]
                                if sheet_name not in existing_sheets:
                                    values_with_context[val_str].append(context)

        return values_with_context

    def display_value_context_improved(self, value, contexts):
        """Affiche le contexte d'une valeur"""
        if not contexts:
            return

        print(f"\n   {'─' * 50}")
        print(f"   Valeur: [{value}]")

        for ctx in contexts[:3]:  # Limiter a 3 contextes
            print(f"      |- Onglet: {ctx['sheet_name']}")
            # Afficher seulement les colonnes pertinentes (premieres colonnes)
            headers_display = ctx['headers'][:8]
            if len(ctx['headers']) > 8:
                headers_display = headers_display + ['...']
            print(f"      |  Colonnes: {', '.join(str(h) for h in headers_display)}")
            # Afficher la ligne formatee
            row_display = self.format_row_display(ctx['row'], ctx['headers'])
            print(f"      '- Donnees: {row_display}")

        if len(contexts) > 3:
            print(f"      ... et {len(contexts) - 3} autre(s) onglet(s)")

    def discover_global_values(self):
        """Decouvre les valeurs globales (tenant, vrf, ap)"""
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
        """Demande un mapping a l'utilisateur"""
        if default:
            print(f"   {prompt_text} [{source_value}] -> [{default}]: ", end="")
        else:
            print(f"   {prompt_text} [{source_value}] -> : ", end="")

        user_input = input().strip()

        if not user_input:
            return default if default else source_value
        return user_input

    # =========================================================================
    # WIZARD MODE - Collecte interactive
    # =========================================================================

    def collect_global_mappings(self, unique_values):
        """Collecte les mappings globaux (tenant -> auto VRF/AP)"""
        # Tenants avec derivation automatique VRF/AP
        if unique_values['tenants']:
            print("\n" + "=" * 58)
            print("[>] CONVERSION DES TENANTS (avec VRF et AP automatiques)")
            print("=" * 58)
            print("    Convention: XXXXX-TN -> XXXXX-VRF, XXXXX-ANP")
            print("    (Appuyez sur Entree pour garder la meme valeur)\n")

            for tenant in unique_values['tenants']:
                dest_tenant = self.prompt_mapping("Tenant", tenant, tenant)
                self.tenant_mapping[tenant] = dest_tenant

                # Deriver automatiquement VRF et AP
                if tenant != dest_tenant:
                    # Extraire le nom de base du tenant source
                    src_base = self.extract_base_name(tenant, '-TN')
                    if src_base == tenant:  # Pas de suffixe -TN
                        src_base = tenant

                    # Extraire le nom de base du tenant destination
                    dest_base = self.extract_base_name(dest_tenant, '-TN')
                    if dest_base == dest_tenant:  # Pas de suffixe -TN
                        dest_base = dest_tenant

                    # Mapper VRF: chercher src_base-VRF -> dest_base-VRF
                    src_vrf = f"{src_base}-VRF"
                    dest_vrf = f"{dest_base}-VRF"
                    if src_vrf in unique_values['vrfs']:
                        self.vrf_mapping[src_vrf] = dest_vrf
                        print(f"      '-> VRF auto: {src_vrf} -> {dest_vrf}")

                    # Mapper AP: chercher src_base-ANP -> dest_base-ANP
                    src_ap = f"{src_base}-ANP"
                    dest_ap = f"{dest_base}-ANP"
                    if src_ap in unique_values['aps']:
                        self.ap_mapping[src_ap] = dest_ap
                        print(f"      '-> AP auto:  {src_ap} -> {dest_ap}")

        # VRFs restants (non mappes automatiquement)
        remaining_vrfs = [v for v in unique_values['vrfs'] if v not in self.vrf_mapping]
        if remaining_vrfs:
            print("\n" + "=" * 58)
            print("[>] CONVERSION DES VRFs (non mappes automatiquement)")
            print("=" * 58)
            print("    (Appuyez sur Entree pour garder la meme valeur)\n")

            for vrf in remaining_vrfs:
                dest = self.prompt_mapping("VRF", vrf, vrf)
                self.vrf_mapping[vrf] = dest

        # APs restants (non mappes automatiquement)
        remaining_aps = [a for a in unique_values['aps'] if a not in self.ap_mapping]
        if remaining_aps:
            print("\n" + "=" * 58)
            print("[>] CONVERSION DES APPLICATION PROFILES (non mappes automatiquement)")
            print("=" * 58)
            print("    (Appuyez sur Entree pour garder la meme valeur)\n")

            for ap in remaining_aps:
                dest = self.prompt_mapping("AP", ap, ap)
                self.ap_mapping[ap] = dest

    def collect_bd_to_l3out_mappings(self):
        """Collecte les mappings L3Out depuis l'onglet bd_to_l3out"""
        # Verifier si l'onglet existe
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

        print("\n" + "=" * 58)
        print("[>] CONVERSION DES L3OUT (bd_to_l3out)")
        print("=" * 58)
        print("    L3Out references par les Bridge Domains")
        print("    (Appuyez sur Entree pour garder la meme valeur)")

        # Afficher le contexte pour chaque L3Out
        for l3out in unique_l3outs:
            # Trouver les BDs qui referencent ce L3Out
            mask = df[l3out_col] == l3out
            matching_rows = df[mask]

            print(f"\n   {'─' * 50}")
            print(f"   L3Out: [{l3out}]")
            print(f"      |- Onglet: bd_to_l3out")
            print(f"      |  Colonnes: {', '.join(str(h) for h in df.columns)}")

            # Afficher les BDs qui utilisent ce L3Out
            bd_list = matching_rows['bridge_domain'].tolist() if 'bridge_domain' in columns_lower else []
            tenant_list = matching_rows['tenant'].tolist() if 'tenant' in columns_lower else []

            if bd_list:
                for i, (tenant, bd) in enumerate(zip(tenant_list[:3], bd_list[:3])):
                    print(f"      |  BD {i+1}: {tenant}/{bd}")
                if len(bd_list) > 3:
                    print(f"      |  ... et {len(bd_list) - 3} autres BDs")

            print(f"      '- Total: {len(matching_rows)} Bridge Domain(s) referencent ce L3Out")

            dest = self.prompt_mapping("L3Out", l3out, l3out)
            self.l3out_mapping[l3out] = dest

    def collect_l3out_mappings(self):
        """Collecte les mappings L3Out pour TOUS les onglets (unifie)"""
        print("\n" + "=" * 58)
        print("[>] CONVERSIONS L3OUT (tous les onglets)")
        print("=" * 58)

        # Node IDs
        node_ids = self.find_all_values(self.node_id_columns)
        if node_ids:
            print(f"\n{'─' * 58}")
            print(f"[*] NODE IDs")
            print(f"{'─' * 58}")

            for node_id, contexts in sorted(node_ids.items()):
                self.display_value_context_improved(node_id, contexts)
                dest = self.prompt_mapping("Node ID", node_id, node_id)
                self.node_id_mapping[node_id] = dest

        # Node Profiles
        node_profiles = self.find_all_values(self.node_profile_columns)
        if node_profiles:
            print(f"\n{'─' * 58}")
            print(f"[*] NODE PROFILES")
            print(f"{'─' * 58}")

            for np, contexts in sorted(node_profiles.items()):
                self.display_value_context_improved(np, contexts)
                dest = self.prompt_mapping("Node Profile", np, np)
                self.node_profile_mapping[np] = dest

        # Interface Profiles (L3Out seulement - exclure les onglets Leaf Interface)
        exclude_leaf_sheets = ['interface_policy_leaf_profile', 'access_port_to_int_policy_leaf']
        int_profiles = self.find_all_values(self.int_profile_columns, exclude_sheets=exclude_leaf_sheets)
        if int_profiles:
            print(f"\n{'─' * 58}")
            print(f"[*] INTERFACE PROFILES")
            print(f"{'─' * 58}")

            for ip, contexts in sorted(int_profiles.items()):
                self.display_value_context_improved(ip, contexts)
                dest = self.prompt_mapping("Interface Profile", ip, ip)
                self.int_profile_mapping[ip] = dest

        # Path EPs
        path_eps = self.find_all_values(self.path_ep_columns)
        if path_eps:
            print(f"\n{'─' * 58}")
            print(f"[*] PATH EPs")
            print(f"{'─' * 58}")

            for path, contexts in sorted(path_eps.items()):
                self.display_value_context_improved(path, contexts)
                dest = self.prompt_mapping("Path EP", path, path)
                self.path_ep_mapping[path] = dest

        # Local AS
        local_as_values = self.find_all_values(self.local_as_columns)
        if local_as_values:
            print(f"\n{'─' * 58}")
            print(f"[*] LOCAL AS")
            print(f"{'─' * 58}")

            for las, contexts in sorted(local_as_values.items()):
                self.display_value_context_improved(las, contexts)
                dest = self.prompt_mapping("Local AS", las, las)
                self.local_as_mapping[las] = dest

    def collect_route_control_mappings(self):
        """Collecte les mappings Route Control pour tous les onglets"""
        print("\n" + "=" * 58)
        print("[>] CONVERSIONS ROUTE CONTROL")
        print("=" * 58)

        # Match Rules
        match_rules = self.find_all_values(self.match_rule_columns)
        if match_rules:
            print(f"\n{'─' * 58}")
            print(f"[*] MATCH RULES")
            print(f"{'─' * 58}")

            for mr, contexts in sorted(match_rules.items()):
                self.display_value_context_improved(mr, contexts)
                dest = self.prompt_mapping("Match Rule", mr, mr)
                self.match_rule_mapping[mr] = dest

        # Route Control Profiles
        rc_profiles = self.find_all_values(self.route_control_profile_columns)
        if rc_profiles:
            print(f"\n{'─' * 58}")
            print(f"[*] ROUTE CONTROL PROFILES")
            print(f"{'─' * 58}")

            for rcp, contexts in sorted(rc_profiles.items()):
                self.display_value_context_improved(rcp, contexts)
                dest = self.prompt_mapping("Route Control Profile", rcp, rcp)
                self.route_control_profile_mapping[rcp] = dest

        # Route Control Contexts
        rc_contexts = self.find_all_values(self.route_control_context_columns)
        if rc_contexts:
            print(f"\n{'─' * 58}")
            print(f"[*] ROUTE CONTROL CONTEXTS")
            print(f"{'─' * 58}")

            for rcc, contexts in sorted(rc_contexts.items()):
                self.display_value_context_improved(rcc, contexts)
                dest = self.prompt_mapping("Route Control Context", rcc, rcc)
                self.route_control_context_mapping[rcc] = dest

    def collect_bd_routing_option(self):
        """Demande si l'utilisateur veut desactiver le routage des BD"""
        print("\n" + "=" * 58)
        print("[>] OPTION ROUTAGE BD")
        print("=" * 58)
        print("    Desactiver le routage pour tous les Bridge Domains?")
        print("    (Mettra enable_routing = false dans l'onglet bd)")
        print("\n    Desactiver le routage? [o/N]: ", end="")

        response = input().strip().lower()
        self.disable_bd_routing = response in ['o', 'oui', 'y', 'yes']

        if self.disable_bd_routing:
            self.print_success("Le routage sera desactive pour tous les BD")
        else:
            self.print_info("Le routage ne sera pas modifie")

    def collect_vlan_descriptions(self):
        """Collecte les descriptions a modifier basees sur VLAN"""
        print("\n" + "=" * 58)
        print("[>] MODIFICATION DES DESCRIPTIONS PAR VLAN")
        print("=" * 58)
        print("    Voulez-vous modifier des descriptions basees sur VLAN?")
        print("\n    Modifier des descriptions? [o/N]: ", end="")

        response = input().strip().lower()
        if response not in ['o', 'oui', 'y', 'yes']:
            self.print_info("Aucune modification de description")
            return

        print("\n" + "-" * 58)
        print("    Format attendu: VLAN,RLXXXXX_XXX.XXX.XXX.XXX/XX_DESCRIPTION")
        print("    Exemple: 200,RL00001_10.1.1.1/24_Serveur_Web")
        print("-" * 58)
        print("    Collez vos lignes puis appuyez sur Entree (ligne vide pour terminer):\n")

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
            self.print_info("Aucune ligne fournie")
            return

        # Parser les lignes
        self.print_info(f"Analyse de {len(lines)} ligne(s)...")

        for line in lines:
            if ',' not in line:
                self.print_warning(f"Ligne ignoree (pas de virgule): {line[:50]}...")
                continue

            parts = line.split(',', 1)  # Split sur la premiere virgule seulement
            vlan_str = parts[0].strip()
            description = parts[1].strip() if len(parts) > 1 else ''

            try:
                vlan = int(vlan_str)
            except ValueError:
                self.print_warning(f"VLAN invalide: {vlan_str}")
                continue

            if not description:
                self.print_warning(f"Description vide pour VLAN {vlan}")
                continue

            self.vlan_descriptions.append((vlan, description))
            self.print_success(f"VLAN {vlan}: {description[:50]}{'...' if len(description) > 50 else ''}")

        self.print_info(f"{len(self.vlan_descriptions)} entree(s) a traiter")

    def collect_interface_config_mappings(self):
        """Collecte les mappings pour convertir Interface Profile -> Interface Config"""
        print("\n" + "=" * 58)
        print("[>] CONVERSION INTERFACE PROFILE -> INTERFACE CONFIG")
        print("=" * 58)

        # Verifier que les onglets existent
        if 'interface_policy_leaf_profile' not in self.excel_data:
            self.print_warning("Onglet 'interface_policy_leaf_profile' non trouve - etape ignoree")
            return

        if 'access_port_to_int_policy_leaf' not in self.excel_data:
            self.print_warning("Onglet 'access_port_to_int_policy_leaf' non trouve - etape ignoree")
            return

        # Demander si l'utilisateur veut faire cette conversion
        print("\n    Voulez-vous convertir les Interface Profiles vers interface_config? [o/N]: ", end="")
        choice = input().strip().lower()
        if choice not in ['o', 'oui', 'y', 'yes']:
            print("    -> Conversion interface_config ignoree")
            return

        profile_df = self.excel_data['interface_policy_leaf_profile']
        access_port_df = self.excel_data['access_port_to_int_policy_leaf']

        # 1. Extraire les interface_profile uniques
        interface_profiles = profile_df['interface_profile'].dropna().unique().tolist()
        self.print_info(f"Interface Profiles trouves: {len(interface_profiles)}")
        for ip in interface_profiles:
            self.print_item(ip)

        # 2. Mapping Interface Profile -> Node ID
        print("\n" + "-" * 58)
        print("[*] MAPPING INTERFACE PROFILE -> NODE ID")
        print("-" * 58)
        profile_to_node = {}
        for profile in interface_profiles:
            print(f"\n    '{profile}' -> Entrez le Node ID: ", end="")
            node_id = input().strip()
            if node_id:
                profile_to_node[profile] = node_id
            else:
                self.print_warning("Node ID vide, ce profile sera ignore")

        if not profile_to_node:
            self.print_error("Aucun mapping defini, conversion ignoree")
            return

        # 3. Demander le type d'interface
        print("\n" + "-" * 58)
        print("[*] TYPE D'INTERFACE")
        print("-" * 58)
        print("    [1] Access (switch_port) - DEFAUT")
        print("    [2] PC/VPC (pc_or_vpc)")
        print("\n    Choix [1]: ", end="")
        type_choice = input().strip()

        if type_choice == '2':
            interface_type = 'pc_or_vpc'
            print("    -> Type selectionne: pc_or_vpc")
        else:
            interface_type = 'switch_port'
            print("    -> Type selectionne: switch_port")

        # 4. Regrouper les interfaces par (interface_profile, policy_group)
        print("\n" + "-" * 58)
        print("[*] MAPPING DES INTERFACES PAR POLICY GROUP")
        print("-" * 58)

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
            self.print_error("Aucun groupe trouve!")
            return

        # 5. Pour chaque groupe, demander les nouvelles interfaces
        interface_mappings = []

        for (profile, policy_group), data in grouped.items():
            node_id = profile_to_node[profile]
            interfaces = data['interfaces']
            access_port_selector = data['access_port_selector']
            description = data['description']

            print(f"\n{'=' * 58}")
            print(f"    Interface Profile: {profile}")
            print(f"    Access Port Selector: {access_port_selector}")
            print(f"    Policy Group: {policy_group}")
            print(f"    Node destination: {node_id}")
            print(f"\n    Interfaces actuelles:")
            for iface in sorted(interfaces, key=lambda x: int(x.split('/')[1]) if '/' in x else 0):
                print(f"      - {iface}")

            print(f"\n    Entrez les nouvelles interfaces (separees par virgule)")
            print(f"    Format: 1/1, 1/2, 1/3 ou eth1/1, eth1/2")
            print(f"    [Entree vide = garder les memes interfaces]")
            print(f"\n    -> ", end="")

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

        # 6. Mapping des descriptions personnalisees
        if interface_mappings:
            print("\n" + "=" * 58)
            print("[*] MAPPING DES DESCRIPTIONS")
            print("=" * 58)
            print("\n    Voulez-vous ajouter des descriptions personnalisees? [o/N]: ", end="")
            desc_choice = input().strip().lower()

            if desc_choice in ['o', 'oui', 'y', 'yes']:
                # 6a. Mapping Node ID -> Nom de Leaf
                print("\n" + "-" * 58)
                print("[*] MAPPING NODE ID -> NOM DE LEAF")
                print("-" * 58)

                # Obtenir les node_id uniques
                unique_nodes = list(set([m['node'] for m in interface_mappings]))
                node_to_leaf = {}

                for node in sorted(unique_nodes):
                    print(f"\n    Node '{node}' -> Nom de Leaf (ex: SF22-127): ", end="")
                    leaf_name = input().strip().upper()
                    if leaf_name:
                        node_to_leaf[node] = leaf_name
                    else:
                        self.print_warning("Nom vide, ce node sera ignore pour les descriptions")

                if node_to_leaf:
                    # 6b. Demander la liste de descriptions
                    print("\n" + "-" * 58)
                    print("[*] LISTE DES DESCRIPTIONS")
                    print("-" * 58)
                    print("\n    Format attendu par ligne:")
                    print("    {NOM_LEAF} {ESPACE(S)} {NO_INTERFACE} {ESPACE(S)} {DESCRIPTION}")
                    print("    Exemple: SF22-127  3  VPZESX1011-onb2-p1-vmnic2")
                    print("\n    Collez votre liste puis appuyez 2 fois sur Entree pour terminer:")
                    print("-" * 58)

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

                    self.print_success(f"{len(description_lines)} lignes de description recues")

                    # 6c. Parser et associer les descriptions
                    descriptions_map = {}  # (node, interface) -> description formatee

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
                                # Description = tout apres le numero d'interface
                                desc_text = ' '.join(parts[2:]).upper()

                                # Formater: (T:SRV E:{AVANT-TIRET} I:{APRES-TIRET})
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

                    self.print_success(f"{updated_count} descriptions mises a jour")

        # 7. Creer le DataFrame et l'ajouter a l'Excel
        if interface_mappings:
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

            print("\n" + "=" * 58)
            self.print_success("INTERFACE_CONFIG GENERE")
            print("=" * 58)
            self.print_info(f"Lignes creees: {len(interface_mappings)}")
            self.print_info("Onglets sources supprimes: interface_policy_leaf_profile, access_port_to_int_policy_leaf")
            print(f"\n    Apercu:")
            print(interface_config_df.to_string(index=False, max_rows=10))
        else:
            self.print_warning("Aucune interface a creer - verifiez les mappings")

    # =========================================================================
    # APPLY CONVERSIONS
    # =========================================================================

    def apply_conversions(self):
        """Applique les conversions a tous les onglets"""
        print("\n" + "=" * 58)
        print("[>] APPLICATION DES CONVERSIONS")
        print("=" * 58)

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

            # Conversion Path EPs (tous les onglets)
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
                self.print_info(f"{sheet_name}: {sheet_changes} modifications")
                total_changes += sheet_changes

        self.print_info(f"Total: {total_changes} modifications appliquees")
        return total_changes

    def apply_vlan_descriptions(self):
        """Applique les modifications de descriptions basees sur VLAN"""
        if not self.vlan_descriptions:
            return 0

        print("\n" + "=" * 58)
        print("[>] APPLICATION DES DESCRIPTIONS PAR VLAN")
        print("=" * 58)

        total_changes = 0

        # Charger l'onglet vlan_pool_encap_block
        if 'vlan_pool_encap_block' not in self.excel_data:
            self.print_warning("Onglet vlan_pool_encap_block non trouve")
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
            self.print_warning("Colonnes block_start/block_end non trouvees")
            return 0

        for vlan, description in self.vlan_descriptions:
            self.print_info(f"Traitement VLAN {vlan}...")

            # Extraire le numero de circuit (tout avant le premier _)
            circuit = description.split('_')[0] if '_' in description else description
            bd_name = f"{circuit}-BD"
            epg_name = f"{circuit}-EPG"

            print(f"      Circuit: {circuit} -> BD: {bd_name}, EPG: {epg_name}")

            # 1. Verifier si VLAN est dans une plage et modifier vlan_pool_encap_block
            vlan_found = False
            for idx, row in vlan_df.iterrows():
                try:
                    start = int(row[start_col])
                    end = int(row[end_col])
                    if start <= vlan <= end:
                        vlan_found = True
                        if desc_col:
                            vlan_df.at[idx, desc_col] = description
                            self.print_success("vlan_pool_encap_block: description mise a jour")
                            total_changes += 1
                        break
                except (ValueError, TypeError):
                    continue

            if not vlan_found:
                self.print_warning(f"VLAN {vlan} non trouve dans les plages")
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
                        self.print_success(f"bd: description mise a jour pour {bd_name}")
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
                        self.print_success(f"epg: description mise a jour pour {epg_name}")
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
                        self.print_success(f"bd_subnet: description mise a jour pour {bd_name}")
                        total_changes += 1

        self.print_info(f"Total descriptions modifiees: {total_changes}")
        return total_changes

    def apply_bd_routing_disable(self):
        """Desactive le routage pour tous les BD"""
        if not self.disable_bd_routing:
            return 0

        if 'bd' not in self.excel_data:
            self.print_warning("Onglet bd non trouve")
            return 0

        bd_df = self.excel_data['bd']
        columns = [str(c).lower() for c in bd_df.columns]

        routing_col = None
        for col in ['enable_routing', 'unicast_route', 'routing']:
            if col in columns:
                routing_col = bd_df.columns[columns.index(col)]
                break

        if not routing_col:
            self.print_warning("Colonne enable_routing non trouvee dans l'onglet bd")
            return 0

        # Mettre toutes les valeurs a false
        count = len(bd_df)
        bd_df[routing_col] = 'false'

        self.print_success(f"Routage desactive pour {count} Bridge Domain(s)")
        return count

    def save_excel(self):
        """Sauvegarde le fichier Excel converti"""
        self.print_info(f"Sauvegarde du fichier: {self.output_excel}")

        with pd.ExcelWriter(self.output_excel, engine='openpyxl') as writer:
            for sheet_name, df in self.excel_data.items():
                df.to_excel(writer, sheet_name=sheet_name, index=False)

        self.print_success(f"Fichier sauvegarde: {self.output_excel}")

    def show_summary(self):
        """Affiche un resume des mappings configures"""
        print("\n" + "=" * 58)
        print("[>] RESUME DES CONVERSIONS")
        print("=" * 58)

        def show_mapping(title, mapping, indent=""):
            changes = {k: v for k, v in mapping.items() if k != v}
            if changes:
                print(f"{indent}{title}:")
                for src, dest in changes.items():
                    print(f"{indent}   {src} -> {dest}")
                return True
            return False

        # Global
        print("\n[*] GLOBAL:")
        has_global = False
        has_global |= show_mapping("Tenants", self.tenant_mapping, "    ")
        has_global |= show_mapping("VRFs", self.vrf_mapping, "    ")
        has_global |= show_mapping("Application Profiles", self.ap_mapping, "    ")
        if not has_global:
            print("    (aucun changement)")

        # BD to L3Out
        print("\n[*] BD TO L3OUT:")
        has_bd_l3out = show_mapping("L3Out", self.l3out_mapping, "    ")
        if not has_bd_l3out:
            print("    (aucun changement)")

        # L3Out unifie
        print("\n[*] L3OUT (tous les onglets):")
        has_l3out = False
        has_l3out |= show_mapping("Node IDs", self.node_id_mapping, "    ")
        has_l3out |= show_mapping("Node Profiles", self.node_profile_mapping, "    ")
        has_l3out |= show_mapping("Interface Profiles", self.int_profile_mapping, "    ")
        has_l3out |= show_mapping("Path EPs", self.path_ep_mapping, "    ")
        has_l3out |= show_mapping("Local AS", self.local_as_mapping, "    ")
        if not has_l3out:
            print("    (aucun changement)")

        # Route Control
        print("\n[*] ROUTE CONTROL:")
        has_rc = False
        has_rc |= show_mapping("Match Rules", self.match_rule_mapping, "    ")
        has_rc |= show_mapping("Route Control Profiles", self.route_control_profile_mapping, "    ")
        has_rc |= show_mapping("Route Control Contexts", self.route_control_context_mapping, "    ")
        if not has_rc:
            print("    (aucun changement)")

        # Options supplementaires
        print("\n[*] OPTIONS SUPPLEMENTAIRES:")
        if self.disable_bd_routing:
            print("    Routage BD: sera desactive pour tous les BD")
        else:
            print("    Routage BD: pas de modification")

        if self.vlan_descriptions:
            print(f"    Descriptions VLAN: {len(self.vlan_descriptions)} entree(s) a modifier")
            for vlan, desc in self.vlan_descriptions[:5]:  # Afficher les 5 premieres
                circuit = desc.split('_')[0] if '_' in desc else desc
                print(f"      - VLAN {vlan}: {circuit} -> {desc[:40]}{'...' if len(desc) > 40 else ''}")
            if len(self.vlan_descriptions) > 5:
                print(f"      ... et {len(self.vlan_descriptions) - 5} autre(s)")
        else:
            print("    Descriptions VLAN: pas de modification")

    # =========================================================================
    # WIZARD MODE
    # =========================================================================

    def run_wizard(self):
        """Execute le mode wizard interactif"""
        # Decouvrir les valeurs globales
        global_values = self.discover_global_values()

        # Afficher le resume des onglets
        self.print_info(f"Tenants: {len(global_values['tenants'])} | VRFs: {len(global_values['vrfs'])} | APs: {len(global_values['aps'])}")

        # 1. Collecte des mappings globaux (tenant -> auto VRF/AP)
        self.collect_global_mappings(global_values)

        # 2. Collecte des mappings BD to L3Out
        self.collect_bd_to_l3out_mappings()

        # 3. Collecte des mappings L3Out (UNIFIE - tous les onglets)
        self.collect_l3out_mappings()

        # 4. Collecte des mappings Route Control
        self.collect_route_control_mappings()

        # 5. Collecte option desactivation routage BD
        self.collect_bd_routing_option()

        # 6. Collecte des descriptions par VLAN
        self.collect_vlan_descriptions()

        # 7. Collecte des mappings Interface Profile -> Interface Config
        self.collect_interface_config_mappings()

        # Afficher le resume
        self.show_summary()

        # Confirmation
        print("\n" + "=" * 58)
        self.print_info(f"Fichier de sortie: {self.output_excel}")
        print("=" * 58)
        print("\n    Appliquer les conversions? [O/n]: ", end="")
        confirm = input().strip().lower()

        if confirm in ['n', 'no', 'non']:
            self.print_error("Conversion annulee")
            return

        # Appliquer
        self._apply_all()

    # =========================================================================
    # YAML MODE - Generation de template
    # =========================================================================

    def generate_yaml_template(self, output_file=None):
        """Genere un template YAML avec toutes les valeurs decouvertes"""
        if output_file is None:
            excel_path = Path(self.excel_file)
            output_file = str(excel_path.parent / f"{excel_path.stem}_template.yml")

        self.print_info("Decouverte des valeurs dans le fichier Excel...")

        # Decouvrir toutes les valeurs
        global_values = self.discover_global_values()

        # L3Out values
        node_ids = self.find_all_values(self.node_id_columns)
        node_profiles = self.find_all_values(self.node_profile_columns)
        exclude_leaf_sheets = ['interface_policy_leaf_profile', 'access_port_to_int_policy_leaf']
        int_profiles = self.find_all_values(self.int_profile_columns, exclude_sheets=exclude_leaf_sheets)
        path_eps = self.find_all_values(self.path_ep_columns)
        local_as_values = self.find_all_values(self.local_as_columns)

        # Route Control values
        match_rules = self.find_all_values(self.match_rule_columns)
        rc_profiles = self.find_all_values(self.route_control_profile_columns)
        rc_contexts = self.find_all_values(self.route_control_context_columns)

        # L3Out names from bd_to_l3out
        l3out_names = []
        if 'bd_to_l3out' in self.excel_data:
            df = self.excel_data['bd_to_l3out']
            columns_lower = [str(c).lower() for c in df.columns]
            for col_name in ['l3out', 'l3out_name']:
                if col_name in columns_lower:
                    idx = columns_lower.index(col_name)
                    real_col = df.columns[idx]
                    l3out_names = sorted([str(v) for v in df[real_col].dropna().unique() if v and str(v).strip()])
                    break

        # Construire le contexte pour chaque valeur
        def get_context_str(contexts):
            """Retourne la liste des onglets ou la valeur a ete trouvee"""
            sheets = [c['sheet_name'] for c in contexts]
            return ', '.join(sorted(set(sheets)))

        # Generer le YAML
        lines = []
        lines.append("# ============================================================")
        lines.append("# FABRIC CONVERTER - Template de conversion")
        lines.append(f"# Genere depuis: {os.path.basename(self.excel_file)}")
        lines.append("# ============================================================")
        lines.append("# Instructions:")
        lines.append("#   - Modifiez les champs 'destination' pour definir les conversions")
        lines.append("#   - Laissez destination = source pour ne pas modifier")
        lines.append(f"#   - Executez: python3 fabric_converter.py {os.path.basename(self.excel_file)}")
        lines.append("#     puis choisissez \"Charger un YAML\"")
        lines.append("# ============================================================")
        lines.append("")

        # --- GLOBAL ---
        lines.append("# --- GLOBAL: Tenants, VRFs, Application Profiles ---")

        lines.append("tenant_mapping:")
        if global_values['tenants']:
            for t in global_values['tenants']:
                lines.append(f'  - source: "{t}"')
                lines.append(f'    destination: "{t}"')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("vrf_mapping:")
        if global_values['vrfs']:
            for v in global_values['vrfs']:
                lines.append(f'  - source: "{v}"')
                lines.append(f'    destination: "{v}"')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("ap_mapping:")
        if global_values['aps']:
            for a in global_values['aps']:
                lines.append(f'  - source: "{a}"')
                lines.append(f'    destination: "{a}"')
        else:
            lines.append("  []")

        lines.append("")

        # --- BD TO L3OUT ---
        lines.append("# --- BD TO L3OUT ---")
        lines.append("l3out_mapping:")
        if l3out_names:
            for l in l3out_names:
                lines.append(f'  - source: "{l}"')
                lines.append(f'    destination: "{l}"')
        else:
            lines.append("  []")

        lines.append("")

        # --- L3OUT ---
        lines.append("# --- L3OUT: Node IDs, Profiles, Paths ---")
        lines.append("# (Valeurs trouvees dans TOUS les onglets L3Out: standard ET floating)")

        lines.append("node_id_mapping:")
        if node_ids:
            for nid, contexts in sorted(node_ids.items()):
                lines.append(f'  - source: "{nid}"')
                lines.append(f'    destination: "{nid}"')
                lines.append(f'    context: "{get_context_str(contexts)}"  # info seulement')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("node_profile_mapping:")
        if node_profiles:
            for np, contexts in sorted(node_profiles.items()):
                lines.append(f'  - source: "{np}"')
                lines.append(f'    destination: "{np}"')
                lines.append(f'    context: "{get_context_str(contexts)}"  # info seulement')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("interface_profile_mapping:")
        if int_profiles:
            for ip, contexts in sorted(int_profiles.items()):
                lines.append(f'  - source: "{ip}"')
                lines.append(f'    destination: "{ip}"')
                lines.append(f'    context: "{get_context_str(contexts)}"  # info seulement')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("path_ep_mapping:")
        if path_eps:
            for pe, contexts in sorted(path_eps.items()):
                lines.append(f'  - source: "{pe}"')
                lines.append(f'    destination: "{pe}"')
                lines.append(f'    context: "{get_context_str(contexts)}"  # info seulement')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("local_as_mapping:")
        if local_as_values:
            for las, contexts in sorted(local_as_values.items()):
                lines.append(f'  - source: "{las}"')
                lines.append(f'    destination: "{las}"')
                lines.append(f'    context: "{get_context_str(contexts)}"  # info seulement')
        else:
            lines.append("  []")

        lines.append("")

        # --- ROUTE CONTROL ---
        lines.append("# --- ROUTE CONTROL ---")
        lines.append("match_rule_mapping:")
        if match_rules:
            for mr, contexts in sorted(match_rules.items()):
                lines.append(f'  - source: "{mr}"')
                lines.append(f'    destination: "{mr}"')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("route_control_profile_mapping:")
        if rc_profiles:
            for rcp, contexts in sorted(rc_profiles.items()):
                lines.append(f'  - source: "{rcp}"')
                lines.append(f'    destination: "{rcp}"')
        else:
            lines.append("  []")

        lines.append("")
        lines.append("route_control_context_mapping:")
        if rc_contexts:
            for rcc, contexts in sorted(rc_contexts.items()):
                lines.append(f'  - source: "{rcc}"')
                lines.append(f'    destination: "{rcc}"')
        else:
            lines.append("  []")

        lines.append("")

        # --- OPTIONS ---
        lines.append("# --- OPTIONS ---")
        lines.append("options:")
        lines.append("  disable_bd_routing: false")

        lines.append("")

        # --- DESCRIPTIONS VLAN ---
        lines.append("# --- DESCRIPTIONS VLAN ---")
        lines.append("# Format: vlan,description")
        lines.append("# Exemple: 200,RL00001_10.1.1.1/24_Serveur_Web")
        lines.append("vlan_descriptions: []")

        lines.append("")

        # --- INTERFACE CONFIG ---
        lines.append("# --- INTERFACE CONFIG ---")
        lines.append("# Conversion Interface Profile -> interface_config")
        lines.append("interface_config:")
        lines.append("  enabled: false")
        lines.append('  interface_type: "switch_port"   # "switch_port" ou "pc_or_vpc"')
        lines.append("  profile_to_node:")
        lines.append("    # - profile: \"Interface_Profile_101\"")
        lines.append("    #   node_id: \"201\"")
        lines.append("  interface_mappings:")
        lines.append("    # - profile: \"Interface_Profile_101\"")
        lines.append("    #   policy_group: \"Server_Access_PG\"")
        lines.append('    #   interfaces: "1/1, 1/2, 1/3"')
        lines.append('    #   description: "(T:SRV E:HOST1 I:vmnic0)"')

        # Ecrire le fichier
        content = '\n'.join(lines) + '\n'
        with open(output_file, 'w', encoding='utf-8') as f:
            f.write(content)

        self.print_success(f"Template YAML genere: {output_file}")
        self.print_info(f"Tenants: {len(global_values['tenants'])} | VRFs: {len(global_values['vrfs'])} | APs: {len(global_values['aps'])}")
        self.print_info(f"Node IDs: {len(node_ids)} | Node Profiles: {len(node_profiles)} | Interface Profiles: {len(int_profiles)}")
        self.print_info(f"Path EPs: {len(path_eps)} | Local AS: {len(local_as_values)}")
        self.print_info(f"L3Out (bd_to_l3out): {len(l3out_names)}")
        self.print_info(f"Match Rules: {len(match_rules)} | RC Profiles: {len(rc_profiles)} | RC Contexts: {len(rc_contexts)}")

        return output_file

    # =========================================================================
    # YAML MODE - Chargement
    # =========================================================================

    def load_yaml_config(self, yaml_file):
        """Charge un fichier YAML de configuration et remplit les mappings"""
        self.print_info(f"Chargement du fichier YAML: {yaml_file}")

        if not os.path.exists(yaml_file):
            self.print_error(f"Fichier non trouve: {yaml_file}")
            sys.exit(1)

        with open(yaml_file, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        if not config:
            self.print_error("Fichier YAML vide ou invalide")
            sys.exit(1)

        # Parser chaque section
        def parse_mapping(section_name):
            """Parse une section de mapping source/destination"""
            mapping = {}
            section = config.get(section_name, [])
            if not section:
                return mapping
            for entry in section:
                src = str(entry.get('source', '')).strip()
                dest = str(entry.get('destination', '')).strip()
                if src and dest:
                    mapping[src] = dest
            return mapping

        # Global
        self.tenant_mapping = parse_mapping('tenant_mapping')
        self.vrf_mapping = parse_mapping('vrf_mapping')
        self.ap_mapping = parse_mapping('ap_mapping')

        # BD to L3Out
        self.l3out_mapping = parse_mapping('l3out_mapping')

        # L3Out
        self.node_id_mapping = parse_mapping('node_id_mapping')
        self.node_profile_mapping = parse_mapping('node_profile_mapping')
        self.int_profile_mapping = parse_mapping('interface_profile_mapping')
        self.path_ep_mapping = parse_mapping('path_ep_mapping')
        self.local_as_mapping = parse_mapping('local_as_mapping')

        # Route Control
        self.match_rule_mapping = parse_mapping('match_rule_mapping')
        self.route_control_profile_mapping = parse_mapping('route_control_profile_mapping')
        self.route_control_context_mapping = parse_mapping('route_control_context_mapping')

        # Options
        options = config.get('options', {})
        if options:
            self.disable_bd_routing = options.get('disable_bd_routing', False)

        # VLAN descriptions
        vlan_desc = config.get('vlan_descriptions', [])
        if vlan_desc:
            for entry in vlan_desc:
                if isinstance(entry, str) and ',' in entry:
                    parts = entry.split(',', 1)
                    try:
                        vlan = int(parts[0].strip())
                        desc = parts[1].strip()
                        self.vlan_descriptions.append((vlan, desc))
                    except (ValueError, IndexError):
                        pass
                elif isinstance(entry, dict):
                    vlan = entry.get('vlan')
                    desc = entry.get('description', '')
                    if vlan and desc:
                        try:
                            self.vlan_descriptions.append((int(vlan), str(desc)))
                        except (ValueError, TypeError):
                            pass

        # Interface config
        iface_config = config.get('interface_config', {})
        if iface_config and iface_config.get('enabled', False):
            self.interface_config_enabled = True
            self.interface_config_type = iface_config.get('interface_type', 'switch_port')

            profile_to_node = iface_config.get('profile_to_node', [])
            if profile_to_node:
                for entry in profile_to_node:
                    profile = entry.get('profile', '')
                    node_id = entry.get('node_id', '')
                    if profile and node_id:
                        self.interface_config_profile_to_node[profile] = str(node_id)

            mappings = iface_config.get('interface_mappings', [])
            if mappings:
                self.interface_config_mappings = mappings

        # Afficher le resume des mappings charges
        active_count = 0
        for mapping_dict in [self.tenant_mapping, self.vrf_mapping, self.ap_mapping,
                            self.l3out_mapping, self.node_id_mapping, self.node_profile_mapping,
                            self.int_profile_mapping, self.path_ep_mapping, self.local_as_mapping,
                            self.match_rule_mapping, self.route_control_profile_mapping,
                            self.route_control_context_mapping]:
            active_count += sum(1 for k, v in mapping_dict.items() if k != v)

        self.print_success(f"YAML charge: {active_count} mapping(s) actif(s) (source != destination)")

        if self.disable_bd_routing:
            self.print_info("Option: disable_bd_routing = true")
        if self.vlan_descriptions:
            self.print_info(f"Descriptions VLAN: {len(self.vlan_descriptions)} entree(s)")
        if self.interface_config_enabled:
            self.print_info(f"Interface config: active ({self.interface_config_type})")

    def apply_interface_config_from_yaml(self):
        """Applique la conversion interface_config depuis la config YAML"""
        if not self.interface_config_enabled:
            return

        if not self.interface_config_profile_to_node and not self.interface_config_mappings:
            self.print_warning("Interface config active mais aucun mapping defini")
            return

        self.print_info("Application de la conversion interface_config...")

        interface_type = self.interface_config_type
        interface_rows = []

        if self.interface_config_mappings:
            # Utiliser les mappings explicites du YAML
            for entry in self.interface_config_mappings:
                profile = entry.get('profile', '')
                policy_group = entry.get('policy_group', '')
                interfaces_str = entry.get('interfaces', '')
                description = entry.get('description', '')

                node_id = self.interface_config_profile_to_node.get(profile, '')
                if not node_id:
                    self.print_warning(f"Pas de node_id pour profile '{profile}', ignore")
                    continue

                # Parser les interfaces
                interfaces = [i.strip() for i in interfaces_str.split(',') if i.strip()]
                for iface in interfaces:
                    if iface.lower().startswith('eth'):
                        iface = iface[3:]
                    interface_rows.append({
                        'node': node_id,
                        'interface': iface,
                        'policy_group': policy_group,
                        'role': 'leaf',
                        'port_type': 'access',
                        'interface_type': interface_type,
                        'admin_state': 'up',
                        'description': description
                    })
        else:
            # Mode automatique: lire depuis les onglets Excel
            if 'access_port_to_int_policy_leaf' not in self.excel_data:
                self.print_warning("Onglet 'access_port_to_int_policy_leaf' non trouve")
                return

            access_port_df = self.excel_data['access_port_to_int_policy_leaf']

            for idx, row in access_port_df.iterrows():
                profile = str(row['interface_profile']) if pd.notna(row.get('interface_profile')) else ''
                policy_group = str(row['policy_group']) if pd.notna(row.get('policy_group')) else ''
                from_port = row.get('from_port', '')
                to_port = row.get('to_port', '')
                description = str(row.get('description', '')) if pd.notna(row.get('description', None)) else ''

                if not profile or not policy_group:
                    continue

                node_id = self.interface_config_profile_to_node.get(profile, '')
                if not node_id:
                    continue

                try:
                    from_p = int(float(from_port))
                    to_p = int(float(to_port))
                    for port in range(from_p, to_p + 1):
                        interface_rows.append({
                            'node': node_id,
                            'interface': f"1/{port}",
                            'policy_group': policy_group,
                            'role': 'leaf',
                            'port_type': 'access',
                            'interface_type': interface_type,
                            'admin_state': 'up',
                            'description': description
                        })
                except (ValueError, TypeError):
                    pass

        if interface_rows:
            interface_config_df = pd.DataFrame(interface_rows)
            columns_order = ['node', 'interface', 'policy_group', 'role', 'port_type',
                           'interface_type', 'admin_state', 'description']
            interface_config_df = interface_config_df[columns_order]

            self.excel_data['interface_config'] = interface_config_df

            if 'interface_policy_leaf_profile' in self.excel_data:
                del self.excel_data['interface_policy_leaf_profile']
            if 'access_port_to_int_policy_leaf' in self.excel_data:
                del self.excel_data['access_port_to_int_policy_leaf']

            self.print_success(f"interface_config genere: {len(interface_rows)} ligne(s)")
        else:
            self.print_warning("Aucune interface a creer depuis la config YAML")

    def run_yaml(self, yaml_file):
        """Execute le mode YAML: charge le fichier et applique les conversions"""
        self.load_yaml_config(yaml_file)

        # Afficher le resume
        self.show_summary()

        # Confirmation
        print("\n" + "=" * 58)
        self.print_info(f"Fichier de sortie: {self.output_excel}")
        print("=" * 58)
        print("\n    Appliquer les conversions? [O/n]: ", end="")
        confirm = input().strip().lower()

        if confirm in ['n', 'no', 'non']:
            self.print_error("Conversion annulee")
            return

        # Appliquer
        self._apply_all()

    # =========================================================================
    # APPLY ALL
    # =========================================================================

    def _apply_all(self):
        """Applique toutes les conversions et sauvegarde"""
        # Appliquer les conversions de mapping
        self.apply_conversions()

        # Appliquer les options supplementaires
        if self.disable_bd_routing:
            print("\n" + "=" * 58)
            print("[>] DESACTIVATION DU ROUTAGE BD")
            print("=" * 58)
            self.apply_bd_routing_disable()

        if self.vlan_descriptions:
            self.apply_vlan_descriptions()

        # Appliquer interface_config si active (mode YAML)
        if self.interface_config_enabled:
            self.apply_interface_config_from_yaml()

        # Sauvegarder
        self.save_excel()

        print("\n" + "=" * 58)
        self.print_success("CONVERSION TERMINEE")
        print("=" * 58)
        self.print_info(f"Fichier source:   {self.excel_file}")
        self.print_info(f"Fichier converti: {self.output_excel}")
        print("\n[+] Utilisez excel_to_csv_simple.py pour deployer sur la nouvelle fabric")

    # =========================================================================
    # MAIN RUN
    # =========================================================================

    def run(self):
        """Execution principale avec menu"""
        # Charger le fichier Excel
        self.load_excel()

        # Charger la liste d'extraction (optionnel)
        self.load_extraction_list()

        # Afficher le resume
        global_values = self.discover_global_values()
        self.print_info(f"Fichier charge: {os.path.basename(self.excel_file)} ({len(self.excel_data)} onglets)")
        self.print_info(f"Tenants: {len(global_values['tenants'])} | VRFs: {len(global_values['vrfs'])} | APs: {len(global_values['aps'])}")

        # Menu principal
        print("\n" + "=" * 58)
        print("    MODE DE CONVERSION")
        print("=" * 58)
        print("    [1] Wizard interactif (questions pas a pas)")
        print("    [2] Fichier YAML (template ou chargement)")
        print("\n    Choix [1]: ", end="")

        mode_choice = input().strip()

        if mode_choice == '2':
            # Sous-menu YAML
            print("\n" + "-" * 58)
            print("    MODE YAML")
            print("-" * 58)
            print("    [A] Generer un template YAML (decouverte automatique)")
            print("    [B] Charger un YAML existant (appliquer les conversions)")
            print("\n    Choix [A]: ", end="")

            yaml_choice = input().strip().upper()

            if yaml_choice == 'B':
                # Charger un YAML existant
                print("\n    Fichier YAML a charger: ", end="")
                yaml_file = input().strip()
                if not yaml_file:
                    self.print_error("Aucun fichier specifie")
                    return
                if not os.path.exists(yaml_file):
                    self.print_error(f"Fichier non trouve: {yaml_file}")
                    return
                self.run_yaml(yaml_file)
            else:
                # Generer un template
                print("\n    Nom du fichier template (Entree = auto): ", end="")
                output_file = input().strip()
                if output_file:
                    self.generate_yaml_template(output_file)
                else:
                    self.generate_yaml_template()
        else:
            # Mode Wizard
            self.run_wizard()


def main():
    print("")
    print("+=========================================================+")
    print("|           FABRIC CONVERTER - Migration ACI              |")
    print("+=========================================================+")
    print("")
    print("[+] Convertit une configuration ACI d'une fabric vers une autre")
    print("[*] Mapping automatique Tenant -> VRF -> AP (suffixes -TN, -VRF, -ANP)")
    print("[*] Mappings L3Out unifies (standard + floating)")
    print("[*] Mappings Route Control (match_rule, route_control_profile, route_control_context)")
    print("")

    # Demander le fichier Excel source
    print("    Fichier Excel source: ", end="")
    excel_file = input().strip()

    if not excel_file:
        print("[X] Aucun fichier specifie")
        sys.exit(1)

    # Ajouter .xlsx si manquant
    if not excel_file.endswith('.xlsx'):
        excel_file += '.xlsx'

    if not os.path.exists(excel_file):
        print(f"[X] Fichier non trouve: {excel_file}")
        sys.exit(1)

    # Lancer la conversion
    converter = FabricConverter(excel_file)
    converter.run()


if __name__ == "__main__":
    main()

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

        # Données Excel
        self.excel_data = {}  # Dict des DataFrames par onglet

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

    def collect_global_mappings(self, unique_values):
        """Collecte les mappings globaux (tenant → auto VRF/AP)"""
        # Tenants avec dérivation automatique VRF/AP
        if unique_values['tenants']:
            print("\n" + "=" * 60)
            print("🏢 CONVERSION DES TENANTS (avec VRF et AP automatiques)")
            print("=" * 60)
            print("Convention: XXXXX-TN → XXXXX-VRF, XXXXX-ANP")
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for tenant in unique_values['tenants']:
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
                    if src_vrf in unique_values['vrfs']:
                        self.vrf_mapping[src_vrf] = dest_vrf
                        print(f"      ↳ VRF auto: {src_vrf} → {dest_vrf}")

                    # Mapper AP: chercher src_base-ANP → dest_base-ANP
                    src_ap = f"{src_base}-ANP"
                    dest_ap = f"{dest_base}-ANP"
                    if src_ap in unique_values['aps']:
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
        print("(Appuyez sur Entrée pour garder la même valeur)")

        # Afficher le contexte pour chaque L3Out
        for l3out in unique_l3outs:
            # Trouver les BDs qui référencent ce L3Out
            mask = df[l3out_col] == l3out
            matching_rows = df[mask]

            print(f"\n   {'─' * 56}")
            print(f"   📍 L3Out: [{l3out}]")
            print(f"      ┌─ Onglet: bd_to_l3out")
            print(f"      │  Colonnes: {', '.join(str(h) for h in df.columns)}")

            # Afficher les BDs qui utilisent ce L3Out
            bd_list = matching_rows['bridge_domain'].tolist() if 'bridge_domain' in columns_lower else []
            tenant_list = matching_rows['tenant'].tolist() if 'tenant' in columns_lower else []

            if bd_list:
                for i, (tenant, bd) in enumerate(zip(tenant_list[:3], bd_list[:3])):
                    print(f"      │  BD {i+1}: {tenant}/{bd}")
                if len(bd_list) > 3:
                    print(f"      │  ... et {len(bd_list) - 3} autres BDs")

            print(f"      └─ Total: {len(matching_rows)} Bridge Domain(s) référencent ce L3Out")

            dest = self.prompt_mapping("L3Out", l3out, l3out)
            self.l3out_mapping[l3out] = dest

    def collect_l3out_mappings(self):
        """Collecte les mappings L3Out pour TOUS les onglets (unifié)"""
        print("\n" + "=" * 60)
        print("🔌 CONVERSIONS L3OUT (tous les onglets)")
        print("=" * 60)

        # Node IDs
        node_ids = self.find_all_values(self.node_id_columns)
        if node_ids:
            print(f"\n{'─' * 60}")
            print(f"🖥️  NODE IDs")
            print(f"{'─' * 60}")

            for node_id, contexts in sorted(node_ids.items()):
                self.display_value_context_improved(node_id, contexts)
                dest = self.prompt_mapping("Node ID", node_id, node_id)
                self.node_id_mapping[node_id] = dest

        # Node Profiles
        node_profiles = self.find_all_values(self.node_profile_columns)
        if node_profiles:
            print(f"\n{'─' * 60}")
            print(f"📋 NODE PROFILES")
            print(f"{'─' * 60}")

            for np, contexts in sorted(node_profiles.items()):
                self.display_value_context_improved(np, contexts)
                dest = self.prompt_mapping("Node Profile", np, np)
                self.node_profile_mapping[np] = dest

        # Interface Profiles (L3Out seulement - exclure les onglets Leaf Interface)
        exclude_leaf_sheets = ['interface_policy_leaf_profile', 'access_port_to_int_policy_leaf']
        int_profiles = self.find_all_values(self.int_profile_columns, exclude_sheets=exclude_leaf_sheets)
        if int_profiles:
            print(f"\n{'─' * 60}")
            print(f"🔌 INTERFACE PROFILES")
            print(f"{'─' * 60}")

            for ip, contexts in sorted(int_profiles.items()):
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

        # Match Rules
        match_rules = self.find_all_values(self.match_rule_columns)
        if match_rules:
            print(f"\n{'─' * 60}")
            print(f"📏 MATCH RULES")
            print(f"{'─' * 60}")

            for mr, contexts in sorted(match_rules.items()):
                self.display_value_context_improved(mr, contexts)
                dest = self.prompt_mapping("Match Rule", mr, mr)
                self.match_rule_mapping[mr] = dest

        # Route Control Profiles
        rc_profiles = self.find_all_values(self.route_control_profile_columns)
        if rc_profiles:
            print(f"\n{'─' * 60}")
            print(f"📋 ROUTE CONTROL PROFILES")
            print(f"{'─' * 60}")

            for rcp, contexts in sorted(rc_profiles.items()):
                self.display_value_context_improved(rcp, contexts)
                dest = self.prompt_mapping("Route Control Profile", rcp, rcp)
                self.route_control_profile_mapping[rcp] = dest

        # Route Control Contexts
        rc_contexts = self.find_all_values(self.route_control_context_columns)
        if rc_contexts:
            print(f"\n{'─' * 60}")
            print(f"🔀 ROUTE CONTROL CONTEXTS")
            print(f"{'─' * 60}")

            for rcc, contexts in sorted(rc_contexts.items()):
                self.display_value_context_improved(rcc, contexts)
                dest = self.prompt_mapping("Route Control Context", rcc, rcc)
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
            profile_to_node: Dict {interface_profile: node_id}
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
            print(f"\n✅ Policy Groups détectés automatiquement:")
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

        # 2. Mapping Node ID → Nom de Leaf
        print("\n" + "-" * 60)
        print("🏷️  MAPPING NODE ID → NOM DE LEAF")
        print("-" * 60)
        print("\n💡 Important pour grappes multi-serveurs (2, 4, 6, 8 leafs):")
        print("   Les leafs seront triées par nom pour déterminer petite/grosse")

        unique_nodes = list(set(profile_to_node.values()))
        node_to_leaf = {}

        for node in sorted(unique_nodes):
            print(f"\n   Node '{node}' → Nom de Leaf (ex: SF22-127): ", end="", flush=True)
            leaf_name = input().strip().upper()
            if leaf_name:
                node_to_leaf[node] = leaf_name
            else:
                print(f"      ⚠️  Nom vide, ce node sera ignoré")

        if not node_to_leaf:
            print("❌ Aucun mapping node → leaf défini")
            return None

        # Créer le mapping inverse: leaf_name → node_id
        leaf_to_node = {v: k for k, v in node_to_leaf.items()}

        # 3. Collecter les descriptions d'interfaces
        print("\n" + "-" * 60)
        print("📋 DESCRIPTIONS DES INTERFACES")
        print("-" * 60)
        print("\nFormat: LEAF_NAME  PORT_NUMBER  DESCRIPTION")
        print("Exemple: SF22-121  3  SERVER101-vmnic2")
        print("\n💡 Le mapping leaf ↔ node sera automatique:")
        print("   Plus petit nom de leaf = plus petit node_id")
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

        # 4. Parser les descriptions et extraire les interfaces
        parsed_interfaces = []
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

        # 5. Trier les leafs et créer le mapping automatique
        # Plus petit nom de leaf → plus petit node_id
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

        # 2. Mapping Interface Profile → Node ID
        print("\n" + "-" * 60)
        print("📍 MAPPING INTERFACE PROFILE → NODE ID")
        print("-" * 60)
        profile_to_node = {}
        for profile in interface_profiles:
            print(f"\n'{profile}' → Entrez le Node ID: ", end="", flush=True)
            node_id = input().strip()
            if node_id:
                profile_to_node[profile] = node_id
            else:
                print(f"   ⚠️  Node ID vide, ce profile sera ignoré")

        if not profile_to_node:
            print("❌ Aucun mapping défini, conversion ignorée")
            return

        # 3. Demander le type d'interface
        print("\n" + "-" * 60)
        print("🔧 TYPE D'INTERFACE")
        print("-" * 60)
        print("[1] Access (switch_port) - DÉFAUT")
        print("[2] PC/VPC (pc_or_vpc)")
        print("\nChoix [1]: ", end="", flush=True)
        type_choice = input().strip()

        if type_choice == '2':
            interface_type = 'pc_or_vpc'
            print("   → Type sélectionné: pc_or_vpc")
        else:
            interface_type = 'switch_port'
            print("   → Type sélectionné: switch_port")

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
            node_id = profile_to_node[profile]
            interfaces = data['interfaces']
            access_port_selector = data['access_port_selector']
            description = data['description']

            print(f"\n{'='*60}")
            print(f"📌 Interface Profile: {profile}")
            print(f"   Access Port Selector: {access_port_selector}")
            print(f"   Policy Group: {policy_group}")
            print(f"   Node destination: {node_id}")
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
                    print(f"\n   Node '{node}' → Nom de Leaf (ex: SF22-127): ", end="", flush=True)
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
                    print("   Exemple: SF22-127  3  VPZESX1011-onb2-p1-vmnic2")
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
        lines.append("# Exemple: 201 = SF22-127")
        lines.append("# (Utilise pour les descriptions personnalisees)")
        lines.append("")

        # INTERFACE_CONFIG_DESCRIPTIONS
        lines.append("[INTERFACE_CONFIG_DESCRIPTIONS]")
        lines.append("# Meme format que le wizard: NOM_LEAF  NO_INTERFACE  DESCRIPTION")
        lines.append("# Exemple: SF22-127  3  VPZESX1011-onb2-p1-vmnic2")
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
        """Exécution en mode wizard interactif (comportement V3 original)"""
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

        # 1. Collecte des mappings globaux (tenant → auto VRF/AP)
        self.collect_global_mappings(global_values)

        # 2. Collecte des mappings BD to L3Out
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
        print("\n💡 Utilisez excel_to_csv_simple.py pour déployer sur la nouvelle fabric")

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
        print("\n💡 Utilisez excel_to_csv_simple.py pour déployer sur la nouvelle fabric")

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

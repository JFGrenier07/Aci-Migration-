#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de conversion de fabric ACI - Version 3.
Convertit un fichier Excel d'une fabric source vers une fabric destination
en modifiant les paramètres clés (tenant, VRF, AP, node_id, path, etc.)

V3:
- Mapping automatique Tenant → VRF → AP (suffixes -TN, -VRF, -ANP)
- Mappings L3Out unifiés (pas de distinction standard/floating)
- Mappings Route Control (match_rule, route_control_profile, route_control_context)
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
        self.route_control_profile_columns = ['route_control_profile']
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

    def find_all_values(self, column_list):
        """
        Trouve les valeurs uniques dans TOUS les onglets.
        Retourne un dict avec les valeurs et leur contexte.
        """
        values_with_context = {}

        for sheet_name, df in self.excel_data.items():
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
            print(f"   {prompt_text} [{source_value}] → [{default}]: ", end="")
        else:
            print(f"   {prompt_text} [{source_value}] → : ", end="")

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

        # Interface Profiles
        int_profiles = self.find_all_values(self.int_profile_columns)
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
        print("\nDésactiver le routage? [o/N]: ", end="")

        response = input().strip().lower()
        self.disable_bd_routing = response in ['o', 'oui', 'y', 'yes']

        if self.disable_bd_routing:
            print("   ✅ Le routage sera désactivé pour tous les BD")
        else:
            print("   ℹ️  Le routage ne sera pas modifié")

    def collect_vlan_descriptions(self):
        """Collecte les descriptions à modifier basées sur VLAN"""
        print("\n" + "=" * 60)
        print("📝 MODIFICATION DES DESCRIPTIONS PAR VLAN")
        print("=" * 60)
        print("Voulez-vous modifier des descriptions basées sur VLAN?")
        print("\nModifier des descriptions? [o/N]: ", end="")

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

    def convert_to_interface_config(self):
        """Convertit interface_policy_leaf_profile + access_port_to_int_policy_leaf vers interface_config"""
        print("\n" + "=" * 60)
        print("🔌 CONVERSION VERS INTERFACE_CONFIG")
        print("=" * 60)

        # Vérifier que les onglets existent
        if 'interface_policy_leaf_profile' not in self.excel_data:
            print("❌ Onglet 'interface_policy_leaf_profile' non trouvé")
            return False

        if 'access_port_to_int_policy_leaf' not in self.excel_data:
            print("❌ Onglet 'access_port_to_int_policy_leaf' non trouvé")
            return False

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
            print(f"\n'{profile}' → Entrez le Node ID: ", end="")
            node_id = input().strip()
            if node_id:
                profile_to_node[profile] = node_id
            else:
                print(f"   ⚠️  Node ID vide, ce profile sera ignoré")

        if not profile_to_node:
            print("❌ Aucun mapping défini, abandon")
            return False

        # 3. Demander le type d'interface
        print("\n" + "-" * 60)
        print("🔧 TYPE D'INTERFACE")
        print("-" * 60)
        print("[1] Access (switch_port) - DÉFAUT")
        print("[2] PC/VPC (pc_or_vpc)")
        print("\nChoix [1]: ", end="")
        type_choice = input().strip()

        if type_choice == '2':
            interface_type = 'pc_or_vpc'
            print("   → Type sélectionné: pc_or_vpc")
        else:
            interface_type = 'switch_port'
            print("   → Type sélectionné: switch_port")

        # 4. Regrouper les interfaces par (interface_profile, policy_group)
        print("\n" + "-" * 60)
        print("🔄 MAPPING DES INTERFACES PAR POLICY GROUP")
        print("-" * 60)

        # Debug: afficher les données brutes
        print(f"\n   DEBUG: {len(access_port_df)} lignes dans access_port_to_int_policy_leaf")
        print(f"   DEBUG: Colonnes: {list(access_port_df.columns)}")
        print(f"   DEBUG: Profiles mappés: {list(profile_to_node.keys())}")

        # Créer un dictionnaire pour regrouper
        grouped = {}
        for idx, row in access_port_df.iterrows():
            # Accès sécurisé aux colonnes avec gestion des NaN
            profile = str(row['interface_profile']) if pd.notna(row['interface_profile']) else ''
            policy_group = str(row['policy_group']) if pd.notna(row['policy_group']) else ''
            from_port = row['from_port'] if pd.notna(row['from_port']) else ''
            to_port = row['to_port'] if pd.notna(row['to_port']) else ''
            description = str(row['description']) if pd.notna(row['description']) else ''

            if not profile or not policy_group:
                continue

            # Ignorer si le profile n'est pas dans le mapping
            if profile not in profile_to_node:
                continue

            key = (profile, policy_group)
            if key not in grouped:
                grouped[key] = {
                    'interfaces': [],
                    'description': description
                }

            # Ajouter les interfaces (gérer les ranges)
            try:
                from_p = int(float(from_port))
                to_p = int(float(to_port))
                for port in range(from_p, to_p + 1):
                    interface = f"1/{port}"
                    if interface not in grouped[key]['interfaces']:
                        grouped[key]['interfaces'].append(interface)
            except (ValueError, TypeError):
                print(f"   ⚠️  Impossible de parser ports: {from_port} - {to_port}")

        # Debug: afficher les groupes trouvés
        print(f"\n   DEBUG: {len(grouped)} groupes (profile, policy_group) trouvés")
        for key, data in grouped.items():
            print(f"   DEBUG: {key} → {len(data['interfaces'])} interfaces: {data['interfaces']}")

        if not grouped:
            print("\n❌ Aucun groupe trouvé! Vérifiez que les interface_profile correspondent.")
            return False

        # 5. Pour chaque groupe, demander les nouvelles interfaces
        interface_mappings = []

        for (profile, policy_group), data in grouped.items():
            node_id = profile_to_node[profile]
            interfaces = data['interfaces']
            description = data['description']

            print(f"\n{'='*60}")
            print(f"📌 Interface Profile: {profile}")
            print(f"   Policy Group: {policy_group}")
            print(f"   Node destination: {node_id}")
            print(f"\n   Interfaces actuelles:")
            for iface in sorted(interfaces, key=lambda x: int(x.split('/')[1]) if '/' in x else 0):
                print(f"      • {iface}")

            print(f"\n   Entrez les nouvelles interfaces (séparées par virgule)")
            print(f"   Format: 1/1, 1/2, 1/3 ou eth1/1, eth1/2")
            print(f"   [Entrée vide = garder les mêmes interfaces]")
            print(f"\n   → ", end="")

            new_interfaces_input = input().strip()

            if new_interfaces_input:
                # Parser les nouvelles interfaces
                new_interfaces = []
                for iface in new_interfaces_input.split(','):
                    iface = iface.strip()
                    # Enlever le préfixe eth si présent
                    if iface.lower().startswith('eth'):
                        iface = iface[3:]
                    if iface:
                        new_interfaces.append(iface)
            else:
                # Garder les mêmes interfaces
                new_interfaces = interfaces

            # Ajouter au mapping
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

        # 6. Créer le DataFrame et l'ajouter à l'Excel
        if interface_mappings:
            import pandas as pd
            interface_config_df = pd.DataFrame(interface_mappings)

            # Réordonner les colonnes
            columns_order = ['node', 'interface', 'policy_group', 'role', 'port_type',
                           'interface_type', 'admin_state', 'description']
            interface_config_df = interface_config_df[columns_order]

            # Ajouter ou remplacer l'onglet interface_config
            self.excel_data['interface_config'] = interface_config_df

            print("\n" + "=" * 60)
            print("✅ INTERFACE_CONFIG GÉNÉRÉ")
            print("=" * 60)
            print(f"   • Lignes créées: {len(interface_mappings)}")
            print(f"\n   Aperçu:")
            print(interface_config_df.to_string(index=False, max_rows=10))

            return True
        else:
            print("❌ Aucune interface à convertir")
            return False

    def run(self):
        """Exécution principale"""
        # Charger le fichier Excel
        self.load_excel()

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

        # 6. Collecte des descriptions par VLAN
        self.collect_vlan_descriptions()

        # Afficher le résumé
        self.show_summary()

        # Confirmation
        print("\n" + "=" * 60)
        print(f"📁 Fichier de sortie: {self.output_excel}")
        print("=" * 60)
        print("\nAppliquer les conversions? [O/n]: ", end="")
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


def main():
    print("=" * 60)
    print("🔄 FABRIC CONVERTER V4 - Migration ACI")
    print("=" * 60)
    print("Convertit une configuration ACI d'une fabric vers une autre\n")

    # Menu principal
    print("📋 MENU PRINCIPAL")
    print("-" * 60)
    print("[1] Conversion complète (Tenant, VRF, AP, L3Out, Route Control)")
    print("[2] Conversion Interface Profile → Interface Config")
    print("[Q] Quitter")
    print("\nChoix: ", end="")

    choice = input().strip().lower()

    if choice == 'q':
        print("👋 Au revoir!")
        sys.exit(0)

    if choice not in ['1', '2']:
        print("❌ Choix invalide")
        sys.exit(1)

    # Demander le fichier Excel source
    print("\n📁 Fichier Excel source: ", end="")
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

    # Créer le converter
    converter = FabricConverter(excel_file)

    if choice == '1':
        # Conversion complète standard
        converter.run()
    elif choice == '2':
        # Conversion Interface Profile → Interface Config
        converter.load_excel()

        if converter.convert_to_interface_config():
            # Demander confirmation pour sauvegarder
            print("\n" + "-" * 60)
            print(f"📁 Fichier de sortie: {converter.output_excel}")
            print("Sauvegarder le fichier? [O/n]: ", end="")
            confirm = input().strip().lower()

            if confirm not in ['n', 'no', 'non']:
                converter.save_excel()
                print("\n" + "=" * 60)
                print("✅ CONVERSION TERMINÉE!")
                print("=" * 60)
                print(f"📂 Fichier source: {converter.excel_file}")
                print(f"📁 Fichier converti: {converter.output_excel}")
            else:
                print("❌ Sauvegarde annulée")


if __name__ == "__main__":
    main()

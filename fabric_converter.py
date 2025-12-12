#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de conversion de fabric ACI.
Convertit un fichier Excel d'une fabric source vers une fabric destination
en modifiant les paramètres clés (tenant, VRF, AP, node_id, path, etc.)

Gère séparément les L3Out Standard et Floating.
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

        # Mappings de conversion - EPG (globaux)
        self.tenant_mapping = {}
        self.vrf_mapping = {}
        self.ap_mapping = {}
        self.l3out_mapping = {}  # Pour bd_to_l3out

        # Mappings L3Out STANDARD
        self.std_node_id_mapping = {}
        self.std_node_profile_mapping = {}
        self.std_int_profile_mapping = {}
        self.std_path_ep_mapping = {}
        self.std_local_as_mapping = {}

        # Mappings L3Out FLOATING
        self.flt_node_id_mapping = {}
        self.flt_node_profile_mapping = {}
        self.flt_int_profile_mapping = {}
        self.flt_path_ep_mapping = {}
        self.flt_local_as_mapping = {}

        # Colonnes à convertir par type
        self.tenant_columns = ['tenant']
        self.vrf_columns = ['vrf']
        self.ap_columns = ['ap']
        self.node_id_columns = ['node_id']
        self.node_profile_columns = ['node_profile', 'logical_node_profile', 'node_profile_name']
        self.int_profile_columns = ['interface_profile', 'logical_interface_profile', 'interface_profile_name']
        self.path_ep_columns = ['path_ep', 'path', 'interface', 'tDn']
        self.local_as_columns = ['local_as', 'local_asn', 'asn', 'local_as_number']

        # Classification des onglets
        self.floating_sheets = [
            'l3out_floating_svi',
            'l3out_floating_svi_path',
            'l3out_floating_svi_secondary_ip',
            'l3out_floating_svi_path_sec',
            'l3out_bgp_peer_floating'
        ]

        self.standard_l3out_sheets = [
            'l3out',
            'l3out_logical_node_profile',
            'l3out_logical_node',
            'l3out_logical_interface_profile',
            'l3out_interface',
            'l3out_bgp_protocol_profile',
            'l3out_bgp_peer',
            'l3out_extepg',
            'l3out_extsubnet',
            'l3out_extepg_to_contract',
            'l3out_logical_interface_vpc_mem'
        ]

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

    def is_floating_sheet(self, sheet_name):
        """Détermine si un onglet est de type floating"""
        return sheet_name in self.floating_sheets or 'floating' in sheet_name.lower()

    def is_standard_l3out_sheet(self, sheet_name):
        """Détermine si un onglet est de type L3Out standard"""
        return sheet_name in self.standard_l3out_sheets

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

    def find_values_by_sheet_type(self, column_list, sheet_type='standard'):
        """
        Trouve les valeurs uniques par type d'onglet (standard ou floating).
        Retourne un dict avec les valeurs et leur contexte.
        """
        values_with_context = {}

        for sheet_name, df in self.excel_data.items():
            # Filtrer par type d'onglet
            if sheet_type == 'floating' and not self.is_floating_sheet(sheet_name):
                continue
            if sheet_type == 'standard' and not self.is_standard_l3out_sheet(sheet_name):
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

        for ctx in contexts:
            print(f"      ┌─ Onglet: {ctx['sheet_name']}")
            # Afficher seulement les colonnes pertinentes (premières colonnes)
            headers_display = ctx['headers'][:8]
            if len(ctx['headers']) > 8:
                headers_display = headers_display + ['...']
            print(f"      │  Colonnes: {', '.join(str(h) for h in headers_display)}")
            # Afficher la ligne formatée
            row_display = self.format_row_display(ctx['row'], ctx['headers'])
            print(f"      └─ Données: {row_display}")

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
        """Collecte les mappings globaux (tenant, vrf, ap)"""
        # Tenants
        if unique_values['tenants']:
            print("\n" + "=" * 60)
            print("🏢 CONVERSION DES TENANTS")
            print("=" * 60)
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for tenant in unique_values['tenants']:
                dest = self.prompt_mapping("Tenant", tenant, tenant)
                self.tenant_mapping[tenant] = dest

        # VRFs
        if unique_values['vrfs']:
            print("\n" + "=" * 60)
            print("🌐 CONVERSION DES VRFs")
            print("=" * 60)
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for vrf in unique_values['vrfs']:
                dest = self.prompt_mapping("VRF", vrf, vrf)
                self.vrf_mapping[vrf] = dest

        # APs
        if unique_values['aps']:
            print("\n" + "=" * 60)
            print("📦 CONVERSION DES APPLICATION PROFILES")
            print("=" * 60)
            print("(Appuyez sur Entrée pour garder la même valeur)\n")

            for ap in unique_values['aps']:
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

    def collect_l3out_mappings(self, sheet_type, mapping_dict_prefix):
        """Collecte les mappings L3Out pour un type donné (standard ou floating)"""
        type_label = "STANDARD" if sheet_type == 'standard' else "FLOATING"
        type_emoji = "📐" if sheet_type == 'standard' else "🎈"

        print("\n" + "=" * 60)
        print(f"{type_emoji} L3OUT {type_label} - CONVERSIONS")
        print("=" * 60)

        # Node IDs
        node_ids = self.find_values_by_sheet_type(self.node_id_columns, sheet_type)
        if node_ids:
            print(f"\n{'─' * 60}")
            print(f"🖥️  NODE IDs ({type_label})")
            print(f"{'─' * 60}")

            mapping = getattr(self, f'{mapping_dict_prefix}_node_id_mapping')
            for node_id, contexts in sorted(node_ids.items()):
                self.display_value_context_improved(node_id, contexts)
                dest = self.prompt_mapping("Node ID", node_id, node_id)
                mapping[node_id] = dest

        # Node Profiles
        node_profiles = self.find_values_by_sheet_type(self.node_profile_columns, sheet_type)
        if node_profiles:
            print(f"\n{'─' * 60}")
            print(f"📋 NODE PROFILES ({type_label})")
            print(f"{'─' * 60}")

            mapping = getattr(self, f'{mapping_dict_prefix}_node_profile_mapping')
            for np, contexts in sorted(node_profiles.items()):
                self.display_value_context_improved(np, contexts)
                dest = self.prompt_mapping("Node Profile", np, np)
                mapping[np] = dest

        # Interface Profiles
        int_profiles = self.find_values_by_sheet_type(self.int_profile_columns, sheet_type)
        if int_profiles:
            print(f"\n{'─' * 60}")
            print(f"🔌 INTERFACE PROFILES ({type_label})")
            print(f"{'─' * 60}")

            mapping = getattr(self, f'{mapping_dict_prefix}_int_profile_mapping')
            for ip, contexts in sorted(int_profiles.items()):
                self.display_value_context_improved(ip, contexts)
                dest = self.prompt_mapping("Interface Profile", ip, ip)
                mapping[ip] = dest

        # Path EPs
        path_eps = self.find_values_by_sheet_type(self.path_ep_columns, sheet_type)
        if path_eps:
            print(f"\n{'─' * 60}")
            print(f"🛤️  PATH EPs ({type_label})")
            print(f"{'─' * 60}")

            mapping = getattr(self, f'{mapping_dict_prefix}_path_ep_mapping')
            for path, contexts in sorted(path_eps.items()):
                self.display_value_context_improved(path, contexts)
                dest = self.prompt_mapping("Path EP", path, path)
                mapping[path] = dest

        # Local AS
        local_as_values = self.find_values_by_sheet_type(self.local_as_columns, sheet_type)
        if local_as_values:
            print(f"\n{'─' * 60}")
            print(f"🔢 LOCAL AS ({type_label})")
            print(f"{'─' * 60}")

            mapping = getattr(self, f'{mapping_dict_prefix}_local_as_mapping')
            for las, contexts in sorted(local_as_values.items()):
                self.display_value_context_improved(las, contexts)
                dest = self.prompt_mapping("Local AS", las, las)
                mapping[las] = dest

    def apply_conversions(self):
        """Applique les conversions à tous les onglets"""
        print("\n" + "=" * 60)
        print("⚙️  APPLICATION DES CONVERSIONS")
        print("=" * 60)

        total_changes = 0

        for sheet_name, df in self.excel_data.items():
            sheet_changes = 0
            columns = [str(c).lower() for c in df.columns]

            # Déterminer quel mapping utiliser pour cet onglet
            is_floating = self.is_floating_sheet(sheet_name)

            # Conversion Tenants (global)
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

            # Conversion VRFs (global)
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

            # Conversion APs (global)
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

            # Sélectionner les mappings selon le type d'onglet
            if is_floating:
                node_id_map = self.flt_node_id_mapping
                np_map = self.flt_node_profile_mapping
                ip_map = self.flt_int_profile_mapping
                path_map = self.flt_path_ep_mapping
                las_map = self.flt_local_as_mapping
            else:
                node_id_map = self.std_node_id_mapping
                np_map = self.std_node_profile_mapping
                ip_map = self.std_int_profile_mapping
                path_map = self.std_path_ep_mapping
                las_map = self.std_local_as_mapping

            # Conversion Node IDs
            for col in self.node_id_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in node_id_map.items():
                        if src != dest:
                            mask = df[real_col].astype(str).str.strip() == str(src).strip()
                            count = mask.sum()
                            if count > 0:
                                try:
                                    df.loc[mask, real_col] = int(dest)
                                except ValueError:
                                    df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Node Profiles
            for col in self.node_profile_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in np_map.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Interface Profiles
            for col in self.int_profile_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in ip_map.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Path EPs
            for col in self.path_ep_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in path_map.items():
                        if src != dest:
                            mask = df[real_col] == src
                            count = mask.sum()
                            if count > 0:
                                df.loc[mask, real_col] = dest
                                sheet_changes += count

            # Conversion Local AS
            for col in self.local_as_columns:
                if col in columns:
                    idx = columns.index(col)
                    real_col = df.columns[idx]
                    for src, dest in las_map.items():
                        if src != dest:
                            mask = df[real_col].astype(str) == src
                            count = mask.sum()
                            if count > 0:
                                try:
                                    df.loc[mask, real_col] = int(dest)
                                except ValueError:
                                    df.loc[mask, real_col] = dest
                                sheet_changes += count

            if sheet_changes > 0:
                type_indicator = "🎈" if is_floating else "📐"
                print(f"   {type_indicator} {sheet_name}: {sheet_changes} modifications")
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

        # Standard L3Out
        print("\n📐 L3OUT STANDARD:")
        has_std = False
        has_std |= show_mapping("Node IDs", self.std_node_id_mapping, "   ")
        has_std |= show_mapping("Node Profiles", self.std_node_profile_mapping, "   ")
        has_std |= show_mapping("Interface Profiles", self.std_int_profile_mapping, "   ")
        has_std |= show_mapping("Path EPs", self.std_path_ep_mapping, "   ")
        has_std |= show_mapping("Local AS", self.std_local_as_mapping, "   ")
        if not has_std:
            print("   (aucun changement)")

        # Floating L3Out
        print("\n🎈 L3OUT FLOATING:")
        has_flt = False
        has_flt |= show_mapping("Node IDs", self.flt_node_id_mapping, "   ")
        has_flt |= show_mapping("Node Profiles", self.flt_node_profile_mapping, "   ")
        has_flt |= show_mapping("Interface Profiles", self.flt_int_profile_mapping, "   ")
        has_flt |= show_mapping("Path EPs", self.flt_path_ep_mapping, "   ")
        has_flt |= show_mapping("Local AS", self.flt_local_as_mapping, "   ")
        if not has_flt:
            print("   (aucun changement)")

    def run(self):
        """Exécution principale"""
        # Charger le fichier Excel
        self.load_excel()

        # Charger la liste d'extraction (optionnel)
        self.load_extraction_list()

        # Découvrir les valeurs globales
        global_values = self.discover_global_values()

        # Afficher le résumé des onglets
        std_sheets = [s for s in self.excel_data.keys() if self.is_standard_l3out_sheet(s)]
        flt_sheets = [s for s in self.excel_data.keys() if self.is_floating_sheet(s)]
        other_sheets = [s for s in self.excel_data.keys()
                       if not self.is_standard_l3out_sheet(s) and not self.is_floating_sheet(s)]

        print("\n📊 Analyse du fichier Excel:")
        print(f"   • Tenants: {len(global_values['tenants'])}")
        print(f"   • VRFs: {len(global_values['vrfs'])}")
        print(f"   • Application Profiles: {len(global_values['aps'])}")
        print(f"   • Onglets L3Out Standard: {len(std_sheets)}")
        print(f"   • Onglets L3Out Floating: {len(flt_sheets)}")
        print(f"   • Autres onglets: {len(other_sheets)}")

        # 1. Collecte des mappings globaux
        self.collect_global_mappings(global_values)

        # 2. Collecte des mappings BD to L3Out
        self.collect_bd_to_l3out_mappings()

        # 3. Collecte des mappings L3Out STANDARD
        if std_sheets:
            self.collect_l3out_mappings('standard', 'std')

        # 4. Collecte des mappings L3Out FLOATING
        if flt_sheets:
            self.collect_l3out_mappings('floating', 'flt')

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
    print("🔄 FABRIC CONVERTER - Migration ACI")
    print("=" * 60)
    print("Convertit une configuration ACI d'une fabric vers une autre")
    print("Gère séparément les L3Out Standard et Floating\n")

    # Demander le fichier Excel source
    print("📁 Fichier Excel source: ", end="")
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

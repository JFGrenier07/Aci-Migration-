#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Diagnostic Ciblé: Trouver l'association BD→L3Out pour un tenant/BD spécifique
"""

import json
import sys
import os
import tarfile
import tempfile
import glob

def load_json_from_file(file_path):
    """Charger JSON depuis .json ou .tar.gz"""
    temp_dir = None

    if file_path.endswith('.tar.gz') or file_path.endswith('.tgz'):
        print("📦 Extraction du tar.gz...")
        temp_dir = tempfile.mkdtemp(prefix='aci_diag_')

        with tarfile.open(file_path, 'r:gz') as tar:
            tar.extractall(path=temp_dir)

        json_pattern = os.path.join(temp_dir, '*_1.json')
        json_files = glob.glob(json_pattern)

        if not json_files:
            json_pattern = os.path.join(temp_dir, '*.json')
            json_files = glob.glob(json_pattern)
            json_files = [f for f in json_files if not f.endswith('.md5')]

        if not json_files:
            raise Exception("Aucun JSON trouvé dans le tar.gz")

        json_file = json_files[0]
        print(f"✅ JSON trouvé: {os.path.basename(json_file)}")

        with open(json_file, 'r') as f:
            data = json.load(f)

        return data, temp_dir
    else:
        print("📄 Chargement du fichier JSON...")
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data, None

def find_objects_recursive(data, obj_class, results=None):
    """Chercher récursivement un type d'objet"""
    if results is None:
        results = []

    if isinstance(data, dict):
        if obj_class in data:
            results.append(data[obj_class])
        for value in data.values():
            find_objects_recursive(value, obj_class, results)
    elif isinstance(data, list):
        for item in data:
            find_objects_recursive(item, obj_class, results)

    return results

def extract_tenant_from_dn(dn):
    """Extraire le tenant depuis le DN"""
    if '/tn-' in dn:
        try:
            tenant = dn.split('/tn-')[1].split('/')[0]
            return tenant
        except:
            return None
    return None

def main():
    print("=" * 80)
    print("🎯 DIAGNOSTIC CIBLÉ: BD→L3Out Association")
    print("=" * 80)

    # 1. Demander le fichier
    print("\n📂 FICHIER BACKUP")
    print("-" * 80)
    if len(sys.argv) >= 2:
        json_file = sys.argv[1]
    else:
        json_file = input("Chemin du fichier .tar.gz ou .json: ").strip()
        if not json_file:
            print("❌ Erreur: Chemin requis")
            sys.exit(1)

    if not os.path.exists(json_file):
        print(f"❌ Erreur: Fichier introuvable: {json_file}")
        sys.exit(1)

    # 2. Charger le JSON
    print(f"\n📥 Chargement: {json_file}")
    temp_dir = None
    try:
        aci_data, temp_dir = load_json_from_file(json_file)
        print("✅ JSON chargé avec succès")
    except Exception as e:
        print(f"❌ Erreur chargement: {e}")
        sys.exit(1)

    # 3. Demander le tenant
    print("\n" + "=" * 80)
    print("🏢 TENANT")
    print("-" * 80)
    if len(sys.argv) >= 3:
        target_tenant = sys.argv[2]
    else:
        # Lister les tenants disponibles via fvTenant (pas via DN)
        tenant_names = set()
        all_tenants = find_objects_recursive(aci_data, 'fvTenant')
        for tenant_obj in all_tenants:
            tenant_name = tenant_obj.get('attributes', {}).get('name', '')
            if tenant_name:
                tenant_names.add(tenant_name)

        if tenant_names:
            print(f"Tenants disponibles ({len(tenant_names)}):")
            for t in sorted(tenant_names):
                print(f"  • {t}")

        target_tenant = input("\nNom du tenant: ").strip()
        if not target_tenant:
            print("❌ Erreur: Tenant requis")
            sys.exit(1)

    # 4. Demander le Bridge Domain
    print("\n" + "=" * 80)
    print("🌉 BRIDGE DOMAIN")
    print("-" * 80)
    if len(sys.argv) >= 4:
        target_bd = sys.argv[3]
    else:
        # Lister les BDs du tenant via fvTenant
        tenant_bds = []
        all_tenants = find_objects_recursive(aci_data, 'fvTenant')

        for tenant_obj in all_tenants:
            tenant_name = tenant_obj.get('attributes', {}).get('name', '')
            if tenant_name == target_tenant:
                tenant_children = tenant_obj.get('children', [])
                for child in tenant_children:
                    if 'fvBD' in child:
                        bd_name = child['fvBD'].get('attributes', {}).get('name', '')
                        if bd_name:
                            tenant_bds.append(bd_name)
                break

        if tenant_bds:
            print(f"Bridge Domains dans '{target_tenant}' ({len(tenant_bds)}):")
            for bd in sorted(tenant_bds):
                print(f"  • {bd}")

        target_bd = input(f"\nNom du Bridge Domain: ").strip()
        if not target_bd:
            print("❌ Erreur: Bridge Domain requis")
            sys.exit(1)

    # 5. Chercher le BD spécifique via fvTenant
    print("\n" + "=" * 80)
    print(f"🔍 RECHERCHE: {target_tenant}/{target_bd}")
    print("=" * 80)

    # Nouvelle approche: chercher via fvTenant au lieu du DN
    all_tenants = find_objects_recursive(aci_data, 'fvTenant')
    found_bd = None
    found_tenant_obj = None

    print(f"\n📊 Nombre de tenants trouvés: {len(all_tenants)}")

    for tenant_obj in all_tenants:
        tenant_attr = tenant_obj.get('attributes', {})
        tenant_name = tenant_attr.get('name', '')

        if tenant_name == target_tenant:
            found_tenant_obj = tenant_obj
            print(f"✅ Tenant trouvé: {tenant_name}")

            # Chercher dans les children du tenant
            tenant_children = tenant_obj.get('children', [])
            print(f"   Children du tenant: {len(tenant_children)}")

            for child in tenant_children:
                if 'fvBD' in child:
                    bd_obj = child['fvBD']
                    bd_name = bd_obj.get('attributes', {}).get('name', '')

                    if bd_name == target_bd:
                        found_bd = bd_obj
                        print(f"✅ Bridge Domain trouvé: {bd_name}")
                        break

            if found_bd:
                break

    if not found_bd:
        print(f"\n❌ Bridge Domain introuvable: {target_tenant}/{target_bd}")
        if found_tenant_obj:
            print(f"\n🔍 Le tenant '{target_tenant}' existe, mais le BD '{target_bd}' n'a pas été trouvé")
            print("\n💡 BDs disponibles dans ce tenant:")
            tenant_children = found_tenant_obj.get('children', [])
            bd_names = []
            for child in tenant_children:
                if 'fvBD' in child:
                    bd_name = child['fvBD'].get('attributes', {}).get('name', '')
                    if bd_name:
                        bd_names.append(bd_name)
            for bd_name in sorted(bd_names):
                print(f"   • {bd_name}")
        else:
            print(f"\n🔍 Le tenant '{target_tenant}' n'existe pas")
        sys.exit(1)

    bd_attr = found_bd.get('attributes', {})
    print(f"\n✅ Bridge Domain trouvé!")
    print(f"   Nom: {bd_attr.get('name', 'N/A')}")
    print(f"   DN: {bd_attr.get('dn', '(vide)')}")

    # 6. Chercher les L3Outs associés
    print("\n" + "=" * 80)
    print("🔗 ASSOCIATIONS BD→L3Out")
    print("=" * 80)

    bd_children = found_bd.get('children', [])
    l3outs_found = []

    print(f"\nNombre de children dans le BD: {len(bd_children)}")

    for i, child in enumerate(bd_children):
        if 'fvRsBDToOut' in child:
            rs_attr = child['fvRsBDToOut'].get('attributes', {})
            l3out_name = rs_attr.get('tnL3extOutName', '')
            rs_dn = rs_attr.get('dn', '')

            l3outs_found.append({
                'l3out': l3out_name,
                'dn': rs_dn,
                'index': i
            })

    # 7. Afficher les résultats
    if len(l3outs_found) == 0:
        print("\n❌ Aucun L3Out associé à ce Bridge Domain")
        print("\n🔍 Vérifications:")
        print("   1. Le BD est-il bien associé à un L3Out dans l'APIC?")
        print("   2. Le backup contient-il les relations complètes?")
        print(f"\n📊 Types de children trouvés dans le BD:")
        child_types = {}
        for child in bd_children:
            for key in child.keys():
                child_types[key] = child_types.get(key, 0) + 1
        for ctype, count in sorted(child_types.items()):
            print(f"   • {ctype}: {count}")
    else:
        print(f"\n✅ {len(l3outs_found)} L3Out(s) associé(s):")
        print("\n" + "-" * 80)
        for assoc in l3outs_found:
            print(f"\n🔹 L3Out: {assoc['l3out']}")
            print(f"   Position: children[{assoc['index']}]")
            print(f"   DN: '{assoc['dn']}'")
            if not assoc['dn']:
                print(f"   ⚠️  DN vide (normal pour certains backups)")

        print("\n" + "-" * 80)
        print("\n📋 RÉSUMÉ:")
        print(f"   Tenant: {target_tenant}")
        print(f"   Bridge Domain: {target_bd}")
        print(f"   L3Outs associés:")
        for assoc in l3outs_found:
            print(f"      → {assoc['l3out']}")

        print("\n✅ ASSOCIATION TROUVÉE!")

    # Cleanup
    if temp_dir and os.path.exists(temp_dir):
        import shutil
        shutil.rmtree(temp_dir)

    print("\n" + "=" * 80)
    print("✅ DIAGNOSTIC TERMINÉ")
    print("=" * 80)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script de Diagnostic: BD→L3Out Detection
Analyse pourquoi les relations BD→L3Out ne sont pas détectées
"""

import json
import sys
import os
import tarfile
import tempfile
import glob

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

def load_json_from_file(file_path):
    """
    Charger le JSON depuis un fichier .json ou .tar.gz
    Retourne: (data, temp_dir)
    temp_dir est None si pas de tar.gz, sinon doit être nettoyé après utilisation
    """
    temp_dir = None

    # Cas 1: Fichier .tar.gz (backup APIC)
    if file_path.endswith('.tar.gz'):
        print("📦 Détection d'un fichier tar.gz (backup APIC)")

        # Créer un répertoire temporaire
        temp_dir = tempfile.mkdtemp(prefix='aci_diagnostic_')
        print(f"📂 Extraction dans: {temp_dir}")

        try:
            # Extraire le tar.gz
            with tarfile.open(file_path, 'r:gz') as tar:
                tar.extractall(path=temp_dir)

            # Chercher le fichier JSON principal (pattern: *_1.json)
            json_pattern = os.path.join(temp_dir, '*_1.json')
            json_files = glob.glob(json_pattern)

            if not json_files:
                # Essayer de trouver n'importe quel .json
                json_pattern = os.path.join(temp_dir, '*.json')
                json_files = glob.glob(json_pattern)
                # Exclure les fichiers .md5
                json_files = [f for f in json_files if not f.endswith('.md5')]

            if not json_files:
                raise Exception("Aucun fichier JSON trouvé dans le tar.gz")

            json_file = json_files[0]
            print(f"✅ Fichier JSON trouvé: {os.path.basename(json_file)}")

            # Charger le JSON
            with open(json_file, 'r') as f:
                data = json.load(f)

            return data, temp_dir

        except Exception as e:
            # Nettoyer le répertoire temporaire en cas d'erreur
            if temp_dir and os.path.exists(temp_dir):
                import shutil
                shutil.rmtree(temp_dir)
            raise Exception(f"Erreur extraction tar.gz: {e}")

    # Cas 2: Fichier .json direct
    else:
        print("📄 Détection d'un fichier JSON")
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data, None

def main():
    print("=" * 80)
    print("🔍 DIAGNOSTIC BD→L3Out - Détection des relations")
    print("=" * 80)

    # Demander le chemin du fichier JSON (comme Mode 2 du script migration)
    if len(sys.argv) >= 2:
        json_file = sys.argv[1]
    else:
        print("\n📦 BACKUP JSON (fichier local)")
        print("-" * 80)
        json_file = input("\n📂 Chemin du fichier JSON backup: ").strip()

        if not json_file:
            print("❌ Erreur: Chemin de fichier requis")
            sys.exit(1)

    # Vérifier que le fichier existe
    if not os.path.exists(json_file):
        print(f"❌ Erreur: Fichier introuvable: {json_file}")
        sys.exit(1)

    # Charger le JSON (supporte .json et .tar.gz)
    print(f"\n📂 Chargement: {json_file}")
    temp_dir = None
    try:
        aci_data, temp_dir = load_json_from_file(json_file)
        print("✅ JSON chargé avec succès")
    except Exception as e:
        print(f"❌ Erreur chargement JSON: {e}")
        sys.exit(1)

    # Trouver tous les BDs
    print("\n" + "=" * 80)
    print("📊 ÉTAPE 1: Chercher tous les Bridge Domains (fvBD)")
    print("=" * 80)

    all_bds = find_objects_recursive(aci_data, 'fvBD')
    print(f"\n✅ Nombre total de BDs dans le fabric: {len(all_bds)}")

    if len(all_bds) == 0:
        print("❌ PROBLÈME: Aucun BD trouvé dans le JSON!")
        sys.exit(1)

    # Analyser chaque BD
    bd_with_l3out = []
    bd_without_l3out = []
    total_relations = 0

    print("\n" + "=" * 80)
    print("📊 ÉTAPE 2: Analyser chaque BD pour trouver fvRsBDToOut")
    print("=" * 80)

    for bd_obj in all_bds:
        bd_attr = bd_obj.get('attributes', {})
        bd_dn = bd_attr.get('dn', '')
        bd_name = bd_attr.get('name', '')
        tenant = extract_tenant_from_dn(bd_dn)

        if not tenant or not bd_name:
            continue

        # Chercher les children
        bd_children = bd_obj.get('children', [])

        # Chercher fvRsBDToOut dans les children
        l3outs_found = []
        for child in bd_children:
            if 'fvRsBDToOut' in child:
                l3out_name = child['fvRsBDToOut']['attributes'].get('tnL3extOutName', '')
                if l3out_name:
                    l3outs_found.append(l3out_name)
                    total_relations += 1

        if l3outs_found:
            bd_with_l3out.append({
                'tenant': tenant,
                'bd': bd_name,
                'l3outs': l3outs_found,
                'count': len(l3outs_found)
            })
        else:
            bd_without_l3out.append({
                'tenant': tenant,
                'bd': bd_name
            })

    # Afficher les résultats
    print(f"\n✅ BDs AVEC L3Out: {len(bd_with_l3out)}")
    print(f"⚪ BDs SANS L3Out: {len(bd_without_l3out)}")
    print(f"📊 Total relations BD→L3Out: {total_relations}")

    if len(bd_with_l3out) > 0:
        print("\n" + "=" * 80)
        print("📋 DÉTAIL DES BDs AVEC L3Out")
        print("=" * 80)

        for bd_info in bd_with_l3out:
            print(f"\n🔹 {bd_info['tenant']}/{bd_info['bd']}")
            print(f"   L3Outs associés ({bd_info['count']}):")
            for l3out in bd_info['l3outs']:
                print(f"      → {l3out}")

    if len(bd_without_l3out) > 0 and len(bd_without_l3out) <= 10:
        print("\n" + "=" * 80)
        print("📋 BDs SANS L3Out (premiers 10)")
        print("=" * 80)

        for bd_info in bd_without_l3out[:10]:
            print(f"   • {bd_info['tenant']}/{bd_info['bd']}")

    # Diagnostic des problèmes potentiels
    print("\n" + "=" * 80)
    print("🔧 DIAGNOSTIC DES PROBLÈMES POTENTIELS")
    print("=" * 80)

    if total_relations == 0:
        print("\n❌ PROBLÈME: Aucune relation BD→L3Out détectée!")
        print("\n🔍 Vérifications à faire:")
        print("   1. Les L3Outs existent-ils dans l'APIC?")
        print("   2. Les BDs sont-ils bien associés aux L3Outs dans l'APIC?")
        print("   3. Le JSON contient-il bien les objets fvRsBDToOut?")

        # Chercher si des fvRsBDToOut existent quelque part
        all_bd_to_out = find_objects_recursive(aci_data, 'fvRsBDToOut')
        print(f"\n   📊 Objets fvRsBDToOut trouvés dans tout le JSON: {len(all_bd_to_out)}")

        if len(all_bd_to_out) > 0:
            print("\n   ⚠️  Des fvRsBDToOut existent mais ne sont pas détectés comme children des BDs!")
            print("   🔍 Exemple de fvRsBDToOut trouvé:")
            example = all_bd_to_out[0]
            print(f"      {json.dumps(example, indent=2)[:500]}")
        else:
            print("\n   ❌ Aucun objet fvRsBDToOut trouvé dans tout le JSON")
            print("   💡 Le JSON ne contient pas les relations BD→L3Out")
            print("   💡 Vérifiez que le JSON est complet (pas un export partiel)")
    else:
        print(f"\n✅ Détection OK: {total_relations} relations trouvées")
        print("\n🔍 Si l'extraction ne fonctionne toujours pas, vérifiez:")
        print("   1. Les BDs sont-ils dans la liste d'extraction (self.found_bds)?")
        print("   2. Les L3Outs sont-ils dans la configuration (self.l3out_configs)?")

    print("\n" + "=" * 80)
    print("✅ DIAGNOSTIC TERMINÉ")
    print("=" * 80)

    # Nettoyer le répertoire temporaire si nécessaire
    if temp_dir and os.path.exists(temp_dir):
        import shutil
        shutil.rmtree(temp_dir)
        print(f"\n🧹 Répertoire temporaire nettoyé: {temp_dir}")

if __name__ == "__main__":
    main()

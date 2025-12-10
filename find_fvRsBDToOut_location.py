#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Script pour trouver l'emplacement exact des objets fvRsBDToOut dans le JSON
"""

import json
import sys
import os
import tarfile
import tempfile
import glob

def find_fvRsBDToOut_with_path(data, current_path="root", results=None):
    """
    Chercher fvRsBDToOut et enregistrer le chemin complet dans la structure
    """
    if results is None:
        results = []

    if isinstance(data, dict):
        # Vérifier si c'est un fvRsBDToOut
        if 'fvRsBDToOut' in data:
            results.append({
                'path': current_path,
                'object': data['fvRsBDToOut'],
                'parent_keys': list(data.keys())
            })

        # Continuer la recherche récursive
        for key, value in data.items():
            new_path = f"{current_path} → {key}"
            find_fvRsBDToOut_with_path(value, new_path, results)

    elif isinstance(data, list):
        for i, item in enumerate(data):
            new_path = f"{current_path}[{i}]"
            find_fvRsBDToOut_with_path(item, new_path, results)

    return results

def find_parent_context(data, target_path, levels_up=2):
    """
    Trouver le contexte parent (remonte de N niveaux dans la structure)
    """
    # Cette fonction aide à comprendre dans quel objet parent se trouve le fvRsBDToOut
    # Pour l'instant, on retourne juste le chemin
    return target_path

def load_json_from_file(file_path):
    """Charger JSON depuis .json ou .tar.gz"""
    temp_dir = None

    if file_path.endswith('.tar.gz'):
        print("📦 Extraction du tar.gz...")
        temp_dir = tempfile.mkdtemp(prefix='aci_find_')

        with tarfile.open(file_path, 'r:gz') as tar:
            tar.extractall(path=temp_dir)

        json_pattern = os.path.join(temp_dir, '*_1.json')
        json_files = glob.glob(json_pattern)

        if not json_files:
            json_pattern = os.path.join(temp_dir, '*.json')
            json_files = glob.glob(json_pattern)
            json_files = [f for f in json_files if not f.endswith('.md5')]

        if not json_files:
            raise Exception("Aucun JSON trouvé")

        json_file = json_files[0]
        print(f"✅ JSON trouvé: {os.path.basename(json_file)}")

        with open(json_file, 'r') as f:
            data = json.load(f)

        return data, temp_dir
    else:
        with open(file_path, 'r') as f:
            data = json.load(f)
        return data, None

def main():
    print("=" * 80)
    print("🔍 TROUVER L'EMPLACEMENT DES fvRsBDToOut")
    print("=" * 80)

    # Demander le fichier
    if len(sys.argv) >= 2:
        json_file = sys.argv[1]
    else:
        json_file = input("\n📂 Chemin du fichier JSON/tar.gz: ").strip()
        if not json_file:
            print("❌ Chemin requis")
            sys.exit(1)

    if not os.path.exists(json_file):
        print(f"❌ Fichier introuvable: {json_file}")
        sys.exit(1)

    # Charger le JSON
    print(f"\n📂 Chargement: {json_file}")
    temp_dir = None
    try:
        aci_data, temp_dir = load_json_from_file(json_file)
        print("✅ JSON chargé")
    except Exception as e:
        print(f"❌ Erreur: {e}")
        sys.exit(1)

    # Chercher tous les fvRsBDToOut avec leur chemin
    print("\n" + "=" * 80)
    print("🔍 RECHERCHE DES fvRsBDToOut DANS TOUTE LA STRUCTURE")
    print("=" * 80)

    results = find_fvRsBDToOut_with_path(aci_data)

    print(f"\n✅ Trouvé: {len(results)} objets fvRsBDToOut")

    if len(results) == 0:
        print("\n❌ Aucun fvRsBDToOut trouvé dans le JSON")
    else:
        # Analyser les chemins pour trouver les patterns communs
        print("\n" + "=" * 80)
        print("📋 DÉTAIL DES EMPLACEMENTS")
        print("=" * 80)

        for i, result in enumerate(results, 1):
            obj = result['object']
            attrs = obj.get('attributes', {})

            print(f"\n🔹 Object #{i}")
            print(f"   📍 Chemin: {result['path']}")
            print(f"   🏷️  L3Out: {attrs.get('tnL3extOutName', 'N/A')}")
            print(f"   🆔 DN: '{attrs.get('dn', '')}'")
            print(f"   📦 Clés du parent: {result['parent_keys']}")

            # Afficher un extrait du chemin pour voir la structure
            path_parts = result['path'].split(' → ')
            if len(path_parts) > 3:
                print(f"   🔗 Structure:")
                for part in path_parts[-5:]:  # Derniers 5 niveaux
                    print(f"      └─ {part}")

        # Analyser les patterns
        print("\n" + "=" * 80)
        print("📊 ANALYSE DES PATTERNS")
        print("=" * 80)

        # Chercher les patterns communs dans les chemins
        common_patterns = {}
        for result in results:
            path = result['path']
            # Extraire les mots-clés importants du chemin
            if 'fvBD' in path:
                key = 'Sous fvBD (attendu)'
            elif 'fvTenant' in path:
                key = 'Sous fvTenant'
            elif 'imdata' in path:
                key = 'Directement sous imdata'
            elif 'children' in path:
                key = 'Dans un tableau children'
            else:
                key = 'Autre emplacement'

            common_patterns[key] = common_patterns.get(key, 0) + 1

        print("\n🔍 Distribution des emplacements:")
        for pattern, count in sorted(common_patterns.items(), key=lambda x: -x[1]):
            print(f"   • {pattern}: {count} objets")

        # Recommandations
        print("\n" + "=" * 80)
        print("💡 RECOMMANDATIONS")
        print("=" * 80)

        if 'Sous fvBD (attendu)' in common_patterns:
            print("\n✅ Les objets sont au bon endroit (children de fvBD)")
            print("   Le problème vient du DN vide, pas de la structure")
            print("\n🔧 Solution: Modifier l'extraction pour utiliser le DN du parent fvBD")
        else:
            print("\n⚠️  Les objets ne sont PAS dans les children des fvBD")
            print("\n🔧 Solutions possibles:")
            print("   1. Chercher les fvRsBDToOut ailleurs dans la structure")
            print("   2. Utiliser une méthode alternative pour associer BD→L3Out")
            print("   3. Vérifier si le backup APIC est complet")

    # Cleanup
    if temp_dir and os.path.exists(temp_dir):
        import shutil
        shutil.rmtree(temp_dir)

    print("\n" + "=" * 80)
    print("✅ ANALYSE TERMINÉE")
    print("=" * 80)

if __name__ == "__main__":
    main()

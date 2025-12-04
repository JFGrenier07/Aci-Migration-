#!/usr/bin/env python3
"""Script pour lister tous les EPG dans l'ACI"""

import requests
import urllib3
import yaml
import re
import getpass
import sys
from collections import defaultdict

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Demander les credentials de manière interactive
print("="*80)
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

base_url = f"https://{ip}"

# Login
session = requests.Session()
login_url = f"{base_url}/api/aaaLogin.json"
payload = {
    "aaaUser": {
        "attributes": {
            "name": user,
            "pwd": password
        }
    }
}

print("🔑 Connexion à l'APIC...")
response = session.post(login_url, json=payload, verify=False, timeout=30)
response.raise_for_status()
print("✅ Authentification réussie\n")

# Récupérer tous les EPG
print("📥 Récupération de la liste des EPG...")
api_url = f"{base_url}/api/node/class/fvAEPg.json"
response = session.get(api_url, verify=False, timeout=60)
response.raise_for_status()

data = response.json()
epgs = data.get('imdata', [])

print(f"✅ {len(epgs)} EPG trouvés\n")

# Grouper par tenant/ap
grouped = defaultdict(lambda: defaultdict(list))

for epg in epgs:
    attr = epg.get('fvAEPg', {}).get('attributes', {})
    dn = attr.get('dn', '')
    name = attr.get('name', '')

    # Extraire tenant et ap
    match_tn = re.search(r'/tn-([^/]+)/', dn)
    match_ap = re.search(r'/ap-([^/]+)/', dn)

    if match_tn and match_ap:
        tenant = match_tn.group(1)
        ap = match_ap.group(1)

        # Ignorer les tenants système
        if tenant not in ['common', 'infra', 'mgmt']:
            grouped[tenant][ap].append(name)

# Afficher
print("=" * 80)
print("TOUS LES EPG DANS VOTRE FABRIC ACI (hors tenants système):")
print("=" * 80)

total = 0
for tenant in sorted(grouped.keys()):
    print(f"\n📦 Tenant: {tenant}")
    for ap in sorted(grouped[tenant].keys()):
        print(f"  📁 AP: {ap}")
        for epg in sorted(grouped[tenant][ap]):
            print(f"     - {epg}")
            total += 1

print("\n" + "=" * 80)
print(f"Total: {total} EPG")
print("=" * 80)

print("\n💡 Format pour epg_list.yml:")
print("-" * 80)
for tenant in sorted(grouped.keys()):
    for ap in sorted(grouped[tenant].keys()):
        print(f"\n---")
        print(f"tenant: {tenant}")
        print(f"ap: {ap}")
        print(f"epgs:")
        for epg in sorted(grouped[tenant][ap]):
            print(f"  - {epg}")

# -*- coding: utf-8 -*-
"""
Classe de base pour les tâches de reverse engineering ACI.
"""

class BaseTask:
    def __init__(self, json_data, mapping, sheet_name):
        """
        Args:
            json_data (dict): Le JSON complet de la config ACI (uni)
            mapping (dict): Le mapping spécifique pour ce module (aci_class, attributes)
            sheet_name (str): Le nom de l'onglet Excel
        """
        self.json_data = json_data
        self.mapping = mapping
        self.sheet_name = sheet_name
        self.aci_class = mapping.get('aci_class')
        self.attributes_map = mapping.get('attributes', {})
        
        # Cache pour les objets trouvés
        self.objects = []

    def extract(self):
        """
        Extrait les objets de la classe cible depuis le JSON global.
        Cette méthode parcourt récursivement le JSON pour trouver tous les objets
        correspondant à self.aci_class.
        Filtre automatiquement les tenants système (common, infra, mgmt).
        """
        if not self.aci_class:
            print(f"⚠️  [{self.sheet_name}] Pas de classe ACI définie dans le mapping.")
            return

        all_objects = self._find_objects_recursive(self.json_data, self.aci_class)
        
        # Filtrage des tenants système
        self.objects = []
        excluded_tenants = ['tn-common', 'tn-infra', 'tn-mgmt']
        
        for obj in all_objects:
            dn = obj.get('attributes', {}).get('dn', '')
            is_system = False
            for sys_tenant in excluded_tenants:
                if f"/{sys_tenant}/" in dn or dn.endswith(f"/{sys_tenant}") or dn == f"uni/{sys_tenant}":
                    is_system = True
                    break
            
            if not is_system:
                self.objects.append(obj)
                
        # Déduplication basée sur le DN
        seen_dns = set()
        unique_objects = []
        for obj in self.objects:
            dn = obj.get('attributes', {}).get('dn')
            if dn and dn not in seen_dns:
                seen_dns.add(dn)
                unique_objects.append(obj)
        self.objects = unique_objects
        
        # print(f"    [{self.sheet_name}] {len(self.objects)} objets '{self.aci_class}' trouvés (après filtrage système).")

    def _find_objects_recursive(self, data, target_class):
        """Recherche récursive des objets"""
        found = []
        
        if isinstance(data, dict):
            for key, value in data.items():
                if key == target_class:
                    found.append(value)
                
                # Continuer la recherche dans les enfants (children ou autres clés)
                if isinstance(value, (dict, list)):
                    found.extend(self._find_objects_recursive(value, target_class))
                    
        elif isinstance(data, list):
            for item in data:
                found.extend(self._find_objects_recursive(item, target_class))
                
        return found

    def get_rows(self, headers):
        """
        Retourne une liste de dictionnaires (lignes Excel) basés sur les headers demandés.
        
        Args:
            headers (list): Liste des noms de colonnes Excel (ex: ['tenant', 'description'])
        """
        rows = []
        
        for obj in self.objects:
            row_data = {}
            attributes = obj.get('attributes', {})
            
            for header in headers:
                # 1. Chercher dans le mapping
                aci_attr = self.attributes_map.get(header)
                
                if aci_attr:
                    # Cas simple: mapping direct (ex: descr)
                    val = attributes.get(aci_attr)
                    
                    # Conversion booléenne ACI (yes/no) -> Python
                    if val == 'yes': val = 'true' # Pour Ansible souvent on veut true/false ou yes/no, à voir
                    if val == 'no': val = 'false'
                    
                    row_data[header] = val
                
                else:
                    # 2. Essayer de deviner (ex: header 'dn' -> attribut 'dn')
                    if header in attributes:
                        row_data[header] = attributes[header]
                    
                    # 3. Cas spéciaux (ex: 'tenant' est souvent dans le DN)
                    elif header == 'tenant' and 'dn' in attributes:
                        # Extraire tn-XXX du DN
                        import re
                        match = re.search(r'tn-([^/]+)', attributes['dn'])
                        if match:
                            row_data[header] = match.group(1)
                            
            rows.append(row_data)
            
        return rows

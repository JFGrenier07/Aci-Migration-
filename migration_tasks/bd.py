# -*- coding: utf-8 -*-
from .base_task import BaseTask

class BdTask(BaseTask):
    """
    Tâche spécifique pour 'bd' (Bridge Domain).
    Gère fvBD et extrait le VRF depuis l'enfant fvRsCtx.
    """
    
    def extract(self):
        # On a besoin des enfants pour le VRF
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            
            # Extraction VRF depuis enfant fvRsCtx
            vrf = ""
            children = obj.get('children', [])
            for child in children:
                if 'fvRsCtx' in child:
                    vrf = child['fvRsCtx']['attributes'].get('tnFvCtxName', '')
            
            print(f"DEBUG BD: {attr.get('name')} VRF: {vrf}")

            
            # Mapping manuel pour les champs complexes ou relations
            row_data = {
                'bd': attr.get('name'),
                'tenant': self._extract_tenant(attr.get('dn')), # Helper method if exists, or parse DN
                'vrf': vrf,
                'description': attr.get('descr'),
                'arp_flooding': attr.get('arpFlood'),
                'enable_routing': attr.get('unicastRoute'),
                'ip_learning': attr.get('ipLearning'),
                'limit_ip_learn': attr.get('limitIpLearnToSubnets'),
                'l2_unknown_unicast': attr.get('unkMacUcastAct'),
                'l3_unknown_multicast': attr.get('unkMcastAct'),
                'multi_dest': attr.get('multiDstPktAct'),
                'mac_address': attr.get('mac'),
                'bd_type': attr.get('type'),
                'enable_multicast': attr.get('mcastAllow'),
                # Ajouter tous les autres champs mappés automatiquement habituellement
                # Pour éviter de tout réécrire, on pourrait utiliser une logique hybride,
                # mais ici on explicite les champs critiques.
            }
            
            # Compléter avec les attributs génériques du mapping si non définis
            # (Simplification: on suppose que les champs ci-dessus couvrent l'essentiel)
            
            rows.append(row_data)
                
        return rows

    def _extract_tenant(self, dn):
        import re
        if not dn: return ""
        match = re.search(r'tn-([^/]+)', dn)
        return match.group(1) if match else ""

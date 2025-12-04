# -*- coding: utf-8 -*-
from .base_task import BaseTask
import re

class SwitchPolicyVpcProtectionGrTask(BaseTask):
    """
    Tâche spécifique pour 'switch_policy_vpc_protection_gr'.
    Gère fabricExplicitGEp et ses enfants (fabricNodePEp).
    """
    
    def extract(self):
        # On a besoin des enfants pour les IDs des switchs
        # BaseTask.extract ne récupère que l'objet lui-même.
        # On suppose que le JSON contient déjà les enfants (subtree="full")
        super().extract()

    def get_rows(self, headers):
        rows = []
        for obj in self.objects:
            attr = obj.get('attributes', {})
            children = obj.get('children', [])
            
            switch_ids = []
            vpc_domain_policy = ""
            
            for child in children:
                # Switch IDs (fabricNodePEp)
                if 'fabricNodePEp' in child:
                    node_id = child['fabricNodePEp']['attributes'].get('id')
                    if node_id:
                        switch_ids.append(node_id)
                
                # VPC Domain Policy (fabricRsVpcInstPol)
                if 'fabricRsVpcInstPol' in child:
                    vpc_domain_policy = child['fabricRsVpcInstPol']['attributes'].get('tnVpcInstPolName')

            # Trier les IDs pour être cohérent
            switch_ids.sort()
            
            switch_1_id = switch_ids[0] if len(switch_ids) > 0 else ""
            switch_2_id = switch_ids[1] if len(switch_ids) > 1 else ""
            
            # Pod ID (souvent 1 par défaut ou dans le NodePEp)
            # On prend le podId du premier switch s'il existe
            pod_id = "1" 
            # TODO: Extraire podId de fabricNodePEp si disponible (attribut 'podId' ?)
            
            row_data = {
                'protection_group': attr.get('name'),
                'protection_group_id': attr.get('id'),
                'switch_1_id': switch_1_id,
                'switch_2_id': switch_2_id,
                'vpc_domain_policy': vpc_domain_policy,
                'vpc_explicit_protection_group': vpc_domain_policy, # Semble être lié à la policy dans le CSV original
                'pod_id': pod_id,
                'description': attr.get('descr')
            }
            
            rows.append(row_data)
                
        return rows

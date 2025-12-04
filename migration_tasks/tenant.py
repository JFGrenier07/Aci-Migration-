# -*- coding: utf-8 -*-
from .base_task import BaseTask

class TenantTask(BaseTask):
    """
    Tâche spécifique pour l'onglet 'tenant'.
    Hérite de la logique générique mais permet des surcharges.
    """
    
    def extract(self):
        # On utilise l'extraction standard
        super().extract()
        
        # Exemple de logique custom : filtrer les tenants système
        # self.objects = [obj for obj in self.objects if not obj['attributes']['name'].startswith('infra')]
        pass

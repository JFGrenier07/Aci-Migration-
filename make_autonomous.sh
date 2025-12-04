#!/bin/bash
# Script pour rendre migration/ totalement autonome

echo "🔧 Rendre migration/ autonome..."

# 1. Copier inventory.yml
if [ -f "../inventory.yml" ]; then
    cp ../inventory.yml inventory.yml
    echo "✅ inventory.yml copié localement"
else
    echo "❌ ../inventory.yml introuvable"
    exit 1
fi

# 2. Modifier les scripts pour utiliser le fichier local
sed -i "s|'../inventory.yml'|'inventory.yml'|g" *.py
echo "✅ Scripts modifiés pour utiliser inventory.yml local"

echo ""
echo "🎉 migration/ est maintenant 100% autonome!"
echo "   Vous pouvez copier ce répertoire n'importe où"

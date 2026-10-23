# PC Component Database

Fichiers :
- pc_components.sqlite : base principale
- components.csv : catalogue tabulaire
- components.json : catalogue JSON
- prices.csv : prix vérifiés avec date et source
- schema.sql : schéma SQL
- README.md : documentation

Architecture prévue pour l'extension à plusieurs milliers de références.

IMPORTANT :
Les prix sont des données volatiles. Une valeur absente signifie "non vérifiée", jamais zéro.
Les références et caractéristiques doivent être revalidées contre la fiche fabricant avant automatisation critique.

Sources web consultées pour ce premier lot :
Materiel.net et LDLC.

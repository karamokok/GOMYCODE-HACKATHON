"""Mesure les performances sur le jeu de test mis de côté.

Ne lit que les messages marqués `split=test` dans corpus_4.csv, en excluant
ceux qui ont servi au réglage du système — la liste est écrite noir sur blanc
ci-dessous plutôt que déduite, pour qu'elle soit vérifiable.

Usage :  python evaluer.py
"""

import csv
import io
import sys

import detector

FICHIER = "corpus_4.csv"

# Messages du jeu de test qui ont servi à construire les garde-fous le
# 26 septembre. Ils sont exclus de la mesure : les compter reviendrait à
# s'évaluer sur ce qu'on a réglé.
CONTAMINES = {"A16", "A18", "N13", "N20"}

# Ce qu'on attend, par étiquette du corpus.
#   arnaque  -> le système doit dire rouge ou orange (il alerte)
#   legitime -> il doit dire vert (il n'alerte pas)
ATTENDU = {"arnaque": {"rouge", "orange"}, "legitime": {"vert"}}


def charger():
    lignes = list(csv.DictReader(io.open(FICHIER, encoding="utf-8-sig")))
    return [l for l in lignes
            if l["split"] == "test" and l["id"] not in CONTAMINES]


def mesurer(lignes):
    resultats = []
    for ligne in lignes:
        analyse = detector.analyser(ligne["texte"])
        couleur = analyse.sortie.couleur if analyse.sortie else "aucune"
        juste = couleur in ATTENDU[ligne["etiquette"]]
        masque = "[" in ligne["texte"]
        resultats.append((ligne, couleur, juste, masque))
        print(f"  {'ok  ' if juste else 'RATE'} {ligne['id']:4} "
              f"{ligne['etiquette']:8} -> {couleur:6} "
              f"{'(texte masqué)' if masque else ''}  {ligne['famille']}",
              flush=True)
    return resultats


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    lignes = charger()
    print(f"=== Jeu de test : {len(lignes)} messages "
          f"({len(CONTAMINES)} exclus pour cause de réglage) ===\n")
    resultats = mesurer(lignes)

    justes = sum(1 for _, _, j, _ in resultats if j)
    arnaques = [r for r in resultats if r[0]["etiquette"] == "arnaque"]
    legitimes = [r for r in resultats if r[0]["etiquette"] == "legitime"]
    detectees = sum(1 for _, _, j, _ in arnaques if j)
    tranquilles = sum(1 for _, _, j, _ in legitimes if j)

    print(f"\n  Arnaques détectées      : {detectees}/{len(arnaques)}")
    print(f"  Légitimes non alertés   : {tranquilles}/{len(legitimes)}")
    print(f"  Total                   : {justes}/{len(resultats)}")

    rates = [r for r in resultats if not r[2]]
    if rates:
        print("\n  Ce qui a été manqué :")
        for ligne, couleur, _, masque in rates:
            print(f"    {ligne['id']:4} attendu {ligne['etiquette']}, "
                  f"obtenu {couleur}"
                  + ("  — texte masqué, lien indisponible" if masque else ""))

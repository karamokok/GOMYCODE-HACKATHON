"""Orchestration des trois étages.

    message collé
      -> normalisation
      -> signals.extraire_signaux()   appel modèle, JSON validé
      -> rules.calculer_verdict()     Python pur, aucune IA
      -> templates.rediger_sortie()   phrases fixes

C'est le seul module que app.py appelle. Il ne lève jamais : toute erreur,
d'où qu'elle vienne, ressort en verdict orange de repli.
"""

from collections import namedtuple

import rules
import signals
import templates

# En dessous, il n'y a pas de quoi analyser. Aucun appel modèle n'est fait.
LONGUEUR_MINIMALE = 10

# Ce que rend analyser().
#   sortie        : un templates.Sortie, ou None si rien n'a été analysé
#   avertissement : texte à afficher en plus, ou "" — soit l'invite quand
#                   l'entrée est inexploitable, soit la mention de troncature.
#                   Les deux cas ne se produisent jamais ensemble.
Analyse = namedtuple("Analyse", "sortie avertissement")

MESSAGE_TROP_COURT = (
    "Colle le message que tu veux faire vérifier. "
    "Il faut au moins quelques mots pour pouvoir l'analyser."
)

AVERTISSEMENT_TRONCATURE = (
    f"Ton message dépassait {signals.TAILLE_MAX} caractères. "
    "Seul le début a été analysé."
)


def normaliser(message):
    """Nettoie le texte collé sans rien lui enlever de signifiant.

    On ne touche NI à la casse NI à la ponctuation : les majuscules en excès
    et les points d'exclamation en rafale sont des signaux que le modèle doit
    pouvoir constater (`anomalies_redaction`).
    """
    if not isinstance(message, str):
        return ""

    texte = message.replace("\r\n", "\n").replace("\r", "\n")
    # Espaces insécables collés par un copier-coller depuis WhatsApp.
    texte = texte.replace(" ", " ").replace(" ", " ")
    # Caractères de contrôle invisibles, sauf saut de ligne et tabulation.
    texte = "".join(c for c in texte if c in "\n\t" or c >= " ")
    return texte.strip()


MESSAGE_CAPTURE_ILLISIBLE = (
    "La capture n'a pas pu être lue. Réessaie avec une image plus nette, "
    "ou colle le texte du message."
)


def analyser_capture(image):
    """Analyse une capture d'écran : on la lit d'abord, on juge ensuite.

    Le modèle vision ne rend aucun verdict. Il recopie l'expéditeur et le
    texte ; tout le reste de la chaîne s'applique ensuite comme d'habitude,
    garde-fous compris.

    Ne lève jamais.
    """
    try:
        expediteur, texte = signals.lire_capture(signals.encoder_image(image))
    except Exception:
        signals._tracer("lecture de capture interrompue")
        return Analyse(None, MESSAGE_CAPTURE_ILLISIBLE)

    if not texte or len(normaliser(texte)) < LONGUEUR_MINIMALE:
        return Analyse(None, MESSAGE_CAPTURE_ILLISIBLE)

    return analyser(texte, expediteur=expediteur)


def analyser(message, expediteur=None):
    """Analyse un message collé et rend une Analyse prête à afficher.

    `expediteur` n'est connu que si la personne a envoyé une capture.

    Ne lève jamais.
    """
    texte = normaliser(message)

    if len(texte) < LONGUEUR_MINIMALE:
        return Analyse(None, MESSAGE_TROP_COURT)

    avertissement = ""
    if len(texte) > signals.TAILLE_MAX:
        texte = texte[:signals.TAILLE_MAX]
        avertissement = AVERTISSEMENT_TRONCATURE

    try:
        signaux, extraction_reussie = signals.extraire_signaux(texte, expediteur)
        if not extraction_reussie:
            return Analyse(templates.sortie_de_repli(), avertissement)

        verdict = rules.calculer_verdict(signaux)
        sortie = templates.rediger_sortie(verdict, texte)
    except Exception:
        # Filet de sécurité. signals n'est pas censé lever, mais aucune trace
        # Python ne doit jamais atteindre l'utilisateur. On ne journalise pas
        # le message : il ne doit laisser aucune trace.
        signals._tracer("analyse interrompue, repli orange")
        return Analyse(templates.sortie_de_repli(), avertissement)

    return Analyse(sortie, avertissement)


# --- Essais en console ------------------------------------------------------

if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    echecs = 0

    print("=== Entrées qui ne déclenchent aucun appel modèle " + "=" * 16)
    entrees_courtes = [
        ("champ vide", ""),
        ("espaces seulement", "     \n\n  \t "),
        ("None", None),
        ("un nombre", 12345),
        ("neuf caractères", "bonjour !"),
        ("sauts de ligne et espaces insécables", "  \n "),
    ]
    for nom, entree in entrees_courtes:
        analyse = analyser(entree)
        if analyse.sortie is None and analyse.avertissement == MESSAGE_TROP_COURT:
            print(f"  ok     {nom} -> invite, aucun appel modèle")
        else:
            print(f"  RATE   {nom} -> {analyse}")
            echecs += 1

    print("\n=== Normalisation " + "=" * 48)
    cas_normalisation = [
        ("retours Windows", "Ligne une\r\nLigne deux", "Ligne une\nLigne deux"),
        ("espaces insécables", "Orange Money", "Orange Money"),
        ("espaces autour", "   du texte   ", "du texte"),
        ("casse préservée", "URGENT!!! Appelez", "URGENT!!! Appelez"),
        ("caractère de contrôle", "abc\x07def", "abcdef"),
    ]
    for nom, entree, attendu in cas_normalisation:
        obtenu = normaliser(entree)
        if obtenu == attendu:
            print(f"  ok     {nom}")
        else:
            print(f"  RATE   {nom} : {obtenu!r} au lieu de {attendu!r}")
            echecs += 1

    print("\n=== Troncature " + "=" * 51)
    long_message = "Envoie 5000 FCFA au 07000000. " * 300
    analyse = analyser(long_message)
    if analyse.avertissement != AVERTISSEMENT_TRONCATURE:
        print("  RATE   aucune mention de troncature")
        echecs += 1
    elif analyse.sortie is None:
        print("  RATE   aucune sortie rendue")
        echecs += 1
    else:
        print(f"  ok     message de {len(long_message)} caractères tronqué, "
              f"mention affichée, verdict {analyse.sortie.couleur}")

    print("\n=== Repli quand l'extraction échoue " + "=" * 30)
    vrai_appel = signals.interroger_modele
    signals.interroger_modele = lambda *a, **k: "le modèle a déraillé"
    try:
        analyse = analyser("Confirmez votre code secret avant ce soir.")
    finally:
        signals.interroger_modele = vrai_appel
    if analyse.sortie and analyse.sortie.couleur == "orange" and \
            analyse.sortie.sous_titre == templates.SOUS_TITRE_REPLI:
        print("  ok     modèle inexploitable -> repli orange")
    else:
        print(f"  RATE   {analyse.sortie}")
        echecs += 1

    print("\n=== Filet de sécurité " + "=" * 44)
    vrai_calcul = rules.calculer_verdict
    rules.calculer_verdict = lambda s: 1 / 0
    try:
        analyse = analyser("Confirmez votre code secret avant ce soir.")
    except Exception as erreur:
        print(f"  RATE   une exception est remontée : {type(erreur).__name__}")
        echecs += 1
        analyse = None
    finally:
        rules.calculer_verdict = vrai_calcul
    if analyse and analyse.sortie and analyse.sortie.couleur == "orange":
        print("  ok     erreur interne -> repli orange, aucune trace Python")
    elif analyse:
        print(f"  RATE   {analyse.sortie}")
        echecs += 1

    print("\n=== Chaîne complète, appel modèle réel " + "=" * 27)
    for message in signals.MESSAGES_ESSAI:
        analyse = analyser(message)
        print(f"\n  {message[:60]}...")
        print(f"  -> {analyse.sortie.couleur.upper()} : {analyse.sortie.titre}")

    print()
    if echecs:
        print(f"{echecs} problème(s). detector.py non validé.")
        raise SystemExit(1)
    print("detector.py validé.")

"""Étage 2 : la couche de règles. Python ordinaire, aucun appel modèle.

C'est ici que le verdict est décidé, et nulle part ailleurs. Le modèle a
constaté des faits ; ce fichier en tire une conclusion par un calcul
déterministe, relisible ligne à ligne, identique à chaque exécution.

C'est l'argument central devant le jury : on ne demande pas à une IA si un
message est une arnaque. On lui demande ce qu'elle voit, et le verdict tombe
d'un barème écrit à la main.
"""

from collections import namedtuple

# Ce que rend calculer_verdict().
#   couleur : "rouge", "orange" ou "vert"
#   score   : entier, INTERNE — jamais montré à l'utilisateur
#   regles  : identifiants des règles déclenchées, par poids décroissant
#   absolue : True si une règle absolue a tranché
Verdict = namedtuple("Verdict", "couleur score regles absolue")

SEUIL_ROUGE = 50
SEUIL_ORANGE = 20

# Score attribué quand une règle absolue tranche. Le barème ne s'applique
# pas dans ce cas : la valeur sert seulement à garder un score cohérent.
SCORE_ABSOLU = 100

# --- Règles absolues --------------------------------------------------------
# Rouge immédiat, le barème n'est pas calculé. Chaque identifiant sert de clé
# à une phrase fixe dans templates.py.
#
# Aucune de ces règles ne repose sur un seul champ que le modèle pourrait
# avoir inventé. La vérification faite samedi l'a montré : `qwen2.5:3b`
# remplit `institution_invoquee` même quand le texte ne nomme aucun organisme.
# L'usurpation exige donc aussi `expediteur_incoherent`.

IDENTIFIANTS_ABSOLUS = ("code_secret_demande", "faux_transfert",
                        "usurpation_identite")


def _regles_absolues(signaux):
    """Liste les règles absolues déclenchées, de la plus grave à la moins.

    On les collecte toutes plutôt que de s'arrêter à la première : le calcul
    du barème est bien abandonné, mais connaître les deux motifs donne une
    meilleure explication à l'utilisateur.
    """
    declenchees = []

    # Aucun opérateur légitime ne demande jamais ce code. Aucune exception.
    if signaux.get("demande_code_secret"):
        declenchees.append("code_secret_demande")

    # Signature du faux transfert : « je t'ai envoyé de l'argent par erreur,
    # renvoie-le-moi ». L'argent n'est jamais arrivé.
    if signaux.get("pretend_erreur_transfert") and signaux.get("demande_argent"):
        declenchees.append("faux_transfert")

    # Se réclamer d'un organisme tout en donnant un contact personnel.
    if signaux.get("institution_invoquee") and signaux.get("expediteur_incoherent"):
        declenchees.append("usurpation_identite")

    return declenchees


# --- Barème -----------------------------------------------------------------
# Ordre décroissant : c'est aussi l'ordre dans lequel les règles déclenchées
# sont rendues, donc l'ordre des phrases d'explication.

BAREME = (
    ("demande_argent", 30),
    ("gain_non_sollicite", 25),
    ("lien_suspect", 25),
    ("demande_donnees_perso", 20),
    ("urgence_artificielle", 15),
    ("menace_ou_sanction", 15),
    ("appel_a_rappeler", 10),
    ("anomalies_redaction", 10),
    ("lien_present", 5),
)


def _regle_ponderee_active(identifiant, signaux):
    """Dit si une règle pondérée s'applique aux signaux donnés."""
    if identifiant == "lien_present":
        # Un lien seul ne pèse presque rien. S'il est suspect, c'est
        # lien_suspect qui compte : on ne facture pas deux fois le même lien.
        return bool(signaux.get("lien_present")) and not signaux.get("lien_suspect")
    return bool(signaux.get(identifiant))


def calculer_verdict(signaux):
    """Rend le Verdict correspondant aux signaux extraits.

    Fonction pure : mêmes signaux, même verdict, toujours.
    """
    absolues = _regles_absolues(signaux)
    if absolues:
        return Verdict("rouge", SCORE_ABSOLU, absolues, True)

    score = 0
    regles = []
    for identifiant, points in BAREME:
        if _regle_ponderee_active(identifiant, signaux):
            score += points
            regles.append(identifiant)

    if score >= SEUIL_ROUGE:
        couleur = "rouge"
    elif score >= SEUIL_ORANGE:
        couleur = "orange"
    else:
        couleur = "vert"

    return Verdict(couleur, score, regles, False)


# --- Essais en console ------------------------------------------------------
# Aucun appel modèle : les signaux sont écrits à la main. Les trois premiers
# sont ceux que `qwen2.5:3b` a réellement rendus samedi sur les trois
# messages de référence.

def _signaux(**modifications):
    """Construit un jeu de signaux : tout à false, sauf ce qu'on précise."""
    signaux = {
        "demande_code_secret": False,
        "demande_argent": False,
        "demande_donnees_perso": False,
        "urgence_artificielle": False,
        "menace_ou_sanction": False,
        "gain_non_sollicite": False,
        "institution_invoquee": None,
        "lien_present": False,
        "lien_suspect": False,
        "expediteur_incoherent": False,
        "anomalies_redaction": False,
        "pretend_erreur_transfert": False,
        "appel_a_rappeler": False,
        "langue": "fr",
        "motif_principal": "",
        "confiance_extraction": 0.0,
    }
    signaux.update(modifications)
    return signaux


# (nom, signaux, couleur attendue, score attendu, règles attendues)
CAS = [
    # --- Les trois messages de référence, signaux réellement observés ---
    (
        "message 1 : arnaque au code Orange Money",
        _signaux(demande_code_secret=True, urgence_artificielle=True,
                 menace_ou_sanction=True, institution_invoquee="Orange Money"),
        "rouge", SCORE_ABSOLU, ["code_secret_demande"],
    ),
    (
        "message 2 : faux transfert Wave",
        _signaux(demande_argent=True, pretend_erreur_transfert=True,
                 institution_invoquee="Wave"),
        "rouge", SCORE_ABSOLU, ["faux_transfert"],
    ),
    (
        "message 3 : vrai message d'opérateur",
        # institution_invoquee est ici une hallucination du modèle : le texte
        # ne nomme aucun organisme. Sans expediteur_incoherent, elle reste
        # sans effet. C'est exactement ce que ce cas vérifie.
        _signaux(institution_invoquee="Orange Money"),
        "vert", 0, [],
    ),

    # --- Règles absolues ---
    (
        "code secret seul, rien d'autre",
        _signaux(demande_code_secret=True),
        "rouge", SCORE_ABSOLU, ["code_secret_demande"],
    ),
    (
        "erreur de transfert sans demande d'argent : pas une absolue",
        _signaux(pretend_erreur_transfert=True),
        "vert", 0, [],
    ),
    (
        "usurpation : organisme invoqué et expéditeur incohérent",
        _signaux(institution_invoquee="MTN", expediteur_incoherent=True),
        "rouge", SCORE_ABSOLU, ["usurpation_identite"],
    ),
    (
        "expéditeur incohérent sans organisme : pas une absolue",
        _signaux(expediteur_incoherent=True),
        "vert", 0, [],
    ),
    (
        "organisme invoqué seul : jamais rouge",
        _signaux(institution_invoquee="Wave"),
        "vert", 0, [],
    ),
    (
        "deux absolues à la fois",
        _signaux(demande_code_secret=True, demande_argent=True,
                 pretend_erreur_transfert=True),
        "rouge", SCORE_ABSOLU, ["code_secret_demande", "faux_transfert"],
    ),

    # --- Seuils, aux bornes exactes ---
    (
        "50 pile : gain + lien suspect",
        _signaux(gain_non_sollicite=True, lien_suspect=True, lien_present=True),
        "rouge", 50, ["gain_non_sollicite", "lien_suspect"],
    ),
    (
        # Tous les points du barème sont multiples de 5 : 49 est inatteignable,
        # la vraie borne sous le rouge est 45.
        "45, juste sous le rouge : argent + urgence",
        _signaux(demande_argent=True, urgence_artificielle=True),
        "orange", 45, ["demande_argent", "urgence_artificielle"],
    ),
    (
        "20 pile : données perso seules",
        _signaux(demande_donnees_perso=True),
        "orange", 20, ["demande_donnees_perso"],
    ),
    (
        "25 : rappel + anomalies + lien simple",
        _signaux(appel_a_rappeler=True, anomalies_redaction=True,
                 lien_present=True),
        "orange", 25,
        ["appel_a_rappeler", "anomalies_redaction", "lien_present"],
    ),
    (
        "15 : anomalies + lien simple",
        _signaux(anomalies_redaction=True, lien_present=True),
        "vert", 15, ["anomalies_redaction", "lien_present"],
    ),
    (
        "5 : un lien et rien d'autre",
        _signaux(lien_present=True),
        "vert", 5, ["lien_present"],
    ),
    (
        "aucun signal",
        _signaux(),
        "vert", 0, [],
    ),

    # --- Le lien n'est jamais facturé deux fois ---
    (
        "lien suspect : 25 points, pas 30",
        _signaux(lien_present=True, lien_suspect=True),
        "orange", 25, ["lien_suspect"],
    ),
    (
        "lien suspect sans lien présent : le modèle s'est contredit",
        _signaux(lien_suspect=True),
        "orange", 25, ["lien_suspect"],
    ),

    # --- Ordre des règles rendues : poids décroissant ---
    (
        "ordre des règles par poids décroissant",
        _signaux(anomalies_redaction=True, demande_argent=True,
                 urgence_artificielle=True, gain_non_sollicite=True),
        "rouge", 80,
        ["demande_argent", "gain_non_sollicite", "urgence_artificielle",
         "anomalies_redaction"],
    ),

    # --- Robustesse : des signaux incomplets ne doivent pas lever ---
    (
        "dictionnaire vide",
        {},
        "vert", 0, [],
    ),
    (
        "quelques clés seulement",
        {"demande_argent": True, "urgence_artificielle": True},
        "orange", 45, ["demande_argent", "urgence_artificielle"],
    ),
]


def _essais():
    echecs = 0
    for nom, signaux, couleur_attendue, score_attendu, regles_attendues in CAS:
        try:
            verdict = calculer_verdict(signaux)
        except Exception as erreur:
            print(f"  LEVE   {nom} : {type(erreur).__name__}")
            echecs += 1
            continue

        ecarts = []
        if verdict.couleur != couleur_attendue:
            ecarts.append(f"couleur={verdict.couleur} au lieu de {couleur_attendue}")
        if verdict.score != score_attendu:
            ecarts.append(f"score={verdict.score} au lieu de {score_attendu}")
        if regles_attendues is not None and verdict.regles != regles_attendues:
            ecarts.append(f"règles={verdict.regles} au lieu de {regles_attendues}")

        if ecarts:
            print(f"  RATE   {nom} : " + " ; ".join(ecarts))
            echecs += 1
        else:
            print(f"  ok     {nom} -> {verdict.couleur} ({verdict.score})")
    return echecs


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8")

    print("=== Règles et seuils " + "=" * 45)
    echecs = _essais()
    print(f"\n{len(CAS) - echecs}/{len(CAS)} cas passés.")
    if echecs:
        print("Étape 3 non validée.")
        raise SystemExit(1)
    print("Étape 3 validée.")

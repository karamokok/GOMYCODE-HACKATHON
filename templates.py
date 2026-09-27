"""Étage 3 : les gabarits de sortie.

Tout ce que l'utilisateur lit est écrit ici, à la main. Le modèle ne rédige
aucune des phrases affichées — il n'a fait que constater des faits, et
rules.py en a tiré un verdict.

Règles de rédaction, à ne pas perdre de vue en modifiant ce fichier :
  - tutoiement, phrases courtes, aucun jargon ;
  - jamais « ce message est sûr » : le système ne peut pas le garantir ;
  - jamais de score ni de pourcentage affiché ;
  - aucune formulation qui culpabilise la personne. On parle du message,
    jamais de celui ou celle qui l'a reçu.
"""

import re
import zlib
from collections import namedtuple

# Ce que rend rediger_sortie(). app.py n'a plus qu'à mettre en forme.
#   conduite           : ce qu'il faut faire à l'instant
#   consigne_operateur : ce que l'opérateur lui-même recommande
Sortie = namedtuple(
    "Sortie",
    "couleur titre sous_titre explications conduite consigne_operateur",
)

MAX_EXPLICATIONS = 3      # Deux ou trois phrases, jamais davantage.
MAX_CONDUITE = 3
MAX_IMPERATIFS_SPECIFIQUES = 2

TITRES = {
    "rouge": ("Arnaque probable", "Ne réponds pas et n'envoie rien"),
    "orange": ("Prudence", "Quelque chose ne va pas dans ce message"),
    "vert": ("Rien de suspect détecté", "Reste vigilant malgré tout"),
}

# Plusieurs formulations par règle. Les clés sont celles de rules.py : les
# trois règles absolues, puis les règles du barème.
#
# Pourquoi des variantes : deux arnaques du même type donnaient exactement le
# même texte, au mot près. Le système paraissait réciter une fiche.
#
# Pourquoi le modèle ne les rédige pas pour autant : il pourrait inventer un
# mauvais conseil. Les variantes sont donc écrites à la main, et le choix est
# DÉTERMINISTE — voir _choisir(). Le même message rend toujours le même texte,
# devant le jury comme en vrai.
#
# Toutes les variantes d'une même règle doivent dire exactement la même chose.
# On change la formulation, jamais le fond.
PHRASES = {
    # Règles absolues
    "code_secret_demande": (
        "Ce message réclame ton code secret. Aucun opérateur ne demande "
        "jamais ce code, ni par SMS, ni par téléphone.",
        "On te demande ici ton code secret. C'est le signe le plus sûr d'une "
        "arnaque : aucun opérateur ne réclame jamais ce code.",
        "Ce message veut que tu communiques ton code secret. Un vrai "
        "opérateur ne fait jamais cette demande, par aucun moyen.",
    ),
    "faux_transfert": (
        "L'expéditeur prétend t'avoir envoyé de l'argent par erreur et veut "
        "que tu le lui renvoies. C'est une arnaque connue : l'argent n'est "
        "jamais arrivé sur ton compte.",
        "Quelqu'un affirme s'être trompé en t'envoyant de l'argent et te "
        "demande de le rendre. C'est un piège répandu : ce versement n'a "
        "jamais eu lieu.",
    ),
    "usurpation_identite": (
        "Le message se présente au nom d'un organisme officiel, mais le "
        "contact qu'il donne est un numéro personnel.",
        "Ce message emprunte le nom d'un organisme officiel alors que le "
        "contact indiqué est un numéro personnel.",
    ),

    # Règles du barème, par poids décroissant
    "demande_argent": (
        "Ce message demande d'envoyer de l'argent.",
        "On te demande ici de verser de l'argent.",
        "Ce message réclame un envoi d'argent.",
    ),
    "gain_non_sollicite": (
        "Ce message annonce un gain que tu n'as jamais demandé.",
        "On t'annonce un gain alors que tu n'as rien joué ni demandé.",
        "Ce message te promet un cadeau que tu n'as pas sollicité.",
    ),
    "lien_suspect": (
        "Le lien de ce message ne mène pas au vrai site de l'organisme.",
        "L'adresse du lien n'est pas celle du site officiel de l'organisme.",
        "Ce lien conduit ailleurs que sur le vrai site de l'organisme.",
    ),
    "demande_donnees_perso": (
        "Ce message réclame des informations personnelles.",
        "On te demande ici des renseignements personnels.",
    ),
    "urgence_artificielle": (
        "Le message presse d'agir tout de suite. C'est une façon de ne pas "
        "laisser le temps de réfléchir.",
        "Ce message impose un délai très court. C'est un moyen de t'empêcher "
        "de prendre le temps de vérifier.",
    ),
    "menace_ou_sanction": (
        "Le message menace de bloquer ton compte ou de te sanctionner.",
        "Ce message agite la menace d'un blocage ou d'une sanction.",
    ),
    "appel_a_rappeler": (
        "Le message demande d'appeler un numéro.",
        "Ce message t'invite à rappeler un numéro.",
    ),
    "anomalies_redaction": (
        "Le message est mal écrit. Les vrais messages d'opérateur le sont "
        "rarement.",
        "La rédaction du message est bancale. Les vrais messages d'opérateur "
        "le sont rarement.",
    ),
    "lien_present": (
        "Le message contient un lien.",
        "Un lien figure dans ce message.",
    ),
}

# Quand aucune règle ne s'est déclenchée, il faut tout de même dire quelque
# chose — sans jamais affirmer que le message est sûr.
EXPLICATION_AUCUN_SIGNAL = (
    "Aucun des signes d'arnaque que ce système sait repérer n'a été trouvé "
    "dans ce message."
)

# Impératif propre à certaines règles. Passe avant les impératifs génériques.
IMPERATIFS_PAR_REGLE = {
    "code_secret_demande": (
        "Ne donne ce code à personne, même à quelqu'un qui dit travailler "
        "chez ton opérateur.",
        "Garde ce code pour toi, même si ton interlocuteur se dit employé de "
        "ton opérateur.",
    ),
    "faux_transfert": (
        "Ne renvoie rien. Vérifie ton solde toi-même avant toute chose.",
        "N'envoie rien en retour. Contrôle ton solde par toi-même d'abord.",
    ),
    "usurpation_identite": (
        "N'utilise pas le numéro donné dans le message. Cherche le numéro "
        "officiel de ton opérateur.",
        "Laisse de côté le numéro du message et passe par le numéro officiel "
        "de ton opérateur.",
    ),
    "demande_argent": (
        "N'envoie pas d'argent.",
        "Ne verse aucune somme.",
    ),
    "gain_non_sollicite": (
        "Un vrai gain ne demande jamais de payer des frais à l'avance.",
        "Aucun gain légitime ne réclame des frais avant d'être versé.",
    ),
    "lien_suspect": (
        "N'ouvre pas le lien.",
        "Ne clique pas sur ce lien.",
    ),
    "demande_donnees_perso": (
        "Ne donne aucune information personnelle.",
        "Ne transmets aucun renseignement personnel.",
    ),
    "appel_a_rappeler": (
        "N'appelle pas le numéro indiqué dans le message.",
        "Ne rappelle pas le numéro que donne ce message.",
    ),
}

IMPERATIFS_GENERIQUES = {
    "rouge": [
        "Ne réponds pas à ce message.",
        "N'envoie ni argent ni code secret.",
        "Bloque le numéro, puis signale-le à ton opérateur.",
    ],
    "orange": [
        "Ne réponds pas tout de suite.",
        "Ne donne ni code secret ni argent.",
        "Vérifie en appelant ton opérateur au numéro officiel.",
    ],
    "vert": [
        "Reste prudent : un message peut tromper sans être repéré ici.",
        "Ne donne jamais ton code secret, même à quelqu'un qui dit "
        "travailler chez ton opérateur.",
        "En cas de doute, appelle ton opérateur toi-même.",
    ],
}

# --- Repli ------------------------------------------------------------------
# Quand l'extraction échoue, on ne sait rien du message. On le dit, et on
# reste en orange. Le sous-titre habituel de l'orange — « quelque chose ne va
# pas dans ce message » — serait faux ici : on n'a rien constaté du tout.

SOUS_TITRE_REPLI = "L'analyse n'a pas pu aller au bout"

EXPLICATIONS_REPLI = [
    "L'analyse de ce message n'a pas abouti.",
    "Ce n'est pas un signe que le message est bon ou mauvais : il n'a pas "
    "pu être vérifié.",
]


# --- Numéros officiels ------------------------------------------------------
#
# Relevés dans le document de collecte de l'équipe. Une personne qui vient de
# recevoir un message alarmant ne doit pas avoir à chercher le numéro : si
# elle le cherche, elle risque de rappeler celui du message, c'est-à-dire
# l'escroc lui-même.
#
# L'opérateur est reconnu dans le TEXTE, jamais par le champ
# `institution_invoquee` : le modèle l'a déjà inventé sur un message qui ne
# nommait personne. Afficher le numéro d'Orange à quelqu'un qui a reçu un
# faux message Wave serait pire que de n'en afficher aucun.

NUMEROS_OFFICIELS = {
    "Wave": "1315",
    "Orange": "0707",
    "MTN": "555",
    "Moov": "1010",
}

# Ce qu'il faut trouver dans le texte pour reconnaître chaque opérateur.
# Cherché en MOTS ENTIERS : « om » collé dans « nom » ou « prénom » faisait
# reconnaître Orange dans n'importe quel message demandant une identité.
MARQUEURS_OPERATEUR = {
    "Wave": ("wave", "wave ci", "wavecdi"),
    "Orange": ("orange", "orange money", "orangemoney", "om", "max it",
               "maxit", "omci"),
    "MTN": ("mtn", "mtn momo", "momo", "mtn ci"),
    "Moov": ("moov", "moov money", "moovmoney", "mymoov", "moov africa",
             "flooz"),
}

CONSEIL_NUMERO = {
    "rouge": "N'appelle pas le numéro écrit dans le message. Le vrai numéro "
             "{operateur}, c'est le {numero}.",
    "orange": "Avant d'agir, appelle {operateur} au {numero} pour vérifier.",
    "vert": "Le vrai numéro {operateur}, c'est le {numero}. Un message qui te "
            "demande d'appeler ailleurs doit t'alerter.",
}

# --- Ce que l'opérateur recommande lui-même ---------------------------------
#
# Relevé sur les pages officielles des quatre opérateurs (septembre 2026).
# Deux raisons d'afficher cela à part de notre propre conduite à tenir :
# la consigne vient de l'opérateur, pas de nous, et elle porte donc plus ;
# et elle couvre des gestes que notre analyse ne peut pas deviner, comme le
# fait de signaler vite pour que les fonds puissent encore être bloqués.
#
# Le 1777, qui circule comme numéro anti-arnaque, n'a PAS été retenu : les
# sources fiables le rattachent à Orange RDC, et la page officielle d'Orange
# Côte d'Ivoire ne donne aucun numéro de signalement. Donner un mauvais
# numéro à une victime serait pire que de n'en donner aucun.

CONSIGNES_OPERATEUR = {
    "Wave":
        "Wave le rappelle : son service client ne demande jamais ton code "
        "secret, ni par téléphone, ni par SMS. En cas de doute, appelle le "
        "1315 ou écris au WhatsApp officiel +225 07 13 15 13 15.",
    "Orange":
        "Orange le rappelle : ne compose jamais un code sur ton téléphone "
        "parce que quelqu'un te le demande, même s'il dit travailler chez "
        "Orange. Et ne fais jamais de dépôt à quelqu'un qui demande de "
        "l'aide par SMS ou sur Facebook.",
    "MTN":
        "MTN le rappelle : raccroche tout appel suspect et signale "
        "l'anomalie au 555. Si de l'argent est déjà parti, porte plainte à "
        "la police, puis rends-toi en agence avec la réquisition.",
    "Moov":
        "Moov le rappelle : ne communique ton code secret à personne. Si de "
        "l'argent est déjà parti, signale-le sans attendre : plus le "
        "signalement est rapide, plus les fonds peuvent encore être bloqués.",
}

CONSIGNE_GENERIQUE = (
    "Les quatre opérateurs le disent tous : aucun d'eux ne demande jamais ton "
    "code secret, et il ne faut jamais composer un code parce que quelqu'un "
    "te le demande. Si de l'argent est déjà parti, signale-le sans attendre : "
    "plus c'est rapide, plus les fonds peuvent encore être bloqués."
)

ACCENTS = str.maketrans("àâäçéèêëîïôöùûüÿ", "aaaceeeeiioouuuy")


def consigne_operateur(operateur):
    """La recommandation officielle, celle de l'opérateur ou la commune."""
    return CONSIGNES_OPERATEUR.get(operateur, CONSIGNE_GENERIQUE)


def reconnaitre_operateur(message):
    """Rend le nom de l'opérateur dont le message se réclame, ou None.

    On compte les mentions plutôt que de se contenter d'une présence : une
    capture d'écran contient souvent le nom de l'opérateur du téléphone dans
    la barre d'état (« MOOV AFRICA CI ») alors que le message, lui, se
    réclame d'une autre marque. Le plus cité l'emporte.

    En cas d'égalité, on ne choisit pas : donner le mauvais numéro serait
    pire que n'en donner aucun.
    """
    texte = (message or "").lower().translate(ACCENTS)

    comptes = {}
    for operateur, marqueurs in MARQUEURS_OPERATEUR.items():
        # Un seul comptage par position : les marqueurs se chevauchent
        # (« moov », « moov africa »), les additionner gonflerait le score.
        positions = set()
        for marqueur in marqueurs:
            for trouve in re.finditer(
                    r"\b" + re.escape(marqueur) + r"\b", texte):
                positions.add(trouve.start())
        if positions:
            comptes[operateur] = len(positions)

    if not comptes:
        return None

    classement = sorted(comptes.items(), key=lambda paire: paire[1], reverse=True)
    if len(classement) > 1 and classement[0][1] == classement[1][1]:
        return None
    return classement[0][0]


# Quand l'opérateur est reconnu, on le nomme au lieu de dire « un organisme
# officiel ». « Le message se présente au nom de Wave » est autrement plus
# parlant, et l'information est sous les yeux de la personne.
PHRASES_AVEC_OPERATEUR = {
    "usurpation_identite": (
        "Le message se présente au nom {de_operateur}, mais le contact qu'il "
        "donne est un numéro personnel.",
        "Ce message emprunte le nom {de_operateur} alors que le contact "
        "indiqué est un numéro personnel.",
    ),
    "lien_suspect": (
        "Le lien de ce message ne mène pas au vrai site {de_operateur}.",
        "L'adresse du lien n'est pas celle du site officiel {de_operateur}.",
        "Ce lien conduit ailleurs que sur le vrai site {de_operateur}.",
    ),
}


def _de(operateur):
    """« de Wave », mais « d'Orange » : l'élision devant une voyelle."""
    if operateur[0].lower() in "aeiouy":
        return f"d'{operateur}"
    return f"de {operateur}"


def _graine(message):
    """Un nombre stable tiré du message, pour choisir une formulation.

    crc32 et non hash() : la fonction native de Python est volontairement
    aléatoire d'une exécution à l'autre, et le même message donnerait alors
    un texte différent à chaque redémarrage.
    """
    return zlib.crc32((message or "").encode("utf-8"))


def _choisir(variantes, graine, decalage=0):
    """Choisit une variante. Déterministe : même message, même formulation."""
    if isinstance(variantes, str):
        return variantes
    return variantes[(graine + decalage) % len(variantes)]


def _explications(verdict, operateur=None, graine=0):
    """Les phrases à afficher, dans l'ordre des règles déclenchées."""
    phrases = []
    for rang, identifiant in enumerate(verdict.regles):
        # Le décalage par rang évite que deux règles d'une même sortie
        # tombent systématiquement sur la variante de même index.
        if operateur and identifiant in PHRASES_AVEC_OPERATEUR:
            phrases.append(
                _choisir(PHRASES_AVEC_OPERATEUR[identifiant], graine, rang)
                .format(operateur=operateur, de_operateur=_de(operateur)))
        elif identifiant in PHRASES:
            phrases.append(_choisir(PHRASES[identifiant], graine, rang))
    if verdict.couleur == "vert":
        # En vert, des règles mineures ont pu se déclencher sans atteindre le
        # seuil. Les afficher seules contredirait le titre : on annonce donc
        # la conclusion d'abord, et l'observation ensuite.
        phrases = [EXPLICATION_AUCUN_SIGNAL] + phrases
    elif not phrases:
        return [EXPLICATION_AUCUN_SIGNAL]
    return phrases[:MAX_EXPLICATIONS]


def _conduite(verdict, operateur=None, graine=0):
    """Deux ou trois impératifs concrets, les plus précis d'abord.

    Quand l'opérateur est reconnu, son vrai numéro passe en tête : c'est le
    geste le plus utile pour quelqu'un qui vient de recevoir un message
    alarmant.
    """
    conduite = []
    ignores = set()

    if operateur:
        conduite.append(CONSEIL_NUMERO[verdict.couleur].format(
            operateur=operateur, numero=NUMEROS_OFFICIELS[operateur]))
        # Ces deux impératifs disent déjà « n'appelle pas le numéro du
        # message ». Les répéter juste après affaiblit le conseil.
        ignores = {"usurpation_identite", "appel_a_rappeler"}

    for rang, identifiant in enumerate(verdict.regles):
        if len(conduite) >= MAX_IMPERATIFS_SPECIFIQUES:
            break
        if identifiant in ignores or identifiant not in IMPERATIFS_PAR_REGLE:
            continue
        phrase = _choisir(IMPERATIFS_PAR_REGLE[identifiant], graine, rang)
        if phrase not in conduite:
            conduite.append(phrase)

    for phrase in IMPERATIFS_GENERIQUES[verdict.couleur]:
        if len(conduite) >= MAX_CONDUITE:
            break
        if phrase not in conduite:
            conduite.append(phrase)
    return conduite


def rediger_sortie(verdict, message=None):
    """Transforme un Verdict de rules.py en texte prêt à afficher.

    `message` sert uniquement à reconnaître l'opérateur pour donner son vrai
    numéro. Aucun morceau du message n'est jamais réaffiché.
    """
    titre, sous_titre = TITRES[verdict.couleur]
    operateur = reconnaitre_operateur(message)
    graine = _graine(message)
    return Sortie(
        couleur=verdict.couleur,
        titre=titre,
        sous_titre=sous_titre,
        explications=_explications(verdict, operateur, graine),
        conduite=_conduite(verdict, operateur, graine),
        consigne_operateur=consigne_operateur(operateur),
    )


def sortie_de_repli():
    """Sortie affichée quand le modèle n'a rien rendu d'exploitable.

    Orange, et on dit clairement qu'on ne sait pas. On n'invente jamais un
    résultat.
    """
    titre, _ = TITRES["orange"]
    return Sortie(
        couleur="orange",
        titre=titre,
        sous_titre=SOUS_TITRE_REPLI,
        explications=list(EXPLICATIONS_REPLI),
        conduite=list(IMPERATIFS_GENERIQUES["orange"]),
        consigne_operateur=CONSIGNE_GENERIQUE,
    )


def formater_texte(sortie):
    """Rendu en texte simple, pour la console et pour les essais."""
    lignes = [sortie.titre.upper(), sortie.sous_titre, ""]
    lignes += [f"- {phrase}" for phrase in sortie.explications]
    lignes += ["", "À faire maintenant :"]
    lignes += [f"  {numero}. {phrase}"
               for numero, phrase in enumerate(sortie.conduite, start=1)]
    lignes += ["", "Ce que dit ton opérateur :",
               f"  {sortie.consigne_operateur}"]
    return "\n".join(lignes)


# --- Essais en console ------------------------------------------------------

# Formulations interdites : le système ne peut garantir aucune sécurité, et
# ne doit jamais renvoyer la faute à la personne.
TOURNURES_INTERDITES = (
    "est sûr", "est sur.", "sécurisé", "securise", "fiable", "sans danger",
    "aucun risque", "sans risque", "score", "%", "pourcent",
    "tu aurais dû", "tu as eu tort", "imprudent", "naïf", "naif",
    "ta faute", "tu n'aurais pas dû",
)


# (nom, texte, opérateur attendu)
CAS_OPERATEUR = [
    # Une seule marque citée.
    ("Wave seul", "L'equipe Wave vous offre un cadeau", "Wave"),
    ("Orange seul", "Orange Money: votre compte sera suspendu", "Orange"),
    ("MTN seul", "MTN MoMo: depot effectue", "MTN"),
    ("Moov seul", "Moov Money vous remercie", "Moov"),
    ("Max it", "Rendez-vous sur Max it ce soir", "Orange"),
    ("MyMoov", "Souscris via MyMoov", "Moov"),
    ("MoMo", "Votre compte MoMo est actif", "MTN"),

    # Barre d'état de la capture qui cite un autre opérateur : c'est le cas
    # réel qui a échoué. La marque du message doit l'emporter.
    ("Wave x3 contre Moov x1 (barre d'état)",
     "cadeau wave de 10.000 F. Cliquez : wavekdo. L'equipe Wave. MOOV AFRICA CI",
     "Wave"),
    ("Orange x2 contre Wave x1",
     "Orange Money vous informe. Solde Orange disponible. via Wave", "Orange"),

    # Égalité stricte : on ne choisit pas plutôt que de se tromper.
    ("égalité Wave / Orange", "Transfert de Wave vers Orange", None),
    ("aucune marque", "Salut, je suis bien arrive a Bouake", None),

    # Le piège corrigé : « om » collé dans d'autres mots.
    ("« nom » ne doit pas donner Orange",
     "Envoyez votre nom et prenom complets", None),
    ("« comme » ne doit pas donner Orange",
     "Fais comme d'habitude, on se voit demain", None),
    ("« om » isolé donne bien Orange",
     "Votre compte OM est debloque", "Orange"),

    # Accents et casse.
    ("majuscules", "WAVE CI VOUS REMERCIE", "Wave"),
    ("accents", "Opérateur Moov Africa Côte d'Ivoire", "Moov"),
]


def _essais_operateur():
    echecs = 0
    for nom, texte, attendu in CAS_OPERATEUR:
        try:
            obtenu = reconnaitre_operateur(texte)
        except Exception as erreur:
            print(f"  LEVE   {nom} : {type(erreur).__name__}")
            echecs += 1
            continue
        if obtenu != attendu:
            print(f"  RATE   {nom} : {obtenu} au lieu de {attendu}")
            echecs += 1
        else:
            print(f"  ok     {nom} -> {obtenu}")
    return echecs


if __name__ == "__main__":
    import sys

    import rules

    sys.stdout.reconfigure(encoding="utf-8")

    echecs = 0

    print("=== Reconnaissance de l'opérateur " + "=" * 32)
    echecs += _essais_operateur()
    print()

    # 1. Toute règle connue de rules.py doit avoir une phrase ici. Sans ça,
    #    une règle se déclencherait sans rien afficher.
    print("=== Couverture des règles " + "=" * 40)
    identifiants = list(rules.IDENTIFIANTS_ABSOLUS) + [
        identifiant for identifiant, _ in rules.BAREME
    ]
    for identifiant in identifiants:
        if identifiant in PHRASES:
            print(f"  ok     {identifiant}")
        else:
            print(f"  RATE   {identifiant} : aucune phrase d'explication")
            echecs += 1

    # 2. Sorties complètes sur des verdicts représentatifs.
    print("\n=== Sorties complètes " + "=" * 44)
    exemples = [
        ("arnaque au code",
         rules.Verdict("rouge", 100, ["code_secret_demande"], True)),
        ("faux transfert",
         rules.Verdict("rouge", 100, ["faux_transfert"], True)),
        ("loterie avec frais",
         rules.Verdict("rouge", 80,
                       ["demande_argent", "gain_non_sollicite",
                        "urgence_artificielle", "appel_a_rappeler"], False)),
        ("message douteux sans certitude",
         rules.Verdict("orange", 30, ["demande_argent"], False)),
        ("message avec un simple lien",
         rules.Verdict("vert", 5, ["lien_present"], False)),
        ("aucun signal",
         rules.Verdict("vert", 0, [], False)),
    ]
    for nom, verdict in exemples:
        sortie = rediger_sortie(verdict)
        print(f"\n--- {nom} ---")
        print(formater_texte(sortie))

    print("\n--- repli, extraction en échec ---")
    print(formater_texte(sortie_de_repli()))

    # 3. Contrôles automatiques sur toutes les sorties possibles.
    print("\n=== Contrôles " + "=" * 52)
    toutes = [rediger_sortie(verdict) for _, verdict in exemples]
    toutes.append(sortie_de_repli())
    # Une sortie par règle prise isolément, pour ne rien laisser hors contrôle.
    for identifiant in identifiants:
        couleur = "rouge" if identifiant in rules.IDENTIFIANTS_ABSOLUS else "orange"
        toutes.append(rediger_sortie(
            rules.Verdict(couleur, 50, [identifiant], couleur == "rouge")))

    for sortie in toutes:
        texte = formater_texte(sortie).lower()

        for tournure in TOURNURES_INTERDITES:
            if tournure in texte:
                print(f"  RATE   « {tournure} » apparaît dans « {sortie.titre} »")
                echecs += 1

        if not 1 <= len(sortie.explications) <= MAX_EXPLICATIONS:
            print(f"  RATE   {len(sortie.explications)} explications "
                  f"dans « {sortie.titre} »")
            echecs += 1
        if not 2 <= len(sortie.conduite) <= MAX_CONDUITE:
            print(f"  RATE   {len(sortie.conduite)} impératifs "
                  f"dans « {sortie.titre} »")
            echecs += 1
        if len(set(sortie.conduite)) != len(sortie.conduite):
            print(f"  RATE   impératif répété dans « {sortie.titre} »")
            echecs += 1

    if not echecs:
        print("  ok     aucune tournure interdite")
        print("  ok     1 à 3 explications, 2 à 3 impératifs, aucun doublon")

    # 4. L'ordre des explications suit celui des règles.
    verdict = rules.Verdict("rouge", 80,
                            ["demande_argent", "gain_non_sollicite",
                             "urgence_artificielle", "appel_a_rappeler"], False)
    sortie = rediger_sortie(verdict)
    graine = _graine(None)
    attendu = [_choisir(PHRASES["demande_argent"], graine, 0),
               _choisir(PHRASES["gain_non_sollicite"], graine, 1),
               _choisir(PHRASES["urgence_artificielle"], graine, 2)]
    if sortie.explications == attendu:
        print("  ok     ordre des explications et troncature à 3")
    else:
        print("  RATE   ordre ou troncature des explications")
        echecs += 1

    # 5. Les variantes : déterminisme, et aucune qui change le fond.
    print("\n=== Variantes de formulation " + "=" * 37)
    message = "Orange Money: confirmez votre code secret avant 18h."
    v = rules.Verdict("rouge", 100, ["code_secret_demande"], True)
    rendus = {formater_texte(rediger_sortie(v, message)) for _ in range(20)}
    if len(rendus) == 1:
        print("  ok     même message, même texte (20 appels)")
    else:
        print(f"  RATE   {len(rendus)} textes différents pour un même message")
        echecs += 1

    # Des messages différents doivent, eux, varier.
    differents = {
        formater_texte(rediger_sortie(v, f"Orange Money code secret {n}"))
        for n in range(40)
    }
    if len(differents) > 1:
        print(f"  ok     messages différents -> {len(differents)} formulations")
    else:
        print("  RATE   aucune variation entre messages différents")
        echecs += 1

    # Toutes les variantes passent le contrôle des tournures interdites.
    toutes_variantes = [
        phrase
        for groupe in list(PHRASES.values()) + list(IMPERATIFS_PAR_REGLE.values())
        for phrase in groupe
    ]
    fautives = [p for p in toutes_variantes
                for t in TOURNURES_INTERDITES if t in p.lower()]
    if fautives:
        print(f"  RATE   {len(fautives)} variante(s) avec tournure interdite")
        echecs += 1
    else:
        print(f"  ok     {len(toutes_variantes)} variantes, aucune interdite")

    print()
    if echecs:
        print(f"{echecs} problème(s). Étape 4 non validée.")
        raise SystemExit(1)
    print("Étape 4 validée.")

"""Étage 1 : extraction de signaux par le modèle.

Le modèle ne juge jamais. Il constate des faits observables dans le texte
et les rend sous forme de JSON. Le verdict est calculé ailleurs, par
rules.py, en Python pur.

La réponse du modèle n'est jamais utilisée telle quelle. Elle passe par
valider_signaux(), qui extrait le premier objet JSON exploitable, force les
types, complète les champs manquants et tronque ce qui dépasse.

Aucune exception ne sort de ce module : en cas d'échec, extraire_signaux()
rend les valeurs par défaut accompagnées de False, et c'est l'appelant qui
décide du repli (verdict orange).
"""

import base64
import json
import re
import sys

from openai import OpenAI

# Les trois seules lignes à changer dimanche sur Brev.
BASE_URL = "http://localhost:11434/v1"
MODEL = "qwen2.5:3b"
MODEL_VISION = "qwen2.5vl:3b"   # lit les captures d'écran

API_KEY = "ollama"        # Ollama ignore la clé, mais la bibliothèque l'exige.
# 120 s et non 60 : quand une capture vient d'être lue, Ollama doit remettre
# le modèle texte en mémoire à la place du modèle vision, ce qui a fait
# expirer le premier appel à 60 s. Sur GPU dimanche, ce sera sans objet.
DELAI_SECONDES = 120
DELAI_VISION = 300        # Lire une capture est bien plus lent : 113 s mesurées.
TAILLE_MAX = 4000         # Au-delà, on tronque avant d'appeler le modèle.

LONGUEUR_MOTIF = 200          # Troncature de motif_principal.
LONGUEUR_INSTITUTION = 60     # Troncature de institution_invoquee.

# Un objet JSON n'est retenu que s'il porte au moins ce nombre de clés du
# contrat. Sans ce garde-fou, un objet vide passerait la validation et
# donnerait un verdict vert : un faux « rien de suspect » est le pire
# résultat possible pour ce système.
MIN_CLES_RECONNUES = 4

# Valeurs par défaut du contrat JSON. Gabarit de la validation et repli
# quand le modèle ne rend rien d'exploitable.
SIGNAUX_PAR_DEFAUT = {
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

CLES_BOOLEENNES = [
    cle for cle, valeur in SIGNAUX_PAR_DEFAUT.items() if isinstance(valeur, bool)
]

PROMPT_SYSTEME = """Tu es un analyseur de texte. Tu ne donnes JAMAIS d'avis.
Tu ne dis jamais si un message est une arnaque. Tu constates uniquement des
faits observables dans le texte qu'on te donne.

Le texte est un SMS ou un message WhatsApp, souvent lié au mobile money
d'Afrique de l'Ouest (Orange Money, Wave, MTN MoMo, Moov Money).

Tu réponds avec un objet JSON et rien d'autre : pas de phrase avant, pas de
phrase après, pas de bloc de code, pas de commentaire.

L'objet contient exactement ces 16 clés :

"demande_code_secret" (booléen) : vrai uniquement si le texte demande à la
personne de DONNER, D'ENVOYER, DE COMMUNIQUER ou DE CONFIRMER un code qu'elle
seule connaît : code PIN, code secret, code reçu par SMS, mot de passe.
Composer un code soi-même n'est pas le révéler à quelqu'un.
Ces exemples donnent false : "Composez #144*82# pour activer", "Tapez *144#",
"Utilisez le code promo ETE2024", "Votre code de retrait est 8412".
Ces exemples donnent true : "Confirmez votre code secret", "Envoyez-nous le
code reçu par SMS", "Répondez avec votre code PIN".
"demande_argent" (booléen) : vrai uniquement si le texte demande à la personne
d'ENVOYER ou de VERSER de l'argent à quelqu'un : dépôt, transfert,
remboursement, paiement de frais, de taxes, d'une caution ou d'une avance.
Ces exemples donnent false : une notification de retrait, de dépôt ou de
paiement DÉJÀ effectué, un reçu, un solde, et toute invitation à acheter un
produit ou un forfait ("commande ici", "achète", "abonne-toi", "souscris").
Acheter quelque chose n'est pas envoyer de l'argent à quelqu'un.
"demande_donnees_perso" (booléen) : le texte réclame nom complet, pièce
d'identité, numéro de compte, adresse, date de naissance, photo de carte.
"urgence_artificielle" (booléen) : le texte impose un délai court ou presse
d'agir tout de suite ("immédiatement", "sous 24h", "dernier avertissement").
"menace_ou_sanction" (booléen) : le texte annonce un blocage de compte, une
suspension, une amende, des poursuites, une perte si on n'agit pas.
"gain_non_sollicite" (booléen) : le texte annonce un gain, un lot, une
tombola, un bonus, un héritage, une sélection que la personne n'a pas demandé.
"institution_invoquee" (texte ou null) : le nom de l'organisme dont le texte
se réclame, tel qu'écrit (par exemple "Orange Money", "Wave", "MTN", le nom
d'une banque, la police). null si aucun organisme n'est nommé.
"lien_present" (booléen) : le texte contient une adresse web ou un lien.
"lien_suspect" (booléen) : ce lien est raccourci (bit.ly, tinyurl), imite le
nom d'une marque avec une faute, ou utilise un domaine sans rapport avec
l'organisme invoqué. Est suspect aussi un domaine qui accole un nom de marque
à d'autres mots (wave-ci-verif.xyz, orange-money-verification.com) et un
domaine en extension inhabituelle (.xyz, .top, .tk, .buzz). false s'il n'y a
pas de lien.
"expediteur_incoherent" (booléen) : le texte se réclame d'un organisme tout
en donnant un numéro personnel, un WhatsApp ou une adresse mail gratuite
comme point de contact.
"anomalies_redaction" (booléen) : fautes d'orthographe nombreuses, majuscules
en excès, ponctuation anormale, mélange de langues, mise en forme bancale.
"pretend_erreur_transfert" (booléen) : l'expéditeur prétend avoir envoyé de
l'argent par erreur sur ce compte et veut se le faire rendre.
"appel_a_rappeler" (booléen) : le texte demande d'appeler ou de rappeler un
numéro, ou d'écrire à un WhatsApp.
"langue" (texte) : code de la langue dominante, "fr", "en", "ar" ou autre.
"motif_principal" (texte) : une phrase courte et factuelle qui dit ce que le
texte demande concrètement. Pas d'avis, pas de conseil. Maximum 200 caractères.
"confiance_extraction" (nombre entre 0.0 et 1.0) : à quel point le texte est
clair à analyser. 1.0 si tout est explicite, 0.3 si le texte est trop court
ou trop ambigu pour se prononcer.

Un booléen n'est vrai que si le fait est réellement présent dans le texte.
Dans le doute, mets false."""

PROMPT_UTILISATEUR = """Analyse le message ci-dessous et rends l'objet JSON.

--- DÉBUT DU MESSAGE ---
{message}
--- FIN DU MESSAGE ---"""

# Ajouté à la reprise quand la première réponse n'était pas exploitable.
RAPPEL_JSON = """

Ta réponse précédente n'était pas un objet JSON exploitable.
Réponds cette fois avec le seul objet JSON, ses 16 clés, rien d'autre.
Commence ta réponse par { et termine-la par }."""

# max_retries=0 : la bibliothèque openai réessaie deux fois d'elle-même par
# défaut. Combiné à notre propre reprise, cela ferait jusqu'à six appels
# réseau au lieu des deux voulus, et ferait attendre quinze secondes devant un
# serveur éteint. La reprise, c'est extraire_signaux() qui la gère, lui seul.
_client = OpenAI(base_url=BASE_URL, api_key=API_KEY, timeout=DELAI_SECONDES,
                 max_retries=0)


def _tracer(etiquette):
    """Trace technique sur la sortie d'erreur.

    N'écrit jamais le texte du message ni la réponse du modèle : la mention
    « ton message est analysé puis effacé » affichée sous le champ doit
    rester vraie.
    """
    print(f"[signals] {etiquette}", file=sys.stderr)


def interroger_modele(message, format_json=True, insister=False):
    """Envoie le message au modèle et rend la réponse brute, en texte.

    format_json pilote response_format : c'est lui qui garantit le JSON pur
    sur Ollama. Si le serveur de dimanche le refuse, la reprise repart sans.

    Aucune validation ici : c'est l'affaire de valider_signaux().
    """
    consigne = PROMPT_SYSTEME + (RAPPEL_JSON if insister else "")
    options = {}
    if format_json:
        options["response_format"] = {"type": "json_object"}

    reponse = _client.chat.completions.create(
        model=MODEL,
        temperature=0,
        messages=[
            {"role": "system", "content": consigne},
            {"role": "user", "content": PROMPT_UTILISATEUR.format(message=message)},
        ],
        **options,
    )
    return reponse.choices[0].message.content


# --- Lecture d'une capture d'écran ------------------------------------------
#
# Copier-coller un SMS perd l'expéditeur, qui est pourtant le signal le plus
# sûr : dans les messages relevés par l'équipe, deux arnaques ne sont
# reconnaissables qu'à leur expéditeur « +454 » au lieu du canal officiel
# d'Orange. La capture d'écran, elle, le montre.
#
# Le modèle vision ne fait qu'une chose : RECOPIER ce qu'il voit. Il ne juge
# rien. Le texte qu'il rend repart ensuite dans la chaîne habituelle, où les
# garde-fous (mots de code, domaines) peuvent s'appliquer — ce qui serait
# impossible s'il rendait directement un verdict.

PROMPT_LECTURE = """Tu recopies le contenu d'une capture d'écran de SMS ou de
message WhatsApp. Tu ne donnes aucun avis, tu n'analyses rien, tu ne résumes
pas : tu recopies.

Réponds exactement sous cette forme, et rien d'autre :

EXPEDITEUR: <le nom ou le numéro affiché en haut de l'écran>
MESSAGE: <le texte du message, mot pour mot, adresses web comprises>

Recopie TOUT le contenu de la bulle du message, de la première ligne à la
dernière. La première ligne est souvent le nom d'un service ou d'une marque
("OrangeMoney", "Wave", "MTN") : c'est une partie du message, recopie-la.
Recopie les adresses web et les numéros caractère par caractère, sans rien
corriger.
Si l'expéditeur n'est pas visible, écris EXPEDITEUR: inconnu."""


def encoder_image(chemin_ou_octets):
    """Rend l'image en base64, prête pour l'API."""
    if isinstance(chemin_ou_octets, (bytes, bytearray)):
        octets = bytes(chemin_ou_octets)
    else:
        with open(chemin_ou_octets, "rb") as fichier:
            octets = fichier.read()
    return base64.b64encode(octets).decode("ascii")


def lire_capture(image_b64):
    """Rend (expediteur, message) lus dans la capture, ou (None, None).

    Ne lève jamais.
    """
    try:
        reponse = _client.chat.completions.create(
            model=MODEL_VISION,
            temperature=0,
            timeout=DELAI_VISION,
            messages=[{"role": "user", "content": [
                {"type": "text", "text": PROMPT_LECTURE},
                {"type": "image_url",
                 "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
            ]}],
        )
        brut = reponse.choices[0].message.content or ""
    except Exception as erreur:
        _tracer(f"lecture de la capture en échec : {type(erreur).__name__}")
        return None, None

    expediteur, message = None, None
    for ligne in brut.splitlines():
        depouillee = ligne.strip()
        if depouillee.upper().startswith("EXPEDITEUR:"):
            expediteur = depouillee.split(":", 1)[1].strip()
        elif depouillee.upper().startswith("MESSAGE:"):
            message = depouillee.split(":", 1)[1].strip()
        elif message is not None and depouillee:
            message += " " + depouillee        # message sur plusieurs lignes

    if expediteur and expediteur.lower() in ("inconnu", "", "none", "null"):
        expediteur = None
    if not message:
        _tracer("capture lue, mais aucun message reconnu")
        return None, None
    return expediteur, message[:TAILLE_MAX]


# --- Expéditeur -------------------------------------------------------------
#
# Relevés dans le document de collecte de l'équipe. Un SMS qui se réclame d'un
# opérateur mais n'arrive pas par l'un de ces canaux est incohérent.

EXPEDITEURS_OFFICIELS = {
    "Orange": ("orange", "tv orange", "info orange", "bonusorange",
               "mardi bonus", "bonus data", "bonsplansom", "max it",
               "orangemoney", "maxit"),
    "Wave": ("wave ci", "wave"),
    "MTN": ("mtn bonus", "mtn astuces", "mtn cchic", "kdo mtn", "mtn",
            "momo"),
    "Moov": ("moovmoney", "mymoov", "moov africa", "moovprotect", "moov tv",
             "app mymoov", "gbesse", "moovtones", "data nuit", "promo gigas",
             "moov fibre", "10go data", "200% bonus", "+123", "moov"),
}

# Numéros de service client officiels : un SMS peut légitimement en venir.
NUMEROS_SERVICE_CLIENT = ("1315", "555", "1010", "0707", "0909",
                          "+22507006060 60", "+225 05 46 46 46 46", "123")

# Noms de marque cherchés DANS LE TEXTE pour savoir si le message se réclame
# d'un opérateur. À ne pas confondre avec EXPEDITEURS_OFFICIELS, qui liste les
# canaux d'envoi : « OMCI » est une marque mais n'est le nom d'aucun canal, et
# un message signé « OMCI vous remercie » arrivant du « +454 » passait donc à
# travers la règle d'usurpation.
#
# Cherchés en mots entiers : « om » collé dans « nom » ou « prénom »
# reconnaîtrait Orange dans n'importe quel message.
MARQUEURS_MARQUE = (
    "orange", "orangemoney", "orange money", "om", "omci", "max it", "maxit",
    "wave", "wave ci",
    "mtn", "momo", "mtn momo",
    "moov", "moovmoney", "moov money", "mymoov", "moov africa", "flooz",
)

MOTIF_MARQUE = re.compile(
    r"\b(?:" + "|".join(re.escape(m) for m in MARQUEURS_MARQUE) + r")\b"
)


def expediteur_est_officiel(expediteur):
    """Dit si l'expéditeur affiché est un canal officiel connu."""
    if not expediteur:
        return False
    nom = " ".join(expediteur.lower().translate(ACCENTS).split())
    compact = nom.replace(" ", "")
    for canaux in EXPEDITEURS_OFFICIELS.values():
        if any(canal in nom for canal in canaux):
            return True
    return any(numero.replace(" ", "") == compact
               for numero in NUMEROS_SERVICE_CLIENT)


# --- Validation -------------------------------------------------------------

# Ce que le modèle peut écrire pour dire « vrai », en français comme en anglais.
MOTS_VRAIS = {"true", "vrai", "oui", "yes", "y", "o", "1", "1.0"}

# Ce qu'il peut écrire pour dire « aucun organisme ».
MOTS_VIDES = {"", "null", "none", "nil", "aucun", "aucune", "n/a", "na", "-", "non"}

NOMS_DE_LANGUES = {
    "français": "fr", "francais": "fr", "french": "fr",
    "anglais": "en", "english": "en",
    "arabe": "ar", "arabic": "ar",
}

MOTS_DE_CONFIANCE = {"haute": 0.8, "elevee": 0.8, "élevée": 0.8,
                     "moyenne": 0.5, "faible": 0.2, "basse": 0.2}


def _compter_cles_connues(objet):
    """Nombre de clés du contrat présentes dans cet objet."""
    return sum(1 for cle in SIGNAUX_PAR_DEFAUT if cle in objet)


def _objet_du_contrat(objet, profondeur=0):
    """Rend l'objet s'il porte le contrat, sinon le cherche dans ses valeurs.

    Le modèle enveloppe parfois sa réponse : {"resultat": {...}} ou
    {"analyse": {...}}. On descend donc de quelques niveaux.
    """
    if _compter_cles_connues(objet) >= MIN_CLES_RECONNUES:
        return objet
    if profondeur >= 3:
        return None
    for valeur in objet.values():
        if isinstance(valeur, dict):
            trouve = _objet_du_contrat(valeur, profondeur + 1)
            if trouve is not None:
                return trouve
    return None


def trouver_objet_json(brut):
    """Extrait le premier objet JSON exploitable d'une réponse brute.

    Tolère le texte avant et après, les blocs de code, les accolades
    orphelines. Rend None si rien d'exploitable.
    """
    if not isinstance(brut, str):
        return None

    decodeur = json.JSONDecoder()
    for position, caractere in enumerate(brut):
        if caractere != "{":
            continue
        try:
            objet, _ = decodeur.raw_decode(brut, position)
        except ValueError:
            continue          # Accolade qui n'ouvre rien de valide : on avance.
        if isinstance(objet, dict):
            trouve = _objet_du_contrat(objet)
            if trouve is not None:
                return trouve
    return None


def forcer_booleen(valeur):
    """Rend un vrai booléen. Tout ce qui est douteux devient False."""
    if isinstance(valeur, bool):
        return valeur
    if isinstance(valeur, (int, float)):
        return valeur != 0
    if isinstance(valeur, str):
        return valeur.strip().lower() in MOTS_VRAIS
    return False


def forcer_institution(valeur):
    """Rend un nom d'organisme propre, ou None."""
    if isinstance(valeur, list):
        valeur = valeur[0] if valeur else None
    if not isinstance(valeur, str):
        return None
    nom = " ".join(valeur.split())        # Espaces et sauts de ligne normalisés.
    if nom.lower() in MOTS_VIDES:
        return None
    return nom[:LONGUEUR_INSTITUTION]


def forcer_langue(valeur):
    """Rend un code de langue court. Défaut : fr."""
    if not isinstance(valeur, str):
        return "fr"
    langue = valeur.strip().lower()
    if langue in NOMS_DE_LANGUES:
        return NOMS_DE_LANGUES[langue]
    if 2 <= len(langue) <= 3 and langue.isalpha():
        return langue
    return "fr"


def forcer_motif(valeur):
    """Rend un texte court. Champ interne, jamais affiché tel quel."""
    if valeur is None:
        return ""
    if not isinstance(valeur, str):
        valeur = str(valeur)
    return " ".join(valeur.split())[:LONGUEUR_MOTIF]


def forcer_confiance(valeur):
    """Rend un flottant entre 0.0 et 1.0."""
    if isinstance(valeur, bool):
        return 1.0 if valeur else 0.0
    if isinstance(valeur, str):
        texte = valeur.strip().lower().replace(",", ".").rstrip("%")
        if texte in MOTS_DE_CONFIANCE:
            return MOTS_DE_CONFIANCE[texte]
        try:
            valeur = float(texte)
        except ValueError:
            return 0.0
    if not isinstance(valeur, (int, float)):
        return 0.0
    valeur = float(valeur)
    if valeur > 1.0:          # Le modèle a écrit un pourcentage : 90 vaut 0.9.
        valeur = valeur / 100.0
    return max(0.0, min(1.0, valeur))


# --- Contre-épreuve de la règle absolue au signal unique --------------------
#
# `demande_code_secret` est la seule règle absolue qui repose sur un champ et
# un seul : elle suffit à elle seule à déclencher le rouge. Or `qwen2.5:3b` la
# coche en voyant un code USSD public (#144*82#) dans un vrai message
# promotionnel d'opérateur, même après trois formulations du prompt.
#
# Le signal ne tient que dans deux cas :
#   - le texte nomme une chose secrète par nature (PIN, OTP, mot de passe...) ;
#   - ou il contient le mot « code » ET un verbe qui réclame quelque chose.
# Sinon on l'éteint. « Votre code de retrait est 8412 » — un vrai SMS
# d'opérateur, très courant — tombe dans ce dernier cas : le mot « code » y
# est, mais personne n'y demande rien.
#
# Ce garde-fou n'allume JAMAIS un signal, il ne fait qu'en éteindre un
# manifestement infondé. Le modèle reste seul juge de ce qu'il constate ; le
# code se contente de refuser l'impossible. À revérifier sur Nemotron, qui
# n'en aura peut-être pas besoin.

# Nommer ces choses-là suffit à rendre le signal plausible : elles sont
# secrètes par définition.
MOTS_SECRETS = ("secret", "confidentiel", "pin", "otp", "mot de passe",
                "motdepasse", "mdp", "password", "passcode")

# « code » seul est ambigu : code USSD, code promo, code de retrait, code de
# transaction. Il lui faut un verbe qui réclame.
VERBES_DE_DEMANDE = (
    "envoy", "renvoy", "communiqu", "confirm", "donnez", "donner", "transmet",
    "partag", "fourni", "indiqu", "repond", "saisi", "tapez", "entrez",
    "dites", "valid", "requis", "besoin", "necessaire", "demand",
    "send", "give", "share", "provide", "enter", "reply",
)

ACCENTS = str.maketrans("àâäçéèêëîïôöùûüÿ", "aaaceeeeiioouuuy")

# Formules qui racontent une opération déjà faite ou en cours.
FORMULES_NOTIFICATION = (
    "vous avez recu", "tu as recu", "vous avez retire", "vous avez effectue",
    "vous allez", "nouveau solde", "solde:", "solde ", "a ete effectue",
    "a ete annule", "transfert reussi", "paiement de", "depot de",
    "retrait de", "achat de", "vous remercie",
)

# Verbes qui réclament réellement un envoi d'argent. Leur présence empêche
# d'éteindre le signal : « j'ai envoyé par erreur, RENVOIE-moi » doit rester.
VERBES_D_ENVOI = (
    "envoie", "envoyez", "envoyer", "renvoie", "renvoyez", "renvoyer",
    "verse", "versez", "paye", "payez", "payer", "depose", "deposez",
    "transfere", "transferez", "rembourse", "remboursez", "reglez",
    "recharge", "rechargez", "send me", "pay ",
)


# --- Vérification des liens -------------------------------------------------
#
# Le modèle juge mal les adresses web : il n'a pas vu « wave-ci-verif.xyz »
# comme suspect. Or dans les messages relevés par l'équipe, le lien est la
# seule chose qui sépare une arnaque d'une vraie promotion : « Cadeau de
# 10 000 F, cliquez ici » est frauduleux avec cloudaccess.host, légitime avec
# le domaine de l'opérateur.
#
# Contrairement à la contre-épreuve du code secret, ces listes peuvent ALLUMER
# `lien_suspect`. Ce n'est pas une heuristique sur les mots du message :
# vérifier qu'une adresse appartient au domaine officiel d'une marque est un
# fait objectif. Le code constate une adresse, il ne juge pas le texte.

# Domaines officiels, relevés dans le document de collecte de l'équipe.
DOMAINES_OFFICIELS = (
    "orange.ci", "wave.com", "mtn.ci", "moov-africa.ci", "jumia.ci",
    "orange.com", "mtn.com", "moov-africa.com",
)

# Hébergeurs gratuits et extensions bon marché, relevés dans les faux cadeaux
# du jeu de messages : netlify.app, cloudaccess.host, th8h.xyz, xvw63.top,
# ujkuw.top.
HEBERGEURS_GRATUITS = (
    "netlify.app", "cloudaccess.host", "github.io", "weebly.com",
    "glitch.me", "vercel.app", "pages.dev", "000webhostapp.com",
)
EXTENSIONS_SUSPECTES = (".xyz", ".top", ".tk", ".buzz", ".host", ".click",
                        ".icu", ".cfd", ".rest")

# Terminaisons admises pour qu'une suite de caractères soit tenue pour une
# adresse. Sans cette liste, « Merci.Votre solde » passerait pour un domaine.
TERMINAISONS_CONNUES = (
    "ci", "com", "net", "org", "info", "biz", "app", "host", "io", "me",
    "ly", "tk", "xyz", "top", "buzz", "site", "online", "shop", "store",
    "africa", "fr", "sn", "ml", "bf", "tg", "bj", "ne", "dev", "cloud",
    "click", "icu", "cfd", "rest", "link",
)

MOTIF_LIEN = re.compile(
    r"(?:https?://)?(?:www\.)?"
    r"((?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+(?:" +
    "|".join(TERMINAISONS_CONNUES) + r"))"
    r"(?:[/?#][^\s]*)?",
    re.IGNORECASE,
)


def trouver_domaines(texte):
    """Liste les domaines des adresses web présentes dans le texte."""
    return [domaine.lower() for domaine in MOTIF_LIEN.findall(texte)]


def _domaine_officiel(domaine):
    return any(domaine == officiel or domaine.endswith("." + officiel)
               for officiel in DOMAINES_OFFICIELS)


def _domaine_douteux(domaine):
    return (any(h in domaine for h in HEBERGEURS_GRATUITS)
            or domaine.endswith(EXTENSIONS_SUSPECTES))


def juger_liens(texte):
    """Rend (au_moins_un_lien, tous_officiels, au_moins_un_douteux)."""
    domaines = trouver_domaines(texte)
    if not domaines:
        return False, False, False
    return (True,
            all(_domaine_officiel(d) for d in domaines),
            any(_domaine_douteux(d) for d in domaines))


def corriger_signaux(signaux, message, expediteur=None):
    """Éteint les signaux que le texte rend impossibles. N'en allume aucun."""
    texte = (message or "").lower().translate(ACCENTS)

    # L'expéditeur n'est connu que si la personne a envoyé une capture.
    # C'est le signal le plus sûr dont on dispose : un message qui se réclame
    # d'un opérateur sans venir de son canal officiel est une usurpation.
    if expediteur:
        marque_citee = bool(MOTIF_MARQUE.search(texte))
        if expediteur_est_officiel(expediteur):
            if signaux["expediteur_incoherent"]:
                _tracer("expediteur_incoherent éteint : canal officiel connu")
            signaux["expediteur_incoherent"] = False
        elif marque_citee:
            if not signaux["expediteur_incoherent"]:
                _tracer("expediteur_incoherent allumé : opérateur cité, "
                        "expéditeur non officiel")
            signaux["expediteur_incoherent"] = True

    if signaux["demande_code_secret"]:
        secret_nomme = any(mot in texte for mot in MOTS_SECRETS)
        code_reclame = "code" in texte and any(
            verbe in texte for verbe in VERBES_DE_DEMANDE
        )
        if not (secret_nomme or code_reclame):
            _tracer("demande_code_secret éteint : le texte ne réclame aucun code")
            signaux["demande_code_secret"] = False

    # Le modèle confond « recevoir de l'argent » et « en réclamer » : il coche
    # demande_argent sur « Vous avez reçu 25 000F » ou « Vous allez faire un
    # retrait », c'est-à-dire sur les deux SMS les plus courants du mobile
    # money. Une notification raconte une opération ; elle ne demande rien.
    #
    # On ne s'appuie surtout pas sur l'expéditeur pour éteindre ce signal :
    # un escroc peut afficher « WAVE CI » comme nom d'expéditeur, et cela
    # ouvrirait un angle mort. On s'en tient à ce que dit le texte.
    if signaux["demande_argent"]:
        raconte_une_operation = any(f in texte for f in FORMULES_NOTIFICATION)
        reclame_un_envoi = any(v in texte for v in VERBES_D_ENVOI)
        if raconte_une_operation and not reclame_un_envoi:
            _tracer("demande_argent éteint : notification, pas une demande")
            signaux["demande_argent"] = False

    # Les liens sont vérifiés, pas devinés.
    lien_trouve, tous_officiels, un_douteux = juger_liens(texte)
    if lien_trouve:
        signaux["lien_present"] = True
        if un_douteux:
            if not signaux["lien_suspect"]:
                _tracer("lien_suspect allumé : hébergeur gratuit ou extension "
                        "inhabituelle")
            signaux["lien_suspect"] = True
        elif tous_officiels:
            if signaux["lien_suspect"]:
                _tracer("lien_suspect éteint : domaine officiel d'opérateur")
            signaux["lien_suspect"] = False
        # Entre les deux, on laisse au modèle ce qu'il a constaté.

    return signaux


def valider_signaux(brut):
    """Transforme une réponse brute en signaux conformes au contrat.

    Rend None si la réponse ne contient rien d'exploitable — c'est le seul
    cas où l'appelant doit envisager une reprise.
    """
    objet = trouver_objet_json(brut)
    if objet is None:
        return None

    signaux = dict(SIGNAUX_PAR_DEFAUT)
    for cle in CLES_BOOLEENNES:
        if cle in objet:
            signaux[cle] = forcer_booleen(objet[cle])
    signaux["institution_invoquee"] = forcer_institution(
        objet.get("institution_invoquee")
    )
    signaux["langue"] = forcer_langue(objet.get("langue"))
    signaux["motif_principal"] = forcer_motif(objet.get("motif_principal"))
    signaux["confiance_extraction"] = forcer_confiance(
        objet.get("confiance_extraction")
    )
    return signaux


def extraire_signaux(message, expediteur=None):
    """Étage 1 complet : message en entrée, signaux validés en sortie.

    Rend le couple (signaux, extraction_reussie). Une seule reprise. Si la
    reprise échoue aussi, rend les valeurs par défaut et False : à l'appelant
    de basculer sur le verdict orange de repli.

    Ne lève jamais.
    """
    message = (message or "")[:TAILLE_MAX]

    for essai in (1, 2):
        insister = essai == 2
        # À la reprise, on retire response_format : si c'est lui que le
        # serveur refuse, le second appel a une chance de passer.
        format_json = essai == 1
        try:
            brut = interroger_modele(message, format_json=format_json,
                                     insister=insister)
        except Exception as erreur:
            _tracer(f"appel {essai} en échec : {type(erreur).__name__}")
            continue

        signaux = valider_signaux(brut)
        if signaux is not None:
            if essai == 2:
                _tracer("reprise réussie")
            return corriger_signaux(signaux, message, expediteur), True
        _tracer(f"réponse {essai} inexploitable")

    _tracer("extraction abandonnée, repli sur les valeurs par défaut")
    return dict(SIGNAUX_PAR_DEFAUT), False


# --- Essais en console ------------------------------------------------------

MESSAGES_ESSAI = [
    # Arnaque au code
    "Orange Money: votre compte sera suspendu. Confirmez votre code secret "
    "a 4 chiffres en repondant a ce message avant 18h sinon blocage definitif.",
    # Faux transfert
    "Bonjour mon frere jai envoye 50000 sur ton numero par erreur avec Wave, "
    "stp renvoie moi largent au 07xxxxxxx cest tout ce que javais",
    # Vrai message d'operateur
    "Vous avez recu 15 000 FCFA de KOUAME YAO. Nouveau solde: 18 250 FCFA. "
    "Frais: 0 FCFA. ID transaction: PP240915.1432.C48291",
]

# Réponses volontairement cassées. (nom, réponse brute, contrôles attendus)
# Un contrôle à None signifie : la validation doit échouer.
REPONSES_CASSEES = [
    (
        "JSON propre",
        '{"demande_code_secret": true, "demande_argent": false, '
        '"urgence_artificielle": true, "menace_ou_sanction": true, '
        '"institution_invoquee": "Orange Money", "langue": "fr", '
        '"motif_principal": "demande le code", "confiance_extraction": 0.8}',
        {"demande_code_secret": True, "institution_invoquee": "Orange Money",
         "confiance_extraction": 0.8},
    ),
    (
        "bavardage autour du JSON",
        'Bien sûr ! Voici mon analyse du message :\n'
        '{"demande_argent": true, "gain_non_sollicite": true, '
        '"lien_present": false, "confiance_extraction": 0.9}\n'
        "J'espère que cela vous aide.",
        {"demande_argent": True, "gain_non_sollicite": True},
    ),
    (
        "bloc de code markdown",
        '```json\n{"demande_code_secret": true, "lien_suspect": true, '
        '"lien_present": true, "langue": "fr"}\n```',
        {"demande_code_secret": True, "lien_suspect": True},
    ),
    (
        "objet enveloppé",
        '{"resultat": {"analyse": {"demande_argent": true, '
        '"pretend_erreur_transfert": true, "menace_ou_sanction": false, '
        '"langue": "fr"}}}',
        {"demande_argent": True, "pretend_erreur_transfert": True},
    ),
    (
        "booléens en toutes lettres",
        '{"demande_code_secret": "oui", "demande_argent": "Non", '
        '"urgence_artificielle": "TRUE", "menace_ou_sanction": "peut-être", '
        '"gain_non_sollicite": 1}',
        {"demande_code_secret": True, "demande_argent": False,
         "urgence_artificielle": True, "menace_ou_sanction": False,
         "gain_non_sollicite": True},
    ),
    (
        "confiance hors bornes et virgule française",
        '{"demande_argent": true, "urgence_artificielle": true, '
        '"lien_present": false, "confiance_extraction": "0,85"}',
        {"confiance_extraction": 0.85},
    ),
    (
        "confiance en pourcentage",
        '{"demande_argent": true, "urgence_artificielle": true, '
        '"lien_present": false, "confiance_extraction": 90}',
        {"confiance_extraction": 0.9},
    ),
    (
        "confiance en toutes lettres",
        '{"demande_argent": true, "urgence_artificielle": true, '
        '"lien_present": false, "confiance_extraction": "haute"}',
        {"confiance_extraction": 0.8},
    ),
    (
        "clés manquantes",
        '{"demande_argent": true, "urgence_artificielle": true, '
        '"lien_present": true, "menace_ou_sanction": false}',
        {"demande_code_secret": False, "institution_invoquee": None,
         "langue": "fr", "motif_principal": "", "confiance_extraction": 0.0},
    ),
    (
        "clés en trop",
        '{"demande_argent": true, "urgence_artificielle": false, '
        '"lien_present": false, "menace_ou_sanction": false, '
        '"verdict": "ARNAQUE", "score": 95, "conseil": "ne répondez pas"}',
        {"demande_argent": True},
    ),
    (
        "institution vide ou factice",
        '{"demande_argent": true, "urgence_artificielle": false, '
        '"lien_present": false, "institution_invoquee": "aucune"}',
        {"institution_invoquee": None},
    ),
    (
        "institution en liste",
        '{"demande_argent": true, "urgence_artificielle": false, '
        '"lien_present": false, "institution_invoquee": ["Wave", "MTN"]}',
        {"institution_invoquee": "Wave"},
    ),
    (
        "motif de 500 caractères",
        '{"demande_argent": true, "urgence_artificielle": false, '
        '"lien_present": false, "motif_principal": "' + "a" * 500 + '"}',
        {"motif_principal": "a" * LONGUEUR_MOTIF},
    ),
    (
        "langue en toutes lettres",
        '{"demande_argent": true, "urgence_artificielle": false, '
        '"lien_present": false, "langue": "Français"}',
        {"langue": "fr"},
    ),
    (
        "valeurs nulles partout",
        '{"demande_code_secret": null, "demande_argent": null, '
        '"lien_present": null, "langue": null, "motif_principal": null, '
        '"confiance_extraction": null}',
        {"demande_code_secret": False, "langue": "fr", "motif_principal": "",
         "confiance_extraction": 0.0},
    ),
    (
        "accolade orpheline avant le vrai objet",
        'Analyse { incomplète ici... puis la vraie réponse : '
        '{"demande_code_secret": true, "demande_argent": false, '
        '"lien_present": false, "menace_ou_sanction": true}',
        {"demande_code_secret": True, "menace_ou_sanction": True},
    ),
    # --- À partir d'ici, la validation doit échouer proprement. ---
    ("réponse vide", "", None),
    ("réponse None", None, None),
    ("texte sans JSON", "Je ne peux pas analyser ce message, désolé.", None),
    ("JSON tronqué", '{"demande_code_secret": true, "demande_arg', None),
    ("liste au lieu d'objet", '[{"demande_code_secret": true}]', None),
    ("objet vide", "{}", None),
    ("objet hors contrat", '{"reponse": "ok", "statut": 200}', None),
    (
        "trop peu de clés du contrat",
        '{"demande_argent": true, "bavardage": "voici"}',
        None,
    ),
]


def _essais_validation():
    """Passe toutes les réponses cassées. Aucune ne doit lever."""
    echecs = 0
    for nom, brut, attendus in REPONSES_CASSEES:
        try:
            signaux = valider_signaux(brut)
        except Exception as erreur:
            print(f"  LEVE   {nom} : {type(erreur).__name__}")
            echecs += 1
            continue

        if attendus is None:
            if signaux is None:
                print(f"  ok     {nom} -> rejet propre")
            else:
                print(f"  RATE   {nom} : accepté alors qu'il fallait rejeter")
                echecs += 1
            continue

        if signaux is None:
            print(f"  RATE   {nom} : rejeté alors qu'il fallait accepter")
            echecs += 1
            continue
        if set(signaux) != set(SIGNAUX_PAR_DEFAUT):
            print(f"  RATE   {nom} : les 16 clés ne sont pas toutes là")
            echecs += 1
            continue

        ecarts = [
            f"{cle}={signaux[cle]!r} au lieu de {attendu!r}"
            for cle, attendu in attendus.items()
            if signaux[cle] != attendu
        ]
        if ecarts:
            print(f"  RATE   {nom} : " + " ; ".join(ecarts))
            echecs += 1
        else:
            print(f"  ok     {nom}")
    return echecs


def _essais_contre_epreuve():
    """La contre-épreuve éteint l'infondé et ne touche à rien d'autre."""
    # (nom, message, code_secret rendu par le modèle, valeur attendue après)
    cas = [
        ("promo USSD, aucun mot de code",
         "Orange: profitez de 10 Go a 2000F. Composez #144*82# pour activer.",
         True, False),
        ("arnaque au code : le mot est là, on n'y touche pas",
         "Confirmez votre code secret a 4 chiffres en repondant a ce message.",
         True, True),
        ("mot de passe en toutes lettres",
         "Envoyez votre mot de passe pour debloquer le compte.",
         True, True),
        ("accents : « reçu par SMS » avec cédille",
         "Communiquez-nous le côde reçu par SMS.",
         True, True),
        ("message anglais",
         "Please send your password to unlock your account.",
         True, True),
        ("signal déjà éteint : rien à faire",
         "Composez #144# pour activer votre forfait.",
         False, False),
        ("message vide",
         "", True, False),
        # Vrais SMS d'opérateur qui contiennent le mot « code ».
        ("code de retrait communiqué, pas demandé",
         "Retrait de 25 000 FCFA chez AGENT KOFFI. Votre code de retrait est 8412.",
         True, False),
        ("code de transaction dans un reçu",
         "Transfert reussi. Code de transaction: PP240915.1432.C48291",
         True, False),
        ("code promo",
         "Utilisez le code promo ETE2024 pour 20% de reduction.",
         True, False),
        # Arnaques à ne surtout pas éteindre.
        ("code PIN réclamé sans le mot « secret »",
         "Votre code PIN est requis pour valider la transaction.",
         True, True),
        ("code à renvoyer",
         "Un code vient de vous etre envoye. Renvoyez-le nous pour confirmer.",
         True, True),
    ]

    echecs = 0
    for nom, message, valeur_modele, attendu in cas:
        signaux = dict(SIGNAUX_PAR_DEFAUT)
        signaux["demande_code_secret"] = valeur_modele
        try:
            corriges = corriger_signaux(signaux, message)
        except Exception as erreur:
            print(f"  LEVE   {nom} : {type(erreur).__name__}")
            echecs += 1
            continue
        if corriges["demande_code_secret"] is not attendu:
            print(f"  RATE   {nom} : code_secret={corriges['demande_code_secret']}"
                  f" au lieu de {attendu}")
            echecs += 1
        else:
            print(f"  ok     {nom}")
    return echecs


def _essais_liens():
    """Liste blanche et liste noire, sur les domaines réellement relevés."""
    # (nom, message, lien_suspect rendu par le modèle, valeur attendue après)
    cas = [
        # Faux cadeaux du jeu de messages : la liste noire les allume.
        ("faux cadeau Wave sur cloudaccess.host",
         "Cadeau de 10.000F CFA offert. Cliquez ici : "
         "https://waveciv.cloudaccess.host/ L'equipe Wave", False, True),
        ("faux cadeau sur netlify.app",
         "Votre fidelite est recompensee https://wavekdo.netlify.app/", False, True),
        ("faux cadeau en .xyz",
         "Wave Anniversaire : 12 000 F CFA. "
         "https://wave230.th8h.xyz/?wave=1073", False, True),
        ("faux Jumia en .top",
         "Jumia Anniversaire Cadeau https://jumia.xvw63.top/", False, True),
        # Promotions légitimes : la liste blanche les éteint.
        ("promo Orange officielle",
         "Soiree Foot sur Max it ! Vivez le match https://www.orange.ci/maxit",
         True, False),
        ("promo Moov officielle",
         "Offre la tablette Edukids. Commande sur "
         "https://www.moov-africa.ci/edukids", True, False),
        ("sous-domaine officiel",
         "Votre compte OM est debloque via https://link.orange.ci/MxtOM",
         True, False),
        # Ni l'un ni l'autre : on laisse au modèle ce qu'il a constaté.
        ("domaine inconnu, modèle méfiant",
         "Resultats du concours sur https://minef.ciconcours.com/", True, True),
        ("domaine inconnu, modèle confiant",
         "Coupons Jumia https://l.cnct.ly/coupons", False, False),
        # Aucun lien : rien ne doit bouger.
        ("aucun lien",
         "Confirmez votre code secret avant 18h.", False, False),
        # Le piège de l'expression régulière.
        ("phrase mal ponctuée, pas un lien",
         "Merci.Votre solde est de 3 100 FCFA.Bonne journee", False, False),
        ("référence de transaction, pas un lien",
         "Transfert reussi. Ref: PP240915.1432.C48291", False, False),
    ]

    echecs = 0
    for nom, message, valeur_modele, attendu in cas:
        signaux = dict(SIGNAUX_PAR_DEFAUT)
        signaux["lien_suspect"] = valeur_modele
        signaux["lien_present"] = valeur_modele
        try:
            corriges = corriger_signaux(signaux, message.lower())
        except Exception as erreur:
            print(f"  LEVE   {nom} : {type(erreur).__name__}")
            echecs += 1
            continue
        if corriges["lien_suspect"] is not attendu:
            print(f"  RATE   {nom} : lien_suspect="
                  f"{corriges['lien_suspect']} au lieu de {attendu}")
            echecs += 1
        else:
            print(f"  ok     {nom}")
    return echecs


def _essais_reprise():
    """Vérifie la reprise unique, sans toucher au modèle."""
    vrai_appel = globals()["interroger_modele"]
    echecs = 0

    scenarios = [
        ("première réponse cassée, reprise bonne",
         ["pas du JSON", '{"demande_code_secret": true, "demande_argent": false, '
                         '"lien_present": false, "langue": "fr"}'],
         True, True),
        ("les deux réponses cassées",
         ["pas du JSON", "toujours pas du JSON"],
         False, False),
        ("premier appel en erreur, reprise bonne",
         [ConnectionError("serveur injoignable"),
          '{"demande_argent": true, "urgence_artificielle": true, '
          '"lien_present": false, "langue": "fr"}'],
         True, True),
        ("les deux appels en erreur",
         [TimeoutError("hors délai"), TimeoutError("hors délai")],
         False, False),
    ]

    for nom, reponses, reussite_attendue, signal_attendu in scenarios:
        compteur = {"appels": 0}

        def faux_appel(message, format_json=True, insister=False, _r=reponses,
                       _c=compteur):
            reponse = _r[_c["appels"]]
            _c["appels"] += 1
            if isinstance(reponse, Exception):
                raise reponse
            return reponse

        globals()["interroger_modele"] = faux_appel
        try:
            signaux, reussite = extraire_signaux("message de test")
        except Exception as erreur:
            print(f"  LEVE   {nom} : {type(erreur).__name__}")
            echecs += 1
            continue
        finally:
            globals()["interroger_modele"] = vrai_appel

        if compteur["appels"] > 2:
            print(f"  RATE   {nom} : {compteur['appels']} appels, 2 au maximum")
            echecs += 1
        elif reussite is not reussite_attendue:
            print(f"  RATE   {nom} : réussite={reussite}")
            echecs += 1
        elif set(signaux) != set(SIGNAUX_PAR_DEFAUT):
            print(f"  RATE   {nom} : les 16 clés ne sont pas toutes là")
            echecs += 1
        elif not reussite and any(signaux[c] for c in CLES_BOOLEENNES):
            print(f"  RATE   {nom} : le repli devrait être tout à false")
            echecs += 1
        else:
            print(f"  ok     {nom} ({compteur['appels']} appel(s))")

    return echecs


if __name__ == "__main__":
    import time

    # La console Windows est en cp1252 : sans ça, les accents s'affichent mal.
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

    if "--modele" in sys.argv:
        for numero, essai in enumerate(MESSAGES_ESSAI, start=1):
            print(f"\n=== Message {numero} " + "=" * 50)
            print(essai)
            debut = time.time()
            signaux, reussite = extraire_signaux(essai)
            print(f"\n--- signaux validés ({time.time() - debut:.1f} s, "
                  f"extraction {'réussie' if reussite else 'en échec'}) ---")
            print(json.dumps(signaux, indent=2, ensure_ascii=False))
        raise SystemExit(0)

    print("=== Validation des réponses cassées " + "=" * 30)
    echecs = _essais_validation()
    print("\n=== Contre-épreuve du code secret " + "=" * 32)
    echecs += _essais_contre_epreuve()
    print("\n=== Liens : liste blanche et liste noire " + "=" * 25)
    echecs += _essais_liens()
    print("\n=== Reprise unique " + "=" * 47)
    echecs += _essais_reprise()

    total = len(REPONSES_CASSEES) + 12 + 12 + 4
    print(f"\n{total - echecs}/{total} essais passés.")
    if echecs:
        print("Étape 2 non validée.")
        raise SystemExit(1)
    print("Aucune exception n'est remontée. Étape 2 validée.")
    print("Pour les appels réels : python signals.py --modele")

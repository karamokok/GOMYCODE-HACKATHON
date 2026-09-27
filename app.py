"""Interface Gradio et câblage.

Ce fichier ne contient aucune logique d'analyse : il appelle detector.analyser()
et met en forme ce qu'il reçoit. Les deux constantes de connexion sont dans
signals.py, pas ici.
"""

import html

import gradio as gr

import detector
import templates

TITRE = "Ce message est-il une arnaque ?"

SOUS_TITRE = (
    "Colle un SMS ou un message WhatsApp que tu trouves louche. "
    "Spécialisé sur les arnaques au mobile money."
)

# Cette mention doit rester vraie : aucun journal ne contient le texte des
# messages, et les mesures d'audience de Gradio sont coupées plus bas.
MENTION_VIE_PRIVEE = "Ton message est analysé puis effacé. Rien n'est conservé."

LIBELLE_BOUTON = "Analyser le message"
LIBELLE_BOUTON_OCCUPE = "Analyse en cours…"

CONSEIL_CAPTURE = (
    "**C'est la meilleure façon de faire.** La capture montre aussi le nom ou "
    "le numéro de l'expéditeur, et c'est souvent lui qui trahit l'arnaque."
)

AVERTISSEMENT_TEXTE = (
    "En copiant le texte, le nom de l'expéditeur est perdu. "
    "L'analyse sera moins sûre qu'avec une capture d'écran."
)

MESSAGE_SANS_CAPTURE = (
    "Envoie une capture d'écran du message pour que je puisse l'analyser."
)

# Trois exemples cliquables : une arnaque au code, un faux transfert, un vrai
# message d'opérateur.
EXEMPLES = [
    (
        "Arnaque au code",
        "Orange Money: votre compte sera suspendu. Confirmez votre code secret "
        "a 4 chiffres en repondant a ce message avant 18h sinon blocage definitif.",
    ),
    (
        "Faux transfert",
        "Bonjour mon frere jai envoye 50000 sur ton numero par erreur avec Wave, "
        "stp renvoie moi largent au 07xxxxxxx cest tout ce que javais",
    ),
    (
        "Vrai message d'opérateur",
        "Vous avez recu 15 000 FCFA de KOUAME YAO. Nouveau solde: 18 250 FCFA. "
        "Frais: 0 FCFA. ID transaction: PP240915.1432.C48291",
    ),
]

CSS = """
.bloc-verdict {
    border-left: 6px solid;
    border-radius: 8px;
    padding: 18px 20px;
    margin-top: 8px;
}
/* Gradio colore le texte en blanc dans son thème sombre, y compris à
   l'intérieur de nos blocs au fond clair : le texte devenait invisible.
   On force chaque élément à reprendre la couleur de son bloc. */
.bloc-verdict *, .avertissement * { color: inherit !important; }
.bloc-verdict .titre { font-size: 1.45em; font-weight: 700; margin: 0; }
.bloc-verdict .sous-titre { font-size: 1.05em; margin: 4px 0 14px 0; }
.bloc-verdict ul, .bloc-verdict ol { margin: 0 0 4px 0; padding-left: 22px; }
.bloc-verdict li { margin-bottom: 7px; line-height: 1.45; }
.bloc-verdict .intitule-conduite {
    font-weight: 700; margin: 16px 0 6px 0;
}
.verdict-rouge  { background:#fdecea; border-color:#c0392b; color:#6b1410; }
.verdict-orange { background:#fff4e5; border-color:#d97706; color:#6b2710; }
.verdict-vert   { background:#eaf6ec; border-color:#2e7d32; color:#123f23; }
.verdict-neutre { background:#eef1f5; border-color:#64748b; color:#1e293b; }
.avertissement {
    background:#fff4e5; border-left:6px solid #d97706; color:#7c2d12;
    border-radius:8px; padding:10px 14px; margin-bottom:10px;
}
/* La consigne officielle de l'opérateur : présente, mais en retrait de la
   conduite à tenir, qui reste l'information principale. */
.bloc-verdict .consigne-operateur {
    margin: 16px 0 0 0;
    padding-top: 12px;
    border-top: 1px solid rgba(0,0,0,0.15);
    font-size: 0.95em;
    opacity: 0.85;
}
.mention-vie-privee { font-size: 0.9em; opacity: 0.75; margin-top: -6px; }
"""


def _bloc(classe, contenu):
    return f'<div class="bloc-verdict {classe}">{contenu}</div>'


def _html_resultat(analyse):
    """Met en forme une detector.Analyse. Ne décide de rien."""
    morceaux = []

    if analyse.avertissement:
        avertissement = html.escape(analyse.avertissement)
        if analyse.sortie is None:
            # Entrée trop courte : l'invite tient lieu de résultat.
            return _bloc("verdict-neutre", f'<p class="titre">{avertissement}</p>')
        morceaux.append(f'<div class="avertissement">{avertissement}</div>')

    sortie = analyse.sortie
    explications = "".join(
        f"<li>{html.escape(phrase)}</li>" for phrase in sortie.explications
    )
    conduite = "".join(
        f"<li>{html.escape(phrase)}</li>" for phrase in sortie.conduite
    )
    morceaux.append(_bloc(
        f"verdict-{sortie.couleur}",
        f'<p class="titre">{html.escape(sortie.titre)}</p>'
        f'<p class="sous-titre">{html.escape(sortie.sous_titre)}</p>'
        f"<ul>{explications}</ul>"
        f'<p class="intitule-conduite">À faire maintenant</p>'
        f"<ol>{conduite}</ol>"
        f'<p class="consigne-operateur">'
        f"{html.escape(sortie.consigne_operateur)}</p>"
    ))
    return "".join(morceaux)


def _analyser_capture(image):
    """Appelé par le bouton de la capture. Ne doit JAMAIS lever non plus."""
    try:
        if image is None:
            return _html_resultat(
                detector.Analyse(None, MESSAGE_SANS_CAPTURE))
        return _html_resultat(detector.analyser_capture(image))
    except Exception:
        return _html_resultat(detector.Analyse(templates.sortie_de_repli(), ""))


def _analyser(message):
    """Appelé par le bouton. Ne doit JAMAIS lever.

    Si cette fonction lève, Gradio interrompt la chaîne et le .then() qui
    réactive le bouton ne s'exécute pas : l'interface reste figée, bouton
    grisé, pour le reste de la session. En démo, c'est terminé. D'où ce
    dernier filet, en plus de celui de detector.analyser().
    """
    try:
        return _html_resultat(detector.analyser(message))
    except Exception:
        return _html_resultat(
            detector.Analyse(templates.sortie_de_repli(), "")
        )


def _occuper():
    return gr.update(interactive=False, value=LIBELLE_BOUTON_OCCUPE)


def _liberer():
    return gr.update(interactive=True, value=LIBELLE_BOUTON)


def construire():
    with gr.Blocks(title=TITRE, analytics_enabled=False) as interface:
        gr.Markdown(f"# {TITRE}\n{SOUS_TITRE}")
        resultat = gr.HTML()

        with gr.Tabs():
            # La capture d'abord : c'est la façon recommandée, parce qu'elle
            # seule montre l'expéditeur. Un copier-coller le perd.
            with gr.Tab("Capture d'écran"):
                gr.Markdown(CONSEIL_CAPTURE)
                capture = gr.Image(
                    label="La capture du message",
                    type="filepath",
                    sources=["upload", "clipboard"],
                    height=300,
                )
                bouton_capture = gr.Button(LIBELLE_BOUTON, variant="primary")

            with gr.Tab("Coller le texte"):
                champ = gr.Textbox(
                    label="Le message reçu",
                    placeholder="Colle ici le message, tel que tu l'as reçu…",
                    lines=7,
                    max_lines=14,
                )
                gr.Markdown(AVERTISSEMENT_TEXTE,
                            elem_classes="mention-vie-privee")
                with gr.Row():
                    boutons_exemples = [
                        gr.Button(nom, size="sm", variant="secondary")
                        for nom, _ in EXEMPLES
                    ]
                bouton = gr.Button(LIBELLE_BOUTON, variant="primary")

        gr.Markdown(MENTION_VIE_PRIVEE, elem_classes="mention-vie-privee")

        for bouton_exemple, (_, texte) in zip(boutons_exemples, EXEMPLES):
            bouton_exemple.click(lambda t=texte: t, None, champ, queue=False)

        # Bouton désactivé pendant l'analyse, et concurrency_limit=1 pour
        # qu'un clic répété ne lance jamais deux analyses en parallèle.
        bouton.click(_occuper, None, bouton, queue=False) \
              .then(_analyser, champ, resultat, concurrency_limit=1) \
              .then(_liberer, None, bouton, queue=False)

        bouton_capture.click(_occuper, None, bouton_capture, queue=False) \
                      .then(_analyser_capture, capture, resultat,
                            concurrency_limit=1) \
                      .then(_liberer, None, bouton_capture, queue=False)

    return interface


# En Gradio 6, le CSS se passe à launch() et non au constructeur Blocks.
#
# Trois façons de lancer :
#
#   python app.py              seul, sur cette machine
#   python app.py --reseau     toute l'équipe sur le même wifi
#   python app.py --partage    toute l'équipe, où qu'elle soit
#
# --reseau expose l'interface sur le réseau local. Rien ne sort du réseau :
# la mention « ton message est analysé puis effacé » reste entièrement vraie.
#
# --partage crée un lien public gradio.live, valable 72 h. Pratique, mais le
# texte des messages transite par un relais externe avant d'arriver ici.
# L'analyse reste locale, mais on ne peut plus dire « rien ne part ailleurs ».
# À réserver aux essais de l'équipe, jamais à la démonstration devant le jury.
if __name__ == "__main__":
    import socket
    import sys

    partage = "--partage" in sys.argv
    reseau = partage or "--reseau" in sys.argv

    if reseau and not partage:
        try:
            adresse = socket.gethostbyname(socket.gethostname())
            print(f"\nSur le réseau local : http://{adresse}:7860\n")
        except OSError:
            pass

    construire().launch(
        css=CSS,
        share=partage,
        server_name="0.0.0.0" if reseau else "127.0.0.1",
    )

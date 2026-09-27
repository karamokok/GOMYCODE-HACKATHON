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

# Ce qui s'affiche PENDANT l'analyse. Sans ça, l'écran ne bouge pas pendant
# vingt à trente secondes — et une démonstration devant un jury se lit alors
# comme un plantage. On annonce aussi la durée : une attente prévue est une
# attente supportable.
ATTENTE_TEXTE = (
    "Analyse du message",
    "Le modèle relève les faits, les règles calculent le verdict. "
    "Compte une vingtaine de secondes.",
)

ATTENTE_CAPTURE = (
    "Lecture de la capture",
    "Le modèle recopie l'expéditeur et le texte, puis l'analyse commence. "
    "C'est l'étape la plus longue : de trente secondes à deux minutes.",
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

# Le thème. Bleu-vert en couleur principale : il habille les boutons et les
# onglets sans jamais entrer en concurrence avec le rouge, l'orange et le vert
# du verdict, qui doivent rester les seules couleurs porteuses de sens.
THEME = gr.themes.Base(
    primary_hue=gr.themes.colors.teal,
    neutral_hue=gr.themes.colors.stone,
    font=[gr.themes.GoogleFont("Source Sans 3"), "system-ui", "sans-serif"],
).set(
    body_background_fill="#FAF8F4",
    body_background_fill_dark="#14130F",
    block_radius="10px",
    button_large_radius="10px",
)

CSS = """
/* Palette. L'accent est un bleu-vert profond, volontairement hors du
   tricolore : rouge, orange et vert sont réservés aux verdicts et ne doivent
   jamais servir de décoration. */
:root {
  --fond:        #FAF8F4;
  --carte:       #FFFFFF;
  --encre:       #1A1814;
  --encre-douce: #5C554A;
  --trait:       #E5DFD4;
  --accent:      #1F5560;

  --rouge-fond: #FDECEA;  --rouge-bord: #C0392B;  --rouge-encre: #6B1410;
  --orange-fond:#FFF4E5;  --orange-bord:#D97706;  --orange-encre:#6B2710;
  --vert-fond:  #EAF6EC;  --vert-bord:  #2E7D32;  --vert-encre:  #123F23;
  --neutre-fond:#EEF1F5;  --neutre-bord:#64748B;  --neutre-encre:#1E293B;
}

@media (prefers-color-scheme: dark) {
  :root:not([data-theme="light"]) {
    --fond:        #14130F;
    --carte:       #1C1A15;
    --encre:       #F0EBE2;
    --encre-douce: #A69C8B;
    --trait:       #312C23;
    --accent:      #6FB3BF;

    --rouge-fond: #2E1512;  --rouge-bord: #E8796C;  --rouge-encre: #FBD9D4;
    --orange-fond:#2C1F0E;  --orange-bord:#DCA24C;  --orange-encre:#FAE8CC;
    --vert-fond:  #13251A;  --vert-bord:  #7CBE8A;  --vert-encre:  #D6EEDC;
    --neutre-fond:#1B1F26;  --neutre-bord:#8A97A8;  --neutre-encre:#DDE3EA;
  }
}

/* L'en-tête : le titre est une question, il doit se lire comme telle. */
.entete h1 {
  font-size: 1.85em !important;
  line-height: 1.15 !important;
  letter-spacing: -0.015em;
  margin-bottom: 0.25em !important;
  text-wrap: balance;
}
.entete p { color: var(--encre-douce); max-width: 34rem; }

/* Le bloc de verdict. */
.bloc-verdict {
  border-left: 6px solid;
  border-radius: 10px;
  padding: 20px 22px;
  margin-top: 10px;
}
/* Gradio force le texte en blanc dans son thème sombre, y compris dans nos
   blocs : sans cette ligne, le résultat devient invisible. */
.bloc-verdict *, .avertissement * { color: inherit !important; }

.bloc-verdict .titre { font-size: 1.45em; font-weight: 700; margin: 0; }
.bloc-verdict .sous-titre { font-size: 1.05em; margin: 4px 0 14px 0; }
.bloc-verdict ul, .bloc-verdict ol { margin: 0 0 4px 0; padding-left: 22px; }
.bloc-verdict li { margin-bottom: 7px; line-height: 1.5; }
.bloc-verdict .intitule-conduite { font-weight: 700; margin: 16px 0 6px 0; }
.bloc-verdict .consigne-operateur {
  margin: 16px 0 0 0;
  padding-top: 12px;
  border-top: 1px solid currentColor;
  font-size: 0.95em;
  opacity: 0.8;
}

.verdict-rouge  { background:var(--rouge-fond);  border-color:var(--rouge-bord);  color:var(--rouge-encre); }
.verdict-orange { background:var(--orange-fond); border-color:var(--orange-bord); color:var(--orange-encre); }
.verdict-vert   { background:var(--vert-fond);   border-color:var(--vert-bord);   color:var(--vert-encre); }
.verdict-neutre { background:var(--neutre-fond); border-color:var(--neutre-bord); color:var(--neutre-encre); }

.avertissement {
  background: var(--orange-fond);
  border-left: 6px solid var(--orange-bord);
  color: var(--orange-encre);
  border-radius: 10px;
  padding: 12px 16px;
  margin-bottom: 10px;
}

/* L'attente. Trois points qui respirent : l'écran doit montrer qu'il
   travaille, sinon trente secondes se lisent comme un plantage. */
.bloc-attente {
  background: var(--carte);
  border-color: var(--accent);
  color: var(--encre);
}
.bloc-attente .sous-titre { color: var(--encre-douce) !important; margin-bottom: 0; }
.pulsation { display: flex; gap: 6px; margin-bottom: 12px; }
.pulsation span {
  width: 9px; height: 9px; border-radius: 50%;
  background: var(--accent);
  animation: respire 1.4s ease-in-out infinite;
}
.pulsation span:nth-child(2) { animation-delay: 0.2s; }
.pulsation span:nth-child(3) { animation-delay: 0.4s; }
@keyframes respire {
  0%, 80%, 100% { opacity: 0.25; transform: scale(0.85); }
  40%           { opacity: 1;    transform: scale(1); }
}
@media (prefers-reduced-motion: reduce) {
  .pulsation span { animation: none; opacity: 0.7; }
}

.mention-vie-privee { font-size: 0.9em; opacity: 0.7; margin-top: 4px; }

/* Téléphone : c'est là que ces messages sont reçus. */
@media (max-width: 640px) {
  .entete h1 { font-size: 1.5em !important; }
  .bloc-verdict { padding: 16px 16px; border-radius: 8px; }
  .bloc-verdict .titre { font-size: 1.28em; }
}
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


def _attente(etat):
    """Le bloc affiché pendant que le modèle travaille."""
    titre, detail = etat
    return (
        '<div class="bloc-verdict bloc-attente">'
        '<div class="pulsation" aria-hidden="true"><span></span><span></span>'
        '<span></span></div>'
        f'<p class="titre">{html.escape(titre)}…</p>'
        f'<p class="sous-titre">{html.escape(detail)}</p>'
        "</div>"
    )


def _attente_texte():
    return _attente(ATTENTE_TEXTE)


def _attente_capture():
    return _attente(ATTENTE_CAPTURE)


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
        gr.Markdown(f"# {TITRE}\n{SOUS_TITRE}", elem_classes="entete")

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

        # Le résultat vient SOUS le bouton : le bouton est en bas de l'écran,
        # et une réponse qui s'affiche au-dessus oblige à remonter pour la
        # lire — sur téléphone, on croit qu'il ne s'est rien passé.
        resultat = gr.HTML()
        gr.Markdown(MENTION_VIE_PRIVEE, elem_classes="mention-vie-privee")

        for bouton_exemple, (_, texte) in zip(boutons_exemples, EXEMPLES):
            bouton_exemple.click(lambda t=texte: t, None, champ, queue=False)

        # Le bloc d'attente s'affiche avant l'appel au modèle, sans passer par
        # la file (queue=False) pour qu'il arrive tout de suite.
        # concurrency_limit=1 : un clic répété ne lance jamais deux analyses.
        bouton.click(_occuper, None, bouton, queue=False) \
              .then(_attente_texte, None, resultat, queue=False) \
              .then(_analyser, champ, resultat, concurrency_limit=1) \
              .then(_liberer, None, bouton, queue=False)

        bouton_capture.click(_occuper, None, bouton_capture, queue=False) \
                      .then(_attente_capture, None, resultat, queue=False) \
                      .then(_analyser_capture, capture, resultat,
                            concurrency_limit=1) \
                      .then(_liberer, None, bouton_capture, queue=False)

    return interface


# En Gradio 6, le CSS ET le thème se passent à launch(), pas au constructeur
# Blocks : sur le constructeur, ils sont ignorés avec un simple avertissement,
# et l'interface s'affiche sans mise en forme sans que rien ne signale l'erreur.
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
        theme=THEME,
        share=partage,
        server_name="0.0.0.0" if reseau else "127.0.0.1",
    )

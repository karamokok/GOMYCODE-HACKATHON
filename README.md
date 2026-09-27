# Détecteur d'arnaque — mobile money Côte d'Ivoire

Un détecteur d'arnaque par message, spécialisé sur la fraude au mobile money
en Côte d'Ivoire : Orange Money, Wave, MTN MoMo, Moov Money.

La personne envoie **une capture d'écran** de son SMS — ou colle le texte si
elle n'en a pas. Le système rend un verdict tricolore, une explication en
français simple, la conduite à tenir immédiate avec le **vrai numéro de son
opérateur**, et la consigne officielle de cet opérateur.

---

## Le principe : aucune IA ne rend le verdict

C'est le cœur du projet. On ne demande jamais au modèle « est-ce une
arnaque ». Le modèle vision **recopie** ce qu'il voit ; le modèle texte
**constate** des faits observables ; le verdict est calculé par du code
Python déterministe, relisible ligne à ligne.

Conséquence : le même message donne toujours le même verdict, et on peut
toujours expliquer pourquoi un message a été classé rouge, règle par règle.

**Il n'y a aucun entraînement de modèle dans ce projet**, et c'est un
argument, pas un manque.

### Les quatre étages

```
capture d'écran                     texte collé
      |                                  |
      v                                  |
  lecture par le modèle vision           |
  (recopie l'expéditeur + le texte)      |
      |                                  |
      +----------------+-----------------+
                       v
                 normalisation
                       v
      extraction de signaux (appel modèle)  -> JSON à 16 clés
                       v
      garde-fous déterministes (Python pur) -> signaux corrigés
                       v
      couche de règles (Python pur)         -> score + verdict
                       v
      gabarits de sortie                    -> ce que la personne lit
```

**Pourquoi la capture d'écran d'abord.** Copier-coller un SMS perd
l'expéditeur, qui est souvent le seul élément trahissant l'arnaque. Dans notre
corpus, une fausse notification de dépôt Orange Money est indiscernable d'une
vraie *par son texte* — pas de lien, pas de demande, pas d'urgence. Seul
l'expéditeur la démasque : un numéro personnel là où le canal officiel
d'Orange devrait apparaître. La capture le montre, le copier-coller non.

---

## Installation

### Prérequis

- **Python 3.13** (testé sur 3.13.9, Windows)
- **[Ollama](https://ollama.com)** installé et démarré

### 1. Les modèles

Deux modèles ouverts, exécutés localement. Aucune donnée ne sort de la
machine.

```bash
ollama pull qwen2.5:3b      # texte   — 1,9 Go
ollama pull qwen2.5vl:3b    # vision  — 3,2 Go
```

Vérifier qu'Ollama répond :

```bash
curl -s http://localhost:11434/api/tags
```

### 2. Les dépendances Python

Deux paquets, pas un de plus.

```bash
pip install gradio openai
```

Versions utilisées : `gradio 6.28.0`, `openai 2.24.0`.

### 3. Configuration

Aucune clé d'API n'est nécessaire : tout tourne en local. Les trois
constantes de connexion sont en haut de `signals.py` :

```python
BASE_URL = "http://localhost:11434/v1"
MODEL = "qwen2.5:3b"                     # modèle texte
MODEL_VISION = "qwen2.5vl:3b"            # lit les captures d'écran
```

Pour pointer vers un autre serveur compatible OpenAI, ces trois lignes
suffisent. La clé `API_KEY = "ollama"` est une valeur factice qu'Ollama
ignore ; la bibliothèque `openai` exige simplement qu'un champ soit présent.

---

## Lancer l'application

```bash
python app.py               # seul, sur cette machine
python app.py --reseau      # accessible à toute l'équipe sur le même wifi
python app.py --partage     # lien public gradio.live, valable 72 h
```

L'interface s'ouvre sur <http://127.0.0.1:7860>.

> **Note sur `--partage`.** Ce mode fait transiter le texte des messages par
> un relais externe. L'analyse reste locale, mais la promesse « rien ne part
> ailleurs » n'est alors plus entièrement vraie. À réserver aux essais de
> l'équipe.

**Avant une démonstration, réveillez les modèles** en envoyant un premier
message : Ollama les décharge de la mémoire après quelques minutes
d'inactivité, et le premier appel passe alors de 21 à 51 secondes.

---

## Les tests

Chaque module se teste seul, **sans appeler les modèles** : les essais sont
instantanés et disent tout de suite si un problème vient du code ou du
serveur.

```bash
python signals.py       # 52 essais : validation, garde-fous, reprise
python rules.py         # 21 cas    : règles absolues, barème, seuils
python templates.py     # sortie    : couverture, tournures interdites, forme
python detector.py      # chaîne complète, avec appels modèle réels
```

```bash
python signals.py --modele    # essais avec de vrais appels au modèle
```

Ce que ces essais couvrent :

| Fichier | Vérifie |
| --- | --- |
| `signals.py` | réponses JSON cassées, types fantaisistes, reprise unique, garde-fous |
| `rules.py` | les trois règles absolues, les neuf poids, les bornes des seuils |
| `templates.py` | chaque règle a une phrase, aucune tournure interdite, forme de la sortie |
| `detector.py` | entrées vides, troncature, pannes réseau, repli orange |

---

## Structure du dépôt

```
app.py                    interface Gradio et câblage
detector.py               orchestration des étages ; ne lève jamais
signals.py                appels modèles, prompts, validation, garde-fous
rules.py                  règles absolues, barème, seuils, calcul du verdict
templates.py              phrases affichées, numéros et consignes officiels
evaluer.py                mesure sur le jeu de test mis de côté

corpus_4.csv              les 42 messages, anonymisés, avec leur étiquette
numeros_officiels_2.csv   numéros et expéditeurs officiels des 4 opérateurs
```

Pas de dossiers, pas de base de données, pas de compte utilisateur.

### Le corpus

`corpus_4.csv` porte une colonne `split` : `dev` pour ce qui a servi à
construire, `test` pour ce qui a été mis de côté. `evaluer.py` ne lit que les
lignes `test`, et exclut nommément quatre messages qui avaient servi au
réglage avant la mise en place du découpage. La liste d'exclusion est écrite
en clair dans le fichier, pour être vérifiable.

Mesure sur les 10 messages réellement intacts : **7/10** — 3 arnaques
détectées sur 5, 4 messages légitimes non signalés sur 5. Deux des trois
échecs tiennent à la mesure elle-même : le corpus ne porte pas d'expéditeur,
donc l'évaluation ne teste que le mode « texte collé », le plus faible des
deux.

---

## Comment le verdict est calculé

### Les trois règles absolues — rouge immédiat

| Condition | Pourquoi |
| --- | --- |
| Demande de code secret | Aucun opérateur ne demande jamais ce code |
| Faux transfert **et** demande d'argent | Signature de l'arnaque au « virement par erreur » |
| Organisme invoqué **et** expéditeur incohérent | Usurpation d'identité |

### Sinon, un barème

| Signal | Points |
| --- | --- |
| Demande d'argent | 30 |
| Gain non sollicité | 25 |
| Lien suspect | 25 |
| Demande de données personnelles | 20 |
| Urgence artificielle | 15 |
| Menace ou sanction | 15 |
| Appel à rappeler | 10 |
| Anomalies de rédaction | 10 |
| Lien présent seul | 5 |

**Seuils : 50 et plus = rouge, 20 à 49 = orange, moins de 20 = vert.**

Le score est interne : il n'est jamais affiché. Et le système ne dit jamais
qu'un message est sûr — seulement que rien de suspect n'a été détecté.

---

## Les garde-fous déterministes

C'est la partie la moins visible et la plus importante. Sans elle, le système
déclare arnaque de **vrais** messages d'opérateur.

**Ils n'inventent jamais un verdict.** Ils constatent un fait objectif — un
mot est-il dans le texte, une adresse appartient-elle au domaine officiel
d'une marque — et corrigent un signal que le modèle a manifestement mal vu.

| Garde-fou | Le problème qu'il corrige |
| --- | --- |
| Code USSD | Le modèle lit `#144*82#` comme un code secret et classe rouge une vraie promotion Orange |
| Notification | Il lit « vous avez reçu 25 000F » comme une demande d'argent |
| Liens | Il ne voit pas qu'un `.xyz` imitant une marque est suspect, ni qu'un domaine officiel ne l'est pas |
| Expéditeur | Un SMS se réclamant de Wave sans venir de son canal officiel est une usurpation |

Deux d'entre eux ne font qu'**éteindre** un signal. Celui des liens peut aussi
en allumer un : vérifier qu'une adresse est hébergée gratuitement ou
n'appartient pas au domaine officiel d'une marque n'est pas une heuristique
sur les mots, c'est une constatation.

---

## Vie privée

- **Les messages ne sont pas conservés.** Vérifié plutôt que supposé : après
  plusieurs analyses, le journal est vide, aucun fichier de cache n'est créé,
  et le texte des messages n'apparaît nulle part sur le disque.
- **Les mesures d'audience de Gradio sont coupées** (`analytics_enabled=False`).
- **La fonction de trace n'écrit que des étiquettes techniques** — jamais le
  message, jamais la réponse du modèle.
- **Les modèles tournent en local.** Aucun message n'est envoyé à un service
  tiers.

---

## Ce que le système ne sait pas faire

Énoncé plutôt que masqué.

- **Une fausse notification de dépôt envoyée depuis un canal qui paraît
  officiel est indécidable.** Le texte seul ne permet pas de trancher ; seule
  la vérification du solde le permettrait.
- **Une vraie promotion contenant le mot « cadeau » reste classée en
  prudence.** Le modèle n'a pas tort textuellement, et prudence ne veut pas
  dire arnaque.
- **Sans capture d'écran, l'expéditeur est perdu**, et l'analyse est moins
  sûre. C'est pourquoi l'onglet capture est mis en avant.

---

## Déclaration des outils et modèles d'IA

Ce que le règlement demande de lister : modèles, agents, jeux de données et API.

| Niveau | Quoi |
| --- | --- |
| **Dans le produit** | `qwen2.5:3b` et `qwen2.5vl:3b`, modèles ouverts exécutés localement via Ollama |
| **Les données** | Corpus de 42 messages anonymisés : 34 relevés en Côte d'Ivoire, 8 fabriqués pour couvrir des cas rares. Un tiers réservé au test. |

**Aucun modèle n'a été entraîné ni affiné.**

---

## Licence et données

Les messages du corpus sont anonymisés : numéros, noms et montants sont
remplacés par des marqueurs. Aucune donnée personnelle ne figure dans ce
dépôt.

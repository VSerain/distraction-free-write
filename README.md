# Freewrite

Application d'écriture en plein écran pour terminal, conçue pour fonctionner sur un PC sans interface graphique. Zéro distraction, tout au clavier.

## Lancement

```bash
python3 main.py
```

## Navigation générale

Dans tous les écrans, la navigation suit le même principe :

| Touche | Action |
|--------|--------|
| `↑` / `↓` | Naviguer dans la liste |
| `→` / `Entrée` | Ouvrir / valider |
| `←` / `Échap` | Revenir en arrière |

---

## Écran d'accueil

Liste tous les projets disponibles et donne accès aux actions globales.

| Touche | Action |
|--------|--------|
| `↑` / `↓` | Naviguer entre les projets et le menu |
| `→` | Ouvrir le projet sélectionné |
| `X` | Supprimer le projet sélectionné (confirmation requise) |
| `→` sur **Nouveau projet** | Créer un nouveau projet |
| `→` sur **Paramètres** | Ouvrir les paramètres |
| `→` sur **Quitter** | Quitter l'application |

Les projets sont stockés dans `~/Projets`.

---

## Explorateur de projet

Navigateur de fichiers et dossiers à l'intérieur d'un projet. Le panneau gauche liste les fichiers, le panneau droit affiche un aperçu du fichier sélectionné ou l'arborescence d'un dossier.

La barre de titre indique l'état Git : `✓ main` (synchronisé) ou `● main` (modifications non commitées).

| Touche | Action |
|--------|--------|
| `↑` / `↓` | Naviguer |
| `→` | Ouvrir le fichier (éditeur) ou entrer dans le dossier |
| `←` | Revenir au niveau précédent |
| `F` | Créer un nouveau fichier |
| `D` | Créer un nouveau dossier |
| `R` | Renommer le fichier ou dossier sélectionné |
| `M` | Déplacer le fichier ou dossier (chemin relatif) |
| `X` | Supprimer le fichier ou dossier sélectionné (confirmation) |
| `U` | Exporter le projet sur une clé USB *(racine du projet uniquement)* |
| `G` | Ouvrir la page Git *(racine du projet uniquement)* |

---

## Éditeur de texte

Éditeur minimaliste sans distraction. La sauvegarde est automatique à chaque modification — il n'y a rien à faire.

| Touche | Action |
|--------|--------|
| Touches directionnelles | Déplacer le curseur |
| `Home` / `End` | Début / fin de ligne |
| `PgUp` / `PgDn` | Défiler d'une page |
| `Backspace` / `Suppr` | Effacer |
| `Entrée` | Nouvelle ligne |
| `Tab` | Insérer 4 espaces |
| `Ctrl+Q` | Quitter l'éditeur |

La sauvegarde est instantanée après chaque frappe. Il n'existe pas de notion de "fichier non sauvegardé".

---

## Git

Accessible depuis l'explorateur avec `G`. Fonctionne comme les autres pages (flèches + `→` pour exécuter).

### Statut affiché

- Branche courante
- Présence de modifications non commitées
- Nombre de commits en avance / en retard par rapport au remote
- URL du remote GitHub

### Actions disponibles

| Action | Description |
|--------|-------------|
| Commiter | Crée un commit avec un message saisi au clavier |
| Push | Pousse les commits vers GitHub |
| Pull | Récupère les modifications depuis GitHub |
| Nouvelle branche | Crée une branche et bascule dessus |
| Changer de branche | Sélectionne une branche existante |
| Historique | Affiche tous les commits avec aperçu des modifications |
| Configurer le remote | Définit ou modifie l'URL GitHub du projet |
| Clé SSH | Affiche la clé publique SSH à copier dans GitHub |

### Historique et restauration

La vue historique affiche la liste des commits à gauche et le détail des fichiers modifiés à droite. Appuyer sur `→` sur un commit propose de restaurer le projet à cet état (l'état actuel est sauvegardé automatiquement avant la restauration).

### Clé SSH

Affiche la clé publique en texte brut pour pouvoir la sélectionner à la souris et la copier dans GitHub. Si aucune clé n'existe, propose d'en générer une (`ed25519`). Depuis cette page, `E` exporte la clé directement sur une clé USB.

---

## Export USB

Accessible avec `U` depuis la racine d'un projet.

- Détecte automatiquement les clés USB montées (`/media`, `/mnt`, `/run/media`)
- Si plusieurs clés sont présentes, propose de choisir
- Affiche l'espace libre disponible sur chaque clé
- Copie l'intégralité du projet (sans le dossier `.git`)
- Demande confirmation si un dossier du même nom existe déjà sur la clé

---

## Statut système

Affiché en permanence dans la barre de titre de tous les écrans, sauf l'éditeur :

```
  FREEWRITE  —  Mon projet          78%+   WiFi:MaBox
```

| Indicateur | Signification |
|------------|---------------|
| `78%` | Batterie à 78%, en décharge |
| `78%+` | Batterie à 78%, en charge |
| `WiFi:MaBox` | Connecté au réseau "MaBox" |
| `WiFi:--` | Aucune connexion WiFi |

Le statut est actualisé toutes les 10 secondes.

---

## Paramètres

Accessible depuis l'écran d'accueil.

### Thème

| Thème | Description |
|-------|-------------|
| Sombre | Fond sombre, texte clair (défaut terminal) |
| Clair | Fond blanc, texte noir |

Le choix est sauvegardé dans `~/.config/freewrite/config.json` et appliqué au démarrage suivant.

### Connexion WiFi

Lance un scan des réseaux disponibles via `nmcli`. Pour chaque réseau :

- Nom du réseau (SSID)
- Force du signal (barres visuelles)
- Indication si le réseau est protégé par mot de passe

Sélectionner un réseau et appuyer sur `→` lance la connexion. Si le réseau est protégé, le mot de passe est demandé.

> Nécessite NetworkManager (`nmcli`) installé sur le système.

---

## Dépendances

- Python 3.10+ (pour `match` et annotations de type `X | Y`)
- `curses` (inclus dans la bibliothèque standard Python)
- `git` — pour les fonctionnalités de versioning
- `nmcli` (NetworkManager) — pour la connexion WiFi
- `iwgetid` (optionnel) — détection du SSID courant
- `ssh-keygen` — pour la génération de clé SSH

## Structure des données

```
~/Projets/              ← tous les projets
    mon-projet/
        fichier.txt
        notes/
            brouillon.txt

~/.config/freewrite/
    config.json         ← thème et préférences

~/.ssh/
    id_ed25519          ← clé SSH générée par l'app (si applicable)
    id_ed25519.pub
```

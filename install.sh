#!/bin/bash
set -euo pipefail

# ── couleurs ──────────────────────────────────────────────────────────────────
GRN='\033[0;32m'
YLW='\033[1;33m'
RED='\033[0;31m'
BLD='\033[1m'
RST='\033[0m'

info()  { echo -e "  ${GRN}✓${RST}  $*"; }
warn()  { echo -e "  ${YLW}!${RST}  $*"; }
error() { echo -e "  ${RED}✗${RST}  $*" >&2; }
title() { echo -e "\n${BLD}═══  $*${RST}"; }

REPO_RAW="https://raw.githubusercontent.com/VSerain/distraction-free-write/main"

# ── vérifications préalables ──────────────────────────────────────────────────

echo ""
echo -e "${BLD}╔══════════════════════════════════════════════╗${RST}"
echo -e "${BLD}║     Installation de DistracFreeWrite         ║${RST}"
echo -e "${BLD}╚══════════════════════════════════════════════╝${RST}"
echo ""

if [ "$EUID" -ne 0 ]; then
    error "Ce script doit être exécuté avec sudo."
    echo ""
    echo "  Relancez avec :"
    echo -e "  ${BLD}curl -fsSL ${REPO_RAW}/install.sh | sudo bash${RST}"
    echo ""
    exit 1
fi

REAL_USER="${SUDO_USER:-}"
if [ -z "$REAL_USER" ] || [ "$REAL_USER" = "root" ]; then
    error "Utilisez sudo depuis un compte utilisateur normal, pas depuis root."
    echo "  Exemple : connectez-vous en tant que 'victor', puis :"
    echo -e "  ${BLD}curl -fsSL ${REPO_RAW}/install.sh | sudo bash${RST}"
    echo ""
    exit 1
fi

REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# ── dépendances système ───────────────────────────────────────────────────────

title "1/4  Dépendances"

apt-get update -qq
apt-get install -y \
    python3 \
    curl \
    git \
    network-manager \
    wireless-tools \
    openssh-client

# Vérification Python 3.10+
if ! python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)" 2>/dev/null; then
    PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
    error "Python 3.10+ requis (installé : $PY_VER)."
    error "Passez à Debian 12 (Bookworm) ou compilez Python manuellement."
    exit 1
fi

# Vérification curses (inclus dans python3 sur Debian, mais absent sur certains systèmes minimaux)
if ! python3 -c "import curses" 2>/dev/null; then
    error "Le module Python 'curses' est manquant."
    error "Essayez : apt-get install -y python3-dev libncursesw5-dev"
    exit 1
fi

info "python3   $(python3 --version)"
info "git       $(git --version | awk '{print $3}')"
info "nmcli     $(nmcli --version 2>/dev/null | awk '{print $NF}' || echo 'ok')"
info "wireless-tools, openssh-client"

# ── téléchargement et installation ───────────────────────────────────────────

title "2/4  Installation de l'application"

INSTALL_DIR="/opt/distracfreewrite"
mkdir -p "$INSTALL_DIR"

# Récupérer la version (dernier tag GitHub)
LATEST_TAG=$(curl -fsSL "https://api.github.com/repos/VSerain/distraction-free-write/tags" \
    2>/dev/null | python3 -c "import sys,json; t=json.load(sys.stdin); print(t[0]['name'] if t else 'main')" 2>/dev/null || echo "main")

echo -e "  Téléchargement de main.py  (version : $LATEST_TAG)..."
curl -fsSL "https://raw.githubusercontent.com/VSerain/distraction-free-write/$LATEST_TAG/main.py" \
    -o "$INSTALL_DIR/main.py"
chmod 644 "$INSTALL_DIR/main.py"
# Propriétaire = utilisateur réel pour permettre les mises à jour depuis l'app
chown "$REAL_USER:$REAL_USER" "$INSTALL_DIR/main.py"
chown "$REAL_USER:$REAL_USER" "$INSTALL_DIR"
info "Application installée dans $INSTALL_DIR  ($LATEST_TAG)"

# Lanceur global
cat > /usr/local/bin/distracfreewrite << 'EOF'
#!/bin/bash
exec python3 /opt/distracfreewrite/main.py
EOF
chmod 755 /usr/local/bin/distracfreewrite
info "Commande 'distracfreewrite' disponible globalement"

# Dossiers utilisateur
mkdir -p "$REAL_HOME/Projets"
chown "$REAL_USER:$REAL_USER" "$REAL_HOME/Projets"
mkdir -p "$REAL_HOME/.config/distracfreewrite"
chown -R "$REAL_USER:$REAL_USER" "$REAL_HOME/.config/distracfreewrite"
info "Dossiers ~/Projets et ~/.config/distracfreewrite créés"

# ── démarrage automatique ─────────────────────────────────────────────────────

title "3/4  Démarrage automatique"
echo ""
echo -e "  Voulez-vous que DistracFreeWrite se lance automatiquement"
echo -e "  au démarrage du PC (connexion automatique sur TTY1) ?"
echo ""
printf "  [o/N] > "
read -r AUTOSTART < /dev/tty

if [[ "$AUTOSTART" =~ ^[oOyY]$ ]]; then

    # Connexion automatique sur TTY1 via systemd
    GETTY_CONF="/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "$GETTY_CONF"
    cat > "$GETTY_CONF/autologin.conf" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $REAL_USER --noclear %I \$TERM
Type=idle
EOF
    info "Connexion automatique sur TTY1 → $REAL_USER"

    # Ajout dans .bash_profile (seulement sur TTY1, pas SSH)
    PROFILE="$REAL_HOME/.bash_profile"
    if [ ! -f "$PROFILE" ]; then
        cat > "$PROFILE" << 'PFEOF'
# ~/.bash_profile
[[ -f ~/.bashrc ]] && source ~/.bashrc
PFEOF
        chown "$REAL_USER:$REAL_USER" "$PROFILE"
    fi

    if grep -q "distracfreewrite" "$PROFILE" 2>/dev/null; then
        warn "Démarrage déjà présent dans $PROFILE, ignoré."
    else
        cat >> "$PROFILE" << 'PFEOF'

# Lancer DistracFreeWrite automatiquement sur TTY1
if [ "$(tty)" = "/dev/tty1" ]; then
    distracfreewrite
fi
PFEOF
        chown "$REAL_USER:$REAL_USER" "$PROFILE"
        info "Lancement automatique ajouté à ~/.bash_profile"
    fi

    systemctl daemon-reload
    info "Configuration systemd rechargée"

else
    warn "Démarrage automatique non configuré."
fi

# ── résumé ────────────────────────────────────────────────────────────────────

title "4/4  Terminé"
echo ""
echo -e "  Application    ${GRN}/opt/distracfreewrite/main.py${RST}"
echo -e "  Commande       ${GRN}distracfreewrite${RST}"
echo -e "  Projets        ${GRN}$REAL_HOME/Projets${RST}"
echo -e "  Configuration  ${GRN}$REAL_HOME/.config/distracfreewrite/config.json${RST}"
echo -e "  Version        ${GRN}$LATEST_TAG${RST}"
echo ""

if [[ "$AUTOSTART" =~ ^[oOyY]$ ]]; then
    echo -e "  ${GRN}Démarrage automatique activé.${RST}"
    echo -e "  Redémarrez le PC pour que les changements prennent effet."
else
    echo -e "  Tapez ${BLD}distracfreewrite${RST} pour lancer l'application."
fi
echo ""

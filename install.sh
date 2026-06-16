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
title() { echo -e "\n${BLD}$*${RST}"; }
ask()   { echo -e "\n  ${YLW}?${RST}  $*"; }

# ── vérifications préalables ──────────────────────────────────────────────────

echo ""
echo -e "${BLD}╔══════════════════════════════════════╗${RST}"
echo -e "${BLD}║        Installation de Freewrite      ║${RST}"
echo -e "${BLD}╚══════════════════════════════════════╝${RST}"
echo ""

if [ "$EUID" -ne 0 ]; then
    error "Ce script doit être exécuté avec sudo."
    echo "       Relancez avec : sudo bash install.sh"
    exit 1
fi

if [ ! -f "$(dirname "$0")/main.py" ]; then
    error "main.py introuvable. Lancez ce script depuis le dossier du projet."
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

# Utilisateur réel (celui qui a lancé sudo)
REAL_USER="${SUDO_USER:-$USER}"
if [ "$REAL_USER" = "root" ]; then
    error "Connectez-vous en tant qu'utilisateur normal et utilisez sudo."
    exit 1
fi
REAL_HOME=$(getent passwd "$REAL_USER" | cut -d: -f6)

# ── dépendances système ───────────────────────────────────────────────────────

title "1/4  Installation des dépendances"

apt-get update -qq
apt-get install -y \
    python3 \
    python3-curses \
    git \
    network-manager \
    wireless-tools \
    openssh-client \
    > /dev/null 2>&1

info "python3 installé       : $(python3 --version)"
info "git installé           : $(git --version | head -1)"
info "nmcli installé         : $(nmcli --version | head -1)"
info "wireless-tools (iwgetid) installé"
info "openssh-client (ssh-keygen) installé"

# Vérification version Python (3.10+ requis)
PY_VER=$(python3 -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')")
PY_MIN="3.10"
if python3 -c "import sys; sys.exit(0 if sys.version_info >= (3,10) else 1)"; then
    info "Version Python : $PY_VER (OK)"
else
    error "Python 3.10+ requis, version actuelle : $PY_VER"
    error "Mettez à jour Python ou passez à Debian 12 (Bookworm)."
    exit 1
fi

# ── installation de l'application ─────────────────────────────────────────────

title "2/4  Installation de l'application"

INSTALL_DIR="/opt/freewrite"
mkdir -p "$INSTALL_DIR"
cp "$SCRIPT_DIR/main.py" "$INSTALL_DIR/main.py"
chmod 644 "$INSTALL_DIR/main.py"
info "Application copiée dans $INSTALL_DIR"

# Lanceur global
cat > /usr/local/bin/freewrite << 'EOF'
#!/bin/bash
exec python3 /opt/freewrite/main.py
EOF
chmod 755 /usr/local/bin/freewrite
info "Commande 'freewrite' disponible globalement"

# Dossier Projets pour l'utilisateur
mkdir -p "$REAL_HOME/Projets"
chown "$REAL_USER:$REAL_USER" "$REAL_HOME/Projets"
info "Dossier ~/Projets créé pour $REAL_USER"

# Dossier de configuration
mkdir -p "$REAL_HOME/.config/freewrite"
chown -R "$REAL_USER:$REAL_USER" "$REAL_HOME/.config/freewrite"
info "Dossier de configuration créé"

# ── démarrage automatique ─────────────────────────────────────────────────────

title "3/4  Démarrage automatique"

ask "Lancer Freewrite automatiquement au démarrage du PC ? [o/N]"
read -r AUTOSTART < /dev/tty

if [[ "$AUTOSTART" =~ ^[oOyY]$ ]]; then

    # Connexion automatique sur TTY1
    GETTY_OVERRIDE="/etc/systemd/system/getty@tty1.service.d"
    mkdir -p "$GETTY_OVERRIDE"
    cat > "$GETTY_OVERRIDE/autologin.conf" << EOF
[Service]
ExecStart=
ExecStart=-/sbin/agetty --autologin $REAL_USER --noclear %I \$TERM
Type=idle
EOF
    info "Connexion automatique sur TTY1 configurée pour $REAL_USER"

    # Lancer freewrite au login sur TTY1 (pas sur SSH ni autre TTY)
    PROFILE="$REAL_HOME/.bash_profile"

    if [ ! -f "$PROFILE" ]; then
        # S'assurer que .bashrc est sourcé si présent
        cat > "$PROFILE" << 'PFEOF'
# ~/.bash_profile
[[ -f ~/.bashrc ]] && source ~/.bashrc
PFEOF
        chown "$REAL_USER:$REAL_USER" "$PROFILE"
    fi

    if grep -q "freewrite" "$PROFILE" 2>/dev/null; then
        warn "Démarrage automatique déjà présent dans $PROFILE, ignoré."
    else
        cat >> "$PROFILE" << 'PFEOF'

# Lancer Freewrite automatiquement sur le terminal principal
if [ "$(tty)" = "/dev/tty1" ]; then
    freewrite
fi
PFEOF
        chown "$REAL_USER:$REAL_USER" "$PROFILE"
        info "Ajouté au profil shell de $REAL_USER"
    fi

    systemctl daemon-reload
    info "Systemd rechargé"

else
    warn "Démarrage automatique ignoré."
    warn "Vous pouvez lancer l'application à tout moment avec : freewrite"
fi

# ── résumé ────────────────────────────────────────────────────────────────────

title "4/4  Installation terminée"
echo ""
echo -e "  Application   : ${GRN}/opt/freewrite/main.py${RST}"
echo -e "  Commande      : ${GRN}freewrite${RST}"
echo -e "  Projets       : ${GRN}$REAL_HOME/Projets${RST}"
echo -e "  Configuration : ${GRN}$REAL_HOME/.config/freewrite/config.json${RST}"
echo ""

if [[ "$AUTOSTART" =~ ^[oOyY]$ ]]; then
    echo -e "  ${GRN}Démarrage automatique actif.${RST}"
    echo -e "  Redémarrez le PC pour que les changements prennent effet."
else
    echo -e "  Tapez ${BLD}freewrite${RST} pour lancer l'application."
fi
echo ""

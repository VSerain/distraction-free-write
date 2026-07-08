#!/usr/bin/env python3
import os
import re
import sys
import json
import time
import curses
import locale
import shutil
import subprocess
from pathlib import Path

locale.setlocale(locale.LC_ALL, "")

PROJECTS_DIR  = Path.home() / "Projets"
_CONFIG_FILE  = Path.home() / ".config" / "distracfreewrite" / "config.json"
_settings: dict = {"theme": "dark"}


def _load_settings():
    global _settings
    if _CONFIG_FILE.exists():
        try:
            _settings.update(json.loads(_CONFIG_FILE.read_text()))
        except Exception:
            pass


def _save_settings():
    _CONFIG_FILE.parent.mkdir(parents=True, exist_ok=True)
    _CONFIG_FILE.write_text(json.dumps(_settings, indent=2))


def _apply_theme(stdscr):
    if not curses.has_colors():
        return
    theme = _settings.get("theme", "dark")
    if theme == "light":
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
        stdscr.bkgd(" ", curses.color_pair(1))
    elif theme == "sepia":
        # Fond crème chaud + texte brun-gris doux → réduction fatigue visuelle
        if curses.can_change_color() and curses.COLORS >= 16:
            curses.init_color(8, 973, 941, 863)   # fond crème
            curses.init_color(9, 239, 208, 188)   # texte brun-gris
            curses.init_pair(1, 9, 8)
        elif curses.can_change_color():
            # TTY 8 couleurs : redéfinir le jaune (3) en crème, jamais de bleu/rose
            curses.init_color(3, 973, 941, 863)
            curses.init_pair(1, curses.COLOR_BLACK, 3)
        else:
            curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_YELLOW)
        stdscr.bkgd(" ", curses.color_pair(1))
    else:
        curses.init_pair(1, -1, -1)
        stdscr.bkgd(" ")


# ── statut système (batterie / wifi) ─────────────────────────────────────────

_sys_cache: dict = {"bat": "", "wifi": "", "ts": 0.0}
_last_redraw: float = 0.0
_REDRAW_INTERVAL: float = 5.0  # secondes entre deux repaints complets


def _read_battery() -> str:
    for name in ("BAT0", "BAT1", "BAT2"):
        cap = Path(f"/sys/class/power_supply/{name}/capacity")
        sta = Path(f"/sys/class/power_supply/{name}/status")
        if cap.exists():
            try:
                pct = cap.read_text().strip()
                st  = sta.read_text().strip() if sta.exists() else ""
                sym = "+" if st in ("Charging", "Full") else ""
                return f"{pct}%{sym}"
            except OSError:
                pass
    return ""


def _read_wifi_ssid() -> str:
    try:
        r = subprocess.run(["iwgetid", "-r"], capture_output=True, text=True, timeout=2)
        return r.stdout.strip()
    except Exception:
        pass
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "ACTIVE,SSID", "device", "wifi"],
            capture_output=True, text=True, timeout=2,
        )
        for line in r.stdout.splitlines():
            if line.startswith("yes:"):
                return line[4:]
    except Exception:
        pass
    return ""


def _is_wifi_connected() -> bool:
    return bool(_read_wifi_ssid())


def _is_network_connected() -> bool:
    """True si une connexion réseau est active (WiFi ou Ethernet)."""
    if shutil.which("nmcli"):
        try:
            r = subprocess.run(
                ["nmcli", "-t", "-f", "STATE", "general"],
                capture_output=True, text=True, timeout=3,
            )
            if "connected" in r.stdout.lower():
                return True
        except Exception:
            pass
    try:
        r = subprocess.run(["ip", "route", "show", "default"],
                           capture_output=True, text=True, timeout=2)
        return bool(r.stdout.strip())
    except Exception:
        return False


def _wifi_set_radio(on: bool):
    if not shutil.which("nmcli"):
        return
    try:
        subprocess.run(
            ["nmcli", "radio", "wifi", "on" if on else "off"],
            capture_output=True, timeout=5,
        )
        _sys_cache["ts"] = 0.0
    except Exception:
        pass


def _refresh_sys_status():
    now = time.time()
    if now - _sys_cache["ts"] < 10:
        return
    _sys_cache["ts"] = now
    _sys_cache["bat"] = _read_battery()
    if _settings.get("wifi_off", False):
        _sys_cache["wifi"] = "WiFi:OFF"
    else:
        ssid = _read_wifi_ssid()
        if ssid:
            _sys_cache["wifi"] = f"WiFi:{ssid}"
        elif _is_network_connected():
            _sys_cache["wifi"] = "ETH"
        else:
            _sys_cache["wifi"] = "WiFi:--"


# ── utilitaires écran ────────────────────────────────────────────────────────

def clamp(v, lo, hi):
    return max(lo, min(hi, v))


def topbar(stdscr, text: str, status: bool = True):
    h, w = stdscr.getmaxyx()
    if status:
        _refresh_sys_status()
        parts = [p for p in (_sys_cache["bat"], _sys_cache["wifi"]) if p]
        right = ("   ".join(parts) + "  ") if parts else ""
    else:
        right = ""
    title  = f"  DISTRACFREEWRITE  —  {text}"
    avail  = max(0, w - 1 - len(right))
    line   = title[:avail].ljust(avail) + right
    try:
        stdscr.attron(curses.A_REVERSE | curses.A_BOLD)
        stdscr.addstr(0, 0, line[:w - 1])
        stdscr.attroff(curses.A_REVERSE | curses.A_BOLD)
    except curses.error:
        pass


def bottombar(stdscr, text: str):
    h, w = stdscr.getmaxyx()
    try:
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(h - 1, 0, text[:w - 1].ljust(w - 1))
        stdscr.attroff(curses.A_REVERSE)
    except curses.error:
        pass


def tree_lines(path: Path, prefix: str = "", depth: int = 0, max_depth: int = 3) -> list[str]:
    if depth > max_depth:
        return []
    try:
        items = sorted(
            (p for p in path.iterdir() if p.name != ".git"),
            key=lambda p: (p.is_file(), p.name.lower()),
        )
    except PermissionError:
        return []
    lines = []
    for i, item in enumerate(items):
        last = i == len(items) - 1
        connector = "└── " if last else "├── "
        name = item.name + "/" if item.is_dir() else item.name
        lines.append(prefix + connector + name)
        if item.is_dir():
            ext = "    " if last else "│   "
            lines.extend(tree_lines(item, prefix + ext, depth + 1, max_depth))
    return lines


def file_preview(path: Path, max_lines: int = 40) -> list[str]:
    try:
        return path.read_text(encoding="utf-8", errors="replace").split("\n")[:max_lines]
    except Exception:
        return ["(impossible à lire)"]


def _format_age(path: Path) -> str:
    try:
        age = time.time() - path.stat().st_mtime
        if age < 60:      return "<1m"
        if age < 3600:    return f"{int(age / 60)}m"
        if age < 86400:   return f"{int(age / 3600)}h"
        return f"{int(age / 86400)}j"
    except OSError:
        return ""


def _format_size(path: Path) -> str:
    try:
        sz = path.stat().st_size
        if sz < 1024:         return f"{sz}o"
        if sz < 1024 * 1024:  return f"{sz // 1024}Ko"
        return f"{sz // (1024 * 1024)}Mo"
    except OSError:
        return ""


def draw_panel(stdscr, items: list[Path], sel: int):
    """Liste à gauche, prévisualisation à droite, séparées par une ligne verticale."""
    h, w = stdscr.getmaxyx()
    content_h = h - 2          # lignes entre topbar et bottombar
    left_w = max(18, min(36, w // 3))
    sep_x  = left_w
    right_x = left_w + 1
    right_w = w - right_x - 1

    # Séparateur vertical
    for row in range(1, h - 1):
        try:
            stdscr.addch(row, sep_x, curses.ACS_VLINE)
        except curses.error:
            pass

    # Panneau gauche — liste
    if not items:
        msg = "(vide)"
        try:
            stdscr.addstr(h // 2, max(0, (left_w - len(msg)) // 2), msg, curses.A_DIM)
        except curses.error:
            pass
    else:
        offset = clamp(sel - content_h // 2, 0, max(0, len(items) - content_h))
        for i in range(offset, min(offset + content_h, len(items))):
            row = 1 + (i - offset)
            item = items[i]
            is_sel = (i == sel)
            prefix = " ▶ " if is_sel else "   "
            name = item.name + "/" if item.is_dir() else item.name
            if not item.is_dir() and left_w >= 22:
                meta  = f" {_format_age(item)}·{_format_size(item)}"
                avail = left_w - len(prefix) - len(meta)
                line  = (prefix + name[:avail].ljust(avail) + meta) if avail > 2 else (prefix + name)[:left_w]
            else:
                line = (prefix + name)[:left_w]
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row, 0, line.ljust(left_w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, line)
            except curses.error:
                pass

    # Panneau droit — prévisualisation
    if items and right_w > 4:
        item = items[sel]
        title = (item.name + "/") if item.is_dir() else item.name
        try:
            stdscr.addstr(1, right_x + 1, title[:right_w - 1], curses.A_BOLD)
        except curses.error:
            pass

        preview = tree_lines(item) if item.is_dir() else file_preview(item)
        for i, line in enumerate(preview[:content_h - 2]):
            try:
                stdscr.addstr(2 + i, right_x + 1, line[:right_w - 1])
            except curses.error:
                pass


def get_input(stdscr, label: str, prefill: str = "") -> str:
    """Saisie inline dans la barre du bas. Retourne "" si Échap."""
    h, w = stdscr.getmaxyx()
    curses.curs_set(1)
    text = prefill
    prompt = f"  {label} : "

    while True:
        bar = (prompt + text)[:w - 2] + " "
        try:
            stdscr.attron(curses.A_REVERSE)
            stdscr.addstr(h - 1, 0, bar.ljust(w - 1))
            stdscr.move(h - 1, min(len(prompt) + len(text), w - 2))
            stdscr.attroff(curses.A_REVERSE)
        except curses.error:
            pass
        stdscr.refresh()

        try:
            key = stdscr.get_wch()
        except curses.error:
            continue

        if isinstance(key, str):
            code = ord(key)
            if key in ("\n", "\r"):
                break
            elif code == 27:
                text = ""
                break
            elif code in (127, 8):
                text = text[:-1]
            elif code >= 32:
                text += key
        elif isinstance(key, int):
            if key == curses.KEY_BACKSPACE:
                text = text[:-1]

    curses.curs_set(0)
    return text.strip()


def confirm(stdscr, question: str) -> bool:
    h, w = stdscr.getmaxyx()
    bar = f"  {question}   O = Oui   N = Non"
    try:
        stdscr.attron(curses.A_REVERSE)
        stdscr.addstr(h - 1, 0, bar[:w - 1].ljust(w - 1))
        stdscr.attroff(curses.A_REVERSE)
    except curses.error:
        pass
    stdscr.refresh()

    while True:
        try:
            key = stdscr.get_wch()
        except curses.error:
            continue
        if isinstance(key, str):
            if key.lower() == "o":
                return True
            if key.lower() == "n" or ord(key) == 27:
                return False


# Séquences d'échappement non reconnues automatiquement par curses.
# Utilisées comme fallback quand get_wch() renvoie '\033' seul.
_ESC_MAP: dict[str, int] = {
    # Flèches (xterm / vt100 / rxvt)
    "\033[A": curses.KEY_UP,    "\033OA": curses.KEY_UP,
    "\033[B": curses.KEY_DOWN,  "\033OB": curses.KEY_DOWN,
    "\033[C": curses.KEY_RIGHT, "\033OC": curses.KEY_RIGHT,
    "\033[D": curses.KEY_LEFT,  "\033OD": curses.KEY_LEFT,
    # Home / End
    "\033[H": curses.KEY_HOME,  "\033OH": curses.KEY_HOME,
    "\033[1~": curses.KEY_HOME, "\033[7~": curses.KEY_HOME,
    "\033[F": curses.KEY_END,   "\033OF": curses.KEY_END,
    "\033[4~": curses.KEY_END,  "\033[8~": curses.KEY_END,
    # Page Up / Down
    "\033[5~": curses.KEY_PPAGE,
    "\033[6~": curses.KEY_NPAGE,
    # Suppr (delete forward)
    "\033[3~": curses.KEY_DC,
    # Shift + flèches (xterm / iTerm2 / Terminal.app)
    "\033[1;2C": curses.KEY_SRIGHT, "\033[2C": curses.KEY_SRIGHT,
    "\033[1;2D": curses.KEY_SLEFT,  "\033[2D": curses.KEY_SLEFT,
    "\033[1;2A": curses.KEY_SR,     "\033[2A": curses.KEY_SR,
    "\033[1;2B": curses.KEY_SF,     "\033[2B": curses.KEY_SF,
    # Shift + flèches style rxvt
    "\033[a": curses.KEY_SR,
    "\033[b": curses.KEY_SF,
    "\033[c": curses.KEY_SRIGHT,
    "\033[d": curses.KEY_SLEFT,
    # Ctrl + ← / →  (Linux / xterm / iTerm2)
    "\033[1;5D": 546, "\033[5D": 546,
    "\033[1;5C": 561, "\033[5C": 561,
    # Ctrl+Shift + ← / → / ↑ / ↓  (Linux / xterm / iTerm2)
    "\033[1;6D": 580, "\033[1;6C": 595,
    "\033[1;6A": 570, "\033[1;6B": 575,
    # Mac Option + ← / →
    "\033b": 546, "\033f": 561,
    # Mac Option+Shift + toutes directions
    "\033[1;4D": 580, "\033[1;4C": 595,
    "\033[1;4A": 570, "\033[1;4B": 575,
}


def next_key(stdscr):
    """Lit une touche. Retourne (char_str | None, keycode_int | None).
    Quand curses renvoie '\\033' seul (séquence non reconnue), on lit la
    suite manuellement avec un court timeout et on consulte _ESC_MAP.
    Effectue un redrawwin() périodique pour éliminer les artefacts TTY."""
    global _last_redraw
    stdscr.timeout(2000)
    try:
        key = stdscr.get_wch()
    except curses.error:
        # Timeout : pas de touche — repaint complet si l'intervalle est écoulé
        now = time.time()
        if now - _last_redraw >= _REDRAW_INTERVAL:
            stdscr.redrawwin()
            _last_redraw = now
        _check_auto_poweroff(stdscr)
        stdscr.timeout(-1)
        return None, None
    stdscr.timeout(-1)
    _register_activity()

    if isinstance(key, str):
        if key == "\033":
            # Lire la suite de la séquence (octets déjà dans le buffer)
            stdscr.timeout(50)
            seq = "\033"
            while len(seq) < 12:
                try:
                    c = stdscr.get_wch()
                    if isinstance(c, str):
                        seq += c
                    else:
                        break
                except curses.error:
                    break
            stdscr.timeout(-1)
            if seq == "\033":
                return "\033", None        # ESC simple (quitter l'éditeur)
            code = _ESC_MAP.get(seq)
            return (None, code) if code is not None else (None, None)
        return key, None

    return None, key


# ── git ─────────────────────────────────────────────────────────────────────

def _git(cwd: Path, *args) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["git"] + list(args), cwd=cwd,
            capture_output=True, text=True, timeout=10,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, str(e)


def git_available() -> bool:
    return shutil.which("git") is not None


def git_is_repo(path: Path) -> bool:
    ok, _ = _git(path, "rev-parse", "--git-dir")
    return ok


def git_init(path: Path) -> tuple[bool, str]:
    ok, out = _git(path, "init")
    if ok:
        _git(path, "add", "-A")
        _git(path, "commit", "--allow-empty", "-m", "Initialisation")
    return ok, out


def git_has_changes(path: Path) -> bool:
    _, out = _git(path, "status", "--short")
    return bool(out.strip())


def git_commit(path: Path, message: str) -> tuple[bool, str]:
    _git(path, "add", "-A")
    return _git(path, "commit", "-m", message)


def git_log(path: Path) -> list[dict]:
    ok, out = _git(path, "log", "--pretty=format:%H\x1f%ar\x1f%s", "--max-count=100")
    if not ok or not out:
        return []
    commits = []
    for line in out.splitlines():
        parts = line.split("\x1f", 2)
        if len(parts) == 3:
            commits.append({"hash": parts[0][:7], "full": parts[0], "date": parts[1], "msg": parts[2]})
    return commits


def git_restore(path: Path, full_hash: str) -> tuple[bool, str]:
    if git_has_changes(path):
        _git(path, "add", "-A")
        _git(path, "commit", "-m", "Sauvegarde automatique avant restauration")
    return _git(path, "checkout", full_hash, "--", ".")


def git_show_stat(path: Path, full_hash: str) -> list[str]:
    ok, out = _git(path, "show", "--stat", "--format=", full_hash)
    if not ok:
        return ["(impossible de lire le commit)"]
    return [l for l in out.splitlines() if l.strip()]


def git_current_branch(path: Path) -> str:
    ok, out = _git(path, "branch", "--show-current")
    return out.strip() if ok else "?"


def git_branches(path: Path) -> list[str]:
    ok, out = _git(path, "branch", "--format=%(refname:short)")
    local = [b.strip() for b in out.splitlines() if b.strip()] if ok else []

    ok2, out2 = _git(path, "branch", "-r", "--format=%(refname:short)")
    local_set = set(local)
    remote_only = []
    if ok2:
        for b in out2.splitlines():
            b = b.strip()
            if not b or "/HEAD" in b:
                continue
            name = b.split("/", 1)[-1] if "/" in b else b
            if name not in local_set:
                remote_only.append(name)

    return local + [f"{b}  [remote]" for b in remote_only]


def git_config_get(key: str) -> str:
    """Lit une valeur de git config --global. Retourne '' si absente."""
    try:
        r = subprocess.run(
            ["git", "config", "--global", key],
            capture_output=True, text=True,
        )
        return r.stdout.strip() if r.returncode == 0 else ""
    except FileNotFoundError:
        return ""


def git_config_set(key: str, value: str) -> tuple[bool, str]:
    """Écrit une valeur dans git config --global."""
    try:
        r = subprocess.run(
            ["git", "config", "--global", key, value],
            capture_output=True, text=True,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except FileNotFoundError as e:
        return False, str(e)


def git_identity_ok() -> bool:
    """True si user.name et user.email sont configurés."""
    return bool(git_config_get("user.name") and git_config_get("user.email"))


def git_push(path: Path) -> tuple[bool, str]:
    branch = git_current_branch(path)
    ok, out = _git(path, "push", "origin", branch)
    if not ok and ("upstream" in out.lower() or "set-upstream" in out.lower()):
        ok, out = _git(path, "push", "--set-upstream", "origin", branch)
    return ok, out


def git_pull(path: Path) -> tuple[bool, str]:
    ok, out = _git(path, "pull")
    if not ok and "unrelated" in out.lower():
        ok, out = _git(path, "pull", "--allow-unrelated-histories")
    return ok, out


def git_clone(url: str, dest: Path) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["git", "clone", url, str(dest)],
            capture_output=True, text=True, timeout=120,
        )
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except (subprocess.TimeoutExpired, FileNotFoundError) as e:
        return False, str(e)


def git_create_branch(path: Path, name: str) -> tuple[bool, str]:
    return _git(path, "checkout", "-b", name)


def git_switch_branch(path: Path, name: str) -> tuple[bool, str]:
    ok, out = _git(path, "checkout", name)
    if not ok and ("did not match" in out or "pathspec" in out.lower()):
        ok, out = _git(path, "checkout", "-b", name, f"origin/{name}")
    return ok, out


def git_remote_url(path: Path) -> str:
    ok, out = _git(path, "remote", "get-url", "origin")
    return out if ok else ""


def git_set_remote(path: Path, url: str) -> tuple[bool, str]:
    ok, _ = _git(path, "remote", "get-url", "origin")
    if ok:
        return _git(path, "remote", "set-url", "origin", url)
    return _git(path, "remote", "add", "origin", url)


def git_fetch(path: Path) -> tuple[bool, str]:
    return _git(path, "fetch", "--quiet")


def git_ahead_behind(path: Path) -> tuple[int, int]:
    """Retourne (en avance, en retard) par rapport au remote."""
    ok, out = _git(path, "rev-list", "--left-right", "--count", "HEAD...@{u}")
    if not ok or not out:
        return 0, 0
    parts = out.split()
    try:
        return int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        return 0, 0


# ── SSH ──────────────────────────────────────────────────────────────────────

_SSH_CANDIDATES = [
    Path.home() / ".ssh" / "id_ed25519.pub",
    Path.home() / ".ssh" / "id_rsa.pub",
    Path.home() / ".ssh" / "id_ecdsa.pub",
]


def _get_pubkey() -> tuple[str, Path | None]:
    for p in _SSH_CANDIDATES:
        if p.exists():
            return p.read_text().strip(), p
    return "", None


# ── pages utilitaires ────────────────────────────────────────────────────────

def _loader(stdscr, message: str):
    """Affiche un message d'attente plein écran (opération bloquante)."""
    h, w = stdscr.getmaxyx()
    stdscr.clear()
    try:
        stdscr.addstr(h // 2, max(0, (w - len(message)) // 2), message, curses.A_DIM)
    except curses.error:
        pass
    bottombar(stdscr, "  Veuillez patienter...")
    stdscr.refresh()
    # Force un repaint complet au retour pour éviter les artefacts post-subprocess
    stdscr.redrawwin()


def _text_page(stdscr, title: str, lines: list[str]):
    """Page plein écran scrollable — texte brut, aucun caractère de boîte."""
    offset = 0
    while True:
        h, w = stdscr.getmaxyx()
        content_h = h - 2
        stdscr.erase()
        topbar(stdscr, title)
        visible = lines[offset:offset + content_h]
        for i, line in enumerate(visible):
            try:
                stdscr.addstr(1 + i, 2, line[:w - 3])
            except curses.error:
                pass
        if len(lines) > content_h:
            bar = f"  haut/bas PgUp PgDn  {offset + 1}-{min(offset + content_h, len(lines))}/{len(lines)}   <- Retour"
        else:
            bar = "  <- Retour"
        bottombar(stdscr, bar)
        stdscr.refresh()
        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            offset = max(0, offset - 1)
        elif code == curses.KEY_DOWN:
            offset = min(max(0, len(lines) - content_h), offset + 1)
        elif code == curses.KEY_PPAGE:
            offset = max(0, offset - content_h)
        elif code == curses.KEY_NPAGE:
            offset = min(max(0, len(lines) - content_h), offset + content_h)
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


def _usb_automount(devpath: str) -> str | None:
    """Tente de monter un périphérique via udisksctl ; retourne le point de montage ou None."""
    try:
        r = subprocess.run(
            ["udisksctl", "mount", "-b", devpath, "--no-user-interaction"],
            capture_output=True, text=True, timeout=15,
        )
        if r.returncode == 0:
            # "Mounted /dev/sdb1 at /media/user/USBNAME."
            for part in r.stdout.split():
                if part.startswith("/") and part != devpath:
                    return part.rstrip(".")
    except (subprocess.TimeoutExpired, FileNotFoundError):
        pass
    return None


def _find_usb_drives() -> list[Path]:
    """Retourne les points de montage des périphériques amovibles.

    Utilise lsblk pour trouver les partitions amovibles (sdb, sdc…),
    les monte automatiquement via udisksctl si nécessaire, puis complète
    avec un scan classique de /media et /mnt.
    """
    import os as _os
    seen: set[Path] = set()
    result: list[Path] = []

    # --- lsblk : détection des périphériques amovibles --------------------
    try:
        r = subprocess.run(
            ["lsblk", "-J", "-o", "NAME,RM,MOUNTPOINT,FSTYPE,TYPE"],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0:
            import json as _json
            data = _json.loads(r.stdout)
            for dev in data.get("blockdevices", []):
                children = dev.get("children") or ([dev] if dev.get("type") == "disk" else [])
                for part in children:
                    if not part.get("rm"):          # pas amovible
                        continue
                    if not part.get("fstype"):      # pas de système de fichiers
                        continue
                    mp = part.get("mountpoint") or ""
                    if mp and mp != "[SWAP]":
                        p = Path(mp)
                        if p not in seen:
                            result.append(p)
                            seen.add(p)
                    else:
                        devpath = f"/dev/{part['name']}"
                        mp = _usb_automount(devpath)
                        if mp:
                            p = Path(mp)
                            if p not in seen:
                                result.append(p)
                                seen.add(p)
    except (subprocess.TimeoutExpired, FileNotFoundError, Exception):
        pass

    # --- fallback : scan classique des répertoires de montage -------------
    username = Path.home().name
    roots = [
        Path("/media") / username,
        Path("/run/media") / username,
        Path("/media"),
        Path("/mnt"),
    ]
    for root in roots:
        if not root.is_dir():
            continue
        try:
            children = sorted(root.iterdir())
        except PermissionError:
            continue
        for child in children:
            if child.is_dir() and _os.path.ismount(child) and child not in seen:
                result.append(child)
                seen.add(child)
    return result


def _pick_usb(stdscr) -> "Path | None":
    """Page plein écran pour choisir une clé USB montée."""
    import os as _os
    drives = _find_usb_drives()
    if not drives:
        _text_page(stdscr, "Aucune clé USB détectée", [
            "Branchez votre clé USB et réessayez.",
            "",
            "Les clés doivent être montées sous /media ou /mnt.",
        ])
        return None

    sel = 0
    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "Choisir une clé USB")
        sel = clamp(sel, 0, len(drives) - 1)
        for i, drive in enumerate(drives):
            is_sel = (i == sel)
            try:
                st = _os.statvfs(drive)
                free_mb = st.f_bavail * st.f_frsize // (1024 * 1024)
                free_str = f"  ({free_mb} Mo libres)"
            except OSError:
                free_str = ""
            line = f" {'>' if is_sel else ' '}  {drive}{free_str}"
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(1 + i, 0, line[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(1 + i, 0, line[:w])
            except curses.error:
                pass
        bottombar(stdscr, "  haut/bas Naviguer   -> Choisir   <- Annuler")
        stdscr.refresh()
        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(len(drives) - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            return drives[sel]
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return None


def _ssh_view(stdscr):
    """Page clé SSH — texte brut + export USB."""
    pub_key, key_path = _get_pubkey()

    if not pub_key:
        if not confirm(stdscr, "Aucune clé SSH trouvée. Générer une clé ed25519 ?"):
            return
        _loader(stdscr, "Génération de la clé SSH en cours...")
        ssh_dir = Path.home() / ".ssh"
        ssh_dir.mkdir(mode=0o700, exist_ok=True)
        new_key = ssh_dir / "id_ed25519"
        try:
            r = subprocess.run(
                ["ssh-keygen", "-t", "ed25519", "-N", "", "-f", str(new_key)],
                capture_output=True, text=True, timeout=15,
            )
            if r.returncode != 0:
                _text_page(stdscr, "Erreur — ssh-keygen", (r.stdout + r.stderr).splitlines())
                return
        except Exception as e:
            _text_page(stdscr, "Erreur — ssh-keygen", [str(e)])
            return
        pub_key, key_path = _get_pubkey()
        if not pub_key:
            _text_page(stdscr, "Erreur", ["Impossible de lire la clé générée."])
            return

    lines = [
        f"Fichier : {key_path}",
        "",
        "Ajoutez cette cle dans GitHub :",
        "  Settings -> SSH and GPG keys -> New SSH key",
        "",
        "Selectionnez la ligne ci-dessous avec la souris pour la copier :",
        "",
        pub_key,
    ]

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "Cle SSH publique")
        for i, line in enumerate(lines[:h - 2]):
            try:
                stdscr.addstr(1 + i, 2, line[:w - 3])
            except curses.error:
                pass
        bottombar(stdscr, "  E Exporter sur cle USB   <- Retour")
        stdscr.refresh()
        ch, code = next_key(stdscr)
        if code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return
        elif ch is not None and ch.lower() == "e":
            drive = _pick_usb(stdscr)
            if drive and key_path:
                dest = drive / key_path.name
                try:
                    shutil.copy2(key_path, dest)
                    _flash(stdscr, f"Cle SSH copiee vers {dest}")
                except Exception as ex:
                    _text_page(stdscr, "Erreur export SSH", [str(ex)])


# ── vues git ─────────────────────────────────────────────────────────────────

def _history_view(stdscr, project_path: Path):
    """Historique plein écran : commits à gauche, stats à droite."""
    commits = git_log(project_path)
    sel = 0
    ahead = behind = 0
    remote = git_remote_url(project_path)

    if remote:
        _loader(stdscr, "Récupération de l'historique remote...")
        git_fetch(project_path)
        ahead, behind = git_ahead_behind(project_path)

    while True:
        sel = clamp(sel, 0, max(0, len(commits) - 1))
        h, w = stdscr.getmaxyx()
        left_w  = max(22, min(46, w // 2))
        right_x = left_w + 1
        right_w = w - right_x - 1
        content_h = h - 2

        stdscr.erase()

        badge = ""
        if behind and ahead: badge = f"  ↑{ahead} ↓{behind}"
        elif ahead:          badge = f"  ↑ {ahead} à pousser"
        elif behind:         badge = f"  ↓ {behind} à récupérer"
        topbar(stdscr, f"Historique{badge}")

        for row in range(1, h - 1):
            try: stdscr.addch(row, left_w, curses.ACS_VLINE)
            except curses.error: pass

        if not commits:
            try:
                m = "(aucun commit)"
                stdscr.addstr(h // 2, max(0, (left_w - len(m)) // 2), m, curses.A_DIM)
            except curses.error:
                pass
        else:
            offset = clamp(sel - content_h // 2, 0, max(0, len(commits) - content_h))
            for i in range(offset, min(offset + content_h, len(commits))):
                row = 1 + (i - offset)
                c = commits[i]
                is_sel = (i == sel)
                line = f"{' ▶ ' if is_sel else '   '}{c['hash']}  {c['msg']}"
                date = f"    {c['date']}"
                try:
                    if is_sel:
                        stdscr.attron(curses.A_REVERSE)
                        stdscr.addstr(row, 0, line[:left_w].ljust(left_w))
                        stdscr.attroff(curses.A_REVERSE)
                    else:
                        stdscr.addstr(row, 0, line[:left_w])
                except curses.error:
                    pass

        if commits and right_w > 4:
            c = commits[sel]
            try:
                stdscr.addstr(1, right_x + 1, f"{c['hash']}  {c['date']}"[:right_w - 1], curses.A_BOLD)
            except curses.error:
                pass
            for i, line in enumerate(git_show_stat(project_path, c["full"])[:content_h - 2]):
                try: stdscr.addstr(2 + i, right_x + 1, line[:right_w - 1])
                except curses.error: pass

        bottombar(stdscr, "  haut/bas Naviguer   -> Restaurer cette version   <- Retour")
        stdscr.refresh()

        ch, code = next_key(stdscr)

        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(max(0, len(commits) - 1), sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            if commits:
                c = commits[sel]
                if confirm(stdscr, f"Restaurer « {c['msg']} » ({c['date']}) ? L'etat actuel sera sauvegarde d'abord."):
                    ok, out = git_restore(project_path, c["full"])
                    _flash(stdscr, "Version restauree" if ok else f"Erreur : {out[:60]}")
                    return
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


def _pick_branch(stdscr, branches: list[str]) -> str | None:
    """Page plein écran de sélection de branche."""
    sel = 0
    while True:
        h, w = stdscr.getmaxyx()
        content_h = h - 2
        stdscr.erase()
        topbar(stdscr, "Changer de branche")
        sel = clamp(sel, 0, len(branches) - 1)
        offset = clamp(sel - content_h // 2, 0, max(0, len(branches) - content_h))
        for i in range(offset, min(offset + content_h, len(branches))):
            row = 1 + (i - offset)
            is_sel = (i == sel)
            line = f" {'>' if is_sel else ' '}  {branches[i]}"
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row, 0, line[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, line[:w])
            except curses.error:
                pass
        bottombar(stdscr, "  haut/bas Naviguer   -> Choisir   <- Annuler")
        stdscr.refresh()
        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(len(branches) - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            return branches[sel]
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return None


_GIT_ACTIONS = [
    ("diff",    "Voir les modifications en cours"),
    ("commit",  "Commiter les modifications"),
    ("push",    "Pousser vers le remote  (push)"),
    ("pull",    "Récupérer depuis le remote  (pull)"),
    ("branch",  "Créer une nouvelle branche"),
    ("switch",  "Changer de branche"),
    ("history", "Historique / Restaurer une version"),
    ("remote",  "Configurer le remote GitHub"),
    ("ssh",     "Voir ma clé SSH  (pour GitHub)"),
]


def _err(stdscr, title: str, out: str) -> str:
    lines = out.splitlines() or ["(pas de detail)"]
    _text_page(stdscr, f"Erreur — {title}", lines)
    return f"✗ Echec : {title}"


def _git_exec(stdscr, project_path: Path, action: str, remote: str) -> str | None:
    if action == "init":
        ok, out = git_init(project_path)
        if not ok:
            return _err(stdscr, "git init", out)
        return "✓ Dépôt Git initialisé"

    if action == "diff":
        _, out = _git(project_path, "diff", "HEAD")
        lines = out.splitlines() or ["(aucune modification par rapport au dernier commit)"]
        _text_page(stdscr, f"Modifications en cours — {project_path.name}", lines)
        return None

    if action == "commit":
        if not git_identity_ok():
            _flash(stdscr, "Identite Git non configuree — ouvrez Parametres > Git", 2.5)
            settings_screen(stdscr)
            if not git_identity_ok():
                return None
        if not git_has_changes(project_path):
            return "Aucune modification à commiter."
        msg = get_input(stdscr, "Message du commit")
        if not msg:
            return None
        ok, out = git_commit(project_path, msg)
        if not ok:
            return _err(stdscr, "git commit", out)
        return "✓ Commit créé"

    if action == "push":
        if not remote:
            return "Configurez d'abord un remote GitHub (option 7)."
        _loader(stdscr, "Envoi vers GitHub (push)...")
        ok, out = git_push(project_path)
        if not ok:
            return _err(stdscr, "git push", out)
        return "✓ Push reussi"

    if action == "pull":
        if not remote:
            return "Configurez d'abord un remote GitHub (option 7)."
        _loader(stdscr, "Recuperation depuis GitHub (pull)...")
        ok, out = git_pull(project_path)
        if not ok:
            return _err(stdscr, "git pull", out)
        return "✓ Pull reussi"

    if action == "branch":
        name = get_input(stdscr, "Nom de la nouvelle branche")
        if not name:
            return None
        ok, out = git_create_branch(project_path, name)
        if not ok:
            return _err(stdscr, "git branch", out)
        return f"✓ Branche « {name} » créée et activée"

    if action == "switch":
        branches = git_branches(project_path)
        if not branches:
            return "Aucune branche disponible."
        chosen = _pick_branch(stdscr, branches)
        if not chosen:
            return None
        branch_name = chosen.removesuffix("  [remote]")
        ok, out = git_switch_branch(project_path, branch_name)
        if not ok:
            return _err(stdscr, "git checkout", out)
        return f"✓ Basculé sur « {branch_name} »"

    if action == "history":
        _history_view(stdscr, project_path)
        return None

    if action == "remote":
        current = git_remote_url(project_path)
        url = get_input(stdscr, "URL GitHub (remote origin)", prefill=current)
        if not url:
            return None
        ok, out = git_set_remote(project_path, url)
        if not ok:
            return _err(stdscr, "git remote", out)
        return "✓ Remote configuré"

    if action == "ssh":
        _ssh_view(stdscr)
        return None

    return None


def _wait_wifi_up(stdscr, timeout: int = 20) -> bool:
    """Attend la reconnexion automatique après activation du radio WiFi.
    Affiche un écran d'attente. Retourne True dès qu'une connexion est détectée."""
    for elapsed in range(timeout):
        if _is_wifi_connected():
            break
        dots = "." * ((elapsed % 3) + 1)
        h, w = stdscr.getmaxyx()
        stdscr.clear()
        msg = f"Activation du WiFi{dots}"
        try:
            stdscr.addstr(h // 2, max(0, (w - len(msg)) // 2), msg, curses.A_DIM)
        except curses.error:
            pass
        bottombar(stdscr, f"  Reconnexion automatique en cours...  ({timeout - elapsed}s)")
        stdscr.refresh()
        time.sleep(1)
    stdscr.redrawwin()
    return _is_wifi_connected()


def git_page(stdscr, project_path: Path):
    """Page Git plein écran — gère l'état WiFi avant d'entrer."""
    _wifi_managed = _settings.get("wifi_off", False)

    # WiFi désactivé : l'activer et attendre reconnexion automatique
    if _wifi_managed:
        _wifi_set_radio(True)
        _wait_wifi_up(stdscr)

    # Toujours pas connecté → écran de connexion WiFi
    if not _is_network_connected():
        _flash(stdscr, "WiFi non connecte — redirection vers la connexion...", 1.2)
        _wifi_connect_screen(stdscr)

    # Dernier contrôle — si l'utilisateur a annulé sans se connecter
    if not _is_network_connected():
        if _wifi_managed:
            _wifi_set_radio(False)
        _flash(stdscr, "Git necessite une connexion reseau.")
        return

    try:
        _git_page_inner(stdscr, project_path)
    finally:
        if _wifi_managed:
            _wifi_set_radio(False)


def _git_page_inner(stdscr, project_path: Path):
    sel = 0
    flash = ""
    flash_until = 0.0
    ahead = behind = 0
    fetched = False

    while True:
        is_repo = git_is_repo(project_path)
        remote  = git_remote_url(project_path) if is_repo else ""

        if is_repo and remote and not fetched:
            _loader(stdscr, "Verification du remote (fetch)...")
            git_fetch(project_path)
            ahead, behind = git_ahead_behind(project_path)
            fetched = True

        actions = _GIT_ACTIONS if is_repo else [("init", "Initialiser un depot Git")]
        sel = clamp(sel, 0, len(actions) - 1)

        status: list[str] = []
        if not is_repo:
            status = ["Aucun depot Git dans ce projet."]
        else:
            branch  = git_current_branch(project_path)
            changes = git_has_changes(project_path)
            status.append(f"Branche : {branch}")
            status.append("  Modifications non commitees" if changes else "  Aucune modification locale")
            if remote:
                parts = []
                if ahead:  parts.append(f"  {ahead} commit(s) non pousse(s)")
                if behind: parts.append(f"  {behind} commit(s) a recuperer")
                status.append("  ".join(parts) if parts else "  Synchronise avec le remote")
                status.append(f"  {remote}")
            else:
                status.append("  Aucun remote GitHub configure")

        h, w = stdscr.getmaxyx()
        content_h = h - 2
        stdscr.erase()
        topbar(stdscr, f"Git — {project_path.name}")

        now = time.time()
        show_flash = flash and now < flash_until
        row = 1

        if show_flash:
            try:
                stdscr.addstr(row, 2, flash[:w - 3], curses.A_BOLD)
            except curses.error:
                pass
            row += 1

        for line in status:
            try:
                stdscr.addstr(row, 2, line[:w - 3])
            except curses.error:
                pass
            row += 1

        row += 1  # ligne vide séparateur

        for i, (_, label) in enumerate(actions):
            if row >= h - 1:
                break
            is_sel = (i == sel)
            line = f" {'>' if is_sel else ' '}  {label}"
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row, 0, line[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, line[:w])
            except curses.error:
                pass
            row += 1

        bottombar(stdscr, "  haut/bas Naviguer   -> Executer   <- Retour")
        stdscr.refresh()

        ch, code = next_key(stdscr)

        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(len(actions) - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            result = _git_exec(stdscr, project_path, actions[sel][0], remote)
            if result:
                flash = result
                flash_until = time.time() + 3.0
                fetched = False
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


# ── éditeur de texte ─────────────────────────────────────────────────────────

def _wrap_segs(text: str, width: int) -> "list[tuple[int,int]]":
    """Word-wrap. Retourne (start, end) pour chaque ligne visuelle."""
    if width <= 0 or not text:
        return [(0, len(text))]
    segs: list[tuple[int, int]] = []
    i, n = 0, len(text)
    while i < n:
        if i + width >= n:
            segs.append((i, n))
            break
        k = text.rfind(' ', i, i + width)
        if k > i:
            segs.append((i, k + 1))   # inclut l'espace final
            i = k + 1
        else:
            segs.append((i, i + width))
            i += width
    return segs or [(0, 0)]


def _cx_to_vrc(segs: "list[tuple[int,int]]", cx: int) -> "tuple[int,int]":
    """Convertit un offset fichier cx en (ligne_visuelle, colonne_visuelle)."""
    n = len(segs)
    for i, (s, e) in enumerate(segs):
        if i < n - 1:
            if s <= cx < e:
                return i, cx - s
        else:
            if s <= cx <= e:
                return i, cx - s
    return n - 1, max(0, cx - segs[-1][0])


class Editor:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.lines: list[str] = []
        self.cy = 0
        self.cx = 0
        self.ovy = 0   # premier rang visuel visible (remplace oy)
        self._dw = 80  # largeur d'affichage utile (mis à jour par _scroll)
        self._mv = 1   # marge verticale (mis à jour par _scroll)
        self.sel_anchor: "tuple[int,int] | None" = None
        self._load()

    def _load(self):
        if self.filepath.exists():
            text = self.filepath.read_text(encoding="utf-8")
            self.lines = text.split("\n")
            if self.lines and self.lines[-1] == "":
                self.lines.pop()
        if not self.lines:
            self.lines = [""]
        # Ouvrir en bas du fichier
        self.cy = len(self.lines) - 1
        self.cx = len(self.lines[self.cy])

    def _save(self):
        self.filepath.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    # ── sélection ────────────────────────────────────────────────────────────

    def _sel_range(self) -> "tuple[tuple[int,int],tuple[int,int]] | None":
        if self.sel_anchor is None:
            return None
        a, b = self.sel_anchor, (self.cy, self.cx)
        if a == b:
            return None
        return (min(a, b), max(a, b))

    def _sel_clear(self):
        self.sel_anchor = None

    def _sel_anchor_here(self):
        if self.sel_anchor is None:
            self.sel_anchor = (self.cy, self.cx)

    def _sel_delete(self):
        rng = self._sel_range()
        if not rng:
            self._sel_clear()
            return
        (r1, c1), (r2, c2) = rng
        if r1 == r2:
            ln = self.lines[r1]
            self.lines[r1] = ln[:c1] + ln[c2:]
        else:
            self.lines[r1] = self.lines[r1][:c1] + self.lines[r2][c2:]
            del self.lines[r1 + 1:r2 + 1]
        self.cy, self.cx = r1, c1
        self._sel_clear()

    # ── affichage ─────────────────────────────────────────────────────────────

    def _total_vrows_before(self, line_idx: int) -> int:
        total = 0
        for i in range(line_idx):
            total += len(_wrap_segs(self.lines[i], self._dw))
        return total

    def _render(self, stdscr, h: int, w: int):
        margin  = _settings.get("margin",   1)
        mv      = self._mv
        max_row = h - mv          # première ligne après la zone de texte
        sel_rng = self._sel_range()
        stdscr.erase()

        # Trouver le fichier-ligne et rang-dans-ligne de ovy
        vrow = 0
        start_fl, start_ril = 0, 0
        for fl in range(len(self.lines)):
            segs = _wrap_segs(self.lines[fl], self._dw)
            nrows = len(segs)
            if vrow + nrows > self.ovy:
                start_fl = fl
                start_ril = self.ovy - vrow
                break
            vrow += nrows

        # Dessiner les lignes visuelles dans la zone [mv, max_row)
        screen_row = mv
        fl, ril_begin = start_fl, start_ril
        while screen_row < max_row and fl < len(self.lines):
            segs = _wrap_segs(self.lines[fl], self._dw)
            for ril in range(ril_begin, len(segs)):
                if screen_row >= max_row:
                    break
                s, e = segs[ril]
                chunk = self.lines[fl][s:e]
                if sel_rng is None:
                    try:
                        stdscr.addstr(screen_row, margin, chunk)
                    except curses.error:
                        pass
                else:
                    (r1, c1), (r2, c2) = sel_rng
                    for ci, ch in enumerate(chunk):
                        fc = s + ci
                        in_sel = (
                            (r1 < fl < r2) or
                            (fl == r1 == r2 and c1 <= fc < c2) or
                            (fl == r1 and fl < r2 and fc >= c1) or
                            (fl == r2 and fl > r1 and fc < c2)
                        )
                        try:
                            stdscr.addch(screen_row, margin + ci, ch,
                                         curses.A_REVERSE if in_sel else 0)
                        except curses.error:
                            pass
                screen_row += 1
            fl += 1
            ril_begin = 0

        # Position du curseur
        cy_segs = _wrap_segs(self.lines[self.cy], self._dw)
        cursor_ril, cursor_col = _cx_to_vrc(cy_segs, self.cx)
        cursor_vrow = self._total_vrows_before(self.cy) + cursor_ril
        try:
            stdscr.move(mv + cursor_vrow - self.ovy, margin + cursor_col)
        except curses.error:
            pass
        stdscr.refresh()

    def run(self, stdscr):
        prev_curs = curses.curs_set(1)
        stdscr.keypad(True)

        try:
            while True:
                h, w = stdscr.getmaxyx()
                self._scroll(h, w)

                self._render(stdscr, h, w)

                ch, code = next_key(stdscr)

                if ch is not None:
                    c = ord(ch)
                    if c == 17 or c == 27:   # Ctrl+Q ou ESC
                        break
                    elif c == 0:             # Ctrl+Space : basculer l'ancre de sélection
                        if self.sel_anchor is None:
                            self.sel_anchor = (self.cy, self.cx)
                        else:
                            self._sel_clear()
                    elif ch in ("\n", "\r"):
                        if self.sel_anchor is not None:
                            self._sel_delete()
                        self._newline(); self._save()
                    elif c in (127, 8):      # Backspace
                        if self._sel_range() is not None:
                            self._sel_delete(); self._save()
                        else:
                            self._sel_clear()
                            self._backspace(); self._save()
                    elif ch == "\t":
                        if self.sel_anchor is not None:
                            self._sel_delete()
                        self._insert("    "); self._save()
                    elif c >= 32:
                        if self.sel_anchor is not None:
                            self._sel_delete()
                        self._insert(ch); self._save()

                elif code is not None:
                    # Ctrl+← / Ctrl+→ : début/fin de ligne (efface la sélection)
                    if code in (546, 543, 545):
                        self._sel_clear(); self.cx = 0
                    elif code in (561, 558, 560):
                        self._sel_clear(); self.cx = len(self.lines[self.cy])
                    # Shift+←/→ et Ctrl+Shift+←/→ : étendre d'un caractère
                    elif code in (580, 583, 582) or code == curses.KEY_SLEFT:
                        self._sel_anchor_here(); self._move_left()
                    elif code in (595, 598, 597) or code == curses.KEY_SRIGHT:
                        self._sel_anchor_here(); self._move_right()
                    # Shift+↑ et Ctrl+Shift+↑ : ancre + fin de ligne du dessus
                    elif code in (570, curses.KEY_SR):
                        self._sel_anchor_here()
                        if self.cy > 0:
                            self.cy -= 1
                            self.cx = len(self.lines[self.cy])
                        else:
                            self.cx = 0
                    # Shift+↓ et Ctrl+Shift+↓ : ancre + début de ligne du dessous
                    elif code in (575, curses.KEY_SF):
                        self._sel_anchor_here()
                        if self.cy < len(self.lines) - 1:
                            self.cy += 1
                            self.cx = 0
                        else:
                            self.cx = len(self.lines[self.cy])
                    # Navigation simple : efface la sélection et déplace
                    elif code == curses.KEY_UP:
                        self._sel_clear(); self._move_up()
                    elif code == curses.KEY_DOWN:
                        self._sel_clear(); self._move_down()
                    elif code == curses.KEY_LEFT:
                        self._sel_clear(); self._move_left()
                    elif code == curses.KEY_RIGHT:
                        self._sel_clear(); self._move_right()
                    elif code == curses.KEY_HOME:
                        self._sel_clear(); self.cx = 0
                    elif code == curses.KEY_END:
                        self._sel_clear(); self.cx = len(self.lines[self.cy])
                    elif code == curses.KEY_PPAGE:
                        self._sel_clear(); self._page_up(h)
                    elif code == curses.KEY_NPAGE:
                        self._sel_clear(); self._page_down(h)
                    elif code == curses.KEY_BACKSPACE:
                        if self._sel_range() is not None:
                            self._sel_delete(); self._save()
                        else:
                            self._sel_clear()
                            self._backspace(); self._save()
                    elif code == curses.KEY_DC:
                        if self._sel_range() is not None:
                            self._sel_delete(); self._save()
                        else:
                            self._sel_clear()
                            self._delete(); self._save()

        finally:
            curses.curs_set(prev_curs)

    def _scroll(self, h: int, w: int):
        margin   = _settings.get("margin",   1)
        self._mv = _settings.get("margin_v", 1)
        self._dw = max(1, w - 2 * margin)
        content_h = max(1, h - 2 * self._mv)
        cy_segs = _wrap_segs(self.lines[self.cy], self._dw)
        ril, _ = _cx_to_vrc(cy_segs, self.cx)
        vrow_cursor = self._total_vrows_before(self.cy) + ril
        if vrow_cursor < self.ovy:
            self.ovy = vrow_cursor
        elif vrow_cursor >= self.ovy + content_h:
            self.ovy = vrow_cursor - content_h + 1

    def _move_up(self):
        dw = self._dw
        segs = _wrap_segs(self.lines[self.cy], dw)
        ril, col = _cx_to_vrc(segs, self.cx)
        if ril > 0:
            ps, pe = segs[ril - 1]
            is_last = (ril - 1 == len(segs) - 1)
            self.cx = min(ps + col, pe if is_last else pe - 1)
        elif self.cy > 0:
            self.cy -= 1
            prev = _wrap_segs(self.lines[self.cy], dw)
            ps, pe = prev[-1]
            self.cx = min(ps + col, pe)

    def _move_down(self):
        dw = self._dw
        segs = _wrap_segs(self.lines[self.cy], dw)
        ril, col = _cx_to_vrc(segs, self.cx)
        if ril < len(segs) - 1:
            ns, ne = segs[ril + 1]
            is_last = (ril + 1 == len(segs) - 1)
            self.cx = min(ns + col, ne if is_last else ne - 1)
        elif self.cy < len(self.lines) - 1:
            self.cy += 1
            nxt = _wrap_segs(self.lines[self.cy], dw)
            ns, ne = nxt[0]
            is_last = (len(nxt) == 1)
            self.cx = min(ns + col, ne if is_last else ne - 1)

    def _move_left(self):
        if self.cx > 0:
            self.cx -= 1
        elif self.cy > 0:
            self.cy -= 1
            self.cx = len(self.lines[self.cy])

    def _move_right(self):
        if self.cx < len(self.lines[self.cy]):
            self.cx += 1
        elif self.cy < len(self.lines) - 1:
            self.cy += 1
            self.cx = 0

    def _vrow_seek(self, target: int, col: int):
        """Déplace le curseur vers le rang visuel 'target' en gardant la colonne."""
        acc = 0
        for i, line in enumerate(self.lines):
            segs = _wrap_segs(line, self._dw)
            nrows = len(segs)
            if acc + nrows > target:
                t_ril = target - acc
                ps, pe = segs[t_ril]
                is_last = (t_ril == nrows - 1)
                self.cy = i
                self.cx = min(ps + col, pe if is_last else pe - 1)
                return
            acc += nrows
        self.cy = len(self.lines) - 1
        self.cx = len(self.lines[self.cy])

    def _page_up(self, h: int):
        dw = self._dw
        content_h = max(1, h - 2 * self._mv)
        segs = _wrap_segs(self.lines[self.cy], dw)
        ril, col = _cx_to_vrc(segs, self.cx)
        vrow = self._total_vrows_before(self.cy) + ril
        self._vrow_seek(max(0, vrow - content_h), col)

    def _page_down(self, h: int):
        dw = self._dw
        content_h = max(1, h - 2 * self._mv)
        segs = _wrap_segs(self.lines[self.cy], dw)
        ril, col = _cx_to_vrc(segs, self.cx)
        total = sum(len(_wrap_segs(l, dw)) for l in self.lines)
        vrow = self._total_vrows_before(self.cy) + ril
        self._vrow_seek(min(total - 1, vrow + content_h), col)

    def _backspace(self):
        if self.cx > 0:
            line = self.lines[self.cy]
            self.lines[self.cy] = line[:self.cx - 1] + line[self.cx:]
            self.cx -= 1
        elif self.cy > 0:
            prev = self.lines[self.cy - 1]
            self.cx = len(prev)
            self.lines[self.cy - 1] = prev + self.lines[self.cy]
            self.lines.pop(self.cy)
            self.cy -= 1
    def _delete(self):
        line = self.lines[self.cy]
        if self.cx < len(line):
            self.lines[self.cy] = line[:self.cx] + line[self.cx + 1:]
        elif self.cy < len(self.lines) - 1:
            self.lines[self.cy] = line + self.lines[self.cy + 1]
            self.lines.pop(self.cy + 1)

    def _newline(self):
        line = self.lines[self.cy]
        self.lines[self.cy] = line[:self.cx]
        self.lines.insert(self.cy + 1, line[self.cx:])
        self.cy += 1
        self.cx = 0

    def _insert(self, text: str):
        line = self.lines[self.cy]
        self.lines[self.cy] = line[:self.cx] + text + line[self.cx:]
        self.cx += len(text)


# ── écrans de navigation ─────────────────────────────────────────────────────

def _flash(stdscr, msg: str, duration: float = 2.0):
    bottombar(stdscr, f"  {msg}")
    stdscr.refresh()
    time.sleep(duration)
    stdscr.redrawwin()


def _export_project_usb(stdscr, project_path: Path):
    """Copie le projet sur une clé USB (sans le dossier .git)."""
    drive = _pick_usb(stdscr)
    if not drive:
        return
    dest = drive / project_path.name
    if dest.exists():
        if not confirm(stdscr, f"'{project_path.name}' existe deja sur la cle. Ecraser ?"):
            return
        shutil.rmtree(dest)
    _loader(stdscr, f"Export de '{project_path.name}' en cours...")
    try:
        shutil.copytree(project_path, dest, ignore=shutil.ignore_patterns(".git"))
        _flash(stdscr, f"Projet exporte vers {dest}")
    except Exception as e:
        _text_page(stdscr, "Erreur export projet", [str(e)])


def browse_screen(stdscr, directory: Path, is_project_root: bool = False,
                  _restore: "Path | None" = None,
                  _proj_root: "Path | None" = None):
    if is_project_root:
        _proj_root = directory
    sel = 0
    _did_restore = False

    while True:
        is_repo = is_project_root and git_available() and git_is_repo(directory)
        items = sorted(
            (p for p in directory.iterdir() if p.name != ".git"),
            key=lambda p: (p.is_file(), p.name.lower()),
        )
        sel = clamp(sel, 0, max(0, len(items) - 1))

        # Navigation automatique vers le dernier fichier ouvert
        if _restore and not _did_restore:
            _did_restore = True
            try:
                if _restore.parent == directory:
                    sel = next(i for i, p in enumerate(items) if p == _restore)
                elif _restore.is_relative_to(directory):
                    next_dir = directory / _restore.relative_to(directory).parts[0]
                    if next_dir.is_dir():
                        try:
                            sel = next(i for i, p in enumerate(items) if p == next_dir)
                        except StopIteration:
                            pass
                        browse_screen(stdscr, next_dir, _restore=_restore, _proj_root=_proj_root)
                        continue
            except (StopIteration, ValueError):
                pass

        # Badge git dans la topbar
        git_badge = ""
        if is_repo:
            branch = git_current_branch(directory)
            git_badge = f"  ● {branch}" if git_has_changes(directory) else f"  ✓ {branch}"

        if is_project_root:
            bar = "  -> Nav   F Fich   D Doss   C Copie   X Suppr   R Renom   M Dep   U USB"
            bar += "   G Git" if git_available() else ""
        else:
            bar = "  -> Nav   F Fich   D Doss   C Copie   X Suppr   R Renommer   M Deplacer"

        stdscr.erase()
        topbar(stdscr, directory.name + git_badge)
        draw_panel(stdscr, items, sel)
        bottombar(stdscr, bar)
        stdscr.refresh()

        ch, code = next_key(stdscr)

        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(max(0, len(items) - 1), sel + 1)
        elif code == curses.KEY_RIGHT or ch in ("\n", "\r"):
            if items:
                item = items[sel]
                if item.is_dir():
                    browse_screen(stdscr, item, _proj_root=_proj_root)
                else:
                    Editor(item).run(stdscr)
                    if _proj_root:
                        _settings["last_open"] = {
                            "project": _proj_root.name,
                            "path": str(item),
                        }
                        _save_settings()
        elif code == curses.KEY_LEFT:
            return
        elif ch is not None:
            k = ch.lower() if ord(ch) >= 32 else None

            if k == "f":
                name = get_input(stdscr, "Nom du fichier")
                if name:
                    path = directory / name
                    if not path.exists():
                        path.touch()
                    Editor(path).run(stdscr)
                    if _proj_root:
                        _settings["last_open"] = {"project": _proj_root.name, "path": str(path)}
                        _save_settings()

            elif k == "d":
                name = get_input(stdscr, "Nom du dossier")
                if name:
                    (directory / name).mkdir(exist_ok=True)

            elif k == "c" and items:
                item = items[sel]
                if item.is_dir():
                    dest = item.parent / (item.name + "_copie")
                    n = 2
                    while dest.exists():
                        dest = item.parent / f"{item.name}_copie{n}"; n += 1
                    _loader(stdscr, f"Copie de '{item.name}'...")
                    try:
                        shutil.copytree(item, dest)
                    except Exception as e:
                        _text_page(stdscr, "Erreur copie", [str(e)])
                else:
                    stem, suffix = item.stem, item.suffix
                    dest = item.parent / f"{stem}_copie{suffix}"
                    n = 2
                    while dest.exists():
                        dest = item.parent / f"{stem}_copie{n}{suffix}"; n += 1
                    try:
                        shutil.copy2(item, dest)
                    except Exception as e:
                        _text_page(stdscr, "Erreur copie", [str(e)])

            elif k == "x" and items:
                item = items[sel]
                kind = "dossier" if item.is_dir() else "fichier"
                if confirm(stdscr, f"Supprimer {kind} « {item.name} » ?"):
                    shutil.rmtree(item) if item.is_dir() else item.unlink()
                    sel = max(0, sel - 1)

            elif k == "r" and items:
                item = items[sel]
                new_name = get_input(stdscr, "Nouveau nom", prefill=item.name)
                if new_name and new_name != item.name:
                    dest = item.parent / new_name
                    if not dest.exists():
                        item.rename(dest)

            elif k == "m" and items:
                item = items[sel]
                raw = get_input(stdscr, "Deplacer vers (chemin relatif)", prefill="")
                if raw:
                    dest_dir = (directory / raw).resolve()
                    if dest_dir.is_dir() and dest_dir != directory:
                        dest = dest_dir / item.name
                        if not dest.exists():
                            item.rename(dest)
                            sel = max(0, sel - 1)
                    else:
                        _flash(stdscr, "Dossier de destination introuvable")

            elif k == "u" and is_project_root:
                _export_project_usb(stdscr, directory)

            elif k == "g" and is_project_root and git_available():
                git_page(stdscr, directory)


# ── logo ASCII art ───────────────────────────────────────────────────────────

_LOGO = [
    r" ___  _    _               ___          __      __   _ _       ",
    r"|   \(_)__| |_ _ _ __ _ __| __| _ ___ __\ \    / / _(_) |_ ___ ",
    r"| |) | (_-<  _| '_/ _` / _| _| '_/ -_) -_) \/\/ / '_| |  _/ -_)",
    r"|___/|_/__/\__|_| \__,_\__|_||_| \___\___|\_/\_/|_| |_|\__\___|",
]
_TAGLINE = "ecrire, sans distraction"

_GITHUB_REPO = "VSerain/distraction-free-write"


def _github_list_repos(username: str, token: str = "") -> "list[dict] | None":
    """Retourne la liste des repos GitHub de l'utilisateur via l'API REST.
    Retourne None en cas d'erreur réseau/API."""
    headers = ["Accept: application/vnd.github+json"]
    if token:
        headers += [f"Authorization: Bearer {token}"]
    try:
        all_repos: list[dict] = []
        page = 1
        while True:
            url = (
                f"https://api.github.com/user/repos?per_page=100&page={page}&sort=updated"
                if token else
                f"https://api.github.com/users/{username}/repos?per_page=100&page={page}&sort=updated"
            )
            cmd = ["curl", "-fsSL"]
            for h in headers:
                cmd += ["-H", h]
            cmd.append(url)
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
            if r.returncode != 0:
                return None
            batch = json.loads(r.stdout)
            if not isinstance(batch, list) or not batch:
                break
            all_repos.extend(batch)
            if len(batch) < 100:
                break
            page += 1
        return all_repos
    except Exception:
        return None


def _pick_github_repo(stdscr, repos: list[dict]) -> "str | None":
    """Picker plein écran dans la liste des repos GitHub. Retourne l'URL SSH."""
    sel = 0
    query = ""
    while True:
        filtered = [r for r in repos if query.lower() in r["full_name"].lower()] if query else repos
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "Choisir un repo GitHub")
        row = 1
        if row < h - 1:
            try:
                prompt = f"  Filtre : {query}_"
                stdscr.addstr(row, 0, prompt[:w])
            except curses.error:
                pass
            row += 1
        sel = clamp(sel, 0, max(0, len(filtered) - 1))
        for i, repo in enumerate(filtered):
            if row >= h - 1:
                break
            is_sel = (i == sel)
            lock = " [prive]" if repo.get("private") else ""
            label = f"  {'>' if is_sel else ' '}  {repo['full_name']}{lock}"
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row, 0, label[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, label[:w])
            except curses.error:
                pass
            row += 1
        if not filtered and row < h - 1:
            try:
                stdscr.addstr(row, 4, "(aucun résultat)")
            except curses.error:
                pass
        bottombar(stdscr, "  haut/bas Nav   -> Cloner   lettres Filtre   Suppr Effacer   <- Retour")
        stdscr.refresh()

        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(max(0, len(filtered) - 1), sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            if filtered:
                return filtered[sel]["ssh_url"]
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return None
        elif code in (curses.KEY_BACKSPACE, curses.KEY_DC) or ch == "\x7f":
            query = query[:-1]
            sel = 0
        elif ch and ch.isprintable():
            query += ch
            sel = 0
_INSTALL_PATH = Path("/opt/distracfreewrite/main.py")


# ── mise à jour et démarrage auto ────────────────────────────────────────────

def _fetch_latest_tag() -> "str | None":
    try:
        r = subprocess.run(
            ["curl", "-fsSL", f"https://api.github.com/repos/{_GITHUB_REPO}/tags"],
            capture_output=True, text=True, timeout=15,
        )
        tags = json.loads(r.stdout)
        return tags[0]["name"] if tags else None
    except Exception:
        return None


def _update_app(stdscr):
    _wifi_managed = _settings.get("wifi_off", False)

    # Même logique que git_page : activer + attendre + connecter si besoin
    if _wifi_managed:
        _wifi_set_radio(True)
        _wait_wifi_up(stdscr)

    if not _is_network_connected():
        _flash(stdscr, "WiFi non connecte — redirection vers la connexion...", 1.2)
        _wifi_connect_screen(stdscr)

    if not _is_network_connected():
        if _wifi_managed:
            _wifi_set_radio(False)
        _flash(stdscr, "La mise a jour necessite une connexion reseau.")
        return

    _loader(stdscr, "Recherche de la derniere version...")
    tag = _fetch_latest_tag()
    if not tag:
        _text_page(stdscr, "Mise a jour", [
            "Impossible de joindre GitHub.",
            "",
            f"URL tentee : api.github.com/repos/{_GITHUB_REPO}/tags",
            "",
            "Verifiez que la connexion fonctionne correctement.",
        ])
        return

    current = _settings.get("version", "inconnue")
    if not confirm(stdscr, f"Installer {tag}  (version actuelle : {current}) ?"):
        return

    _loader(stdscr, f"Telechargement de {tag}...")
    url = f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{tag}/main.py"
    tmp = Path("/tmp/distracfreewrite_update.py")
    try:
        r = subprocess.run(["curl", "-fsSL", url, "-o", str(tmp)],
                           capture_output=True, text=True, timeout=30)
        if r.returncode != 0:
            _text_page(stdscr, "Erreur telechargement", r.stderr.splitlines())
            return
        if not _INSTALL_PATH.parent.exists():
            _text_page(stdscr, "Erreur", [f"{_INSTALL_PATH} introuvable.", "", "L'application est-elle installee via install.sh ?"])
            return
        if not os.access(_INSTALL_PATH, os.W_OK):
            _text_page(stdscr, "Erreur permissions", [
                f"Impossible d'ecrire dans {_INSTALL_PATH}.",
                "",
                "Relancez l'installation : sudo bash install.sh",
            ])
            return
        shutil.copy2(tmp, _INSTALL_PATH)
        _settings["version"] = tag
        _save_settings()
        if _settings.get("auto_poweroff_min", 0) > 0:
            _ensure_poweroff_system(stdscr)
        if confirm(stdscr, f"Version {tag} installee. Redemarrer le systeme maintenant ?"):
            curses.endwin()
            subprocess.run(["systemctl", "reboot"], check=False)
        else:
            _text_page(stdscr, "Mise a jour reussie", [
                f"Version {tag} installee.",
                "",
                "Quittez et relancez l'application pour appliquer.",
            ])
    except Exception as e:
        _text_page(stdscr, "Erreur", [str(e)])
    finally:
        if _wifi_managed:
            _wifi_set_radio(False)


def _is_autostart_enabled() -> bool:
    profile = Path.home() / ".bash_profile"
    return profile.exists() and "distracfreewrite" in profile.read_text()


def _toggle_autostart(stdscr):
    profile = Path.home() / ".bash_profile"
    if _is_autostart_enabled():
        if not confirm(stdscr, "Desactiver le demarrage automatique ?"):
            return
        text = profile.read_text()
        text = re.sub(
            r"\n# Lancer DistracFreeWrite automatiquement.*?fi\n",
            "\n",
            text,
            flags=re.DOTALL,
        )
        profile.write_text(text)
        _flash(stdscr, "Demarrage automatique desactive")
    else:
        if not confirm(stdscr, "Activer le demarrage automatique sur TTY1 ?"):
            return
        if not profile.exists():
            profile.write_text("# ~/.bash_profile\n[[ -f ~/.bashrc ]] && source ~/.bashrc\n")
        with open(profile, "a") as f:
            f.write(
                "\n# Lancer DistracFreeWrite automatiquement sur TTY1\n"
                'if [ "$(tty)" = "/dev/tty1" ]; then\n'
                "    distracfreewrite\n"
                "fi\n"
            )
        _flash(stdscr, "Demarrage automatique active")


def _wifi_connect_screen(stdscr):
    """Liste les réseaux WiFi et permet de s'y connecter via nmcli."""
    _loader(stdscr, "Recherche des reseaux WiFi...")
    try:
        r = subprocess.run(
            ["nmcli", "-t", "-f", "SSID,SIGNAL,SECURITY", "device", "wifi", "list", "--rescan", "yes"],
            capture_output=True, text=True, timeout=20,
        )
        if r.returncode != 0:
            _text_page(stdscr, "Erreur WiFi", (r.stdout + r.stderr).splitlines()
                       or ["nmcli a retourné une erreur."])
            return
        seen: set[str] = set()
        networks: list[tuple[str, str, str]] = []
        for line in r.stdout.splitlines():
            parts = line.split(":")
            ssid = parts[0].strip()
            if not ssid or ssid in seen:
                continue
            seen.add(ssid)
            signal   = parts[1].strip() if len(parts) > 1 else "?"
            security = parts[2].strip() if len(parts) > 2 else ""
            networks.append((ssid, signal, security))
        networks.sort(key=lambda n: -int(n[1]) if n[1].isdigit() else 0)
    except FileNotFoundError:
        _text_page(stdscr, "Erreur WiFi", ["nmcli introuvable.", "", "Installez NetworkManager."])
        return
    except Exception as e:
        _text_page(stdscr, "Erreur WiFi", [str(e)])
        return

    if not networks:
        _text_page(stdscr, "WiFi", ["Aucun reseau detecte."])
        return

    sel = 0
    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "Connexion WiFi")
        sel = clamp(sel, 0, len(networks) - 1)
        for i, (ssid, signal, security) in enumerate(networks):
            if 1 + i >= h - 1:
                break
            is_sel = (i == sel)
            lock = " [protege]" if security else ""
            bars = int(signal) // 25 if signal.isdigit() else 0
            bar_str = "#" * bars + "-" * (4 - bars)
            line = f"  {'>' if is_sel else ' '}  {ssid}  [{bar_str}]{lock}"
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(1 + i, 0, line[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(1 + i, 0, line[:w])
            except curses.error:
                pass
        bottombar(stdscr, "  haut/bas Naviguer   -> Connecter   <- Retour")
        stdscr.refresh()

        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(len(networks) - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            ssid, _, security = networks[sel]
            cmd = ["nmcli", "device", "wifi", "connect", ssid]
            if security:
                pwd = get_input(stdscr, f"Mot de passe pour {ssid}")
                if not pwd:
                    continue
                cmd += ["password", pwd]
            _loader(stdscr, f"Connexion a {ssid}...")
            r = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            if r.returncode == 0:
                _sys_cache["ts"] = 0.0  # force refresh du cache wifi
                _flash(stdscr, f"Connecte a {ssid}")
                return
            else:
                _text_page(stdscr, f"Erreur — {ssid}", (r.stdout + r.stderr).splitlines())
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


def settings_screen(stdscr):
    """Écran des paramètres."""
    _THEMES       = [
        ("dark",  "Sombre"),
        ("light", "Clair"),
        ("sepia", "Doux  —  confort visuel (fond creme, texte brun-gris)"),
    ]
    MARGIN_IDX    = len(_THEMES)           # 3
    MARGIN_V_IDX  = len(_THEMES) + 1      # 4
    WIFI_IDX      = len(_THEMES) + 2      # 5
    WIFI_OFF_IDX  = len(_THEMES) + 3      # 6
    GIT_NAME_IDX   = len(_THEMES) + 4      # 7
    GIT_EMAIL_IDX  = len(_THEMES) + 5      # 8
    GH_USER_IDX    = len(_THEMES) + 6      # 9
    GH_TOKEN_IDX   = len(_THEMES) + 7      # 10
    UPDATE_IDX     = len(_THEMES) + 8      # 11
    AUTO_IDX       = len(_THEMES) + 9      # 12
    POWEROFF_IDX   = len(_THEMES) + 10     # 13
    DEBUG_IDX      = len(_THEMES) + 11     # 14
    QUIT_IDX       = len(_THEMES) + 12     # 15
    TOTAL          = len(_THEMES) + 13     # 16
    _POWEROFF_STEPS = [0, 5, 10, 15, 20, 30, 45, 60, 90, 120]
    current       = _settings.get("theme", "dark")
    sel           = next((i for i, (k, _) in enumerate(_THEMES) if k == current), 0)

    def _sep(row):
        try:
            stdscr.addstr(row, 3, "-" * min(w - 6, 50), curses.A_DIM)
        except curses.error:
            pass

    def _heading(row, text):
        try:
            stdscr.addstr(row, 3, text, curses.A_BOLD)
        except curses.error:
            pass

    def _item(row, idx, label):
        if row >= h - 1:
            return
        is_sel = (sel == idx)
        line = f"  {'>' if is_sel else ' '}  {label}"
        try:
            if is_sel:
                stdscr.attron(curses.A_REVERSE)
                stdscr.addstr(row, 0, line[:w].ljust(w))
                stdscr.attroff(curses.A_REVERSE)
            else:
                stdscr.addstr(row, 0, line[:w])
        except curses.error:
            pass

    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "Parametres")
        row = 3

        # ── Theme ──
        _heading(row, "Theme");  row += 2
        for i, (key, label) in enumerate(_THEMES):
            active = "  <- actif" if key == _settings.get("theme") else ""
            _item(row, i, label + active);  row += 1

        row += 1;  _sep(row);  row += 2

        # ── Editeur ──
        _heading(row, "Editeur");  row += 2
        m  = _settings.get("margin",   1)
        mv = _settings.get("margin_v", 1)
        _item(row, MARGIN_IDX,   f"Marge laterale :   [{max(0,m-1)}] {m} [{m+1}]  (← / →)");  row += 1
        _item(row, MARGIN_V_IDX, f"Marge verticale :  [{max(0,mv-1)}] {mv} [{mv+1}]  (← / →)");  row += 2

        _sep(row);  row += 2

        # ── Reseau ──
        _heading(row, "Reseau");  row += 2
        ssid  = _sys_cache.get("wifi", "")
        extra = f"   ({ssid})" if ssid and ssid != "WiFi:--" and ssid != "WiFi:OFF" else ""
        _item(row, WIFI_IDX, "Se connecter au WiFi" + extra);  row += 1
        wifi_off_state = "active" if _settings.get("wifi_off", False) else "desactive"
        _item(row, WIFI_OFF_IDX, f"Desactiver WiFi hors git/MAJ : {wifi_off_state}");  row += 2

        _sep(row);  row += 2

        # ── Git ──
        _heading(row, "Git");  row += 2
        git_name  = git_config_get("user.name")  or "(non defini)"
        git_email = git_config_get("user.email") or "(non defini)"
        _item(row, GIT_NAME_IDX,  f"Nom    : {git_name}");   row += 1
        _item(row, GIT_EMAIL_IDX, f"Email  : {git_email}");  row += 1
        gh_user  = _settings.get("github_user",  "") or "(non defini)"
        gh_token = _settings.get("github_token", "")
        gh_token_disp = ("*" * min(8, len(gh_token))) if gh_token else "(non defini)"
        _item(row, GH_USER_IDX,  f"GitHub user  : {gh_user}");      row += 1
        _item(row, GH_TOKEN_IDX, f"GitHub token : {gh_token_disp}"); row += 2

        _sep(row);  row += 2

        # ── Application ──
        _heading(row, "Application");  row += 2
        ver = _settings.get("version", "?")
        _item(row, UPDATE_IDX, f"Installer la derniere version   (actuelle : {ver})");  row += 1
        auto_state = "active" if _is_autostart_enabled() else "desactive"
        _item(row, AUTO_IDX, f"Demarrage automatique : {auto_state}");  row += 2

        poweroff_min = _settings.get("auto_poweroff_min", 0)
        poweroff_lbl = "desactive" if poweroff_min == 0 else f"{poweroff_min} min"
        _item(row, POWEROFF_IDX, f"Extinction auto apres veille (inactif ou capot ferme) : {poweroff_lbl}  (← / →)");  row += 1
        _item(row, DEBUG_IDX, "Debug  —  diagnostics et commandes shell");  row += 2

        _sep(row);  row += 2
        _item(row, QUIT_IDX, "Fermer DistracFreeWrite  —  retourner au terminal")

        bottombar(stdscr, "  haut/bas Naviguer   -> Appliquer / Ouvrir   <- Retour")
        stdscr.refresh()

        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(TOTAL - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            if sel < len(_THEMES):
                key, _ = _THEMES[sel]
                _settings["theme"] = key
                _save_settings()
                _apply_theme(stdscr)
            elif sel == MARGIN_IDX:
                _settings["margin"] = min(8, _settings.get("margin", 1) + 1)
                _save_settings()
            elif sel == MARGIN_V_IDX:
                _settings["margin_v"] = min(8, _settings.get("margin_v", 1) + 1)
                _save_settings()
            elif sel == WIFI_IDX:
                if _settings.get("wifi_off", False):
                    _wifi_set_radio(True)
                _wifi_connect_screen(stdscr)
            elif sel == WIFI_OFF_IDX:
                new_val = not _settings.get("wifi_off", False)
                _settings["wifi_off"] = new_val
                _save_settings()
                _wifi_set_radio(not new_val)
                _sys_cache["ts"] = 0.0
            elif sel == GIT_NAME_IDX:
                current_name = git_config_get("user.name")
                val = get_input(stdscr, "Nom pour les commits Git", prefill=current_name)
                if val:
                    ok, out = git_config_set("user.name", val)
                    if not ok:
                        _text_page(stdscr, "Erreur git config", out.splitlines() or ["(inconnu)"])
            elif sel == GIT_EMAIL_IDX:
                current_email = git_config_get("user.email")
                val = get_input(stdscr, "Email pour les commits Git", prefill=current_email)
                if val:
                    ok, out = git_config_set("user.email", val)
                    if not ok:
                        _text_page(stdscr, "Erreur git config", out.splitlines() or ["(inconnu)"])
            elif sel == GH_USER_IDX:
                val = get_input(stdscr, "Nom d'utilisateur GitHub", prefill=_settings.get("github_user", ""))
                if val is not None:
                    _settings["github_user"] = val
                    _save_settings()
            elif sel == GH_TOKEN_IDX:
                val = get_input(stdscr, "Token GitHub (Personal Access Token — laisser vide pour supprimer)", prefill="")
                if val is not None:
                    _settings["github_token"] = val
                    _save_settings()
            elif sel == UPDATE_IDX:
                _update_app(stdscr)
            elif sel == AUTO_IDX:
                _toggle_autostart(stdscr)
            elif sel == POWEROFF_IDX:
                cur = _settings.get("auto_poweroff_min", 0)
                idx = _POWEROFF_STEPS.index(cur) if cur in _POWEROFF_STEPS else 0
                idx = min(len(_POWEROFF_STEPS) - 1, idx + 1)
                _settings["auto_poweroff_min"] = _POWEROFF_STEPS[idx]
                _save_settings()
                if _settings["auto_poweroff_min"] > 0:
                    _ensure_poweroff_system(stdscr)
            elif sel == DEBUG_IDX:
                _debug_screen(stdscr)
            elif sel == QUIT_IDX:
                if confirm(stdscr, "Fermer DistracFreeWrite et revenir au terminal ?"):
                    return True
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            if sel == MARGIN_IDX:
                _settings["margin"] = max(0, _settings.get("margin", 1) - 1)
                _save_settings()
            elif sel == MARGIN_V_IDX:
                _settings["margin_v"] = max(0, _settings.get("margin_v", 1) - 1)
                _save_settings()
            elif sel == POWEROFF_IDX:
                cur = _settings.get("auto_poweroff_min", 0)
                idx = _POWEROFF_STEPS.index(cur) if cur in _POWEROFF_STEPS else 0
                idx = max(0, idx - 1)
                _settings["auto_poweroff_min"] = _POWEROFF_STEPS[idx]
                _save_settings()
            else:
                return False

    return False


def _do_poweroff():
    curses.endwin()
    for cmd in [["systemctl", "poweroff"], ["poweroff"], ["sudo", "shutdown", "-h", "now"]]:
        try:
            subprocess.run(cmd, timeout=5)
            break
        except Exception:
            continue


# ── debug ─────────────────────────────────────────────────────────────────────

_DIAG_POWEROFF_CMD = r"""
echo "== journalctl (lid / hibernate / suspend / logind / poweroff) =="
journalctl -b --no-pager | grep -iE 'lid|hibernat|suspend|logind|poweroff|shutdown' | tail -80
echo
echo "== journalctl noyau (PM / hibernation / ACPI / resume) =="
journalctl -k -b --no-pager | grep -iE 'PM:|hibernat|resume|ACPI' | tail -80
echo
echo "== memoire / swap =="
free -h
swapon --show
echo
echo "== reprise apres hibernation =="
echo -n "cmdline actuel : "; grep -o 'resume[^ ]*' /proc/cmdline | tr '\n' ' '; echo
cat /etc/initramfs-tools/conf.d/resume 2>/dev/null || echo "(pas de config initramfs-tools/resume)"
grep -o 'resume[^"]*' /etc/default/grub 2>/dev/null || echo "(pas de resume dans /etc/default/grub)"
echo
echo "== bootloader =="
echo -n "update-grub    : "; which update-grub 2>&1 || echo "absent"
echo -n "grub-mkconfig  : "; which grub-mkconfig 2>&1 || echo "absent"
echo -n "/boot          : "; ls /boot/ 2>&1
echo -n "/boot/efi      : "; ls /boot/efi 2>&1
echo "efibootmgr :"; efibootmgr 2>&1
echo "cmdline complet : $(cat /proc/cmdline)"
echo "/etc/default/grub :"
cat /etc/default/grub 2>&1
echo
echo "== drop-in logind =="
cat /etc/systemd/logind.conf.d/50-distracfreewrite-poweroff.conf 2>/dev/null || echo "(absent)"
echo
echo "== hook systemd-sleep =="
cat /usr/lib/systemd/system-sleep/distracfreewrite-poweroff 2>/dev/null || echo "(absent)"
echo
echo "== alarme RTC / marqueur =="
echo -n "wakealarm: "; cat /sys/class/rtc/rtc0/wakealarm 2>/dev/null || echo "(illisible)"
echo -n "marqueur : "; cat /run/distracfreewrite-poweroff-alarm 2>/dev/null || echo "(absent)"
"""


def _run_shell(cmd: str, timeout: int = 30) -> list[str]:
    try:
        r = subprocess.run(["bash", "-c", cmd], capture_output=True, text=True, timeout=timeout)
        out = (r.stdout or "") + (r.stderr or "")
        lines = out.splitlines() or ["(aucune sortie)"]
        lines.append(f"[code de retour : {r.returncode}]")
        return lines
    except subprocess.TimeoutExpired:
        return ["Commande interrompue (timeout)."]
    except Exception as e:
        return [f"Erreur : {e}"]


def _send_to_webhook(url: str, text: str) -> tuple[bool, str]:
    try:
        r = subprocess.run(
            ["curl", "-fsS", "-X", "POST",
             "-H", "Content-Type: text/plain; charset=utf-8",
             "--data-binary", "@-", url],
            input=text, capture_output=True, text=True, timeout=15,
        )
        if r.returncode != 0:
            return False, (r.stderr or "erreur curl").strip()
        return True, ""
    except Exception as e:
        return False, str(e)


def _send_debug_result(stdscr, text: str):
    """Envoie le texte vers l'URL webhook configuree (ex: webhook.site),
    pour lire le resultat depuis un navigateur au lieu de recopier le
    terminal a la main."""
    url = _settings.get("debug_webhook_url", "")
    if not url:
        url = get_input(stdscr, "URL webhook (cree-en une sur webhook.site puis colle l'URL ici)")
        if not url:
            return
        _settings["debug_webhook_url"] = url
        _save_settings()

    wifi_managed = _settings.get("wifi_off", False)
    if wifi_managed:
        _wifi_set_radio(True)
        _wait_wifi_up(stdscr)
    if not _is_network_connected():
        _flash(stdscr, "WiFi non connecte — redirection vers la connexion...", 1.2)
        _wifi_connect_screen(stdscr)
    if not _is_network_connected():
        if wifi_managed:
            _wifi_set_radio(False)
        _flash(stdscr, "Envoi impossible : pas de connexion reseau.")
        return

    _loader(stdscr, "Envoi en cours...")
    ok, err = _send_to_webhook(url, text)
    if wifi_managed:
        _wifi_set_radio(False)

    if ok:
        _flash(stdscr, "Resultat envoye.")
    else:
        _text_page(stdscr, "Erreur d'envoi", [err or "Erreur inconnue."])


def _debug_result_page(stdscr, title: str, lines: list[str]):
    """Comme _text_page, avec 's' pour envoyer le contenu au webhook configure."""
    offset = 0
    text = "\n".join(lines)
    while True:
        h, w = stdscr.getmaxyx()
        content_h = h - 2
        stdscr.erase()
        topbar(stdscr, title)
        visible = lines[offset:offset + content_h]
        for i, line in enumerate(visible):
            try:
                stdscr.addstr(1 + i, 2, line[:w - 3])
            except curses.error:
                pass
        if len(lines) > content_h:
            bar = (f"  haut/bas PgUp PgDn  {offset + 1}-{min(offset + content_h, len(lines))}/{len(lines)}"
                   f"   s Envoyer   <- Retour")
        else:
            bar = "  s Envoyer   <- Retour"
        bottombar(stdscr, bar)
        stdscr.refresh()

        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            offset = max(0, offset - 1)
        elif code == curses.KEY_DOWN:
            offset = min(max(0, len(lines) - content_h), offset + 1)
        elif code == curses.KEY_PPAGE:
            offset = max(0, offset - content_h)
        elif code == curses.KEY_NPAGE:
            offset = min(max(0, len(lines) - content_h), offset + content_h)
        elif ch is not None and ch.lower() == "s":
            _send_debug_result(stdscr, text)
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


def _debug_screen(stdscr):
    items = [
        "Diagnostic extinction / veille",
        "Executer une commande shell",
        "Configurer l'URL d'envoi (webhook)",
        "Dernier resultat d'installation (extinction/veille)",
        "Forcer une hibernation maintenant (test, sans le capot)",
    ]
    sel = 0
    while True:
        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "Debug")
        for i, label in enumerate(items):
            row = 2 + i
            is_sel = (sel == i)
            extra = ""
            if i == 2:
                url = _settings.get("debug_webhook_url", "")
                extra = f"   ({url})" if url else "   (non definie)"
            line = f"  {'>' if is_sel else ' '}  {label}{extra}"
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row, 0, line[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, line[:w])
            except curses.error:
                pass
        bottombar(stdscr, "  haut/bas Naviguer   -> Ouvrir   <- Retour")
        stdscr.refresh()

        ch, code = next_key(stdscr)
        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(len(items) - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            if sel == 0:
                _loader(stdscr, "Diagnostic en cours...")
                lines = _run_shell(_DIAG_POWEROFF_CMD, timeout=20)
                _debug_result_page(stdscr, "Diagnostic extinction / veille", lines)
            elif sel == 1:
                cmd = get_input(stdscr, "Commande shell a executer")
                if cmd:
                    _loader(stdscr, "Execution...")
                    lines = _run_shell(cmd)
                    _debug_result_page(stdscr, f"$ {cmd}", lines)
            elif sel == 2:
                current_url = _settings.get("debug_webhook_url", "")
                val = get_input(stdscr, "URL webhook (ex: https://webhook.site/xxxx)", prefill=current_url)
                if val is not None:
                    _settings["debug_webhook_url"] = val
                    _save_settings()
            elif sel == 3:
                try:
                    content = _POWEROFF_INSTALL_LOG.read_text()
                    lines = content.splitlines() or ["(journal vide)"]
                except Exception:
                    lines = ["Aucune installation n'a encore ete tentee.",
                              f"({_POWEROFF_INSTALL_LOG} absent)"]
                _debug_result_page(stdscr, "Dernier resultat d'installation", lines)
            elif sel == 4:
                if confirm(stdscr, "Hiberner maintenant pour tester, sans passer par "
                                    "le capot ? La machine va s'endormir tout de suite."):
                    curses.endwin()
                    for cmd in (["systemctl", "hibernate"], ["sudo", "systemctl", "hibernate"]):
                        try:
                            subprocess.run(cmd, timeout=10)
                            break
                        except Exception:
                            continue
                    stdscr.refresh()
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


def _poweroff(stdscr):
    if not confirm(stdscr, "Eteindre l'ordinateur ?"):
        return
    _do_poweroff()


# ── extinction automatique apres veille ──────────────────────────────────────

_last_activity: float = time.time()


def _register_activity():
    global _last_activity
    _last_activity = time.time()


def _check_auto_poweroff(stdscr):
    """Eteint la machine sans confirmation apres X minutes d'inactivite,
    pour economiser la batterie sur les veilles prolongees."""
    minutes = _settings.get("auto_poweroff_min", 0)
    if not minutes:
        return
    if time.time() - _last_activity >= minutes * 60:
        _do_poweroff()


# ── extinction apres veille systeme prolongee (capot ferme) ─────────────────
#
# Pendant une veille (suspend S3), ce process est gele : il ne peut ni
# compter le temps ni agir. On pose donc une alarme RTC materielle juste
# avant la mise en veille : SI le firmware sait reveiller la machine par
# RTC depuis S3, elle se reveille et s'eteint toute seule au bout de X
# minutes, capot ferme.
#
# Sur beaucoup de portables (et confirme sur du materiel Apple via
# `dmesg | grep rtc_cmos` -> "RTC can wake from S4" seulement), ce reveil
# RTC ne fonctionne PAS depuis S3. On a essaye de forcer l'hibernation
# (S4, reveil RTC fiable) a la fermeture du capot, mais sur ce meme
# materiel Apple l'hibernation echoue systematiquement au reveil
# ("Hibernate inconsistent memory map detected" / "Image mismatch:
# architecture specific data" — le firmware EFI rapporte une carte
# memoire legerement differente a chaque demarrage, ce qui fait echouer
# la validation de securite du noyau et redemarre a froid en perdant la
# session). C'est une limitation materiel/firmware, pas un bug logiciel :
# ni S3 (pas de reveil RTC) ni S4 (echec de reprise) ne permettent un
# reveil autonome fiable sur ce type de machine.
#
# On revient donc a la veille classique (S3, rapide et fiable) pour la
# fermeture du capot. L'extinction reste garantie de maniere reactive :
# le hook post-reveil verifie systematiquement, a CHAQUE reveil (que ce
# soit le reveil RTC s'il fonctionne, ou simplement l'utilisateur qui
# rouvre le capot), si le delai configure est depasse, et eteint
# immediatement si c'est le cas — au lieu de laisser la machine en veille
# indefiniment sans jamais nettoyer.
#
# Le hook relit "auto_poweroff_min" dans config.json a chaque veille : un
# changement fait dans l'app est donc pris en compte des la prochaine mise
# en veille, sans reinstallation.

_SLEEP_HOOK_PATH       = Path("/usr/lib/systemd/system-sleep/distracfreewrite-poweroff")
_SLEEP_HOOK_VERSION    = 1   # a incrementer si le contenu du hook change
_LOGIND_DROPIN_PATH    = Path("/etc/systemd/logind.conf.d/50-distracfreewrite-poweroff.conf")
_LOGIND_DROPIN_VERSION = 2   # a incrementer si le contenu du drop-in change
_POWEROFF_INSTALL_LOG  = Path.home() / ".config" / "distracfreewrite" / "poweroff_install.log"


def _save_poweroff_install_log(ok: bool, report: str):
    try:
        _POWEROFF_INSTALL_LOG.parent.mkdir(parents=True, exist_ok=True)
        header = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] resultat : {'OK' if ok else 'ECHEC'}\n"
        _POWEROFF_INSTALL_LOG.write_text(header + report)
    except Exception:
        pass


def _sleep_hook_content(home: Path) -> str:
    return f"""#!/bin/bash
# Installe par DistracFreeWrite — ne pas editer a la main.
# hook_version={_SLEEP_HOOK_VERSION}

CONFIG_FILE="{home}/.config/distracfreewrite/config.json"
MARKER="/run/distracfreewrite-poweroff-alarm"
RTC="/sys/class/rtc/rtc0/wakealarm"

case "$1/$2" in
  pre/*)
    [ -f "$CONFIG_FILE" ] || exit 0
    [ -w "$RTC" ] || exit 0
    MINUTES=$(python3 -c "import json,sys
try:
    print(int(json.load(open(sys.argv[1])).get('auto_poweroff_min', 0)))
except Exception:
    print(0)" "$CONFIG_FILE" 2>/dev/null || echo 0)
    [ "$MINUTES" -gt 0 ] 2>/dev/null || exit 0
    TARGET=$(( $(date +%s) + MINUTES * 60 ))
    echo 0 > "$RTC" 2>/dev/null
    echo "$TARGET" > "$RTC" 2>/dev/null
    echo "$TARGET" > "$MARKER"
    ;;
  post/*)
    [ -f "$MARKER" ] || exit 0
    TARGET=$(cat "$MARKER")
    rm -f "$MARKER"
    echo 0 > "$RTC" 2>/dev/null
    NOW=$(date +%s)
    if [ "$NOW" -ge "$((TARGET - 15))" ]; then
        systemctl poweroff
    fi
    ;;
esac
"""


def _logind_dropin_content() -> str:
    return f"""[Login]
# Installe par DistracFreeWrite — ne pas editer a la main.
# dropin_version={_LOGIND_DROPIN_VERSION}
#
# Veille classique (S3) a la fermeture du capot : rapide et fiable.
# L'hibernation (S4) a ete testee mais echoue a la reprise sur certains
# materiels (carte memoire firmware incoherente entre redemarrages) —
# voir le commentaire au-dessus de _SLEEP_HOOK_PATH. L'extinction apres
# le delai configure reste garantie de maniere reactive, au reveil.
HandleLidSwitch=suspend
HandleLidSwitchExternalPower=suspend
"""


def _system_setup_up_to_date() -> bool:
    try:
        hook_ok = f"hook_version={_SLEEP_HOOK_VERSION}" in _SLEEP_HOOK_PATH.read_text()
    except Exception:
        hook_ok = False
    try:
        dropin_ok = f"dropin_version={_LOGIND_DROPIN_VERSION}" in _LOGIND_DROPIN_PATH.read_text()
    except Exception:
        dropin_ok = False
    return hook_ok and dropin_ok


def _install_poweroff_system_as_root(home: "Path | None" = None) -> tuple[bool, str]:
    """Ecrit le hook systemd-sleep et le drop-in logind (capot => veille),
    puis recharge systemd-logind. A appeler alors que ce process est deja
    root (install.sh, ou apres elevation sudo depuis l'app). Retourne
    (ok, journal detaille) — le journal est toujours rempli, meme en cas
    de succes."""
    log: list[str] = []
    try:
        _SLEEP_HOOK_PATH.write_text(_sleep_hook_content(home or Path.home()))
        _SLEEP_HOOK_PATH.chmod(0o755)
        log.append(f"hook ecrit : {_SLEEP_HOOK_PATH}")
        _LOGIND_DROPIN_PATH.parent.mkdir(parents=True, exist_ok=True)
        _LOGIND_DROPIN_PATH.write_text(_logind_dropin_content())
        _LOGIND_DROPIN_PATH.chmod(0o644)
        log.append(f"drop-in ecrit : {_LOGIND_DROPIN_PATH}")
        r = subprocess.run(["systemctl", "restart", "systemd-logind"],
                            capture_output=True, text=True, timeout=15, check=False)
        log.append(f"systemctl restart systemd-logind -> code {r.returncode}")
        if r.stderr.strip():
            log.append(r.stderr.strip())
        return True, "\n".join(log)
    except Exception as e:
        log.append(f"erreur : {e}")
        return False, "\n".join(log)


def _ensure_poweroff_system(stdscr) -> bool:
    """S'assure que le hook systemd-sleep et le drop-in logind (capot =>
    veille) sont presents et a jour. Si absents (ex: mise a jour depuis
    une ancienne version installee sans eux), propose une elevation sudo
    ponctuelle pour les installer — permet aux installations existantes
    d'obtenir la fonctionnalite sans relancer install.sh."""
    if _system_setup_up_to_date():
        return True

    msg = ("Extinction apres veille prolongee : le capot fermera en veille "
           "classique. Si la machine reste endormie plus longtemps que le "
           "delai configure, elle s'eteindra au prochain reveil (reouverture "
           "du capot).")
    if not confirm(stdscr, msg + " Installer (mot de passe administrateur) ?"):
        return False

    home = Path.home()
    script = Path(__file__).resolve()

    curses.endwin()
    try:
        print("\nMot de passe administrateur necessaire pour installer "
              "l'extinction automatique apres veille prolongee.\n")
        # sudo lit le mot de passe sur /dev/tty directement : capturer
        # stdout/stderr ici n'empeche pas le prompt de s'afficher.
        r = subprocess.run(["sudo", sys.executable, str(script),
                            "--install-poweroff-system", str(home)],
                            capture_output=True, text=True)
        ok = (r.returncode == 0)
        report = (r.stdout or "") + (r.stderr or "")
    except Exception as e:
        ok = False
        report = str(e)
    finally:
        stdscr.refresh()

    _save_poweroff_install_log(ok, report)

    if not ok:
        _text_page(stdscr, "Installation incomplete", [
            "Le module d'extinction apres veille prolongee n'a pas pu",
            "etre installe (mot de passe incorrect ou sudo indisponible).",
            "",
            "Le reglage reste actif pour l'inactivite simple (app ouverte),",
            "mais pas pour la mise en veille (capot ferme).",
            "",
            "Detail : Debug > \"Dernier resultat d'installation\".",
        ])
    return ok


def _clone_screen(stdscr):
    """Clone un dépôt GitHub dans ~/Projets."""
    _wifi_managed = _settings.get("wifi_off", False)
    if _wifi_managed:
        _wifi_set_radio(True)
        _wait_wifi_up(stdscr)
    if not _is_network_connected():
        _flash(stdscr, "WiFi non connecte — redirection vers la connexion...", 1.2)
        _wifi_connect_screen(stdscr)
    if not _is_network_connected():
        if _wifi_managed:
            _wifi_set_radio(False)
        _flash(stdscr, "Le clonage necessite une connexion reseau.")
        return

    try:
        # ── Tentative de listing via l'API GitHub ─────────────────────────
        github_user  = _settings.get("github_user", "")
        github_token = _settings.get("github_token", "")
        url = None

        if github_user or github_token:
            _loader(stdscr, "Chargement de vos repos GitHub...")
            repos = _github_list_repos(github_user, github_token)
            if repos is not None:
                url = _pick_github_repo(stdscr, repos)
                if url is None:
                    return  # l'utilisateur a appuyé sur Retour
            else:
                _flash(stdscr, "Impossible de charger les repos — saisie manuelle.", 1.5)

        if not url:
            url = get_input(stdscr, "URL GitHub a cloner (SSH ou HTTPS)")
        if not url:
            return

        guess = url.rstrip("/").split("/")[-1]
        if guess.endswith(".git"):
            guess = guess[:-4]
        name = get_input(stdscr, "Nom du projet local", prefill=guess)
        if not name:
            return
        dest = PROJECTS_DIR / name
        if dest.exists():
            _flash(stdscr, f"Un projet « {name} » existe deja.")
            return
        _loader(stdscr, f"Clonage de {url}...")
        ok, out = git_clone(url, dest)
        if ok:
            _flash(stdscr, f"Projet « {name} » clone avec succes !")
        else:
            _text_page(stdscr, "Erreur — git clone", out.splitlines() or ["(pas de detail)"])
    finally:
        if _wifi_managed:
            _wifi_set_radio(False)


def home_screen(stdscr):
    """Écran d'accueil : logo centré + projets + menu."""
    sel = 0
    logo_w = max(len(l) for l in _LOGO)

    while True:
        projects = sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir())
        n = len(projects)
        total = n + 4   # n projets + Nouveau + Cloner + Paramètres + Eteindre
        sel = clamp(sel, 0, total - 1)

        h, w = stdscr.getmaxyx()
        stdscr.erase()
        topbar(stdscr, "")

        # ── Logo centré ──────────────────────────────────────────────────────
        lx  = max(0, (w - logo_w) // 2)
        row = 2
        for line in _LOGO:
            try:
                stdscr.addstr(row, lx, line[:w - lx], curses.A_BOLD)
            except curses.error:
                pass
            row += 1
        row += 1
        tx = max(0, (w - len(_TAGLINE)) // 2)
        try:
            stdscr.addstr(row, tx, _TAGLINE, curses.A_DIM)
        except curses.error:
            pass
        row += 2
        sep_w = min(logo_w, w - 6)
        sx = max(0, (w - sep_w) // 2)
        try:
            stdscr.addstr(row, sx, "-" * sep_w, curses.A_DIM)
        except curses.error:
            pass
        row += 2

        # ── Projets ──────────────────────────────────────────────────────────
        try:
            stdscr.addstr(row, 3, "Projets", curses.A_BOLD)
        except curses.error:
            pass
        row += 2

        if not projects:
            try:
                stdscr.addstr(row, 5, "(aucun projet)", curses.A_DIM)
            except curses.error:
                pass
            row += 1
        else:
            for i, proj in enumerate(projects):
                if row >= h - 2:
                    break
                is_sel = (sel == i)
                line = f"  {'>' if is_sel else ' '}  {proj.name}"
                try:
                    if is_sel:
                        stdscr.attron(curses.A_REVERSE)
                        stdscr.addstr(row, 0, line[:w].ljust(w))
                        stdscr.attroff(curses.A_REVERSE)
                    else:
                        stdscr.addstr(row, 0, line[:w])
                except curses.error:
                    pass
                row += 1

        row += 1
        try:
            stdscr.addstr(row, 3, "-" * min(sep_w, w - 6), curses.A_DIM)
        except curses.error:
            pass
        row += 2

        # ── Menu fixe ─────────────────────────────────────────────────────────
        menu_items = [
            (n,     "  +  Nouveau projet"),
            (n + 1, "  v  Cloner depuis GitHub"),
            (n + 2, "  *  Parametres"),
            (n + 3, "  o  Eteindre l'ordinateur"),
        ]
        for item_idx, label in menu_items:
            if row >= h - 1:
                break
            is_sel = (sel == item_idx)
            try:
                if is_sel:
                    stdscr.attron(curses.A_REVERSE)
                    stdscr.addstr(row, 0, label[:w].ljust(w))
                    stdscr.attroff(curses.A_REVERSE)
                else:
                    stdscr.addstr(row, 0, label[:w])
            except curses.error:
                pass
            row += 1

        bottombar(stdscr, "  haut/bas Naviguer   -> Ouvrir / Valider   X Supprimer projet")
        stdscr.refresh()

        ch, code = next_key(stdscr)
        k = ch.lower() if (ch is not None and ord(ch) >= 32) else None

        if code == curses.KEY_UP:
            sel = max(0, sel - 1)
        elif code == curses.KEY_DOWN:
            sel = min(total - 1, sel + 1)
        elif code in (curses.KEY_RIGHT, curses.KEY_ENTER) or ch in ("\n", "\r"):
            if sel < n:
                proj = projects[sel]
                restore = None
                last = _settings.get("last_open", {})
                if last.get("project") == proj.name:
                    try:
                        rp = Path(last["path"])
                        if rp.exists() and rp.is_relative_to(proj):
                            restore = rp
                    except Exception:
                        pass
                browse_screen(stdscr, proj, is_project_root=True, _restore=restore)
            elif sel == n:
                name = get_input(stdscr, "Nom du nouveau projet")
                if name:
                    new_path = PROJECTS_DIR / name
                    new_path.mkdir(parents=True, exist_ok=True)
                    new_projects = sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir())
                    names = [p.name for p in new_projects]
                    sel = names.index(name) if name in names else sel
            elif sel == n + 1:
                _clone_screen(stdscr)
                new_projects = sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir())
                sel = clamp(sel, 0, len(new_projects) + 3)
            elif sel == n + 2:
                if settings_screen(stdscr):
                    return
            elif sel == n + 3:
                _poweroff(stdscr)
        elif k == "x" and sel < n:
            to_del = projects[sel]
            if confirm(stdscr, f"Supprimer le projet \"{to_del.name}\" et tout son contenu ?"):
                shutil.rmtree(to_del)
                sel = max(0, sel - 1)


# ── point d'entrée ───────────────────────────────────────────────────────────

def main(stdscr):
    curses.raw()
    curses.curs_set(0)
    stdscr.keypad(True)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
    _load_settings()
    _apply_theme(stdscr)
    PROJECTS_DIR.mkdir(parents=True, exist_ok=True)

    # Force les codes clavier (indépendant du terminfo)
    # Sur Mac : Ctrl+←/→ est intercepté par macOS ; Terminal.app envoie
    # \033b / \033f (Option+←/→) à la place — on les mappe aux mêmes actions.
    for _seq, _code in [
        ("\033[1;5D", 546), ("\033[1;5C", 561),           # Ctrl+←/→
        ("\033b",     546), ("\033f",     561),           # Option+←/→ (Mac)
        ("\033[1;2D", curses.KEY_SLEFT),                  # Shift+←
        ("\033[1;2C", curses.KEY_SRIGHT),                 # Shift+→
        ("\033[1;2A", curses.KEY_SR),                     # Shift+↑
        ("\033[1;2B", curses.KEY_SF),                     # Shift+↓
        ("\033[1;6D", 580), ("\033[1;6C", 595),           # Ctrl+Shift+←/→
        ("\033[1;6A", 570), ("\033[1;6B", 575),           # Ctrl+Shift+↑/↓
        ("\033[1;4D", 580), ("\033[1;4C", 595),           # Option+Shift+←/→ (Mac)
        ("\033[1;4A", 570), ("\033[1;4B", 575),           # Option+Shift+↑/↓ (Mac)
    ]:
        try:
            curses.define_key(_seq, _code)
        except Exception:
            pass

    if _settings.get("wifi_off", False):
        _wifi_set_radio(False)

    home_screen(stdscr)


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--install-poweroff-system":
        # Appele par install.sh (deja root) ou par _ensure_poweroff_system
        # via sudo : ecriture directe des fichiers systeme.
        _home = Path(sys.argv[2]) if len(sys.argv) > 2 else Path.home()
        _ok, _report = _install_poweroff_system_as_root(_home)
        print(_report)   # toujours affiche (succes ou echec) pour diagnostic
        sys.exit(0 if _ok else 1)

    os.environ.setdefault("ESCDELAY", "25")   # ESC réactif sans attendre 1 s
    curses.wrapper(main)

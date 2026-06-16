#!/usr/bin/env python3
import os
import re
import json
import time
import curses
import locale
import shutil
import subprocess
from pathlib import Path

locale.setlocale(locale.LC_ALL, "")

PROJECTS_DIR  = Path.home() / "Projets"
_CONFIG_FILE  = Path.home() / ".config" / "freewrite" / "config.json"
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
    if _settings.get("theme") == "light":
        curses.init_pair(1, curses.COLOR_BLACK, curses.COLOR_WHITE)
        stdscr.bkgd(" ", curses.color_pair(1))
    else:
        curses.init_pair(1, -1, -1)
        stdscr.bkgd(" ")


# ── statut système (batterie / wifi) ─────────────────────────────────────────

_sys_cache: dict = {"bat": "", "wifi": "", "ts": 0.0}


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


def _refresh_sys_status():
    now = time.time()
    if now - _sys_cache["ts"] < 10:
        return
    _sys_cache["ts"] = now
    _sys_cache["bat"]  = _read_battery()
    ssid = _read_wifi_ssid()
    _sys_cache["wifi"] = f"WiFi:{ssid}" if ssid else "WiFi:--"


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
    title  = f"  FREEWRITE  —  {text}"
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


def next_key(stdscr):
    """Lit une touche. Retourne (char_str | None, keycode_int | None)."""
    try:
        key = stdscr.get_wch()
    except curses.error:
        return None, None
    if isinstance(key, str):
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
    if not ok:
        return []
    return [b.strip() for b in out.splitlines() if b.strip()]


def git_push(path: Path) -> tuple[bool, str]:
    branch = git_current_branch(path)
    ok, out = _git(path, "push", "origin", branch)
    if not ok and ("upstream" in out.lower() or "set-upstream" in out.lower()):
        ok, out = _git(path, "push", "--set-upstream", "origin", branch)
    return ok, out


def git_pull(path: Path) -> tuple[bool, str]:
    return _git(path, "pull")


def git_create_branch(path: Path, name: str) -> tuple[bool, str]:
    return _git(path, "checkout", "-b", name)


def git_switch_branch(path: Path, name: str) -> tuple[bool, str]:
    return _git(path, "checkout", name)


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
    stdscr.erase()
    try:
        stdscr.addstr(h // 2, max(0, (w - len(message)) // 2), message, curses.A_DIM)
    except curses.error:
        pass
    bottombar(stdscr, "  Veuillez patienter...")
    stdscr.refresh()


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


def _find_usb_drives() -> list[Path]:
    """Retourne les points de montage détectés sous /media et /mnt."""
    import os as _os
    username = Path.home().name
    roots = [
        Path("/media") / username,
        Path("/run/media") / username,
        Path("/media"),
        Path("/mnt"),
    ]
    seen: set[Path] = set()
    result: list[Path] = []
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

    if action == "commit":
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
        ok, out = git_switch_branch(project_path, chosen)
        if not ok:
            return _err(stdscr, "git checkout", out)
        return f"✓ Basculé sur « {chosen} »"

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


def git_page(stdscr, project_path: Path):
    """Page Git plein écran."""
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

class Editor:
    def __init__(self, filepath: Path):
        self.filepath = filepath
        self.lines: list[str] = []
        self.cy = 0
        self.cx = 0
        self.oy = 0
        self.ox = 0
        self._load()

    def _load(self):
        if self.filepath.exists():
            text = self.filepath.read_text(encoding="utf-8")
            self.lines = text.split("\n")
            if self.lines and self.lines[-1] == "":
                self.lines.pop()
        if not self.lines:
            self.lines = [""]

    def _save(self):
        self.filepath.write_text("\n".join(self.lines) + "\n", encoding="utf-8")

    def run(self, stdscr):
        prev_curs = curses.curs_set(1)
        stdscr.keypad(True)

        try:
            while True:
                h, w = stdscr.getmaxyx()
                self._scroll(h, w)
                self._draw(stdscr, h, w)

                ch, code = next_key(stdscr)

                if ch is not None:
                    c = ord(ch)
                    if c == 17:                  # Ctrl+Q
                        break
                    elif ch in ("\n", "\r"):
                        self._newline()
                        self._save()
                    elif c in (127, 8):          # Backspace
                        self._backspace()
                        self._save()
                    elif ch == "\t":
                        self._insert("    ")
                        self._save()
                    elif c >= 32:
                        self._insert(ch)
                        self._save()
                elif code is not None:
                    if code == curses.KEY_UP:
                        self._move_up()
                    elif code == curses.KEY_DOWN:
                        self._move_down()
                    elif code == curses.KEY_LEFT:
                        self._move_left()
                    elif code == curses.KEY_RIGHT:
                        self._move_right()
                    elif code == curses.KEY_HOME:
                        self.cx = 0
                    elif code == curses.KEY_END:
                        self.cx = len(self.lines[self.cy])
                    elif code == curses.KEY_PPAGE:
                        self._page_up(h)
                    elif code == curses.KEY_NPAGE:
                        self._page_down(h)
                    elif code == curses.KEY_BACKSPACE:
                        self._backspace()
                        self._save()
                    elif code == curses.KEY_DC:
                        self._delete()
                        self._save()

        finally:
            curses.curs_set(prev_curs)

    def _scroll(self, h, w):
        content_h = h - 2
        if self.cy < self.oy:
            self.oy = self.cy
        elif self.cy >= self.oy + content_h:
            self.oy = self.cy - content_h + 1
        if self.cx < self.ox:
            self.ox = self.cx
        elif self.cx >= self.ox + w:
            self.ox = self.cx - w + 1

    def _draw(self, stdscr, h, w):
        stdscr.erase()
        topbar(stdscr, self.filepath.name, status=False)

        content_h = h - 2
        for row in range(content_h):
            line_idx = self.oy + row
            if line_idx < len(self.lines):
                visible = self.lines[line_idx][self.ox:self.ox + w - 1]
                try:
                    stdscr.addstr(row + 1, 0, visible)
                except curses.error:
                    pass

        bottombar(stdscr, f"  L{self.cy + 1}:{self.cx + 1}   Ctrl+Q Quitter")

        try:
            stdscr.move(self.cy - self.oy + 1, self.cx - self.ox)
        except curses.error:
            pass
        stdscr.refresh()

    def _move_up(self):
        if self.cy > 0:
            self.cy -= 1
            self.cx = min(self.cx, len(self.lines[self.cy]))

    def _move_down(self):
        if self.cy < len(self.lines) - 1:
            self.cy += 1
            self.cx = min(self.cx, len(self.lines[self.cy]))

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

    def _page_up(self, h):
        self.cy = max(0, self.cy - (h - 2))
        self.cx = min(self.cx, len(self.lines[self.cy]))

    def _page_down(self, h):
        self.cy = min(len(self.lines) - 1, self.cy + (h - 2))
        self.cx = min(self.cx, len(self.lines[self.cy]))

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


def browse_screen(stdscr, directory: Path, is_project_root: bool = False):
    sel = 0

    while True:
        is_repo = is_project_root and git_available() and git_is_repo(directory)
        items = sorted(
            (p for p in directory.iterdir() if p.name != ".git"),
            key=lambda p: (p.is_file(), p.name.lower()),
        )
        sel = clamp(sel, 0, max(0, len(items) - 1))

        # Badge git dans la topbar
        git_badge = ""
        if is_repo:
            branch = git_current_branch(directory)
            git_badge = f"  ● {branch}" if git_has_changes(directory) else f"  ✓ {branch}"

        if is_project_root:
            bar = "  -> <- Nav   F Fich   D Doss   X Suppr   R Renom   M Dep   U USB"
            bar += "   G Git" if git_available() else ""
        else:
            bar = "  -> <- Nav   F Fichier   D Dossier   X Suppr   R Renommer   M Deplacer"

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
                    browse_screen(stdscr, item)
                else:
                    Editor(item).run(stdscr)
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

            elif k == "d":
                name = get_input(stdscr, "Nom du dossier")
                if name:
                    (directory / name).mkdir(exist_ok=True)

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
    r"  ___  ___  ___ ___ _ _ ___ ___ _____ ___ ",
    r" | __|| _ \| __| __| | | _ \_ _|_   _| __|",
    r" | _| |   /| _|| _|| | |   /| |  | | | _| ",
    r" |_|  |_|_\|___|___|\_/|_|_\___|  |_| |___|",
]
_TAGLINE = "ecrire, sans distraction"

_GITHUB_REPO = "VSerain/distraction-free-write"
_INSTALL_PATH = Path("/opt/freewrite/main.py")


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
    _loader(stdscr, "Recherche de la derniere version...")
    tag = _fetch_latest_tag()
    if not tag:
        _text_page(stdscr, "Mise a jour", ["Impossible de contacter GitHub.", "", "Verifiez votre connexion."])
        return

    current = _settings.get("version", "inconnue")
    if not confirm(stdscr, f"Installer {tag}  (version actuelle : {current}) ?"):
        return

    _loader(stdscr, f"Telechargement de {tag}...")
    url = f"https://raw.githubusercontent.com/{_GITHUB_REPO}/{tag}/main.py"
    tmp = Path("/tmp/freewrite_update.py")
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
        _text_page(stdscr, "Mise a jour reussie", [
            f"Version {tag} installee.",
            "",
            "Quittez et relancez l'application pour appliquer.",
        ])
    except Exception as e:
        _text_page(stdscr, "Erreur", [str(e)])


def _is_autostart_enabled() -> bool:
    profile = Path.home() / ".bash_profile"
    return profile.exists() and "freewrite" in profile.read_text()


def _toggle_autostart(stdscr):
    profile = Path.home() / ".bash_profile"
    if _is_autostart_enabled():
        if not confirm(stdscr, "Desactiver le demarrage automatique ?"):
            return
        text = profile.read_text()
        text = re.sub(
            r"\n# Lancer Freewrite automatiquement.*?fi\n",
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
                "\n# Lancer Freewrite automatiquement sur TTY1\n"
                'if [ "$(tty)" = "/dev/tty1" ]; then\n'
                "    freewrite\n"
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
    _THEMES    = [("dark", "Sombre"), ("light", "Clair")]
    WIFI_IDX   = len(_THEMES)          # 2
    UPDATE_IDX = len(_THEMES) + 1      # 3
    AUTO_IDX   = len(_THEMES) + 2      # 4
    TOTAL      = len(_THEMES) + 3      # 5
    current    = _settings.get("theme", "dark")
    sel        = next((i for i, (k, _) in enumerate(_THEMES) if k == current), 0)

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

        # ── Reseau ──
        _heading(row, "Reseau");  row += 2
        ssid  = _sys_cache.get("wifi", "")
        extra = f"   ({ssid})" if ssid and ssid != "WiFi:--" else ""
        _item(row, WIFI_IDX, "Se connecter au WiFi" + extra);  row += 2

        _sep(row);  row += 2

        # ── Application ──
        _heading(row, "Application");  row += 2
        ver = _settings.get("version", "?")
        _item(row, UPDATE_IDX, f"Installer la derniere version   (actuelle : {ver})");  row += 1
        auto_state = "active" if _is_autostart_enabled() else "desactive"
        _item(row, AUTO_IDX, f"Demarrage automatique : {auto_state}")

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
            elif sel == WIFI_IDX:
                _wifi_connect_screen(stdscr)
            elif sel == UPDATE_IDX:
                _update_app(stdscr)
            elif sel == AUTO_IDX:
                _toggle_autostart(stdscr)
        elif code == curses.KEY_LEFT or (ch is not None and ord(ch) == 27):
            return


def home_screen(stdscr):
    """Écran d'accueil : logo centré + projets + menu."""
    sel = 0
    logo_w = max(len(l) for l in _LOGO)

    while True:
        projects = sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir())
        n = len(projects)
        total = n + 3   # n projets + Nouveau + Paramètres + Quitter
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
            (n + 1, "  *  Parametres"),
            (n + 2, "     Quitter"),
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
                browse_screen(stdscr, projects[sel], is_project_root=True)
            elif sel == n:
                name = get_input(stdscr, "Nom du nouveau projet")
                if name:
                    new_path = PROJECTS_DIR / name
                    new_path.mkdir(parents=True, exist_ok=True)
                    new_projects = sorted(p for p in PROJECTS_DIR.iterdir() if p.is_dir())
                    names = [p.name for p in new_projects]
                    sel = names.index(name) if name in names else sel
            elif sel == n + 1:
                settings_screen(stdscr)
            elif sel == n + 2:
                return
        elif k == "x" and sel < n:
            proj = projects[sel]
            if confirm(stdscr, f"Supprimer le projet \"{proj.name}\" et tout son contenu ?"):
                shutil.rmtree(proj)
                sel = max(0, sel - 1)
        elif k == "q" or (ch is not None and ord(ch) == 27):
            return


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
    home_screen(stdscr)


if __name__ == "__main__":
    curses.wrapper(main)

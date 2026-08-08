#!/usr/bin/env python3
"""Scraper cpliege.be -> JSON statiques (docs/api/).

Le site est un export Excel en HTML (windows-1252), régénéré chaque jour
vers 6h50. Ce script convertit les pages utiles en JSON propres pour
l'app iOS. Aucune dépendance externe (stdlib uniquement).
"""

import json
import re
import sys
import time
import html as htmllib
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE = "https://www.cpliege.be/"
OUT = Path(__file__).resolve().parent.parent / "docs" / "api"

DIVISION_RE = re.compile(r"^(MM|DD|TOP DIVISION|U\s?\d+)\b")
# numéros de match : 401011, AW100001, NADSE11ACA (nat.), 95 (coupe)...
MATCHNO_RE = re.compile(r"^(?=.*\d)[A-Z0-9]{2,}$")
DAY_RE = re.compile(r"^(LUNDI|MARDI|MERCREDI|JEUDI|VENDREDI|SAMEDI|DIMANCHE)$", re.I)
DATE_RE = re.compile(r"^\d{2}/\d{2}/\d{2,4}$")
TIME_RE = re.compile(r"^\d{1,2}\.\d{2}$")
REMIS_RE = re.compile(r"^Remis", re.I)
NEWS_DATE_RE = re.compile(
    r"^(Lundi|Mardi|Mercredi|Jeudi|Vendredi|Samedi|Dimanche)\s+\d{1,2}(er)?\s+\S+\s+\d{4}$", re.I
)
UPDATED_RE = re.compile(r"(Dernière mise\s*à\s*jour|Edition du)\s*:?\s*(le\s*)?([\d/]+\s*à\s*[\d:]+)", re.I)


def fetch(path: str) -> str:
    url = BASE + path
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "cpliege-data-scraper"})
            with urllib.request.urlopen(req, timeout=60) as resp:
                return resp.read().decode("cp1252", errors="replace")
        except Exception:
            if attempt == 2:
                raise
            time.sleep(5)
    raise RuntimeError("unreachable")


def parse_rows(src: str):
    """Retourne les lignes de tableaux comme listes de cellules.

    Chaque cellule est un dict {t: texte, red: bool} — `red` sert à
    détecter les numéros de match modifiés (affichés en rouge).
    """
    # le rouge vient de classes CSS de l'export Excel (.xlNNN {... color:red})
    red_classes = set()
    for style in re.findall(r"<style[^>]*>(.*?)</style>", src, flags=re.S | re.I):
        for cls in re.findall(r"\.(xl\d+)\s*{[^}]*color\s*:\s*(?:red|#FF0000)", style, re.I):
            red_classes.add(cls)
    red_class_re = re.compile(r"class=[\"']?(" + "|".join(red_classes) + r")\b") if red_classes else None
    src = re.sub(r"<(style|script)[^>]*>.*?</\1>", "", src, flags=re.S | re.I)
    rows = []
    for r in re.findall(r"<tr[^>]*>(.*?)</tr>", src, flags=re.S | re.I):
        cells = []
        for m in re.finditer(r"<td([^>]*)>(.*?)</td>", r, flags=re.S | re.I):
            attrs, c = m.group(1), m.group(2)
            red = bool(re.search(r"color\s*[:=]\s*[\"']?\s*(red|#?FF0000)", attrs + c, re.I))
            if not red and red_class_re is not None:
                red = bool(red_class_re.search(attrs) or red_class_re.search(c))
            text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", c))).strip()
            cells.append({"t": text, "red": red})
        if any(c["t"] for c in cells):
            rows.append(cells)
    return rows


def texts(row):
    return [c["t"] for c in row if c["t"]]


def find_updated(rows):
    for row in rows[:8]:
        m = UPDATED_RE.search(" ".join(texts(row)))
        if m:
            return m.group(3).strip()
    return None


def is_int(s):
    return bool(re.match(r"^-?\d+$", s))


# ---------------------------------------------------------------- résultats

def parse_results(src: str):
    """resulsen/resuljeu/resulnat : par division, résultats du WE + classement."""
    rows = parse_rows(src)
    out = {"updated": find_updated(rows), "divisions": []}
    div = None
    for row in rows:
        ne = texts(row)
        if len(ne) == 1 and DIVISION_RE.match(ne[0]):
            div = {"name": ne[0], "results": [], "standings": [], "notes": []}
            out["divisions"].append(div)
            continue
        if div is None:
            continue
        nums = [x for x in ne if is_int(x)]
        names = [x for x in ne if not is_int(x)]
        # classement : équipe + 6 nombres (J, G, P, pour, contre, points)
        if len(names) == 1 and len(nums) >= 6:
            j, g, p, pf, pc, pts = (int(x) for x in nums[:6])
            div["standings"].append({
                "team": names[0], "played": j, "won": g, "lost": p,
                "for": pf, "against": pc, "points": pts,
            })
        # résultat / affiche du WE : 2 équipes (+ scores si joué)
        elif len(names) == 2 and len(nums) in (0, 2):
            res = {"home": names[0], "away": names[1],
                   "scoreHome": None, "scoreAway": None}
            if len(nums) == 2:
                res["scoreHome"], res["scoreAway"] = int(nums[0]), int(nums[1])
            div["results"].append(res)
        else:
            div["notes"].append(" ".join(ne))
    return out


# ---------------------------------------------------------------- calendriers

def parse_match_cells(ne, red):
    """Interprète une ligne de match (calendrier ou page club)."""
    m = {"no": ne[0], "modified": red, "day": None, "date": None,
         "time": None, "remisAu": None, "home": None, "away": None}
    rest = []
    for x in ne[1:]:
        if DAY_RE.match(x) and m["day"] is None:
            m["day"] = x.capitalize()
        elif len(x) == 1 and x in "LMJVSD" and m["day"] is None:
            m["day"] = x
        elif DATE_RE.match(x) and m["date"] is None:
            m["date"] = x
        elif TIME_RE.match(x) and m["time"] is None:
            m["time"] = x.replace(".", ":")
        elif REMIS_RE.match(x):
            m["remisAu"] = x
        else:
            rest.append(x)
    if len(rest) >= 2:
        m["home"], m["away"] = rest[0], rest[1]
    elif len(rest) == 1:
        m["home"] = rest[0]
    # cellule excédentaire = étiquette de division/compétition
    # (partie chronologique et matchs non programmés des pages club)
    m["label"] = rest[2] if len(rest) >= 3 else None
    return m


def parse_calendar(src: str):
    """calensen/calenjeu : semaines > divisions > matchs."""
    rows = parse_rows(src)
    out = {"updated": find_updated(rows), "weeks": []}
    week = None
    div = None
    for row in rows:
        ne = texts(row)
        joined = " ".join(ne)
        if joined.upper().startswith("SEMAINE DU"):
            week = {"label": joined, "divisions": []}
            out["weeks"].append(week)
            div = None
            continue
        if week is None:
            continue
        if len(ne) == 1 and DIVISION_RE.match(ne[0]):
            div = {"name": ne[0], "matches": []}
            week["divisions"].append(div)
            continue
        if div is not None and ne and MATCHNO_RE.match(ne[0]):
            red = row[0]["red"] if row else False
            m = parse_match_cells(ne, red)
            m.pop("label")
            div["matches"].append(m)
    return out


# ---------------------------------------------------------------- clubs

def parse_caleclub(src: str):
    """caleclub.asp : liste des clubs -> pages clubs/clubNNNN.asp."""
    clubs = {}
    for href, label in re.findall(
        r'<a href="([Cc]lubs/club(?:\d+)\.asp)"[^>]*>(.*?)</a>', src, flags=re.S | re.I
    ):
        text = re.sub(r"\s+", " ", htmllib.unescape(re.sub(r"<[^>]+>", "", label))).strip()
        m = re.match(r"^(\d+)\s+(.*)$", text)
        if not m:
            continue
        matricule = int(m.group(1))
        clubs[matricule] = {
            "matricule": matricule,
            "name": m.group(2).strip(),
            "page": "clubs/club%04d.asp" % matricule,
        }
    return sorted(clubs.values(), key=lambda c: c["matricule"])


def parse_club(src: str):
    """clubs/clubNNNN.asp : calendrier de toutes les équipes du club.

    Structure de la page :
    1. "Par journée" : une section par équipe (en-tête = division) ;
    2. une section "COUPE" (matchs de coupe, toutes équipes) ;
    3. une reprise chronologique : mêmes matchs avec la division en
       dernière cellule -> doublons, ignorés ;
    4. en bas : rencontres non programmées (pas de date, étiquette de
       compétition en dernière cellule).
    """
    rows = parse_rows(src)
    club_name = texts(rows[0])[0] if rows else None
    out = {"club": club_name, "updated": find_updated(rows),
           "teams": [], "cup": [], "unscheduled": []}
    section = None    # section d'équipe courante (partie 1)
    in_cup = False
    for row in rows:
        ne = texts(row)
        if len(ne) == 1 and ne[0] == "COUPE":
            in_cup = True
            section = None
            continue
        if len(ne) == 1 and DIVISION_RE.match(ne[0]) and not in_cup:
            section = {"division": ne[0], "team": None, "matches": []}
            out["teams"].append(section)
            continue
        if ne and MATCHNO_RE.match(ne[0]):
            red = row[0]["red"] if row else False
            match = parse_match_cells(ne, red)
            label = match.pop("label")
            if label is not None:
                # partie chronologique (avec date : doublon de la partie 1)
                # ou rencontre non programmée (sans date)
                if not (match["date"] or match["time"] or match["day"]):
                    match["division"] = label
                    out["unscheduled"].append(match)
            elif in_cup:
                out["cup"].append(match)
            elif section is not None:
                section["matches"].append(match)
    # nom de l'équipe = nom apparaissant dans le plus de matchs de la section
    for team in out["teams"]:
        counts = {}
        for m in team["matches"]:
            for name in (m["home"], m["away"]):
                if name:
                    counts[name] = counts.get(name, 0) + 1
        if counts:
            team["team"] = max(counts, key=counts.get)
    return out


def parse_lesclubs(src: str):
    """lesclubs.asp : annuaire (contact, salle, couleurs, équipes par niveau)."""
    rows = parse_rows(src)
    out = {"updated": find_updated(rows), "clubs": []}
    club = None
    field = None
    for row in rows:
        cells = [c["t"] for c in row]
        ne = texts(row)
        if not ne:
            continue
        m = re.match(r"^(\d+)\s*-\s*(.+)$", ne[0])
        if m and len(ne) == 1 and not DIVISION_RE.match(ne[0]):
            club = {"matricule": int(m.group(1)), "name": m.group(2).strip(),
                    "secretary": [], "email": None, "colors": None,
                    "venue": None, "teams": {}}
            out["clubs"].append(club)
            field = None
            continue
        if club is None:
            continue
        label = cells[0] if cells else ""
        value = " ".join(x for x in ne[1:] if x) if label else " ".join(ne)
        if label == "Secrétaire":
            field = "secretary"
            club["secretary"].append(value)
        elif label == "Courriel":
            field = None
            club["email"] = value
        elif label == "Equipements":
            field = None
            club["colors"] = value
        elif label == "Terrain":
            field = "venue"
            club["venue"] = value
        elif label in ("Nationales", "Régionales", "Provinciales"):
            field = ("teams", label)
            club["teams"][label] = value
        elif not label and ne:
            # ligne de continuation du champ précédent
            if field == "secretary":
                club["secretary"].append(value)
            elif field == "venue":
                club["venue"] = (club["venue"] or "") + " " + value
            elif isinstance(field, tuple) and field[0] == "teams":
                club["teams"][field[1]] += " " + value
    for c in out["clubs"]:
        c["teams"] = {
            k: [t.strip() for t in v.split(" - ") if t.strip()]
            for k, v in c["teams"].items()
        }
    return out


# ---------------------------------------------------------------- infos

def parse_infos(src: str):
    """infos.asp : fil d'actualités, groupé par date."""
    rows = parse_rows(src)
    items = []
    current = None
    for row in rows:
        ne = texts(row)
        joined = " ".join(ne).strip()
        if not joined:
            continue
        if NEWS_DATE_RE.match(joined):
            current = {"date": joined, "paragraphs": []}
            items.append(current)
        elif current is not None:
            current["paragraphs"].append(joined)
    return {"items": items}


# ---------------------------------------------------------------- main

def write(path: str, data):
    f = OUT / path
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")),
                 encoding="utf-8")
    print(f"  {path}: {f.stat().st_size} bytes")


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    meta = {"generatedAt": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "source": "https://www.cpliege.be", "pages": {}}

    print("== résultats & classements ==")
    for path, name in [("resulsen.asp", "seniors"), ("resuljeu.asp", "jeunes"),
                       ("resulnat.asp", "natreg")]:
        data = parse_results(fetch(path))
        write(f"resultats/{name}.json", data)
        meta["pages"][path] = data.get("updated")

    print("== calendriers ==")
    for path, name in [("calensen.asp", "seniors"), ("calenjeu.asp", "jeunes")]:
        data = parse_calendar(fetch(path))
        write(f"calendriers/{name}.json", data)
        meta["pages"][path] = data.get("updated")

    print("== infos ==")
    write("infos.json", parse_infos(fetch("infos.asp")))

    print("== annuaire clubs ==")
    directory = parse_lesclubs(fetch("lesclubs.asp"))
    write("annuaire.json", directory)
    meta["pages"]["lesclubs.asp"] = directory.get("updated")

    print("== clubs & calendriers personnalisés ==")
    clubs = parse_caleclub(fetch("caleclub.asp"))
    details = {c["matricule"]: c for c in directory["clubs"]}
    for club in clubs:
        info = details.get(club["matricule"], {})
        club["colors"] = info.get("colors")
        club["venue"] = info.get("venue")
    write("clubs.json", {"clubs": clubs})
    errors = []
    for club in clubs:
        try:
            data = parse_club(fetch(club["page"]))
            data["matricule"] = club["matricule"]
            write("clubs/%d.json" % club["matricule"], data)
        except Exception as e:  # un club qui casse ne doit pas bloquer le reste
            errors.append({"club": club["matricule"], "error": str(e)})
            print(f"  ERREUR club {club['matricule']}: {e}", file=sys.stderr)
        time.sleep(0.4)

    meta["clubCount"] = len(clubs)
    meta["errors"] = errors
    write("meta.json", meta)
    if errors:
        sys.exit(1)


if __name__ == "__main__":
    main()

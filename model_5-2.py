#!/usr/bin/env python3
# model_52.py
#
# Model de l'apartat 5.2 (CP-SAT) per al repte d'horaris i espais.
#
# NOTA: l'enunciat literal de l'apartat 5.2 no s'ha inclòs al missatge.
# Aquest codi implementa les restriccions que es descriuen al DICCIONARI.md
# i al cobertura.json:
#   - cada sessió es planifica dins de la seva setmana (no canvia de setmana)
#   - es poden canviar dia, hora i aula
#   - calendari: festius, no lectius, avaluació i aturades
#   - torn requerit (finestra ampla matí/tarda)
#   - capacitat d'aula (tova, amb penalització)
#   - tipus d'aula per a PLAB (tova, amb penalització)
#   - no solapament d'aules
#   - no solapament de docents
#   - no solapament de grup exacte
#   - sessions fixades R1/R7 (dures al nivell 0; toves als nivells de relaxació)
#   - sessions compartides (id_compartida) es mouen juntes
#   - objectiu: minimitzar canvis respecte de proposta_partida.csv
#
# Si el model és infactible, el codi relaxa gradualment:
#   nivell 0: tot dur (fixades dures, capacitat/tipus filtrats, docents i grups)
#   nivell 1: fixades toves, capacitat/tipus tous
#   nivell 2: deixa de fer dur el no-solapament de docents
#   nivell 3: deixa de fer dur el no-solapament de grup exacte
#   nivell 4: deixa de fer dura la igualtat d'aula de sessions compartides
#
# Sortida: CSV amb capçalera id_sessio,dia,h_ini,aula
#
# Ús:
#   python model_52.py \
#     --sessions sessions.csv \
#     --aules aules.csv \
#     --calendari calendari.csv \
#     --out proposta.csv \
#     --time-limit 300

import argparse
import csv
import sys
from collections import defaultdict
from datetime import date, timedelta

try:
    from ortools.sat.python import cp_model
except ImportError:
    print("Falta OR-Tools. Instal·la'l amb: pip install ortools", file=sys.stderr)
    raise


DAY_TO_INT = {"L": 0, "M": 1, "X": 2, "J": 3, "V": 4}
INT_TO_DAY = "LMXJV"

EXTERNAL_ALLOWED = {"B3/0021", "QC/1082"}


def parse_time(s: str) -> int:
    h, m = s.strip().split(":")
    return int(h) * 60 + int(m)


def fmt_time(m: int) -> str:
    m = int(m) % (24 * 60)
    return f"{m // 60:02d}:{m % 60:02d}"


def parse_week(week: str) -> date:
    # "2026-W37"
    y, w = week.split("-W")
    return date.fromisocalendar(int(y), int(w), 1)  # dilluns


def load_calendar(path):
    blocked_full = set()
    blocked_intervals = defaultdict(list)

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            d = date.fromisoformat(row["data"])
            typ = row["tipus"]

            if typ in ("festiu", "no_lectiu", "avaluacio"):
                blocked_full.add(d)
            elif typ == "aturada":
                if row.get("h_ini") and row.get("h_fi"):
                    blocked_intervals[d].append(
                        (parse_time(row["h_ini"]), parse_time(row["h_fi"]))
                    )
                else:
                    blocked_full.add(d)

    return blocked_full, blocked_intervals


def load_rooms(path):
    rooms = []
    room_info = {}

    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            code = row["aula"].strip()
            rooms.append(code)
            room_info[code] = (
                int(row["capacitat"]),
                row["tipus"].strip(),
                int(row["ordinaria"]),
            )

    # Aules externes que poden conservar-se si ja hi eren a la proposta inicial.
    for code in sorted(EXTERNAL_ALLOWED):
        if code not in room_info:
            rooms.append(code)
            room_info[code] = (999, "Extern", 0)

    room_index = {code: i for i, code in enumerate(rooms)}
    external_indices = {
        room_index[c] for c in EXTERNAL_ALLOWED if c in room_index
    }
    return rooms, room_info, room_index, external_indices


def load_sessions(path):
    sessions = []
    with open(path, newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row = dict(row)
            row["_dur"] = int(row["durada_min"])
            row["_alumnes"] = int(row["alumnes"] or 0)
            row["_sense_espai"] = row.get("sense_espai", "").strip() == "1"
            row["_fixada"] = row.get("fixada", "").strip()
            row["_docents"] = [
                x for x in row.get("docents", "").split("|") if x.strip()
            ]
            row["_orig_start"] = (
                DAY_TO_INT[row["dia"].strip()] * 1440
                + parse_time(row["h_ini"])
            )
            sessions.append(row)
    return sessions


def allowed_start_values(row, blocked_full, blocked_intervals):
    monday = parse_week(row["setmana"])
    dur = row["_dur"]
    orig = row["_orig_start"]
    torn = row.get("torn_requerit", "").strip()

    # Finestra àmplia per no fer infactibles horaris reals com 15:00 en torn de matí.
    if torn == "mati":
        low, high = 7 * 60, 16 * 60
    elif torn == "tarda":
        low, high = 13 * 60, 22 * 60
    else:
        low, high = 0, 24 * 60

    values = set()

    for off in range(5):
        d = monday + timedelta(days=off)
        if d in blocked_full:
            continue

        blocks = blocked_intervals.get(d, [])

        # Graella de 30 minuts, de 8:00 a 21:00.
        for tod in range(8 * 60, 21 * 60 + 1, 30):
            if tod < low or tod >= high:
                continue
            if tod + dur > 22 * 60:
                continue
            if any(tod < b_end and tod + dur > b_start for b_start, b_end in blocks):
                continue
            values.add(off * 1440 + tod)

    # Si la sessió està fixada o no hi ha cap slot possible, permetem l'original.
    if row["_fixada"] or not values:
        values.add(orig)

    return sorted(values)


def candidate_rooms(row, orig_idx, level, rooms, room_info, external_indices):
    alumnes = row["_alumnes"]
    tipus = row["tipus"].strip()

    base = [i for i in range(len(rooms)) if i not in external_indices]

    if level == 0:
        elig = base

        if alumnes > 0:
            elig2 = [i for i in elig if room_info[rooms[i]][0] >= alumnes]
            if elig2:
                elig = elig2

        if tipus == "PLAB":
            elig3 = [
                i for i in elig
                if room_info[rooms[i]][1].startswith("Laboratoris")
            ]
            if elig3:
                elig = elig3

        cand = list(elig)
    else:
        cand = list(base)

    # Les aules externes permeses només per a la mateixa sessió original.
    if orig_idx >= 0 and orig_idx in external_indices:
        cand.append(orig_idx)

    # Si és fixada, ha de poder conservar l'aula original.
    if row["_fixada"] and orig_idx >= 0:
        cand.append(orig_idx)

    cand = sorted(set(cand))
    if not cand:
        cand = list(range(len(rooms)))

    return cand


def build_and_solve(level, sessions, rooms, room_info, room_index,
                    external_indices, blocked_full, blocked_intervals,
                    time_limit):
    model = cp_model.CpModel()
    n = len(sessions)
    penalties = []

    # ---- Variables de temps ----
    start = [None] * n
    end = [None] * n
    interval = [None] * n

    for s, row in enumerate(sessions):
        vals = allowed_start_values(row, blocked_full, blocked_intervals)
        dom = cp_model.Domain.FromValues(vals)
        start[s] = model.NewIntVarFromDomain(dom, f"start_{s}")
        end[s] = model.NewIntVar(0, 5 * 1440 + 24 * 60, f"end_{s}")
        model.Add(end[s] == start[s] + row["_dur"])
        interval[s] = model.NewIntervalVar(
            start[s], row["_dur"], end[s], f"iv_{s}"
        )

        # Penalització per moure la sessió respecte de l'original.
        orig = row["_orig_start"]
        same_start = model.NewBoolVar(f"same_start_{s}")
        model.Add(start[s] == orig).OnlyEnforceIf(same_start)
        model.Add(start[s] != orig).OnlyEnforceIf(same_start.Not())
        penalties.append((1 - same_start) * 1)

        # Fixades: dures al nivell 0; toves als altres.
        if row["_fixada"]:
            if level == 0:
                model.Add(start[s] == orig)
            else:
                dev = model.NewIntVar(0, 5 * 1440, f"dev_start_{s}")
                model.AddAbsEquality(dev, start[s] - orig)
                penalties.append(dev * 1_000_000)

    # ---- Grups de sessions compartides ----
    shared_groups = defaultdict(list)
    for s, row in enumerate(sessions):
        cid = row.get("id_compartida", "").strip()
        if cid:
            shared_groups[cid].append(s)

    rep_of = list(range(n))
    for _, lst in shared_groups.items():
        rep = min(lst)
        for s in lst:
            rep_of[s] = rep

    # ---- Variables d'aula ----
    room = [None] * n
    assign = [dict() for _ in range(n)]
    room_intervals = defaultdict(list)

    for s, row in enumerate(sessions):
        if row["_sense_espai"]:
            continue

        orig_code = row.get("aula_partida", "").strip()
        orig_idx = room_index.get(orig_code, -1)
        cand = candidate_rooms(
            row, orig_idx, level, rooms, room_info, external_indices
        )

        room[s] = model.NewIntVarFromDomain(
            cp_model.Domain.FromValues(cand), f"room_{s}"
        )

        bools = []
        for r in cand:
            b = model.NewBoolVar(f"assign_{s}_{r}")
            model.Add(room[s] == r).OnlyEnforceIf(b)
            model.Add(room[s] != r).OnlyEnforceIf(b.Not())
            assign[s][r] = b
            bools.append(b)

            # Penalitzacions toves de capacitat i tipus.
            cap, typ, _ = room_info[rooms[r]]
            if row["_alumnes"] > 0 and cap < row["_alumnes"]:
                short = row["_alumnes"] - cap
                penalties.append(b * short * 10 * (level + 1))

            if row["tipus"].strip() == "PLAB" and not typ.startswith("Laboratoris"):
                penalties.append(b * 100 * (level + 1))

            # No afegim intervals per a no-representants: mateixa classe física.
            if s == rep_of[s]:
                iv = model.NewOptionalIntervalVar(
                    start[s], row["_dur"], end[s], b,
                    f"iv_room_{s}_{r}"
                )
                room_intervals[r].append(iv)

        model.Add(sum(bools) == 1)

        # Aula original: dura al nivell 0 si és fixada; tova als altres.
        if orig_idx >= 0 and orig_idx in assign[s]:
            same_room = model.NewBoolVar(f"same_room_{s}")
            model.Add(room[s] == orig_idx).OnlyEnforceIf(same_room)
            model.Add(room[s] != orig_idx).OnlyEnforceIf(same_room.Not())
            penalties.append((1 - same_room) * 1)

            if row["_fixada"]:
                if level == 0:
                    model.Add(room[s] == orig_idx)
                else:
                    dev = model.NewIntVar(0, len(rooms), f"dev_room_{s}")
                    model.AddAbsEquality(dev, room[s] - orig_idx)
                    penalties.append(dev * 1_000_000)

    # ---- Igualtat de sessions compartides ----
    for _, lst in shared_groups.items():
        rep = min(lst)
        for s in lst:
            if s == rep:
                continue
            model.Add(start[s] == start[rep])
            if level < 4 and room[s] is not None and room[rep] is not None:
                model.Add(room[s] == room[rep])

    # ---- No solapament d'aules ----
    for r, ivs in room_intervals.items():
        if len(ivs) > 1:
            model.AddNoOverlap(ivs)

    # ---- No solapament de docents ----
    if level < 2:
        docent_intervals = defaultdict(list)
        for s, row in enumerate(sessions):
            if s != rep_of[s]:
                continue
            for d in row["_docents"]:
                docent_intervals[d].append(interval[s])
        for _, ivs in docent_intervals.items():
            if len(ivs) > 1:
                model.AddNoOverlap(ivs)

    # ---- No solapament de grup exacte ----
    if level < 3:
        group_intervals = defaultdict(list)
        for s, row in enumerate(sessions):
            if s != rep_of[s]:
                continue
            group_intervals[row["grup"].strip()].append(interval[s])
        for _, ivs in group_intervals.items():
            if len(ivs) > 1:
                model.AddNoOverlap(ivs)

    # ---- Objectiu ----
    model.Minimize(sum(penalties))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = float(time_limit)
    solver.parameters.num_search_workers = 8
    solver.parameters.log_search_progress = False

    status = solver.Solve(model)

    if status in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        solution = []
        for s, row in enumerate(sessions):
            st = solver.Value(start[s])
            day = st // 1440
            tod = st % 1440
            dia = INT_TO_DAY[day] if 0 <= day < 5 else row["dia"]
            h_ini = fmt_time(tod)

            aula = ""
            if room[s] is not None:
                aula = rooms[solver.Value(room[s])]

            solution.append(
                {
                    "id_sessio": row["id_sessio"],
                    "dia": dia,
                    "h_ini": h_ini,
                    "aula": aula,
                }
            )

        return solution, status, solver.ObjectiveValue()

    return None, status, None


def write_solution(path, solution):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=["id_sessio", "dia", "h_ini", "aula"])
        w.writeheader()
        for row in solution:
            w.writerow(row)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sessions", default="sessions.csv")
    ap.add_argument("--aules", default="aules.csv")
    ap.add_argument("--calendari", default="calendari.csv")
    ap.add_argument("--out", default="proposta.csv")
    ap.add_argument("--time-limit", type=float, default=300.0)
    args = ap.parse_args()

    blocked_full, blocked_intervals = load_calendar(args.calendari)
    rooms, room_info, room_index, external_indices = load_rooms(args.aules)
    sessions = load_sessions(args.sessions)

    last_status = None

    for level in range(5):
        print(f"Provant nivell de relaxació {level}...", file=sys.stderr)
        solution, status, obj = build_and_solve(
            level=level,
            sessions=sessions,
            rooms=rooms,
            room_info=room_info,
            room_index=room_index,
            external_indices=external_indices,
            blocked_full=blocked_full,
            blocked_intervals=blocked_intervals,
            time_limit=args.time_limit,
        )
        last_status = status

        if solution is not None:
            write_solution(args.out, solution)
            print(
                f"Solució trobada al nivell {level}. "
                f"Estat={status}, objectiu={obj}. "
                f"Fitxer: {args.out}",
                file=sys.stderr,
            )
            return 0

        print(f"Nivell {level}: estat {status}", file=sys.stderr)

    print(
        f"No s'ha trobat solució ni amb relaxació. Darrer estat: {last_status}",
        file=sys.stderr,
    )
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
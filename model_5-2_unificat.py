#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
MODEL 5.2 UNIFICAT (Fase 1 torns + Fase 2 aules) -> proposta-torns.csv

Un sol script que:
  1. Carrega paquet/sessions.csv, aules.csv i proposta_partida.csv (o els del directori actual).
  2. FASE 1 (CP-SAT): mou dia i hora de les activitats mobles (per bloc d'activitats compartides)
     complint, com a restriccions DURES, tot el que l'enunciat demana:
       R1 torns (1r/2n mati; 3r, 4t, doble i master tarda; fixades no es toquen)
       R2 finestres 8.30-14.30 i 14.30-21.00 (tenint en compte la DURADA de la sessio)
       R2-CALENDARI (nomes dies amb classe a la partida, a la mateixa setmana)
       R4 docent, alumnat (mateixa cohort + teoria/practica del mateix grup) i R4-PLAB
       R7 PLAB fixats
       R8 reserva de 2 aules ordinaries lliures (condicio necessaria agregada per franja)
     Objectiu: minimitzar sessions mogudes (R9).
  3. FASE 2 (CP-SAT): assigna aula a cada sessio que en necessita (R3 tipus/aforament, R4-AULA,
     R8 reserva exacta, R6 aula base per grup i mateix passadis, pocs canvis vs la partida).
  4. Nomes si no hi ha solucio amb tot dur: relaxa, ho declara a relaxacions.csv i ho diu per pantalla.
  5. Escriu proposta-torns.csv amb el format de proposta_partida.csv: id_sessio,dia,h_ini,aula
     (dia en L/M/X/J/V, hora HH:MM, aula buida si no n'hi ha) per a TOTES les sessions del 2n semestre
     (semestre segons la DATA, >= 2027-02-01, com diu l'enunciat: 7.739 sessions).
  6. Imprimeix una comprovacio pròpia (aproximada) per regla; la definitiva es:
       python -m horaris check proposta-torns.csv --semestre 2

Us:  python model_5-2_unificat.py [--temps1 240] [--temps2 240] [--sortida proposta-torns.csv]
"""
import argparse
import os
import sys
import time
from collections import defaultdict

import numpy as np
import pandas as pd
from ortools.sat.python import cp_model

DIES = ['L', 'M', 'X', 'J', 'V']
INI_SEM2 = pd.Timestamp('2027-02-01')      # semestre per data (enunciat 8.3)
INICI_DIA, MIG_DIA, FI_DIA = 510, 870, 1260  # 08:30, 14:30, 21:00 (minuts)
MAX_ORDINARIES_OCUPADES = 19                # 21 aules docents - 2 de reserva (R8)
LABS_INTEGRATS = {'Q2/0007', 'Q2/0011', 'Q2/0013', 'Q2/0017', 'Q2/0019', 'Q3/0007'}
GRAN = 2000                                 # separacio entre dies en el temps absolut


def hm(t):
    h, m = str(t).split(':')
    return int(h) * 60 + int(m)


def fm(x):
    return f"{int(x) // 60:02d}:{int(x) % 60:02d}"


def cami(nom):
    for p in (os.path.join('paquet', nom), nom):
        if os.path.exists(p):
            return p
    raise FileNotFoundError(nom)


def solapen(d1, s1, e1, d2, s2, e2):
    return d1 == d2 and s1 < e2 and s2 < e1


def passadis(aula):
    esp, num = str(aula).split('/')
    return (esp, num[0])


# --------------------------------------------------------------------------------------
# 1. DADES
# --------------------------------------------------------------------------------------
def carrega():
    ses = pd.read_csv(cami('sessions.csv'))
    aul = pd.read_csv(cami('aules.csv'))
    par = pd.read_csv(cami('proposta_partida.csv'))
    ses['data'] = pd.to_datetime(ses['data'])
    aul['tipus'] = aul['tipus'].astype(str).str.strip()
    aul['capacitat'] = pd.to_numeric(aul['capacitat'], errors='coerce').fillna(0).astype(int)

    s2 = ses[ses['data'] >= INI_SEM2].copy()
    s2 = s2.merge(par.rename(columns={'dia': 'dia_p', 'h_ini': 'h_p', 'aula': 'aula_p'}),
                  on='id_sessio', how='left')
    s2['dow'] = s2['data'].dt.dayofweek
    s2['lunes'] = s2['data'] - pd.to_timedelta(s2['dow'], unit='D')
    s2['sense'] = s2['sense_espai'].fillna(0).astype(int) == 1
    s2['fix'] = s2['fixada'].notna() | (s2['tipus'] == 'PLAB')
    return s2, aul, par


def carrega_calendari():
    """paquet/calendari.csv: festius, no lectius i avaluacio bloquegen el dia; les aturades, nomes la franja."""
    bloq, aturades = set(), defaultdict(list)
    try:
        cal = pd.read_csv(cami('calendari.csv'))
    except FileNotFoundError:
        print("   (calendari.csv no trobat: nomes es fan servir els dies amb classe de la partida)")
        return bloq, aturades
    for _, r in cal.iterrows():
        d = pd.Timestamp(r['data'])
        if r['tipus'] == 'aturada' and pd.notna(r['h_ini']):
            aturades[d].append((hm(r['h_ini']), hm(r['h_fi'])))
        else:
            bloq.add(d)
    return bloq, aturades


def construeix_blocs(s2, aul):
    """Activitats (mateix grup/dia/hora cada setmana) i blocs (activitats compartides = una sola classe)."""
    acts = {}
    for aid, g in s2.groupby('activitat_id', sort=False):
        r = g.iloc[0]
        aules_g = g['aula_p'].dropna()
        acts[aid] = dict(
            id=aid, codi=r['codi'], tipus=r['tipus'], grup=str(r['grup']),
            coh=[t for t in str(r['titulacions_curs']).split('|')] if pd.notna(r['titulacions_curs']) else [],
            doc=[t for t in str(r['docents']).split('|')] if pd.notna(r['docents']) else [],
            alum=int(g['alumnes'].max()), sense=bool(r['sense']), fix=bool(g['fix'].any()),
            torn=r['torn_requerit'], dia0=DIES.index(r['dia_p']), h0=hm(r['h_p']),
            dur=int(r['durada_min']), aula0=(aules_g.mode().iloc[0] if len(aules_g) else None),
            weeks=set(g['lunes']), n=len(g), sess=list(g['id_sessio']))

    # unio d'activitats compartides
    pare = {a: a for a in acts}

    def troba(a):
        while pare[a] != a:
            pare[a] = pare[pare[a]]
            a = pare[a]
        return a

    comp = s2[s2['id_compartida'].notna()].groupby('id_compartida')['activitat_id'].unique()
    for lst in comp:
        for a in lst[1:]:
            pare[troba(a)] = troba(lst[0])
    grups = defaultdict(list)
    for a in acts:
        grups[troba(a)].append(a)

    aules_set = set(aul['aula'])
    blocs = []
    for k, membres in grups.items():
        ms = [acts[a] for a in membres]
        fixos = [m for m in ms if m['fix']]
        ref = fixos[0] if fixos else ms[0]
        b = dict(ms=ms, fix=bool(fixos), dia0=ref['dia0'], h0=ref['h0'],
                 dur=max(m['dur'] for m in ms), n=sum(m['n'] for m in ms),
                 weeks=set().union(*[m['weeks'] for m in ms]),
                 docs=set(d for m in ms for d in m['doc']),
                 plab=all(m['tipus'] == 'PLAB' for m in ms))
        t_m = sum(m['n'] for m in ms if m['torn'] == 'mati')
        t_t = sum(m['n'] for m in ms if m['torn'] == 'tarda')
        b['torn'] = 'mati' if t_m >= t_t else 'tarda'
        espai = [m for m in ms if not m['sense'] and m['tipus'] != 'PLAB']
        aula0s = [m['aula0'] for m in ms if m['aula0']]
        b['aula0'] = aula0s[0] if aula0s else None
        b['fora'] = None
        b['rooms'] = []
        b['needs_room'] = False
        if espai and not b['plab']:
            if b['aula0'] and b['aula0'] not in aules_set:
                b['fora'] = b['aula0']              # B3/0021, QC/1082...: es queden on son
            else:
                b['needs_room'] = True
        b['alum'] = sum(m['alum'] for m in espai)
        b['pau'] = bool(espai) and all(m['tipus'] == 'PAUL' for m in espai)
        b['grupkey'] = (ms[0]['codi'], ms[0]['grup'])
        # aula que no es pot tocar: una sessio FIXADA que ja te aula a la partida la manté (R1-FIXADA);
        # un PLAB manté la seva (R7) i, si es una aula docent/seminari, ocupa aquell espai (R4-AULA / R8)
        b['occ'] = None
        if b['aula0'] in aules_set and (b['plab'] or (b['fix'] and b['needs_room'])):
            b['occ'] = b['aula0']
        blocs.append(b)
    return acts, blocs


def aules_permeses(b, aul):
    """R3-TIPUS i R3-AFORAMENT. Teoria/seminari: aula docent o seminari. PAUL: a mes, labs integrats i informatica."""
    out = []
    for _, r in aul.iterrows():
        ok = r['tipus'] in ('Aules docents', 'Seminaris')
        if b['pau'] and (r['aula'] in LABS_INTEGRATS or r['tipus'] == 'Aules informàtiques'):
            ok = True
        if ok and r['capacitat'] >= b['alum']:
            out.append(r['aula'])
    return out


# --------------------------------------------------------------------------------------
# 2. FASE 1: DIA I HORA
# --------------------------------------------------------------------------------------
def finestra_ok(s, dur, torn):
    if torn == 'mati':
        return INICI_DIA <= s < MIG_DIA and s + dur <= MIG_DIA
    return s >= MIG_DIA and s + dur <= FI_DIA


def fase1(blocs, aul, dates_valides, temps, permet_excepcions_torn, cal_bloq=frozenset(), cal_aturades=None, extra=None):
    cal_aturades = cal_aturades or {}
    extra = extra or {}
    n_b = len(blocs)
    aul_ord = aul[aul['tipus'] == 'Aules docents']
    caps_ord = sorted(aul_ord['capacitat'].tolist())
    n_noord = int((aul['tipus'].isin(['Seminaris'])).sum() + len(LABS_INTEGRATS) +
                  (aul['tipus'] == 'Aules informàtiques').sum())

    # ---- candidats ----
    cands = {}
    for i, b in enumerate(blocs):
        if b['fix']:
            cands[i] = [(b['dia0'], b['h0'], 0)]
            continue
        cs = {}
        torns = [b['torn']] + ([('tarda' if b['torn'] == 'mati' else 'mati')] if permet_excepcions_torn else [])
        for t_idx, torn in enumerate(torns):
            hores = range(INICI_DIA, MIG_DIA, 60) if torn == 'mati' else range(MIG_DIA, FI_DIA, 30)
            for d in range(5):
                dates = [w + pd.Timedelta(days=d) for w in b['weeks']]
                mateix_dia = (d == b['dia0'])
                # el mateix dia no es mira si es festiu/avaluacio (la partida ja hi te classe: es el dia d'origen);
                # un dia nou ha de ser lectiu i no pot ser festiu, no lectiu ni setmana d'avaluacio (R2-CALENDARI)
                if not mateix_dia and any(dt_ not in dates_valides or dt_ in cal_bloq for dt_ in dates):
                    continue
                for s in hores:
                    if any(s < bb and s + b['dur'] > aa for dt_ in dates for aa, bb in cal_aturades.get(dt_, ())
                           if not (mateix_dia and b['h0'] < bb and b['h0'] + b['dur'] > aa)):
                        continue                          # R2-CALENDARI: aturada (Comunitaria, Activitats Campus)
                    if finestra_ok(s, b['dur'], torn):
                        cs[(d, s)] = 0 if t_idx == 0 else 1
            o = (b['dia0'], b['h0'])
            if o not in cs:
                for t_idx2, torn2 in enumerate(torns):
                    if finestra_ok(b['h0'], b['dur'], torn2):
                        cs[o] = t_idx2
                        break
        cands[i] = [(d, s, ex) for (d, s), ex in cs.items()]

    # ---- recursos (conflictes) ----
    res_doc = defaultdict(set)
    for i, b in enumerate(blocs):
        for d in b['docs']:
            res_doc[('D', d)].add(i)

    te_nums = defaultdict(set)
    for b in blocs:
        for m in b['ms']:
            if m['tipus'] == 'TE':
                te_nums[m['codi']].add(m['grup'].split('/')[-1])

    def arrel(m):
        n = m['grup'].split('/')[-1]
        if m['tipus'] == 'TE':
            return n
        if n in te_nums[m['codi']]:
            return n
        if len(n) > 1 and n[:-1] in te_nums[m['codi']]:
            return n[:-1]
        return n

    subs = defaultdict(set)
    for b in blocs:
        for m in b['ms']:
            if m['tipus'] in ('PAUL', 'SEM'):
                for c in m['coh']:
                    subs[(c, arrel(m))].add(m['grup'].split('/')[-1])
    res_alu = defaultdict(set)
    for i, b in enumerate(blocs):
        for m in b['ms']:
            if m['tipus'] == 'PLAB':
                continue
            for c in m['coh']:
                r = arrel(m)
                if m['tipus'] == 'TE':
                    for s in (subs[(c, r)] | {'TE'}):
                        res_alu[(c, r, s)].add(i)
                else:
                    res_alu[(c, r, m['grup'].split('/')[-1])].add(i)

    plab_per_codi = defaultdict(list)
    for i, b in enumerate(blocs):
        if b['plab']:
            for m in b['ms']:
                plab_per_codi[m['codi']].append(i)

    parelles = set()
    for r in list(res_doc.values()) + list(res_alu.values()):
        l = sorted(r)
        for x in range(len(l)):
            for y in range(x + 1, len(l)):
                if blocs[l[x]]['weeks'] & blocs[l[y]]['weeks']:
                    parelles.add((l[x], l[y]))

    def interv(i, c):
        return c[0], c[1], c[1] + blocs[i]['dur']

    # ---- prohibicions contra blocs fixats i contra PLAB ----
    prohibit = defaultdict(set)
    mm_parelles = []
    for (i, j) in parelles:
        bi, bj = blocs[i], blocs[j]
        if bi['fix'] and bj['fix']:
            continue                                    # heretat
        if bi['fix'] != bj['fix']:
            f, m = (i, j) if bi['fix'] else (j, i)
            fb = blocs[f]
            for c in cands[m]:
                orig = (c[0], c[1]) == (blocs[m]['dia0'], blocs[m]['h0'])
                if solapen(*interv(m, c), fb['dia0'], fb['h0'], fb['h0'] + fb['dur']):
                    herencia = orig and solapen(blocs[m]['dia0'], blocs[m]['h0'], blocs[m]['h0'] + blocs[m]['dur'],
                                                fb['dia0'], fb['h0'], fb['h0'] + fb['dur'])
                    if not herencia:
                        prohibit[m].add((c[0], c[1]))
        else:
            mm_parelles.append((i, j))
    for i, b in enumerate(blocs):
        if b['fix'] or b['plab']:
            continue
        for m in b['ms']:
            for p in plab_per_codi.get(m['codi'], []):
                pb = blocs[p]
                if not (pb['weeks'] & b['weeks']):
                    continue
                for c in cands[i]:
                    if (c[0], c[1]) == (b['dia0'], b['h0']):
                        continue
                    if solapen(*interv(i, c), pb['dia0'], pb['h0'], pb['h0'] + pb['dur']):
                        prohibit[i].add((c[0], c[1]))
    for i in range(n_b):
        if extra.get(i):
            mes = [c for c in cands[i] if (c[0], c[1]) not in extra[i]]
            if mes:
                prohibit[i] |= set(extra[i])
        if prohibit[i]:
            cands[i] = [c for c in cands[i] if (c[0], c[1]) not in prohibit[i]]
        if not cands[i]:
            print(f"   ! bloc {blocs[i]['ms'][0]['id']} sense cap candidat possible")
            return None, 'SENSE_CANDIDATS'

    # ---- model ----
    model = cp_model.CpModel()
    x = {}
    for i, b in enumerate(blocs):
        lst = []
        for c in cands[i]:
            x[(i, c[0], c[1])] = model.NewBoolVar(f"x{i}_{c[0]}_{c[1]}")
            lst.append(x[(i, c[0], c[1])])
        model.AddExactlyOne(lst)

    tvar, iv = {}, {}
    def get_t(i):
        if i not in tvar:
            ab = [c[0] * GRAN + c[1] for c in cands[i]]
            t = model.NewIntVar(min(ab), max(ab), f"t{i}")
            model.Add(t == sum(x[(i, c[0], c[1])] * (c[0] * GRAN + c[1]) for c in cands[i]))
            tvar[i] = t
        return tvar[i]

    for (i, j) in mm_parelles:
        ti, tj = get_t(i), get_t(j)
        oi = (blocs[i]['dia0'], blocs[i]['h0'], blocs[i]['dur'])
        oj = (blocs[j]['dia0'], blocs[j]['h0'], blocs[j]['dur'])
        heretat = solapen(oi[0], oi[1], oi[1] + oi[2], oj[0], oj[1], oj[1] + oj[2])
        if not heretat:
            model.AddNoOverlap([model.NewFixedSizeIntervalVar(ti, blocs[i]['dur'], ''),
                                model.NewFixedSizeIntervalVar(tj, blocs[j]['dur'], '')])
        else:
            # solapament heretat de la partida: poden tornar a coincidir NOMES si es mouen junts
            # (mateix dia i mateixa hora d'inici); en qualsevol altre cas no es poden solapar
            same = model.NewBoolVar('')
            model.Add(ti == tj).OnlyEnforceIf(same)
            model.Add(ti != tj).OnlyEnforceIf(same.Not())
            model.AddNoOverlap([model.NewOptionalFixedSizeIntervalVar(ti, blocs[i]['dur'], same.Not(), ''),
                                model.NewOptionalFixedSizeIntervalVar(tj, blocs[j]['dur'], same.Not(), '')])

    # ---- R8 agregat: capacitat d'aules per franja ----
    cap_aula = dict(zip(aul['aula'], aul['capacitat']))
    ord_set = set(aul_ord['aula'])
    for b in blocs:
        b['rooms'] = []
    must_ord, dem_alum = {}, {}
    for i, b in enumerate(blocs):
        if b['occ'] and b['occ'] in cap_aula and (not b['plab'] or aul.set_index('aula').loc[b['occ'], 'tipus'] in ('Aules docents', 'Seminaris')):
            must_ord[i] = b['occ'] in ord_set
            dem_alum[i] = cap_aula[b['occ']]
        elif b['needs_room']:
            b['rooms'] = aules_permeses(b, aul)
            must_ord[i] = not any(r not in ord_set for r in b['rooms'])
            dem_alum[i] = b['alum']
    ocup_const = defaultdict(list)
    ocup_var = defaultdict(list)
    for i, b in enumerate(blocs):
        if i not in dem_alum:
            continue
        for c in cands[i]:
            u0 = (c[1] - 480) // 15
            u1 = -(-(c[1] + b['dur'] - 480) // 15)
            for u in range(u0, u1):
                if b['fix']:
                    ocup_const[(c[0], u)].append(i)
                else:
                    ocup_var[(c[0], u)].append((x[(i, c[0], c[1])], i))
    thr = [0] + sorted(set(caps_ord))
    n_cons = 0
    for key in set(ocup_var) | set(ocup_const):
        cons = ocup_const.get(key, [])
        var = ocup_var.get(key, [])
        if not var:
            continue
        for xx in thr:
            lim = sum(1 for cc in caps_ord if cc > xx)
            if xx == 0:
                lim = min(lim, MAX_ORDINARIES_OCUPADES)
            k = sum(1 for i in cons if must_ord[i] and dem_alum[i] > xx)
            terms = [v for v, i in var if must_ord[i] and dem_alum[i] > xx]
            if terms:
                model.Add(sum(terms) <= max(lim, k) - k)
                n_cons += 1
        k = len(cons)
        model.Add(sum(v for v, i in var) <= max(MAX_ORDINARIES_OCUPADES + n_noord, k) - k)

    # ---- objectiu: minimitzar canvis (R9) ----
    obj = []
    for i, b in enumerate(blocs):
        if b['fix']:
            continue
        for c in cands[i]:
            if (c[0], c[1]) == (b['dia0'], b['h0']):
                cost = 0 if c[2] == 0 else 5000 * b['n']
            else:
                cost = b['n'] * (10 + 4 * (c[0] != b['dia0'])) + abs(c[1] - b['h0']) // 30
                cost += 5000 * b['n'] * c[2]
            if cost:
                obj.append(cost * x[(i, c[0], c[1])])
            if (c[0], c[1]) == (b['dia0'], b['h0']):
                model.AddHint(x[(i, c[0], c[1])], 1)
    model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = temps
    solver.parameters.num_workers = 8
    solver.parameters.log_search_progress = False
    st = solver.Solve(model)
    nom = solver.StatusName(st)
    print(f"   Fase 1 estat: {nom}  objectiu={solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else '-'}")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, nom
    sol = {}
    for i, b in enumerate(blocs):
        for c in cands[i]:
            if solver.Value(x[(i, c[0], c[1])]):
                sol[i] = (c[0], c[1], c[2])
    return sol, nom


# --------------------------------------------------------------------------------------
# 3. FASE 2: AULES
# --------------------------------------------------------------------------------------
def fase2(blocs, sol, aul, temps, permet_sense_aula):
    cap = dict(zip(aul['aula'], aul['capacitat']))
    ordinaria = set(aul[aul['tipus'] == 'Aules docents']['aula'])
    model = cp_model.CpModel()
    y, slack = {}, {}
    ivs_room = defaultdict(list)
    ivs_ord = []
    # ocupacions que no es poden tocar: PLAB amb aula docent/seminari i fixades que ja tenien aula
    fixes = []                      # (aula, dia, inici, durada)
    for i, b in enumerate(blocs):
        if b['occ'] and (b['plab'] or b['needs_room']):
            fixes.append((b['occ'], sol[i][0], sol[i][1], b['dur']))
    ocupades = defaultdict(list)
    for r, d, s_, du in fixes:
        ocupades[r].append((d, s_, s_ + du))
        if r in ordinaria:
            ivs_ord.append(model.NewFixedSizeIntervalVar(d * GRAN + s_, du, ''))
    idx = [i for i, b in enumerate(blocs) if b['needs_room'] and not b['occ']]
    for i in idx:
        b = blocs[i]
        d, s, _ = sol[i]
        rooms = [r for r in (b['rooms'] or aules_permeses(b, aul))
                 if not any(solapen(d, s, s + b['dur'], dd, ss, ee) for dd, ss, ee in ocupades.get(r, ()))]
        lst = []
        for r in rooms:
            y[(i, r)] = model.NewBoolVar(f"y{i}_{r}")
            lst.append(y[(i, r)])
            itv = model.NewOptionalFixedSizeIntervalVar(d * GRAN + s, b['dur'], y[(i, r)], '')
            ivs_room[r].append(itv)
            if r in ordinaria:
                ivs_ord.append(itv)
        b['rooms2'] = rooms
        if permet_sense_aula:
            slack[i] = model.NewBoolVar(f"sl{i}")
            lst.append(slack[i])
        if not lst:
            return None, 'SENSE_AULES_PERMESES'
        model.AddExactlyOne(lst)
    for r, l in ivs_room.items():
        model.AddNoOverlap(l)
    model.AddCumulative(ivs_ord, [1] * len(ivs_ord), MAX_ORDINARIES_OCUPADES)

    # R6: aula base per grup + mateix passadis per familia
    obj = []
    per_grup = defaultdict(list)
    per_fam = defaultdict(list)
    for i in idx:
        per_grup[blocs[i]['grupkey']].append(i)
        g = blocs[i]['ms'][0]['grup'].split('/')[-1]
        per_fam[(blocs[i]['ms'][0]['codi'], g[:-1] if blocs[i]['ms'][0]['tipus'] != 'TE' and len(g) > 1 else g)].append(i)
    for gk, l in per_grup.items():
        if len(l) < 2:
            continue
        rs = sorted(set(r for i in l for (j, r) in y if j == i)) if False else sorted({r for i in l for r in blocs[i]['rooms2']})
        base = {r: model.NewBoolVar('') for r in rs}
        model.AddExactlyOne(list(base.values()))
        for i in l:
            dev = model.NewBoolVar('')
            for r in blocs[i]['rooms2']:
                if (i, r) in y:
                    model.Add(y[(i, r)] <= base[r] + dev)
            obj.append(10 * blocs[i]['n'] * dev)
    for fk, l in per_fam.items():
        if len(l) < 2:
            continue
        pas = sorted({passadis(r) for i in l for r in blocs[i]['rooms2']})
        fb = {p: model.NewBoolVar('') for p in pas}
        model.AddExactlyOne(list(fb.values()))
        for i in l:
            dev = model.NewBoolVar('')
            for r in blocs[i]['rooms2']:
                if (i, r) in y:
                    model.Add(y[(i, r)] <= fb[passadis(r)] + dev)
            obj.append(6 * blocs[i]['n'] * dev)
    # canvis respecte de l'aula d'avui + ajust de mida
    for i in idx:
        b = blocs[i]
        for r in blocs[i]['rooms2']:
            if (i, r) not in y:
                continue
            c = 0
            if b['aula0'] and r != b['aula0']:
                c += 3 * b['n']
            c += (cap[r] - b['alum']) // 10
            if c:
                obj.append(c * y[(i, r)])
            if b['aula0'] == r:
                model.AddHint(y[(i, r)], 1)
        if i in slack:
            obj.append(100000 * b['n'] * slack[i])
    model.Minimize(sum(obj))

    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = temps
    solver.parameters.num_workers = 8
    st = solver.Solve(model)
    nom = solver.StatusName(st)
    print(f"   Fase 2 estat: {nom}  objectiu={solver.ObjectiveValue() if st in (cp_model.OPTIMAL, cp_model.FEASIBLE) else '-'}")
    if st not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, nom
    aula = {i: b['occ'] for i, b in enumerate(blocs) if b['occ'] and b['needs_room'] and not b['plab']}
    for i in idx:
        aula[i] = ''
        for r in blocs[i]['rooms2']:
            if (i, r) in y and solver.Value(y[(i, r)]):
                aula[i] = r
    return aula, nom


# --------------------------------------------------------------------------------------
# 4. COMPROVACIO PROPIA (aproximada; la definitiva es el verificador oficial)
# --------------------------------------------------------------------------------------
def comprova(final, s2, aul, blocs, acts, dates_valides):
    f = final.merge(s2[['id_sessio', 'activitat_id', 'data', 'dow', 'lunes', 'durada_min', 'alumnes', 'tipus',
                        'torn_requerit', 'docents', 'sense', 'fix', 'dia_p', 'h_p']], on='id_sessio')
    blk = {}
    for i, b in enumerate(blocs):
        for m in b['ms']:
            blk[m['id']] = i
    f['blk'] = f['activitat_id'].map(blk)
    f['d'] = f['dia'].map({d: k for k, d in enumerate(DIES)})
    f['ndata'] = f['lunes'] + pd.to_timedelta(f['d'], unit='D')
    f['ini'] = f['h_ini'].map(hm)
    f['fi'] = f['ini'] + f['durada_min']
    mati = f['ini'] < MIG_DIA
    r1 = int(((mati & (f['torn_requerit'] == 'tarda')) | (~mati & (f['torn_requerit'] == 'mati'))).sum())
    r1_fix = int((f['fix'] & ((mati & (f['torn_requerit'] == 'tarda')) | (~mati & (f['torn_requerit'] == 'mati')))).sum())
    r2 = int((((f['ini'] < MIG_DIA) & (f['fi'] > MIG_DIA)) | (f['fi'] > FI_DIA) | (f['ini'] < INICI_DIA)).sum())
    r2c = int((~f['ndata'].isin(dates_valides)).sum())
    cap = dict(zip(aul['aula'], aul['capacitat']))
    ordin = set(aul[aul['tipus'] == 'Aules docents']['aula'])
    amb_aula = f[(f['aula'] != '') & f['aula'].isin(cap) & ~f['sense']]
    r3a = int((amb_aula.apply(lambda r: cap[r['aula']] < r['alumnes'], axis=1)).sum()) if len(amb_aula) else 0
    r3t = 0
    for _, r in amb_aula.iterrows():
        b = blocs[r['blk']]
        if r['tipus'] != 'PLAB' and r['aula'] not in aules_permeses({**b, 'alum': 0}, aul):
            r3t += 1
    necessita = f['blk'].map(lambda i: blocs[i]['needs_room']) & ~f['sense']
    r5 = int((necessita & (f['aula'] == '')).sum())

    def solapaments(df, clau):
        d = df.drop_duplicates(clau + ['blk']).sort_values(clau + ['ini'])
        d['mx'] = d.groupby(clau)['fi'].cummax().groupby([d[c] for c in clau]).shift()
        return int((d['ini'] < d['mx']).sum())

    r4a = solapaments(amb_aula.assign(), ['ndata', 'aula'])
    dd = f[f['docents'].notna()].assign(doc=lambda t: t['docents'].str.split('|')).explode('doc')
    r4d = solapaments(dd, ['ndata', 'doc'])
    base = dd.assign(ndata=dd['data'], ini=dd['h_p'].map(hm))
    base['fi'] = base['ini'] + base['durada_min']
    r4d_base = solapaments(base, ['ndata', 'doc'])
    # R8 per franja horaria
    r8 = 0
    oc = f[f['aula'].isin(ordin)].drop_duplicates(['blk', 'ndata'])
    for h in range(510, 1260, 60):
        e = oc[(oc['ini'] < h + 60) & (oc['fi'] > h)]
        c = e.groupby('ndata')['aula'].nunique()
        r8 += int((c > MAX_ORDINARIES_OCUPADES).sum())
    mogudes = int(((f['dia'] != f['dia_p']) | (f['h_ini'] != f['h_p'])).sum())
    print("\n=== COMPROVACIO PROPIA (aproximada) ===")
    print(f"  sessions al fitxer ............ {len(f)} (7739 esperades)")
    print(f"  R1-TORN (sessions) ............ {r1}   (de les quals fixades/heretades: {r1_fix})")
    print(f"  R2-FINESTRA ................... {r2}")
    print(f"  R2-CALENDARI (dia sense classe) {r2c}")
    print(f"  R3-AFORAMENT .................. {r3a}")
    print(f"  R3-TIPUS ...................... {r3t}")
    print(f"  R4-AULA (sessions, inclou heretats) {r4a}")
    print(f"  R4-DOCENT (sessions) .......... {r4d}   (a la partida ja n'hi havia {r4d_base}: heretats)")
    print(f"  R5-SENSE-AULA ................. {r5}")
    print(f"  R8-RESERVA (dates/franges) .... {r8}")
    print(f"  Sessions amb dia/hora canviat . {mogudes}")
    return f


def relaxacions_heretades(out, s2, blocs, aul):
    """Incompliments que el verificador NO considera heretats perque la proposta hi ha posat aula
    (sessions FIXADES que no en tenien) o perque l'aula d'una fixada no es pot canviar (R1-FIXADA).
    S'han de declarar: no es poden evitar sense moure o deixar sense aula una sessio fixada."""
    cap = dict(zip(aul['aula'], aul['capacitat']))
    o = out.set_index('id_sessio')
    info = s2.set_index('id_sessio')
    r1, r2, r3 = [], [], []
    for b in blocs:
        if not b['fix'] or b['plab']:
            continue
        for m in b['ms']:
            if m['sense'] or m['tipus'] == 'PLAB':
                continue
            for sid in m['sess']:
                orig_aula = info.at[sid, 'aula_p']
                nova = o.at[sid, 'aula']
                if nova and pd.isna(orig_aula):
                    ini = hm(o.at[sid, 'h_ini'])
                    fi = ini + int(info.at[sid, 'durada_min'])
                    t = info.at[sid, 'torn_requerit']
                    if (ini < MIG_DIA) != (t == 'mati'):
                        r1.append(sid)
                    if not ((INICI_DIA <= ini and fi <= MIG_DIA) or (MIG_DIA <= ini and fi <= FI_DIA)):
                        r2.append(sid)
        if b['occ'] and b['needs_room'] and b['alum'] > cap[b['occ']]:
            r3 += [sid for m in b['ms'] if not m['sense'] for sid in m['sess']]
    out_r = []
    if r1:
        out_r.append(('R1-TORN', r1, "Sessio FIXADA (R1-FIXADA: GEI i GEET+GEST de 1r i 2n no es toquen) amb torn requerit "
                      "diferent del seu horari (grup de doble titulacio compartit amb un grup de l'altre torn). Heretat "
                      "de la partida; nomes cal declarar-lo perque li hem hagut d'assignar aula (R5)."))
    if r2:
        out_r.append(('R2-FINESTRA', r2, "Sessio FIXADA que ja creuava les 14.30 a la partida; no es pot moure (R1-FIXADA) "
                      "i se li ha hagut d'assignar aula (R5)."))
    if r3:
        out_r.append(('R3-AFORAMENT', r3, "Sessio FIXADA a una aula amb menys places que alumnes; l'aula d'una fixada no es "
                      "pot canviar (R1-FIXADA) i no hi ha cap manera de resoldre-ho sense tocar-la."))
    return out_r


def executa_verificador(fitxer, amb_relax):
    """Si el paquet 'horaris' es al costat, passa el verificador oficial i en mostra el resum."""
    if not os.path.isdir('horaris'):
        return
    import subprocess
    cmd = [sys.executable, '-m', 'horaris', 'check', fitxer, '--semestre', '2',
           '--json', 'informe.json', '--violacions', 'violacions.csv']
    if amb_relax:
        cmd += ['--relaxacions', 'relaxacions.csv']
    print("\n=== VERIFICADOR OFICIAL ===")
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8', timeout=600,
                           env={**os.environ, 'PYTHONUTF8': '1'})
        print((r.stdout or '')[-3000:] + (r.stderr or '')[-1500:])
    except Exception as e:                                   # no ha d'impedir haver generat el CSV
        print(f"   (no s'ha pogut executar el verificador: {e})")


def hores_mortes(blocs, tempsfn):
    """Indicador R9: hores mortes per familia (cohort+arrel de grup) i dia, en hores."""
    fam = defaultdict(set)
    for i, b in enumerate(blocs):
        for m in b['ms']:
            if m['tipus'] == 'PLAB':
                continue
            n = m['grup'].split('/')[-1]
            for c in m['coh']:
                fam[(c, n if m['tipus'] == 'TE' else n[:-1] if len(n) > 1 else n)].add(i)
    tot = 0.0
    for k, l in fam.items():
        per_dia = defaultdict(list)
        for i in l:
            d, s = tempsfn(i)
            per_dia[d].append((s, s + blocs[i]['dur']))
        for d, iv in per_dia.items():
            iv.sort()
            fi = iv[0][1]
            for s, e in iv[1:]:
                if s > fi:
                    tot += (s - fi) / 60
                fi = max(fi, e)
    return tot


# --------------------------------------------------------------------------------------
def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--temps1', type=float, default=240.0, help="segons per a la fase 1")
    ap.add_argument('--temps2', type=float, default=240.0, help="segons per a la fase 2")
    ap.add_argument('--sortida', default='proposta-torns.csv')
    ap.add_argument('--nomes-comprova', action='store_true', help="nomes comprova un CSV ja generat")
    a = ap.parse_args()
    t0 = time.time()
    if a.nomes_comprova:
        s2, aul, par = carrega()
        dv = {pd.Timestamp(d) for d in s2['data'].unique()}
        acts, blocs = construeix_blocs(s2, aul)
        for b in blocs:
            if b['needs_room']:
                b['rooms'] = aules_permeses(b, aul)
        comprova(pd.read_csv(a.sortida, keep_default_na=False), s2, aul, blocs, acts, dv)
        return
    print("--- MODEL 5.2 UNIFICAT: torns (fase 1) + aules (fase 2) ---")

    s2, aul, par = carrega()
    assert (s2['dia_p'] == s2['dow'].map(lambda k: DIES[k])).all(), "dies de la partida incoherents amb la data"
    dates_valides = set(s2['data'].unique())
    dates_valides = {pd.Timestamp(d) for d in dates_valides}
    cal_bloq, cal_at = carrega_calendari()
    acts, blocs = construeix_blocs(s2, aul)
    print(f"Sessions 2n semestre (per data): {len(s2)} | activitats: {len(acts)} | blocs (compartides unides): {len(blocs)}")
    print(f"Blocs fixats: {sum(b['fix'] for b in blocs)} | mobles: {sum(not b['fix'] for b in blocs)}")

    # Bucle fase 1 -> fase 2: si no hi cap aula per a alguna sessio mobil, es prohibeix la seva franja i es torna a
    # fer la fase 1 (la fase 1 nomes coneix una condicio necessaria agregada de capacitat d'aules).
    extra = defaultdict(set)
    for ronda in range(1, 5):
        relaxacions = []
        print(f"\nFASE 1 (ronda {ronda}): dia i hora (tot dur: R1 torns, R2, calendari, R4, R7, R8)...")
        sol, est = fase1(blocs, aul, dates_valides, a.temps1, False, cal_bloq, cal_at, extra)
        if sol is None:
            print("   No hi ha solucio amb R1 dura. Provo permetent excepcions a R1 (es declararan)...")
            sol, est = fase1(blocs, aul, dates_valides, a.temps1, True, cal_bloq, cal_at, extra)
        if sol is None:
            print("   !! Sense solucio a la fase 1 (estat: %s). Es mantenen dia/hora de la partida." % est)
            sol = {i: (b_['dia0'], b_['h0'], 0) for i, b_ in enumerate(blocs)}
        else:
            for i, b_ in enumerate(blocs):
                if sol[i][2] == 1:
                    relaxacions.append(('R1-TORN', [sid for m in b_['ms'] for sid in m['sess']],
                                        "El mati no te capacitat per a aquest grup sense incomplir R4 (docent/alumnat) o R8"))
        moguts = sum(b_['n'] for i, b_ in enumerate(blocs) if (sol[i][0], sol[i][1]) != (b_['dia0'], b_['h0']))
        print(f"   Sessions mogudes de dia/hora: {moguts}")

        print(f"\nFASE 2 (ronda {ronda}): aules (R3, R4-AULA, R8 exacta, R6 aula base)...")
        for b_ in blocs:
            if b_['needs_room']:
                b_['rooms'] = aules_permeses(b_, aul)
        aula, est2 = fase2(blocs, sol, aul, a.temps2, permet_sense_aula=False)
        if aula is not None:
            break
        print("   No hi ha assignacio d'aules completa; busco quines sessions no hi caben...")
        aula, est2 = fase2(blocs, sol, aul, min(a.temps2, 90.0), permet_sense_aula=True)
        if aula is None:
            aula = {i: '' for i, b_ in enumerate(blocs) if b_['needs_room']}
            break
        sense = [i for i, r in aula.items() if r == '' and blocs[i]['needs_room']]
        movibles = [i for i in sense if not blocs[i]['fix'] and (sol[i][0], sol[i][1]) != (-1, -1)]
        print(f"   Blocs sense aula: {len(sense)} (mobles: {len(movibles)})")
        if not movibles or ronda == 4:
            for i in sense:
                relaxacions.append(('R5-SENSE-AULA', [sid for m in blocs[i]['ms'] if not m['sense'] for sid in m['sess']],
                                    "No hi ha aula del tipus i aforament adequats lliure en aquesta franja respectant R8"))
            break
        for i in movibles:
            extra[i].add((sol[i][0], sol[i][1]))

    # ---------- SORTIDA ----------
    rows = []
    for i, b in enumerate(blocs):
        d, s, _ = sol[i]
        for m in b['ms']:
            if b['plab']:
                a_ = m['aula0'] or ''
            elif m['sense'] or m['tipus'] == 'PLAB':
                a_ = m['aula0'] if m['tipus'] == 'PLAB' and m['aula0'] else ''
            elif b['fora']:
                a_ = b['fora']
            else:
                a_ = aula.get(i, '')
            for sid in m['sess']:
                rows.append({'id_sessio': sid, 'dia': DIES[d], 'h_ini': fm(s), 'aula': a_})
    out = pd.DataFrame(rows).sort_values('id_sessio')
    # PLAB: es mantenen tal qual (dia, hora i aula de la partida)
    out = out.set_index('id_sessio')
    plab_ids = s2.loc[s2['tipus'] == 'PLAB', 'id_sessio']
    pp = par.set_index('id_sessio').loc[plab_ids]
    out.loc[plab_ids, ['dia', 'h_ini']] = pp[['dia', 'h_ini']].values
    out.loc[plab_ids, 'aula'] = pp['aula'].fillna('').values
    out = out.reset_index()
    out['aula'] = out['aula'].fillna('')
    out[['id_sessio', 'dia', 'h_ini', 'aula']].to_csv(a.sortida, index=False)
    print(f"\n✅ Escrit '{a.sortida}' amb {len(out)} sessions (format: id_sessio,dia,h_ini,aula)")

    relaxacions += relaxacions_heretades(out, s2, blocs, aul)
    if relaxacions:
        rel = pd.DataFrame([{'restriccio': r, 'sessions': '|'.join(sl), 'justificacio': j} for r, sl, j in relaxacions])
        rel = rel.groupby(['restriccio', 'justificacio'], as_index=False)['sessions'].agg(lambda v: '|'.join(v))
        rel[['restriccio', 'sessions', 'justificacio']].to_csv('relaxacions.csv', index=False)
        print(f"⚠️  S'han hagut de relaxar regles: escrit 'relaxacions.csv' ({len(relaxacions)} blocs)")
    else:
        if os.path.exists('relaxacions.csv'):
            os.remove('relaxacions.csv')      # evita deixar un fitxer d'una execucio anterior
        print("✔  Cap relaxacio necessaria: totes les restriccions modelades s'han complert com a dures.")

    comprova(out, s2, aul, blocs, acts, dates_valides)
    executa_verificador(a.sortida, bool(relaxacions))
    h_ant = hores_mortes(blocs, lambda i: (blocs[i]['dia0'], blocs[i]['h0']))
    h_nou = hores_mortes(blocs, lambda i: (sol[i][0], sol[i][1]))
    print(f"  Hores mortes (indicador, setmana tipus): partida {h_ant:.0f} h -> proposta {h_nou:.0f} h")
    print(f"\nTemps total: {time.time() - t0:.0f} s")
    print("▶  Verificador oficial:  python -m horaris check proposta-torns.csv --semestre 2"
          + ("  --relaxacions relaxacions.csv" if relaxacions else ""))


if __name__ == '__main__':
    main()

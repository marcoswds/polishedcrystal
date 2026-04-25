#!/usr/bin/env python3
from __future__ import annotations

import argparse
import functools
import re
from dataclasses import dataclass
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
SQL_DIR = ROOT / "sql"

# When False, strip `if DEF(FAITHFUL)` blocks and use Polished Crystal `else` stats/data.
# Set True only if you intentionally want vanilla Faithful ROM numbers.
USE_FAITHFUL_BUILD = False


def preprocess_asm(path: Path, faithful: bool = USE_FAITHFUL_BUILD) -> list[str]:
    lines = path.read_text(encoding="utf-8").splitlines()
    out: list[str] = []
    stack: list[tuple[bool, bool]] = []
    active = True
    cond_re = re.compile(r"^\s*if\s+(!?)DEF\(FAITHFUL\)\s*$")
    for raw in lines:
        stripped = raw.strip()
        m = cond_re.match(stripped)
        if m:
            cond = faithful
            if m.group(1) == "!":
                cond = not cond
            stack.append((active, cond))
            active = active and cond
            continue
        if stripped == "else":
            if not stack:
                continue
            parent_active, cond = stack[-1]
            active = parent_active and (not cond)
            continue
        if stripped == "endc":
            if not stack:
                continue
            parent_active, _cond = stack.pop()
            active = parent_active
            continue
        if active:
            out.append(raw)
    return out


def strip_inline_comment(line: str) -> str:
    return line.split(";", 1)[0].strip()


def sql_string(value: str) -> str:
    return "'" + value.replace("\\", "\\\\").replace("'", "''") + "'"


def append_bulk_insert(
    lines: list[str],
    table: str,
    columns: list[str],
    values_sql: list[str],
    chunk_size: int = 1000,
) -> None:
    if not values_sql:
        return
    prefix = f"INSERT INTO {table} ({', '.join(columns)}) VALUES "
    for i in range(0, len(values_sql), chunk_size):
        chunk = values_sql[i : i + chunk_size]
        lines.append(prefix + ", ".join(chunk) + ";")


def humanize_code(code: str) -> str:
    parts = code.lower().split("_")
    return " ".join(p.capitalize() for p in parts if p)


def parse_rawchar_lines(path: Path) -> dict[str, str]:
    out: dict[str, str] = {}
    for line in preprocess_asm(path):
        m = re.match(r"^\s*([A-Za-z0-9_]+):\s+rawchar\s+\"(.*)\"\s*$", line)
        if not m:
            continue
        label = m.group(1)
        text = m.group(2).replace("@", "").strip()
        out[label] = text
    return out


def parse_text_blocks(path: Path) -> dict[str, str]:
    lines = preprocess_asm(path)
    descriptions: dict[str, str] = {}
    pending_labels: list[str] = []
    current_text: list[str] = []
    in_block = False

    label_re = re.compile(r"^\s*([A-Za-z0-9_]+):\s*$")
    text_re = re.compile(r'^\s*(text|next)\s+"(.*)"\s*$')

    for line in lines:
        label_m = label_re.match(line)
        if label_m:
            if in_block and current_text:
                joined = " ".join(current_text).replace("#mon", "Pokemon").strip()
                for lbl in pending_labels:
                    descriptions[lbl] = joined
                current_text = []
            pending_labels.append(label_m.group(1))
            in_block = False
            continue

        text_m = text_re.match(line)
        if text_m and pending_labels:
            current_text.append(text_m.group(2).replace("@", "").strip())
            in_block = True
            continue

        if line.strip() == "done" and pending_labels:
            joined = " ".join(current_text).replace("#mon", "Pokemon").strip()
            for lbl in pending_labels:
                descriptions[lbl] = joined
            pending_labels = []
            current_text = []
            in_block = False

    return descriptions


def parse_ability_data() -> tuple[list[str], dict[str, str], dict[str, str]]:
    names_file = DATA_DIR / "abilities" / "names.asm"
    desc_file = DATA_DIR / "abilities" / "descriptions.asm"

    order: list[str] = []
    for line in preprocess_asm(names_file):
        stripped = strip_inline_comment(line)
        if "assert_table_length" in stripped:
            break
        m = re.match(r"^\s*dw\s+([A-Za-z0-9_]+)\s*$", stripped)
        if m:
            order.append(m.group(1))

    names = parse_rawchar_lines(names_file)
    descriptions = parse_text_blocks(desc_file)
    return order, names, descriptions


def parse_move_names() -> list[str]:
    out: list[str] = []
    path = DATA_DIR / "moves" / "names.asm"
    for line in preprocess_asm(path):
        m = re.match(r'^\s*li\s+"(.*)"\s*$', strip_inline_comment(line))
        if m:
            out.append(m.group(1))
    return out


def parse_move_descriptions() -> tuple[list[str], dict[str, str]]:
    path = DATA_DIR / "moves" / "descriptions.asm"
    pointer_labels: list[str] = []
    for line in preprocess_asm(path):
        stripped = strip_inline_comment(line)
        if "assert_table_length" in stripped:
            break
        m = re.match(r"^\s*dw\s+([A-Za-z0-9_]+)\s*$", stripped)
        if m:
            pointer_labels.append(m.group(1))
    text_map = parse_text_blocks(path)
    return pointer_labels, text_map


def parse_moves() -> list[dict[str, object]]:
    moves_file = DATA_DIR / "moves" / "moves.asm"
    move_names = parse_move_names()
    pointer_labels, text_map = parse_move_descriptions()
    move_rows: list[dict[str, object]] = []

    for line in preprocess_asm(moves_file):
        stripped = strip_inline_comment(line)
        m = re.match(
            r"^\s*move\s+([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*,\s*(-?\d+)\s*,\s*([A-Z0-9_]+)\s*,\s*(-?\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*([A-Z0-9_]+)\s*$",
            stripped,
        )
        if not m:
            continue
        move_rows.append(
            {
                "code": m.group(1),
                "effect": m.group(2),
                "power": int(m.group(3)),
                "type_code": m.group(4),
                "accuracy": int(m.group(5)),
                "pp": int(m.group(6)),
                "effect_chance": int(m.group(7)),
                "category": m.group(8),
            }
        )

    if len(move_rows) != len(move_names):
        raise ValueError(f"Move code/name mismatch: {len(move_rows)} != {len(move_names)}")
    if len(move_rows) != len(pointer_labels):
        raise ValueError(f"Move code/description mismatch: {len(move_rows)} != {len(pointer_labels)}")

    for i, row in enumerate(move_rows):
        row["name"] = move_names[i]
        row["description"] = text_map.get(pointer_labels[i], "")
        if row["power"] == 0:
            row["power"] = None
        if row["accuracy"] == -1:
            row["accuracy"] = None
    return move_rows


@dataclass
class PokemonRow:
    species_code: str
    form_code: str
    name: str
    hp: int
    atk: int
    defn: int
    sat: int
    sdf: int
    spe: int
    bst: int
    evolution_form: str | None
    evolution_level: int | None
    evolution_requirement: str | None
    type1: str
    type2: str
    abilities: list[str]
    tmhm_moves: list[str]


FORM_SUFFIXES = [
    "PLAIN",
    "ALOLAN",
    "GALARIAN",
    "HISUIAN",
    "PALDEAN",
    "ARMORED",
    "BLOODMOON",
]


@functools.lru_cache(maxsize=1)
def pokemon_type_codes() -> frozenset[str]:
    """ASM identifiers that are Pokemon types (constants/type_constants.asm)."""
    path = ROOT / "constants" / "type_constants.asm"
    names: list[str] = []
    recording = False
    for raw in path.read_text(encoding="utf-8").splitlines():
        s = strip_inline_comment(raw)
        if re.match(r"^\s*const_def\b", s):
            if recording:
                break
            recording = True
            continue
        if "DEF NUM_TYPES" in s:
            break
        m = re.match(r"^\s*const\s+([A-Za-z0-9_]+)", s)
        if m and recording:
            names.append(m.group(1))
    return frozenset(names)


def parse_species_form_from_code(code: str) -> tuple[str, str]:
    for suffix in FORM_SUFFIXES:
        suffix_token = "_" + suffix
        if code.endswith(suffix_token):
            return code[: -len(suffix_token)], suffix
    return code, "PLAIN"


def parse_base_stats_file(path: Path) -> PokemonRow:
    stats = None
    type1 = None
    type2 = None
    species_code = None
    abilities: list[str] = []
    tmhm_moves: list[str] = []

    types_known = pokemon_type_codes()

    for raw in preprocess_asm(path):
        line = strip_inline_comment(raw)
        if not line:
            continue

        # Legacy layout: bst total, hp, atk, def, sat, sdf, spe
        m_bst = re.match(r"^\s*bst\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$", line)
        if m_bst:
            stats = tuple(int(m_bst.group(i)) for i in range(1, 8))
            continue

        # Current layout: db hp, atk, def, spe, sat, sdf ; total BST
        m_stats_db = re.match(
            r"^\s*db\s+(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*$",
            line,
        )
        if m_stats_db and stats is None:
            hp, atk, defn, spe, sat, sdf = (int(m_stats_db.group(i)) for i in range(1, 7))
            m_bst_comment = re.search(r";\s*(\d+)\s*BST\b", raw, re.I)
            bst = int(m_bst_comment.group(1)) if m_bst_comment else hp + atk + defn + spe + sat + sdf
            stats = (bst, hp, atk, defn, sat, sdf, spe)
            continue

        m_type = re.match(r"^\s*db\s+([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*$", line)
        if m_type and stats is not None and type1 is None:
            a, b = m_type.group(1), m_type.group(2)
            if a in types_known and b in types_known:
                type1, type2 = a, b
            continue

        m_abil = re.match(r"^\s*abilities_for\s+([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*$", line)
        if m_abil:
            species_code = m_abil.group(1)
            abilities = [m_abil.group(2), m_abil.group(3), m_abil.group(4)]
            continue

        m_tmhm = re.match(r"^\s*tmhm\s+(.+)$", line)
        if m_tmhm:
            tmhm_moves = [token.strip() for token in m_tmhm.group(1).split(",") if token.strip()]
            continue

    if not (stats and type1 and type2 and species_code):
        raise ValueError(f"Failed parsing base stats file: {path}")

    species_base, form_code = parse_species_form_from_code(species_code)
    name = humanize_code(species_base)
    if form_code != "PLAIN":
        name = f"{name} ({humanize_code(form_code)})"

    return PokemonRow(
        species_code=species_base,
        form_code=form_code,
        name=name,
        hp=stats[1],
        atk=stats[2],
        defn=stats[3],
        sat=stats[4],
        sdf=stats[5],
        spe=stats[6],
        bst=stats[0],
        evolution_form=None,
        evolution_level=None,
        evolution_requirement=None,
        type1=type1,
        type2=type2,
        abilities=abilities,
        tmhm_moves=tmhm_moves,
    )


def parse_base_stats_index() -> list[tuple[Path, str]]:
    index_file = DATA_DIR / "pokemon" / "base_stats.asm"
    includes: list[tuple[Path, str]] = []
    include_re = re.compile(r'^\s*INCLUDE\s+"([^"]+)"(?:\s*;\s*(.*))?$')
    for raw in preprocess_asm(index_file):
        m = include_re.match(raw)
        if not m:
            continue
        rel = m.group(1).replace("/", "\\")
        if "data\\pokemon\\base_stats\\" not in rel:
            continue
        comment = (m.group(2) or "").strip()
        includes.append((ROOT / Path(rel.replace("\\", "/")), comment))
    return includes


def parse_tmhm_methods() -> dict[str, str]:
    path = DATA_DIR / "moves" / "tmhm_moves.asm"
    methods: dict[str, str] = {}
    for raw in preprocess_asm(path):
        line = raw.rstrip()
        m = re.match(r"^\s*db\s+([A-Z0-9_]+)\s*(?:;\s*(.*))?$", line)
        if not m:
            continue
        move_code = m.group(1)
        if move_code == "0":
            continue
        comment = m.group(2) or ""
        method = "tutor" if "MT" in comment else "tm_hm"
        methods[move_code] = method
    return methods


def parse_type_matchups() -> dict[tuple[str, str], float]:
    path = DATA_DIR / "types" / "type_matchups.asm"
    out: dict[tuple[str, str], float] = {}
    value_map = {
        "NO_EFFECT": 0.0,
        "NOT_VERY_EFFECTIVE": 0.5,
        "SUPER_EFFECTIVE": 2.0,
    }
    for raw in preprocess_asm(path):
        line = strip_inline_comment(raw)
        if not line:
            continue
        if re.match(r"^\s*db\s+\$fe\s*$", line):
            break
        m = re.match(r"^\s*db\s+([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*,\s*([A-Z0-9_]+)\s*$", line)
        if not m:
            continue
        attacker, defender, effect = m.group(1), m.group(2), m.group(3)
        if effect in value_map:
            out[(attacker, defender)] = value_map[effect]
    return out


def relation_from_multiplier(multiplier: float) -> str:
    if multiplier == 0:
        return "Immune"
    if multiplier <= 0.25:
        return "2x resist"
    if multiplier < 1:
        return "Resist"
    if multiplier >= 4:
        return "2x super effective"
    if multiplier > 1:
        return "Super effective"
    return "Normal"


def normalize_mon_token(value: str) -> str:
    return re.sub(r"[^A-Z0-9]", "", value.upper())


def parse_levelup_moves() -> dict[str, list[tuple[int, str]]]:
    path = DATA_DIR / "pokemon" / "evos_attacks.asm"
    out: dict[str, list[tuple[int, str]]] = {}
    current = None
    for raw in preprocess_asm(path):
        line = strip_inline_comment(raw)
        if not line:
            continue
        m_mon = re.match(r"^\s*evos_attacks\s+([A-Za-z0-9_]+)\s*$", line)
        if m_mon:
            current = normalize_mon_token(m_mon.group(1))
            out.setdefault(current, [])
            continue
        m_learn = re.match(r"^\s*learnset\s+(\d+)\s*,\s*([A-Z0-9_]+)\s*$", line)
        if m_learn and current:
            out[current].append((int(m_learn.group(1)), m_learn.group(2)))
    return out


def parse_evolution_data() -> dict[str, tuple[str, int | None, str | None]]:
    path = DATA_DIR / "pokemon" / "evos_attacks.asm"
    out: dict[str, tuple[str, int | None, str | None]] = {}
    current = None
    for raw in preprocess_asm(path):
        line = strip_inline_comment(raw)
        if not line:
            continue
        m_mon = re.match(r"^\s*evos_attacks\s+([A-Za-z0-9_]+)\s*$", line)
        if m_mon:
            current = normalize_mon_token(m_mon.group(1))
            continue
        if current is None or current in out:
            continue
        m_evo = re.match(r"^\s*evo_data\s+(.+)$", line)
        if not m_evo:
            continue
        tokens = [t.strip() for t in m_evo.group(1).split(",") if t.strip()]
        if not tokens:
            continue
        method = tokens[0]
        if method == "EVOLVE_LEVEL":
            level = int(tokens[1]) if len(tokens) > 1 and tokens[1].isdigit() else None
            out[current] = ("lvl_up", level, None)
        elif method == "EVOLVE_ITEM":
            requirement = tokens[1] if len(tokens) > 1 else None
            out[current] = ("stones", None, requirement)
        else:
            requirement = ", ".join(tokens[1:]) if len(tokens) > 1 else method
            out[current] = ("others", None, requirement)
    return out


def parse_evolution_edges() -> list[tuple[str, str, str]]:
    path = DATA_DIR / "pokemon" / "evos_attacks.asm"
    out: list[tuple[str, str, str]] = []
    current = None
    for raw in preprocess_asm(path):
        line = strip_inline_comment(raw)
        if not line:
            continue
        m_mon = re.match(r"^\s*evos_attacks\s+([A-Za-z0-9_]+)\s*$", line)
        if m_mon:
            current = normalize_mon_token(m_mon.group(1))
            continue
        if current is None:
            continue
        m_evo = re.match(r"^\s*evo_data\s+(.+)$", line)
        if not m_evo:
            continue
        tokens = [t.strip() for t in m_evo.group(1).split(",") if t.strip()]
        if len(tokens) < 3:
            continue

        target_form = "PLAIN"
        last = tokens[-1]
        if last.endswith("_FORM") or last == "NO_FORM":
            target_form = "NO_FORM" if last == "NO_FORM" else last.replace("_FORM", "")
            target_species = tokens[-2]
        else:
            target_species = tokens[-1]
        out.append((current, normalize_mon_token(target_species), normalize_mon_token(target_form)))
    return out


def build_row_evolution_parents(
    pokemon_rows: list[PokemonRow], edges: list[tuple[str, str, str]]
) -> dict[tuple[str, str], set[tuple[str, str]]]:
    row_keys = {(r.species_code, r.form_code) for r in pokemon_rows}
    by_species: dict[str, list[str]] = {}
    key_by_form_token: dict[str, tuple[str, str]] = {}
    plain_by_species: dict[str, tuple[str, str]] = {}
    for r in pokemon_rows:
        by_species.setdefault(r.species_code, []).append(r.form_code)
        key_by_form_token[normalize_mon_token(f"{r.species_code}_{r.form_code}")] = (r.species_code, r.form_code)
        if r.form_code == "PLAIN":
            plain_by_species[r.species_code] = (r.species_code, r.form_code)

    parents: dict[tuple[str, str], set[tuple[str, str]]] = {k: set() for k in row_keys}

    for parent_token, target_species, target_form in edges:
        if parent_token in key_by_form_token:
            parent_candidates = [key_by_form_token[parent_token]]
        elif parent_token in plain_by_species:
            parent_candidates = [plain_by_species[parent_token]]
        elif parent_token in by_species:
            parent_candidates = [(parent_token, f) for f in by_species[parent_token]]
        else:
            parent_candidates = []

        for parent_species, parent_form in parent_candidates:
            if target_form == "NOFORM":
                child_key = (target_species, parent_form)
            else:
                child_key = (target_species, target_form or "PLAIN")
            if child_key not in row_keys:
                fallback = (target_species, "PLAIN")
                if fallback not in row_keys:
                    continue
                child_key = fallback
            parents[child_key].add((parent_species, parent_form))

    return parents


def gather_types(pokemon_rows: list[PokemonRow], move_rows: list[dict[str, object]]) -> list[tuple[str, str]]:
    codes: set[str] = set()
    for p in pokemon_rows:
        codes.add(p.type1)
        codes.add(p.type2)
    for m in move_rows:
        codes.add(str(m["type_code"]))
    ordered = sorted(codes)
    return [(c, humanize_code(c) if c != "UNKNOWN_T" else "???" ) for c in ordered]


def build_pokemon_rows() -> list[PokemonRow]:
    includes = parse_base_stats_index()
    out: list[PokemonRow] = []
    seen: dict[tuple[str, str], int] = {}
    for path, comment in includes:
        row = parse_base_stats_file(path)
        key = (row.species_code, row.form_code)
        if key in seen:
            if comment:
                row.form_code = comment.upper().replace("-", "_").replace(" ", "_")
                row.name = f"{humanize_code(row.species_code)} ({humanize_code(row.form_code)})"
            else:
                row.form_code = f"{row.form_code}_{seen[key] + 1}"
                row.name = f"{humanize_code(row.species_code)} ({row.form_code})"
            key = (row.species_code, row.form_code)
        seen[key] = seen.get(key, 0) + 1
        out.append(row)
    return out


def generate_seed_sql(output: Path) -> None:
    pokemon_rows = build_pokemon_rows()
    move_rows = parse_moves()
    ability_order, ability_names, ability_descs = parse_ability_data()
    tmhm_methods = parse_tmhm_methods()
    levelup = parse_levelup_moves()
    evolutions = parse_evolution_data()
    evolution_edges = parse_evolution_edges()
    type_matchups = parse_type_matchups()
    types = gather_types(pokemon_rows, move_rows)
    evolution_parents = build_row_evolution_parents(pokemon_rows, evolution_edges)

    type_id = {code: idx + 1 for idx, (code, _name) in enumerate(types)}

    lines: list[str] = []
    lines.append("USE pokemon_db;")
    lines.append("SET FOREIGN_KEY_CHECKS = 0;")
    lines.append("START TRANSACTION;")
    lines.append("")
    for table in ["pokemon_moves", "pokemon_abilities", "pokemon", "moves", "type_defensive_relations", "abilities", "types"]:
        lines.append(f"TRUNCATE TABLE {table};")
    lines.append("")

    type_values: list[str] = []
    for idx, (code, name) in enumerate(types, start=1):
        type_values.append(f"({idx}, {sql_string(code)}, {sql_string(name)})")
    append_bulk_insert(lines, "types", ["id", "code", "name"], type_values, chunk_size=500)
    lines.append("")

    type_codes = [code for code, _name in types]
    type_def_rel_values: list[str] = []
    for i, type1 in enumerate(type_codes):
        # Single-type defensive profile.
        for atk in type_codes:
            m1 = type_matchups.get((atk, type1), 1.0)
            relation = relation_from_multiplier(m1)
            type_def_rel_values.append(f"({type_id[type1]}, NULL, {type_id[atk]}, {sql_string(relation)})")

        # Dual-type defensive profile (unordered pairs).
        for j in range(i + 1, len(type_codes)):
            type2 = type_codes[j]
            for atk in type_codes:
                m1 = type_matchups.get((atk, type1), 1.0)
                m2 = type_matchups.get((atk, type2), 1.0)
                relation = relation_from_multiplier(m1 * m2)
                type_def_rel_values.append(
                    f"({type_id[type1]}, {type_id[type2]}, {type_id[atk]}, {sql_string(relation)})"
                )
    append_bulk_insert(
        lines,
        "type_defensive_relations",
        ["type1_id", "type2_id", "type3_id", "relation"],
        type_def_rel_values,
        chunk_size=1000,
    )
    lines.append("")

    abilities_filtered = [a for a in ability_order if a in ability_names]
    ability_id: dict[str, int] = {}
    ability_values: list[str] = []
    for idx, label in enumerate(abilities_filtered, start=1):
        ability_id[label.upper()] = idx
        ability_values.append(
            f"({idx}, {sql_string(label.upper())}, {sql_string(ability_names.get(label, label))}, {sql_string(ability_descs.get(label + 'Description', ability_descs.get(label, '')))} )"
        )
    append_bulk_insert(lines, "abilities", ["id", "code", "name", "description"], ability_values, chunk_size=500)
    lines.append("")

    move_id: dict[str, int] = {}
    move_values: list[str] = []
    for idx, row in enumerate(move_rows, start=1):
        move_id[str(row["code"])] = idx
        power_sql = "NULL" if row["power"] is None else str(row["power"])
        acc_sql = "NULL" if row["accuracy"] is None else str(row["accuracy"])
        move_values.append(
            f"({idx}, {sql_string(str(row['code']))}, {sql_string(str(row['name']))}, {sql_string(str(row['description']))}, "
            f"{sql_string(str(row['effect']))}, {power_sql}, {acc_sql}, {row['pp']}, {row['effect_chance']}, {sql_string(str(row['category']))}, {type_id[str(row['type_code'])]})"
        )
    append_bulk_insert(
        lines,
        "moves",
        ["id", "code", "name", "description", "effect", "power", "accuracy", "pp", "effect_chance", "category", "type_id"],
        move_values,
        chunk_size=500,
    )
    lines.append("")

    pokemon_id: dict[tuple[str, str], int] = {}
    pokemon_values: list[str] = []
    for idx, row in enumerate(pokemon_rows, start=1):
        form_key = normalize_mon_token(f"{row.species_code}_{row.form_code}")
        species_key = normalize_mon_token(row.species_code)
        evo = evolutions.get(form_key) or evolutions.get(species_key)
        if evo is not None:
            row.evolution_form, row.evolution_level, row.evolution_requirement = evo

        pokemon_id[(row.species_code, row.form_code)] = idx
        type2_sql = "NULL" if row.type1 == row.type2 else str(type_id[row.type2])
        evo_form_sql = "NULL" if row.evolution_form is None else sql_string(row.evolution_form)
        evo_level_sql = "NULL" if row.evolution_level is None else str(row.evolution_level)
        evo_req_sql = "NULL" if row.evolution_requirement is None else sql_string(row.evolution_requirement)
        pokemon_values.append(
            f"({idx}, {sql_string(row.species_code)}, {sql_string(row.form_code)}, {sql_string(row.name)}, "
            f"{row.hp}, {row.atk}, {row.defn}, {row.sat}, {row.sdf}, {row.spe}, {row.bst}, {evo_form_sql}, {evo_level_sql}, {evo_req_sql}, {type_id[row.type1]}, {type2_sql})"
        )
    append_bulk_insert(
        lines,
        "pokemon",
        ["id", "species_code", "form_code", "name", "hp", "atk", "def", "sat", "sdf", "spe", "bst", "evolution_form", "evolution_level", "evolution_requirement", "primary_type_id", "secondary_type_id"],
        pokemon_values,
        chunk_size=500,
    )
    lines.append("")

    pokemon_ability_values: list[str] = []
    for row in pokemon_rows:
        pid = pokemon_id[(row.species_code, row.form_code)]
        for slot, ability in enumerate(row.abilities, start=1):
            aid = ability_id.get(ability)
            if aid is None:
                continue
            pokemon_ability_values.append(f"({pid}, {aid}, {slot})")
    append_bulk_insert(lines, "pokemon_abilities", ["pokemon_id", "ability_id", "slot"], pokemon_ability_values, chunk_size=1000)
    lines.append("")

    pokemon_move_values: list[str] = []
    for row in pokemon_rows:
        pid = pokemon_id[(row.species_code, row.form_code)]
        form_key = normalize_mon_token(f"{row.species_code}_{row.form_code}")
        species_key = normalize_mon_token(row.species_code)

        species_moves = levelup.get(form_key)
        if species_moves is None:
            species_moves = levelup.get(species_key, [])
        for level, move_code in species_moves:
            mid = move_id.get(move_code)
            if mid is None:
                continue
            pokemon_move_values.append(f"({pid}, {mid}, 'level_up', {level})")

        # Bring level-up moves from all previous evolutions in the chain.
        ancestor_keys: set[tuple[str, str]] = set()
        stack = list(evolution_parents.get((row.species_code, row.form_code), set()))
        while stack:
            anc = stack.pop()
            if anc in ancestor_keys:
                continue
            ancestor_keys.add(anc)
            stack.extend(evolution_parents.get(anc, set()))

        for anc_species, anc_form in ancestor_keys:
            anc_form_key = normalize_mon_token(f"{anc_species}_{anc_form}")
            anc_species_key = normalize_mon_token(anc_species)
            anc_moves = levelup.get(anc_form_key)
            if anc_moves is None:
                anc_moves = levelup.get(anc_species_key, [])
            for level, move_code in anc_moves:
                mid = move_id.get(move_code)
                if mid is None:
                    continue
                pokemon_move_values.append(f"({pid}, {mid}, 'prev_evo_lvl_up', {level})")

        for move_code in row.tmhm_moves:
            mid = move_id.get(move_code)
            if mid is None:
                continue
            method = tmhm_methods.get(move_code, "tm_hm")
            pokemon_move_values.append(f"({pid}, {mid}, {sql_string(method)}, 0)")
    if pokemon_move_values:
        prefix = "INSERT IGNORE INTO pokemon_moves (pokemon_id, move_id, learn_method, learn_level) VALUES "
        chunk_size = 2000
        for i in range(0, len(pokemon_move_values), chunk_size):
            chunk = pokemon_move_values[i : i + chunk_size]
            lines.append(prefix + ", ".join(chunk) + ";")

    lines.append("")
    lines.append("COMMIT;")
    lines.append("SET FOREIGN_KEY_CHECKS = 1;")
    lines.append("")
    lines.append("-- Validation checks")
    lines.append("SELECT COUNT(*) AS total_types FROM types;")
    lines.append("SELECT COUNT(*) AS total_pokemon FROM pokemon;")
    lines.append("SELECT COUNT(*) AS total_abilities FROM abilities;")
    lines.append("SELECT COUNT(*) AS total_moves FROM moves;")
    lines.append("SELECT COUNT(*) AS total_pokemon_abilities FROM pokemon_abilities;")
    lines.append("SELECT COUNT(*) AS total_pokemon_moves FROM pokemon_moves;")
    lines.append("SELECT COUNT(*) AS total_type_defensive_relations FROM type_defensive_relations;")

    output.write_text("\n".join(lines), encoding="utf-8")


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate MySQL seed SQL from Polished Crystal data files.")
    parser.add_argument("--output", default=str(SQL_DIR / "seed_data.sql"), help="Output SQL file path")
    args = parser.parse_args()
    out_path = Path(args.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    generate_seed_sql(out_path)
    print(f"Wrote {out_path}")


if __name__ == "__main__":
    main()

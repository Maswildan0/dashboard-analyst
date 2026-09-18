"""Student registration analysis (quota, registration, BPP tariff).

Reads the tidy `Data Long` dataset shipped in `finance/data/`. The workbook is
the current source because there is no database table for it yet; this module is
the only place that knows the source, so Phase 2 can swap the loader for a
database-backed import without touching the views or the template.

Aggregation rules (agreed with the requester):

* quota and registration are SUMMED over the selected study programs;
* tariff is AVERAGED over the non-null tariffs — never summed. A tariff is a
  price per study program, so adding them together would be meaningless;
* a missing tariff stays null (it is not a zero price);
* a missing quota/registration means "no intake recorded", which aggregates as 0;
* rows where tariff, quota and registration are all null are ignored.

Selecting a single study program therefore reduces to that program's own
numbers, giving its historical trend with no special-casing.
"""
import json
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from pathlib import Path

DATA_FILE = Path(__file__).resolve().parent.parent / 'data' / 'student_registration.json'

# Sentinel for "no filter" in the JSON payload and query strings.
_ALL = ''
ONE = Decimal(1)
TENTH = Decimal('0.1')


@lru_cache(maxsize=1)
def _records():
    """Parsed rows, each carrying a non-empty identity key.

    Eight rows in the workbook have a blank `Kode Prodi` but a real program and
    real quota/registration (the Jakarta campus D3 programme). Their data must
    count towards the aggregates, but a blank code cannot be the dropdown value:
    it would collide with the "Semua Program Studi" sentinel and make that
    programme impossible to select. Those rows therefore fall back to a
    namespaced key built from the program name, which no real code can match.
    """
    with DATA_FILE.open(encoding='utf-8') as fh:
        records = json.load(fh)['records']
    for row in records:
        row['key'] = row['code'] or 'nama:' + row['study_program']
    return tuple(records)


def get_years():
    """Every year present in the dataset, ascending."""
    return sorted({r['year'] for r in _records()})


def get_faculties():
    """Faculty/campus names present in the dataset, sorted."""
    return sorted({r['faculty'] for r in _records()})


def get_study_programs(faculty=None):
    """Study programs as {value, label}, optionally limited to one faculty.

    `value` is the program code, which is unique across faculties (verified:
    no code maps to two identities). `label` is the program name.
    """
    rows = _records()
    if faculty:
        rows = [r for r in rows if r['faculty'] == faculty]
    options = {}
    for row in rows:
        options.setdefault(row['key'], row['study_program'])
    return [{'value': key, 'label': name}
            for key, name in sorted(options.items(), key=lambda kv: kv[1])]


def _select(faculty=None, study_program=None):
    rows = _records()
    if faculty:
        rows = [r for r in rows if r['faculty'] == faculty]
    if study_program:
        rows = [r for r in rows if r['key'] == study_program]
    return rows


def _whole(value):
    """Round half-up to an int. Tariffs and totals are whole rupiah/students."""
    return int(Decimal(str(value)).quantize(ONE, rounding=ROUND_HALF_UP))


def _one_decimal(value):
    """Round half-up to one decimal (achievement percentages)."""
    return float(Decimal(str(value)).quantize(TENTH, rounding=ROUND_HALF_UP))


def display_count(value):
    """Indonesian thousands separator: 13185 -> '13.185'. Matches intcomma."""
    sign = '-' if value < 0 else ''
    digits = str(abs(int(value)))
    parts = []
    while len(digits) > 3:
        parts.insert(0, digits[-3:])
        digits = digits[:-3]
    parts.insert(0, digits)
    return sign + '.'.join(parts)


def display_percent(value):
    """'94,2%' — Indonesian decimal comma. '-' when undefined (no quota)."""
    return '-' if value is None else f'{_one_decimal(value):.1f}'.replace('.', ',') + '%'


def display_rupiah(value):
    """'Rp10.556.174'. '-' when there is no tariff."""
    return '-' if value is None else 'Rp' + display_count(value)


def display_difference(value):
    """Signed difference: registrations above quota read '+150'."""
    return ('+' if value > 0 else '') + display_count(value)


def get_registration_trend(faculty=None, study_program=None):
    """Aggregated series + summary for the selected scope.

    Returns a dict shaped for both the JSON endpoint and the template, so the
    page and the AJAX refresh can never disagree.
    """
    rows = _select(faculty, study_program)
    years = get_years()

    quota, registration, tariffs = [], [], []
    per_year = {}
    for year in years:
        year_rows = [r for r in rows if r['year'] == year]
        q = sum(r['quota'] for r in year_rows)
        g = sum(r['registration'] for r in year_rows)
        t = [r['tariff'] for r in year_rows if r['tariff'] is not None]
        avg = (sum(t) / len(t)) if t else None
        # Guard the divide: a scope with no quota has no achievement, and must
        # not be reported as 0% (which would read as a real shortfall).
        achievement = None if q == 0 else _one_decimal(g / q * 100)
        tariff_average = None if avg is None else _whole(avg)
        quota.append(q)
        registration.append(g)
        tariffs.append(tariff_average)
        per_year[year] = {
            'year': year,
            'quota': q,
            'registration': g,
            'difference': g - q,
            'achievement': achievement,
            'tariff_average': tariff_average,
            # Row count lets the table show a per-year empty state instead of a
            # misleading 0/0/0 row for programs that had no intake that year.
            'programs': len(year_rows),
            # Display strings are built here, once, so the server-rendered table
            # and the AJAX-refreshed one cannot format the same number differently.
            'disp': {
                'quota': display_count(q),
                'registration': display_count(g),
                'difference': display_difference(g - q),
                'achievement': display_percent(achievement),
                'tariff_average': display_rupiah(tariff_average),
            },
        }

    # A scope "has data" only when some row contributes a real measure. Rows can
    # exist while every figure is zero (a programme that never took an intake),
    # and charting that would draw the empty chart the page is meant to avoid.
    measured = [r for r in rows
                if r['quota'] or r['registration'] or r['tariff'] is not None]
    # Headline year: the newest year that actually has data in this scope, so a
    # filtered selection never reports a blank 0 from a year it does not cover.
    covered = [y for y in years if per_year[y]['programs']] if measured else []
    latest = covered[-1] if covered else None
    summary = {
        'year': latest,
        'quota': per_year[latest]['quota'] if latest else 0,
        'registration': per_year[latest]['registration'] if latest else 0,
        'achievement': per_year[latest]['achievement'] if latest else None,
        'tariff_average': per_year[latest]['tariff_average'] if latest else None,
    }
    summary['disp'] = {
        'quota': display_count(summary['quota']),
        'registration': display_count(summary['registration']),
        'achievement': display_percent(summary['achievement']),
        'tariff_average': display_rupiah(summary['tariff_average']),
    }

    return {
        'filters': {'faculty': faculty or _ALL, 'study_program': study_program or _ALL},
        # Included here so the page and the JSON endpoint produce the same
        # chart title; the AJAX refresh would otherwise drop the subtitle.
        'chart_label': filter_labels(faculty, study_program),
        'years': years,
        'series': {'quota': quota, 'registration': registration, 'tariff': tariffs},
        'summary': summary,
        'table': [per_year[y] for y in years],
        'has_data': bool(measured),
        'program_count': len({r['key'] for r in rows}),
    }


def filter_labels(faculty, study_program):
    """Human-readable subtitle for the chart title, or None when unfiltered.

    A selected study program wins over its faculty: the narrower selection is
    what the chart actually shows.
    """
    if study_program:
        for row in _records():
            if row['key'] == study_program:
                return row['study_program']
        return None
    return faculty or None

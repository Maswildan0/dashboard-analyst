"""Registrasi Mahasiswa: aggregation contract and page wiring.

The numbers here are the whole point of the page, so these tests pin the
aggregation rules rather than the markup: quota/registration are summed,
tariff is averaged (never summed), and a missing quota never divides by zero.
"""
from decimal import Decimal, ROUND_HALF_UP

from django.contrib.auth.models import User
from django.test import SimpleTestCase, TestCase

from finance.services import student_registration_service as srs


class AggregationTests(SimpleTestCase):
    def test_tariff_is_averaged_never_summed(self):
        """The headline rule: BPP is a price per program, so it cannot be added."""
        trend = srs.get_registration_trend('FAKULTAS INFORMATIKA (FIF)')
        for year, avg in zip(trend['years'], trend['series']['tariff']):
            if avg is None:
                continue
            tariffs = [r['tariff'] for r in srs._records()
                       if r['year'] == year
                       and r['faculty'] == 'FAKULTAS INFORMATIKA (FIF)'
                       and r['tariff'] is not None]
            expected = int(Decimal(sum(tariffs) / len(tariffs)).quantize(
                Decimal(1), rounding=ROUND_HALF_UP))
            with self.subTest(year=year):
                self.assertEqual(avg, expected)
                if len(tariffs) > 1:
                    self.assertNotEqual(avg, sum(tariffs))

    def test_quota_and_registration_are_summed_over_programs(self):
        trend = srs.get_registration_trend('FAKULTAS INFORMATIKA (FIF)')
        for year, quota in zip(trend['years'], trend['series']['quota']):
            rows = [r for r in srs._records()
                    if r['year'] == year and r['faculty'] == 'FAKULTAS INFORMATIKA (FIF)']
            with self.subTest(year=year):
                self.assertEqual(quota, sum(r['quota'] for r in rows))

    def test_null_tariffs_are_excluded_from_the_average_not_zeroed(self):
        """A missing price must not drag the average down."""
        for faculty in srs.get_faculties():
            trend = srs.get_registration_trend(faculty)
            for year, avg in zip(trend['years'], trend['series']['tariff']):
                rows = [r for r in srs._records()
                        if r['year'] == year and r['faculty'] == faculty]
                real = [r['tariff'] for r in rows if r['tariff'] is not None]
                with self.subTest(faculty=faculty, year=year):
                    if not real:
                        self.assertIsNone(avg)
                    else:
                        self.assertGreaterEqual(avg, 0)
                        self.assertLessEqual(avg, max(real))

    def test_single_program_reduces_to_its_own_trend(self):
        """One program selected = that program's numbers, no aggregation needed."""
        rows = [r for r in srs._records() if r['code'] == '5208']
        trend = srs.get_registration_trend('FAKULTAS INFORMATIKA (FIF)', '5208')
        by_year = {r['year']: r for r in rows}
        for year, quota in zip(trend['years'], trend['series']['quota']):
            with self.subTest(year=year):
                self.assertEqual(quota, by_year[year]['quota'])

    def test_zero_quota_yields_no_achievement_instead_of_dividing_by_zero(self):
        """`Registrasi / Kuota` is undefined when nothing was offered."""
        # 5208 has quota 0 in 2019 and a real quota afterwards.
        trend = srs.get_registration_trend('FAKULTAS INFORMATIKA (FIF)', '5208')
        row = next(r for r in trend['table'] if r['year'] == 2019)
        self.assertEqual(row['quota'], 0)
        self.assertIsNone(row['achievement'])
        self.assertEqual(row['disp']['achievement'], '-')

    def test_tariff_only_scope_still_counts_as_data(self):
        """A blended-learning programme registered no students but does carry a
        tariff, so it has something to show and must not be called empty."""
        trend = srs.get_registration_trend('FAKULTAS TEKNIK ELEKTRO (FTE)', '5101-blend')
        self.assertTrue(trend['has_data'])
        self.assertEqual(trend['summary']['quota'], 0)
        self.assertEqual(trend['summary']['tariff_average'], 12500000)

    def test_unknown_scope_reports_no_data_and_no_headline_year(self):
        for faculty, program in [('NO SUCH FACULTY', ''), ('', 'no-such-code')]:
            with self.subTest(faculty=faculty, program=program):
                trend = srs.get_registration_trend(faculty, program)
                self.assertFalse(trend['has_data'])
                self.assertIsNone(trend['summary']['year'])
                self.assertEqual(trend['program_count'], 0)

    def test_achievement_matches_registration_over_quota(self):
        trend = srs.get_registration_trend('FAKULTAS TEKNIK ELEKTRO (FTE)')
        for row in trend['table']:
            if row['quota'] == 0:
                continue
            with self.subTest(year=row['year']):
                self.assertAlmostEqual(row['achievement'],
                                       row['registration'] / row['quota'] * 100, places=1)

    def test_difference_is_registration_minus_quota(self):
        trend = srs.get_registration_trend()
        for row in trend['table']:
            with self.subTest(year=row['year']):
                self.assertEqual(row['difference'], row['registration'] - row['quota'])

    def test_summary_reports_the_newest_year_covered_by_the_selection(self):
        """A filtered scope must not report a blank 0 from a year it lacks."""
        trend = srs.get_registration_trend('FAKULTAS INFORMATIKA (FIF)', '5208')
        self.assertEqual(trend['summary']['year'], 2026)
        self.assertEqual(trend['summary']['quota'], 120)
        self.assertEqual(trend['summary']['registration'], 148)

    def test_display_strings_use_indonesian_formatting(self):
        trend = srs.get_registration_trend()
        self.assertEqual(trend['summary']['disp']['quota'], '13.185')
        self.assertEqual(trend['summary']['disp']['tariff_average'], 'Rp10.556.174')
        # Decimal comma, matching the rest of the dashboard's number handling.
        self.assertIn(',', trend['summary']['disp']['achievement'])
        self.assertTrue(trend['summary']['disp']['achievement'].endswith('%'))

    def test_rows_are_only_kept_when_some_measure_exists(self):
        """The loader drops rows whose tariff, quota and registration are all
        blank in the workbook, so no wholly empty row reaches the aggregates."""
        for row in srs._records():
            with self.subTest(code=row['code'], year=row['year']):
                self.assertFalse(
                    row['tariff'] is None and row['quota'] == 0 and row['registration'] == 0
                    and row['faculty'] == '' and row['study_program'] == '',
                    'a row with no tariff, quota, registration or identity survived',
                )

    def test_blank_program_code_still_yields_a_selectable_option(self):
        """Eight rows have a blank Kode Prodi but real data. A blank dropdown
        value would collide with the 'Semua Program Studi' sentinel."""
        codes = [o['value'] for o in srs.get_study_programs()]
        self.assertNotIn('', codes)
        self.assertEqual(len(codes), len(set(codes)))
        blank = [r for r in srs._records() if not r['code']]
        self.assertTrue(blank, 'expected the workbook to contain blank-code rows')
        for key in {r['key'] for r in blank}:
            self.assertTrue(key)
            self.assertTrue(any(o['value'] == key for o in srs.get_study_programs()))

    def test_blank_code_program_data_counts_towards_totals(self):
        """Its quota is real, so dropping it would understate the totals."""
        key = next(r['key'] for r in srs._records() if not r['code'])
        trend = srs.get_registration_trend('TELKOM UNIVERSITY KAMPUS JAKARTA', key)
        self.assertEqual(trend['summary']['year'], 2026)
        self.assertEqual(trend['series']['quota'][0], 200)  # 2019


class OptionsTests(SimpleTestCase):
    def test_faculties_come_from_the_data(self):
        faculties = srs.get_faculties()
        self.assertGreater(len(faculties), 0)
        self.assertEqual(faculties, sorted(faculties))
        self.assertEqual({r['faculty'] for r in srs._records()}, set(faculties))

    def test_study_programs_are_narrowed_by_faculty(self):
        everything = srs.get_study_programs()
        one = srs.get_study_programs('FAKULTAS INFORMATIKA (FIF)')
        self.assertLess(len(one), len(everything))
        codes = {o['value'] for o in one}
        self.assertEqual(
            codes,
            {r['code'] for r in srs._records() if r['faculty'] == 'FAKULTAS INFORMATIKA (FIF)'},
        )

    def test_program_code_identifies_one_program_across_the_dataset(self):
        """The dropdown value is the code, so a code must never be ambiguous."""
        seen = {}
        for row in srs._records():
            seen.setdefault(row['key'], set()).add((row['faculty'], row['study_program']))
        ambiguous = {c: v for c, v in seen.items() if len(v) > 1}
        self.assertEqual(ambiguous, {})

    def test_chart_label_prefers_the_narrower_selection(self):
        self.assertIsNone(srs.filter_labels('', ''))
        self.assertEqual(srs.filter_labels('FAKULTAS INFORMATIKA (FIF)', ''),
                         'FAKULTAS INFORMATIKA (FIF)')
        self.assertEqual(srs.filter_labels('FAKULTAS INFORMATIKA (FIF)', '5208'),
                         'S1 Data Sains')


class PageTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user('registrasi-viewer', password='x')
        self.client.force_login(self.user)

    def test_page_renders_the_analysis(self):
        r = self.client.get('/dashboard/registrasi-mahasiswa/')
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Analisis Kuota, Registrasi, dan Tarif BPP')
        self.assertContains(r, 'Ringkasan per Tahun')
        self.assertContains(r, 'Semua Fakultas')
        self.assertContains(r, 'Semua Program Studi')

    def test_page_works_without_javascript(self):
        """The numbers must be in the HTML, not only fetched by the table script."""
        trend = srs.get_registration_trend()
        r = self.client.get('/dashboard/registrasi-mahasiswa/')
        self.assertContains(r, trend['summary']['disp']['quota'])
        self.assertContains(r, trend['summary']['disp']['tariff_average'])

    def test_sidebar_links_to_the_page(self):
        r = self.client.get('/dashboard/registrasi-mahasiswa/')
        self.assertContains(r, 'Registrasi Mahasiswa')
        self.assertContains(r, 'active')

    def test_data_endpoint_returns_the_documented_shape(self):
        payload = self.client.get('/dashboard/registrasi-mahasiswa/data/').json()
        self.assertEqual(set(payload) >= {'filters', 'years', 'series', 'summary', 'has_data',
                                          'table', 'chart_label'}, True)
        self.assertEqual(set(payload['series']), {'quota', 'registration', 'tariff'})
        self.assertEqual(set(payload['summary']) >= {'year', 'quota', 'registration',
                                                     'achievement', 'tariff_average'}, True)
        self.assertEqual(len(payload['years']), len(payload['series']['quota']))

    def test_data_endpoint_applies_the_filter(self):
        everything = self.client.get('/dashboard/registrasi-mahasiswa/data/').json()
        filtered = self.client.get('/dashboard/registrasi-mahasiswa/data/',
                                   {'faculty': 'FAKULTAS INFORMATIKA (FIF)'}).json()
        self.assertLess(sum(filtered['series']['quota']), sum(everything['series']['quota']))
        self.assertEqual(filtered['filters']['faculty'], 'FAKULTAS INFORMATIKA (FIF)')
        self.assertEqual(filtered['chart_label'], 'FAKULTAS INFORMATIKA (FIF)')

    def test_programs_endpoint_narrows_to_the_faculty(self):
        r = self.client.get('/dashboard/registrasi-mahasiswa/program-studi/',
                            {'faculty': 'FAKULTAS INFORMATIKA (FIF)'})
        codes = {p['value'] for p in r.json()['study_programs']}
        self.assertEqual(codes, {o['value'] for o in srs.get_study_programs('FAKULTAS INFORMATIKA (FIF)')})

    def test_unknown_filter_reports_empty_instead_of_widening(self):
        """Widening to 'all' would show unfiltered totals under a faculty label."""
        payload = self.client.get('/dashboard/registrasi-mahasiswa/data/',
                                  {'faculty': 'NO SUCH FACULTY'}).json()
        self.assertEqual(payload['filters']['faculty'], 'NO SUCH FACULTY')
        self.assertFalse(payload['has_data'])
        self.assertEqual(set(payload['series']['quota']), {0})

    def test_unknown_filter_renders_the_empty_state_not_an_empty_chart(self):
        r = self.client.get('/dashboard/registrasi-mahasiswa/',
                            {'faculty': 'NO SUCH FACULTY'})
        self.assertEqual(r.status_code, 200)
        self.assertContains(r, 'Tidak ada data Registrasi Mahasiswa')
        self.assertContains(r, 'id="regm-body" hidden')

    def test_thousands_and_rupiah_formatting_render(self):
        r = self.client.get('/dashboard/registrasi-mahasiswa/')
        self.assertContains(r, 'Rp')


class PageAuthTests(TestCase):
    def test_anonymous_is_redirected_to_login_with_next(self):
        target = '/dashboard/registrasi-mahasiswa/'
        r = self.client.get(target)
        self.assertEqual(r.status_code, 302)
        self.assertEqual(r.url, f'/login/?next={target}')

    def test_anonymous_data_endpoint_is_denied(self):
        r = self.client.get('/dashboard/registrasi-mahasiswa/data/')
        self.assertIn(r.status_code, (302, 401))

    def test_ajax_caller_gets_json_not_a_login_page(self):
        """A fetch() must not silently receive HTML and report a false success."""
        r = self.client.get('/dashboard/registrasi-mahasiswa/data/',
                            headers={'X-Requested-With': 'XMLHttpRequest'})
        self.assertEqual(r.status_code, 401)
        self.assertFalse(r.json()['ok'])

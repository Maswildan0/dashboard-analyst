"""Revenue Overview cards act as slicers: each one deep-links into the
matching revenue table carrying the filters active on the page."""

import re
from html import unescape
from urllib.parse import parse_qs

from django.test import TestCase

from finance.models import (
    Campus,
    FinancialPeriod,
    FinancialSummary,
    OrganizationUnit,
    PPMaster,
    RevenueCategory,
    RevenueTransactionSummary,
)

# The overview's own filter allowlists (dashboard.data.OPTIONS) — the deep
# links must be validated against the finance master data below.
OVERVIEW_YEAR = 2025


class RevenueOverviewCardTest(TestCase):
    TF_PATH = '/dashboard/revenue/tf/'

    def setUp(self):
        self.campus = Campus.objects.create(code='BDG', name='Bandung')
        self.period = FinancialPeriod.objects.create(
            year=2026, month=8, period_start='2026-08-01', period_end='2026-08-31')
        # Previous-year period: exists, but carries no revenue rows.
        FinancialPeriod.objects.create(
            year=OVERVIEW_YEAR, month=8, period_start='2025-08-01', period_end='2025-08-31')
        FinancialSummary.objects.create(
            period=self.period, campus=self.campus, organization_unit=None,
            revenue_actual='607521600000.00', revenue_target='642879999999.99',
            expense_actual='486624801600.00', expense_budget='519208823067.20',
            shu_actual='120896798400.00', shu_target='123869671721.31',
        )
        for code, amount in (('TF', '522468576000.00'),
                             ('NTF_PROJECT', '60000000000.00'),
                             ('NTF_RESEARCH', '25000000000.00')):
            RevenueTransactionSummary.objects.create(
                period=self.period, campus=self.campus, organization_unit=None,
                revenue_category=RevenueCategory.objects.create(code=code, name=code),
                actual_amount=amount, target_amount=amount,
            )
        # Master data that DOES match the overview allowlists (direktorat/
        # kode_pp options are 'BTP'/'9112'), and one that does not.
        self.org = OrganizationUnit.objects.create(
            code='BTP', name='Direktorat BTP', campus=self.campus, unit_type='OTHER')
        PPMaster.objects.create(pp_code='9112', organization_unit=self.org)

    def overview(self, **params):
        resp = self.client.get('/dashboard/', params)
        self.assertEqual(resp.status_code, 200)
        return resp

    @staticmethod
    def card_links(html):
        """{destination path -> query params} for every slicer card."""
        out = {}
        for href in re.findall(r'href="([^"]*)"', html):
            href = unescape(href)  # Django escapes the & between query params
            if href.startswith('/dashboard/revenue/'):
                path, _, query = href.partition('?')
                out[path] = parse_qs(query)
        return out

    @staticmethod
    def kpi_tags(html):
        """{kpi index -> tag name} for the KPI cards."""
        return {m.group('idx'): m.group('tag') for m in re.finditer(
            r'<(?P<tag>a|div)\b[^>]*data-kpi="(?P<idx>\d+)"', html)}

    def test_every_card_links_to_its_revenue_table(self):
        html = self.overview().content.decode()
        links = self.card_links(html)
        self.assertEqual(set(links), {
            '/dashboard/revenue/data/',
            '/dashboard/revenue/tf/',
            '/dashboard/revenue/ntf-project/',
            '/dashboard/revenue/ntf-research/',
        })
        for params in links.values():
            self.assertEqual(params, {'tahun[]': ['2026'], 'bulan[]': ['8']})

    def test_realisasi_card_is_a_link_and_rka_card_is_not(self):
        html = self.overview().content.decode()
        # KPI[0] = Realisasi Bulan Berjalan -> Data Revenue; KPI[1] = RKA.
        self.assertEqual(self.kpi_tags(html), {'0': 'a', '1': 'div'})
        # The legacy mock drill-through must be gone (it pointed at
        # /dashboard/data/table and would hijack the card click).
        self.assertNotIn('data-period=', html)

    def test_applied_filters_are_carried_to_the_destination(self):
        html = self.overview(
            tahun=OVERVIEW_YEAR, direktorat='BTP', kode_pp='9112').content.decode()
        for params in self.card_links(html).values():
            self.assertEqual(params, {
                'tahun[]': ['2025'],
                'bulan[]': ['8'],
                'org[]': [str(self.org.pk)],
                'pp[]': ['9112'],
            })
        # 'tipe' has no revenue-table counterpart: the clicked card fixes the
        # type, so it must never leak into a link.
        for params in self.card_links(html).values():
            self.assertNotIn('jenis[]', params)

    def test_invalid_filter_values_are_dropped(self):
        # 2023 / ASUS / 9999 are valid overview options but absent from the
        # finance master data -> they must not reach (and empty) a table. The
        # year falls back to the active period, 'tipe' still maps to its
        # category value (TF exists in the master data).
        html = self.overview(
            tahun='2023', direktorat='ASUS', kode_pp='9999', tipe='TF').content.decode()
        for params in self.card_links(html).values():
            self.assertEqual(params, {'tahun[]': ['2026'], 'bulan[]': ['8'],
                                      'jenis[]': ['TF']})

    def test_tipe_is_carried_as_revenue_categories(self):
        # TF is a single category; NTF covers both NTF categories (the same
        # split the composition pie shows).
        tf = self.overview(tipe='TF').content.decode()
        self.assertEqual(self.card_links(tf)[self.TF_PATH],
                         {'tahun[]': ['2026'], 'bulan[]': ['8'], 'jenis[]': ['TF']})
        ntf = self.overview(tipe='NTF').content.decode()
        self.assertEqual(self.card_links(ntf)[self.TF_PATH],
                         {'tahun[]': ['2026'], 'bulan[]': ['8'],
                          'jenis[]': ['NTF_PROJECT', 'NTF_RESEARCH']})
        semua = self.overview(tipe='Semua').content.decode()
        self.assertNotIn('jenis[]', self.card_links(semua)[self.TF_PATH])

    def test_filter_options_expose_validated_values_for_the_client(self):
        html = self.overview().content.decode()
        # The in-place filter apply rebuilds the card hrefs client-side from
        # these attributes, so they must carry the same validation.
        self.assertIn('data-revenue-param="tahun[]"', html)
        self.assertIn('data-revenue-param="org[]"', html)
        self.assertIn('data-revenue-param="pp[]"', html)
        self.assertIn('data-revenue-period="year"', html)
        self.assertIn('data-revenue-month-param="bulan[]"', html)
        self.assertIn('data-period-year="2026"', html)
        self.assertIn('data-period-month="8"', html)
        self.assertRegex(html, r'<option value="2025" data-revenue="2025"')
        self.assertRegex(html, r'<option value="2023" data-revenue=""')
        self.assertRegex(html, r'<option value="BTP" data-revenue="%d"' % self.org.pk)
        self.assertRegex(html, r'<option value="ASUS" data-revenue=""')
        self.assertRegex(html, r'<option value="9112" data-revenue="9112"')
        self.assertRegex(html, r'<option value="9113" data-revenue=""')
        # Tipe -> revenue category contract ('NTF' covers both categories).
        self.assertRegex(html, r'<option value="TF" data-revenue="TF"')
        self.assertRegex(html, r'<option value="NTF" data-revenue="NTF_PROJECT,NTF_RESEARCH"')
        self.assertIn('data-revenue-account-param="account[]"', html)
        self.assertIn('data-revenue-param="jenis[]"', html)
        # A master/reset option must render an EMPTY value, never Python's
        # repr for a missing map entry or a list.
        self.assertNotIn('data-revenue="None"', html)
        self.assertNotRegex(html, r"data-revenue=\"[^\"]*[\[\]'][^\"]*\"")


class RevenueOverviewNoDataTest(TestCase):
    """Without finance data the cards still render; only the period is dropped."""

    def test_links_fall_back_to_destination_defaults(self):
        resp = self.client.get('/dashboard/')
        self.assertEqual(resp.status_code, 200)
        html = resp.content.decode()
        for href in re.findall(r'href="([^"]*)"', html):
            if href.startswith('/dashboard/revenue/'):
                self.assertFalse(href.endswith('?'), href)
        self.assertIn('data-period-year=""', html)

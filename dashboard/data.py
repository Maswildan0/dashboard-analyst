"""Mock realisasi project dataset.

Ported 1:1 from the original Laravel DashboardController (the 32-project
list with the same values and the same cyclic direktorat assignment). The
dashboard and the Data Realisasi page are both generated from this data.
"""

# Direktorat assigned cyclically to the 32 projects (project index % 5).
DIREKTORAT_POOL = ['BTP', 'ASUS', 'PDPB', 'BSP', 'DIT']

MONTHS = [
    'Januari', 'Februari', 'Maret', 'April', 'Mei', 'Juni',
    'Juli', 'Agustus', 'September', 'Oktober', 'November', 'Desember',
]

OPTIONS = {
    'tipe': ['NTF', 'TF', 'Semua'],
    'direktorat': ['BTP', 'ASUS', 'PDPB', 'BSP', 'DIT', 'Semua'],
    'kodePP': ['9112', '9113', '9114', '9115', 'Semua'],
    'tahun': [2023, 2024, 2025, 2026],
}

PROJECTS = [
    {'unit': 'Divisi Konstruksi', 'kodePP': '001-2606.0001', 'noPP': 'PP-001', 'nama': 'Pembangunan Jalan Tol Semarang-Demak Seksi 2', 'nilai': 1_245_000_000_000, 'totalPendapatan': 245_500_000_000, 'pendapatanBerjalan': 987_500_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '002-2606.0001', 'noPP': 'PP-002', 'nama': 'Proyek PLTU Batang 2x1000 MW',           'nilai': 2_100_000_000_000, 'totalPendapatan': 420_000_000_000, 'pendapatanBerjalan': 1_680_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '003-2606.0001', 'noPP': 'PP-003', 'nama': 'Pembangunan Bendungan Cipanas',          'nilai': 998_000_000_000,  'totalPendapatan': 199_000_000_000, 'pendapatanBerjalan': 510_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '004-2606.0001', 'noPP': 'PP-004', 'nama': 'Data Center Telkom Nusantara',          'nilai': 1_750_000_000_000, 'totalPendapatan': 350_000_000_000, 'pendapatanBerjalan': 1_210_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '005-2606.0001', 'noPP': 'PP-005', 'nama': 'Pembangunan Menara BTS 4G',              'nilai': 640_000_000_000,  'totalPendapatan': 128_000_000_000, 'pendapatanBerjalan': 402_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '006-2606.0001', 'noPP': 'PP-006', 'nama': 'Pembangunan PLTA Jatigede',              'nilai': 1_120_000_000_000, 'totalPendapatan': 224_000_000_000, 'pendapatanBerjalan': 876_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '007-2606.0001', 'noPP': 'PP-007', 'nama': 'Pembangunan Jembatan Suramadu',          'nilai': 1_450_000_000_000, 'totalPendapatan': 290_000_000_000, 'pendapatanBerjalan': 1_020_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '008-2606.0001', 'noPP': 'PP-008', 'nama': 'Satelit Telekomunikasi MERAH PUTIH',     'nilai': 2_450_000_000_000, 'totalPendapatan': 490_000_000_000, 'pendapatanBerjalan': 1_930_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '009-2606.0001', 'noPP': 'PP-009', 'nama': 'Fiber Optik Palapa Ring Timur',          'nilai': 890_000_000_000,  'totalPendapatan': 178_000_000_000, 'pendapatanBerjalan': 620_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '010-2606.0001', 'noPP': 'PP-010', 'nama': 'Pembangunan Bandara Yogyakarta',        'nilai': 1_380_000_000_000, 'totalPendapatan': 276_000_000_000, 'pendapatanBerjalan': 954_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '011-2606.0001', 'noPP': 'PP-011', 'nama': 'Pembangunan PLTMH Kapasitas 100 MW',     'nilai': 720_000_000_000,  'totalPendapatan': 144_000_000_000, 'pendapatanBerjalan': 486_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '012-2606.0001', 'noPP': 'PP-012', 'nama': 'Smart City Jakarta Pusat',              'nilai': 640_000_000_000,  'totalPendapatan': 128_000_000_000, 'pendapatanBerjalan': 390_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '013-2606.0001', 'noPP': 'PP-013', 'nama': '5G Site Deployment Jawa Barat',         'nilai': 560_000_000_000,  'totalPendapatan': 112_000_000_000, 'pendapatanBerjalan': 348_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '014-2606.0001', 'noPP': 'PP-014', 'nama': 'Pembangunan MRT Jakarta Fase 2',         'nilai': 1_980_000_000_000, 'totalPendapatan': 396_000_000_000, 'pendapatanBerjalan': 1_240_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '015-2606.0001', 'noPP': 'PP-015', 'nama': 'Pembangunan PLTS Terapung Cirata',       'nilai': 840_000_000_000,  'totalPendapatan': 168_000_000_000, 'pendapatanBerjalan': 510_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '016-2606.0001', 'noPP': 'PP-016', 'nama': 'Pusat Data Nasional Batam',              'nilai': 2_200_000_000_000, 'totalPendapatan': 440_000_000_000, 'pendapatanBerjalan': 1_560_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '017-2606.0001', 'noPP': 'PP-017', 'nama': 'Kabel Laut Indonesia Timur',            'nilai': 740_000_000_000,  'totalPendapatan': 148_000_000_000, 'pendapatanBerjalan': 472_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '018-2606.0001', 'noPP': 'PP-018', 'nama': 'Pembangunan Pelabuhan Patimban',        'nilai': 1_620_000_000_000, 'totalPendapatan': 324_000_000_000, 'pendapatanBerjalan': 1_080_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '019-2606.0001', 'noPP': 'PP-019', 'nama': 'Pembangunan PLTD 2x25 MW Ambon',        'nilai': 480_000_000_000,  'totalPendapatan': 96_000_000_000,   'pendapatanBerjalan': 288_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '020-2606.0001', 'noPP': 'PP-020', 'nama': 'Pembangunan ATCS Surabaya',             'nilai': 580_000_000_000,  'totalPendapatan': 116_000_000_000, 'pendapatanBerjalan': 372_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '021-2606.0001', 'noPP': 'PP-021', 'nama': 'Rehabilitasi Jaringan Kabel',           'nilai': 420_000_000_000,  'totalPendapatan': 84_000_000_000,   'pendapatanBerjalan': 260_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '022-2606.0001', 'noPP': 'PP-022', 'nama': 'Pembangunan Jalan Akses Tol',            'nilai': 520_000_000_000,  'totalPendapatan': 104_000_000_000, 'pendapatanBerjalan': 332_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '023-2606.0001', 'noPP': 'PP-023', 'nama': 'Pembangunan PLTP Lahendong',            'nilai': 660_000_000_000,  'totalPendapatan': 132_000_000_000, 'pendapatanBerjalan': 410_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '024-2606.0001', 'noPP': 'PP-024', 'nama': 'Sistem Kartu Identitas Digital',        'nilai': 380_000_000_000,  'totalPendapatan': 76_000_000_000,   'pendapatanBerjalan': 234_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '025-2606.0001', 'noPP': 'PP-025', 'nama': 'Penguatan Jaringan Backbone',          'nilai': 900_000_000_000,  'totalPendapatan': 180_000_000_000, 'pendapatanBerjalan': 610_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '026-2606.0001', 'noPP': 'PP-026', 'nama': 'Pembangunan Jembatan Merah Putih',       'nilai': 1_050_000_000_000, 'totalPendapatan': 210_000_000_000, 'pendapatanBerjalan': 700_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '027-2606.0001', 'noPP': 'PP-027', 'nama': 'Pembangunan PLTMH 50 MW Sulawesi',       'nilai': 540_000_000_000,  'totalPendapatan': 108_000_000_000, 'pendapatanBerjalan': 330_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '028-2606.0001', 'noPP': 'PP-028', 'nama': 'Pembangunan IoT Monitoring',            'nilai': 340_000_000_000,  'totalPendapatan': 68_000_000_000,   'pendapatanBerjalan': 210_000_000_000},
    {'unit': 'Divisi Telekom',    'kodePP': '029-2606.0001', 'noPP': 'PP-029', 'nama': 'Pembangunan VSAT Remote Area',          'nilai': 460_000_000_000,  'totalPendapatan': 92_000_000_000,   'pendapatanBerjalan': 278_000_000_000},
    {'unit': 'Divisi Konstruksi', 'kodePP': '030-2606.0001', 'noPP': 'PP-030', 'nama': 'Pembangunan Gedung Kementerian Energi',   'nilai': 780_000_000_000,  'totalPendapatan': 156_000_000_000, 'pendapatanBerjalan': 508_000_000_000},
    {'unit': 'Divisi Energi',     'kodePP': '031-2606.0001', 'noPP': 'PP-031', 'nama': 'Pembangunan PLTS Rooftop 20 MW',         'nilai': 410_000_000_000,  'totalPendapatan': 82_000_000_000,   'pendapatanBerjalan': 250_000_000_000},
    {'unit': 'Divisi Digital',    'kodePP': '032-2606.0001', 'noPP': 'PP-032', 'nama': 'Sistem Keamanan Siber Nasional',         'nilai': 610_000_000_000,  'totalPendapatan': 122_000_000_000, 'pendapatanBerjalan': 380_000_000_000},
]


def realisasi_dataset(tahun: int) -> list[dict]:
    """32 projects repeated across the 12 months of the given year, each
    tagged with the cyclic direktorat value used by the direktorat filter."""
    rows = []
    for i, p in enumerate(PROJECTS):
        row = dict(p)
        row['direktorat'] = DIREKTORAT_POOL[i % len(DIREKTORAT_POOL)]
        # Tipe split ~58/42 (19 NTF / 13 TF of 32) mirroring the dashboard pie.
        row['tipe'] = 'NTF' if i < 19 else 'TF'
        for idx, month in enumerate(MONTHS):
            r = dict(row)
            r['month'] = month
            r['monthIdx'] = idx
            r['tahun'] = tahun
            rows.append(r)
    return rows

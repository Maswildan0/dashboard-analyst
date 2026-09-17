from django.urls import path

from . import manual_views, revenue_views

app_name = 'revenue'

urlpatterns = [
    path('', revenue_views.overview, name='overview'),
    path('filter/pps/', revenue_views.filter_pps, name='filter-pps'),
    path('filter/accounts/', revenue_views.filter_accounts, name='filter-accounts'),
    path('tf/', revenue_views.tf_detail, name='tf'),
    path('ntf-research/', revenue_views.ntf_research_detail, name='ntf-research'),
    path('data/', revenue_views.data_revenue_list, name='data'),
    path('ntf-project/', revenue_views.ntf_project_list, name='ntf-project'),
    path('ntf-project/<int:project_id>/recognitions/', revenue_views.project_recognitions, name='project-recognitions'),
    path('account/recognitions/', revenue_views.account_recognitions, name='account-recognitions'),
    path('data-quality/', revenue_views.data_quality, name='data-quality'),

    # --- Manual revenue data management (create/edit/void/restore/adjust) ---
    path('manual/create/', manual_views.create, name='manual-create'),
    path('manual/<int:entry_id>/edit/', manual_views.edit, name='manual-edit'),
    path('manual/project/<int:project_id>/edit/', manual_views.project_edit, name='manual-project-edit'),
    path('manual/<int:entry_id>/void/', manual_views.void, name='manual-void'),
    path('manual/<int:entry_id>/restore/', manual_views.restore, name='manual-restore'),
    path('manual/adjustment/', manual_views.adjustment, name='manual-adjustment'),
    path('manual/entries/', manual_views.entries, name='manual-entries'),
    path('manual/history/', manual_views.history, name='manual-history'),
    path('manual/deleted/', manual_views.deleted, name='manual-deleted'),
    # Cascading master data for the manual form (never hardcoded in JS).
    path('manual/options/pps/', manual_views.option_pps, name='manual-options-pps'),
    path('manual/options/accounts/', manual_views.option_accounts, name='manual-options-accounts'),
    path('manual/options/projects/', manual_views.option_projects, name='manual-options-projects'),
    path('manual/options/ledger/', manual_views.option_ledger, name='manual-options-ledger'),
]

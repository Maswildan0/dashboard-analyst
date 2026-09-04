from django.urls import path

from . import revenue_views

app_name = 'revenue'

urlpatterns = [
    path('', revenue_views.overview, name='overview'),
    path('filter/pps/', revenue_views.filter_pps, name='filter-pps'),
    path('filter/accounts/', revenue_views.filter_accounts, name='filter-accounts'),
    path('tf/', revenue_views.tf_detail, name='tf'),
    path('ntf-research/', revenue_views.ntf_research_detail, name='ntf-research'),
    path('ntf-project/', revenue_views.ntf_project_list, name='ntf-project'),
    path('ntf-project/<int:project_id>/recognitions/', revenue_views.project_recognitions, name='project-recognitions'),
    path('account/recognitions/', revenue_views.account_recognitions, name='account-recognitions'),
    path('data-quality/', revenue_views.data_quality, name='data-quality'),
]
